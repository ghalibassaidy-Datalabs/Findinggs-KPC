# HIGH-004 — 3 DB Connection Pool Diambil Per Request di `get_current_user`

![Severity](https://img.shields.io/badge/Severity-HIGH-red)
![Module](https://img.shields.io/badge/Module-Performance%20%2F%20Database-orange)
![Status](https://img.shields.io/badge/Status-Open-critical)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Technical Analysis](#technical-analysis)
3. [Business Impact](#business-impact)
4. [Real Use Case Scenario](#real-use-case-scenario)
5. [Root Cause Analysis](#root-cause-analysis)
6. [Evidence / Code Reference](#evidence--code-reference)
7. [Reproduction / Testing Steps](#reproduction--testing-steps)
8. [Risk Assessment](#risk-assessment)
9. [Recommended Fix](#recommended-fix)
10. [Refactor Recommendation](#refactor-recommendation)
11. [Long-Term Improvement Recommendation](#long-term-improvement-recommendation)

---

## Executive Summary

Setiap HTTP request ke endpoint yang dilindungi oleh `get_current_user` dependency mengonsumsi **3 koneksi database** secara berurutan — satu untuk validasi JWT + cek user, satu lagi untuk mengambil roles/permissions, dan satu lagi untuk mengambil custodian divisions. Ini terjadi karena setiap helper function membuat `session_scope()` baru secara independen.

Dengan konfigurasi `pool_size=5, max_overflow=10` (total maksimal 15 koneksi), sistem hanya mampu menangani **5 request concurrent** sebelum koneksi pool habis dan request berikutnya masuk ke queue/timeout.

---

## Technical Analysis

### Alur Eksekusi `get_current_user()`

```
Request masuk
    │
    ├─ get_current_user()                      [app/core/security.py]
    │   ├─ get_current_user_from_jwt(token)
    │   │   └─ _load_user_from_jwt()
    │   │       └─ session_scope() #1 ─────── DB Connection #1 (fetch user)
    │   │
    │   ├─ _attach_roles_permissions_to_state()
    │   │   └─ session_scope() #2 ─────────── DB Connection #2 (roles + permissions)
    │   │
    │   └─ _attach_custodian_divisions_to_state()
    │       └─ session_scope() #3 ──────────── DB Connection #3 (custodian divisions)
    │
    └─ Endpoint handler (juga mendapat db: Session dari get_db)
        └─ get_db() ──────────────────────────── DB Connection #4 (jika endpoint butuh DB)
```

**Total: 3-4 koneksi database per request biasa** (lebih jika endpoint menggunakan `get_db`)

### Code yang Bermasalah

```python
# app/core/security.py
async def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
):
    user = await get_current_user_from_jwt(token)  # ← buka session_scope #1

    request.state.user = user
    _attach_roles_permissions_to_state(request)    # ← buka session_scope #2
    _attach_custodian_divisions_to_state(request)  # ← buka session_scope #3
    return user
```

```python
def _attach_roles_permissions_to_state(request: Request) -> None:
    try:
        with session_scope() as db:  # ← Connection #2 dibuka di sini
            email, local_user = _get_user_email_and_local_user(request, db)
            ...
    except Exception as e:
        ...

def _attach_custodian_divisions_to_state(request: Request) -> None:
    try:
        with session_scope() as db:  # ← Connection #3 dibuka di sini
            email, local_user = _get_user_email_and_local_user(request, db)
            ...
    except Exception as e:
        ...
```

**Note:** `_get_user_email_and_local_user()` dipanggil DUA KALI — sekali di `_attach_roles_permissions_to_state` dan sekali di `_attach_custodian_divisions_to_state` — artinya user email/lookup query terjadi dua kali secara terpisah.

### Konfigurasi Pool

```python
# app/core/config.py
database_pool_size: int = Field(default=5, alias="DATABASE_POOL_SIZE")
database_max_overflow: int = Field(default=10, alias="DATABASE_MAX_OVERFLOW")
```

**Kapasitas efektif:** Pool size 5 + max overflow 10 = **15 koneksi total**
**Concurrent requests yang bisa dilayani:** 15 ÷ 3 = **5 request bersamaan** sebelum queue

---

## Business Impact

| Dampak                        | Deskripsi                                                                |
| ----------------------------- | ------------------------------------------------------------------------ |
| **Throughput rendah**         | Hanya ~5 concurrent requests sebelum DB pool exhausted                   |
| **Timeout di traffic tinggi** | Request akan timeout/error saat banyak user menggunakan sistem bersamaan |
| **500 errors cascade**        | Pool exhaustion menyebabkan HTTP 500 di semua endpoint secara bersamaan  |
| **Database overload**         | Setiap request membuka lebih banyak koneksi dari yang diperlukan         |
| **Latency tinggi**            | Setiap request menunggu 3 kali round-trip ke DB hanya untuk autentikasi  |
| **False SLA violation**       | Sistem bisa terasa "down" padahal hanya DB pool yang exhausted           |

---

## Real Use Case Scenario

### Skenario 1: Morning Rush — Semua User Login Bersamaan

```
Jam 08:00 — semua karyawan mulai bekerja
    ├─ 10 user membuka dashboard bersamaan
    ├─ Setiap request = 3 koneksi DB
    ├─ 10 × 3 = 30 koneksi dibutuhkan
    ├─ Pool maksimal = 15 koneksi
    └─ Request ke-6 dst: "QueuePool limit of size 5 overflow 10 reached"
       → HTTP 500 Internal Server Error
       → User melihat error, refresh, membuat lebih banyak request
       → Cascade failure
```

### Skenario 2: Background Job + User Request

```
Celery worker memproses invoice OCR (menggunakan DB connection)
+ 4 user sedang browsing (12 koneksi)
+ 1 user melakukan export data (1 koneksi)
= Pool habis, request baru gagal
```

### Skenario 3: Slow Database Response

```
Database lambat karena query heavy (misalnya analisis bid)
→ Connection dipegang lebih lama
→ Pool habis lebih cepat
→ User lain yang melakukan request ringan pun terdampak
```

---

## Root Cause Analysis

**Tipe masalah:** Architecture flaw — session management yang tidak efisien

**Akar masalah:**

1. `get_current_user()` adalah **global dependency** yang berjalan untuk setiap request yang dilindungi, sehingga inefficiency-nya dikalikan dengan jumlah total request
2. Setiap helper function (`_attach_roles_permissions_to_state`, `_attach_custodian_divisions_to_state`) membuat `session_scope()` independen daripada menerima session yang sudah ada
3. `_load_user_from_jwt()` menggunakan `session_scope()` alih-alih menerima session dari caller
4. User lookup dilakukan **dua kali** (sekali per helper function) padahal informasinya sama

---

## Evidence / Code Reference

| Item        | Detail                                                                    |
| ----------- | ------------------------------------------------------------------------- |
| **File**    | `app/core/security.py` — fungsi `get_current_user()`                      |
| **File**    | `app/core/security.py` — fungsi `_attach_roles_permissions_to_state()`    |
| **File**    | `app/core/security.py` — fungsi `_attach_custodian_divisions_to_state()`  |
| **File**    | `app/core/security.py` — fungsi `_load_user_from_jwt()`                   |
| **File**    | `app/core/config.py` — `database_pool_size=5`, `database_max_overflow=10` |
| **Pattern** | `session_scope()` dipanggil 3 kali berturut-turut untuk satu request      |

---

## Reproduction / Testing Steps

### Pre-condition

- Aplikasi berjalan
- PostgreSQL berjalan dengan pool default

### Monitor Koneksi per Request

```bash
# Terminal 1: Monitor koneksi PostgreSQL aktif
watch -n 0.5 'psql $DATABASE_URL -c "SELECT count(*), state FROM pg_stat_activity WHERE datname = current_database() GROUP BY state"'

# Terminal 2: Kirim satu request
curl -X GET "http://localhost:8000/api/v1/activity-logs" \
  -H "Authorization: Bearer $TOKEN"

# Observasi: koneksi aktif naik ke 3-4 saat request diproses
```

### Load Test untuk Melihat Pool Exhaustion

```bash
# Install hey atau wrk
# apt install hey

# Kirim 20 concurrent requests
hey -n 20 -c 20 \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/activity-logs"

# Expected (healthy): semua request 200 OK
# Actual (masalah): beberapa request HTTP 500 "QueuePool limit... reached"
```

### Cek Log Error

```bash
# Saat pool exhausted, lihat log aplikasi:
grep "QueuePool limit\|TimeoutError\|pool" logs/app.log

# Expected output:
# ERROR - TimeoutError: QueuePool limit of size 5 overflow 10 reached,
#         connection timed out, timeout 10
```

---

## Risk Assessment

| Aspek                         | Nilai                                                             |
| ----------------------------- | ----------------------------------------------------------------- |
| **Severity**                  | HIGH                                                              |
| **Urgency**                   | HIGH — akan terjadi di production saat concurrent users meningkat |
| **Likelihood**                | HIGH — terjadi setiap kali ada 5+ concurrent users                |
| **Impact if not fixed**       | HTTP 500 cascade, downtime saat traffic tinggi                    |
| **Estimated Fix Complexity**  | MEDIUM — refactor `get_current_user()` untuk pass session         |
| **Estimated Production Risk** | HIGH — performance blocker                                        |

---

## Recommended Fix

### Refactor `get_current_user()` — Single Session

```python
# app/core/security.py

async def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),  # ← SATU session, inject dari luar
):
    """
    Authenticate using internal JWT and enrich request.state.
    Uses a SINGLE database session for all DB operations.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not token:
        raise credentials_exception

    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        sub: str = payload.get("sub")
        if sub is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # Satu query untuk user
    user = db.exec(
        select(User).where(User.email == sub, User.is_active)
    ).first()
    if not user:
        raise credentials_exception

    # Satu query untuk roles
    roles = db.exec(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
    ).all()

    # Satu query untuk permissions
    permissions = db.exec(
        select(Permission.name)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
    ).all()

    # Satu query untuk custodian divisions
    custodian_divisions = CustodianDivisionService.get_custodian_divisions_for_user(
        db, user.id
    )

    # Simpan ke request.state
    request.state.user = user
    request.state.roles = sorted(set(r[0] if isinstance(r, tuple) else r for r in roles))
    request.state.permissions = sorted(set(p[0] if isinstance(p, tuple) else p for p in permissions))
    request.state.custodian_division_ids = [d.id for d in custodian_divisions]

    return user
```

**Hasil:** Dari 3-4 koneksi per request menjadi **1 koneksi per request** — throughput naik 3-4x.

---

## Refactor Recommendation

1. Hapus `_attach_roles_permissions_to_state()` dan `_attach_custodian_divisions_to_state()` setelah refactor
2. Hapus `_get_user_email_and_local_user()` yang tidak lagi diperlukan
3. Pertimbangkan caching roles/permissions di request.state level — tidak diperlukan DB round-trip jika informasi sudah tersedia di JWT claims
4. Tambahkan monitoring koneksi database via metrics endpoint

---

## Long-Term Improvement Recommendation

1. **Embed roles/permissions di JWT** — Sertakan roles/permissions dalam JWT payload saat token dibuat; `get_current_user()` tidak perlu query DB untuk ini sama sekali. Hanya fetch ulang saat token di-refresh.
2. **Connection pool monitoring** — Tambahkan metric untuk pool utilization, alert jika >80%
3. **Increase pool size** — Sebagai mitigasi sementara, naikkan `DATABASE_POOL_SIZE` dan `DATABASE_MAX_OVERFLOW`, namun ini bukan solusi arsitektur
4. **PgBouncer** — Implementasi connection pooler di level database untuk efisiensi lebih baik

---

_Related Finding: HIGH-004 berdiri sendiri tapi terkait dengan seluruh endpoint yang menggunakan `get_current_user`_
_Related API: Semua endpoint di `/api/_`yang memerlukan autentikasi*
*Related Table:`auth.users`, `auth.roles`, `auth.permissions`, `scd.custodian_divisions`\*
