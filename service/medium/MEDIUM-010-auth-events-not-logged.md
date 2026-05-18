# MEDIUM-010 — Auth Events Tidak Tercatat di Audit Log

![Severity](https://img.shields.io/badge/Severity-MEDIUM-yellow)
![Module](https://img.shields.io/badge/Module-Authentication%20%2F%20Audit-orange)
![Status](https://img.shields.io/badge/Status-Open-important)

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

Event-event autentikasi kritis tidak dicatat di audit log (`tracking.user_activity_logs`):

- **Login berhasil** via SSO atau JWT tidak di-log
- **Login gagal** (password salah, user tidak aktif) tidak di-log
- **Auto-create user baru** via SSO tidak di-log (lihat MEDIUM-007)
- **Logout** tidak di-log

Ketiadaan audit trail untuk event autentikasi berarti **tidak ada data forensik** jika terjadi insiden keamanan — tidak bisa menjawab pertanyaan: "Siapa yang login kapan? Dari mana? Berapa kali ada percobaan login gagal?"

---

## Technical Analysis

### Login Berhasil — Tidak Di-log

```python
# app/api/v1/auth.py — callback() dan login_for_access_token()
# Setelah login berhasil:
return Token(
    access_token=internal_access_token,
    ...
)
# ← TIDAK ada: UserActivityLogService.log_activity() call
```

### Login Gagal — Tidak Di-log

```python
# app/api/v1/auth.py — login_for_access_token()
if not user or not user.is_active or not user.password:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        # ← TIDAK ada: logging event "login_failed" ke audit trail
    )

if not verify_password(form_data.password, user.password):
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        # ← TIDAK ada: logging event "login_failed" ke audit trail
    )
```

### Logout — Tidak Di-log

```python
# app/api/v1/auth.py — logout()
@router.post("/logout")
async def logout(request: Request, redirect_uri: str = Query(None)):
    redirect_url = ...
    logout_url = ...
    return {"logout_url": logout_url}
    # ← TIDAK ada: UserActivityLogService.log_activity() call
```

### Infrastruktur Audit Log Sudah Ada — Tapi Tidak Digunakan

```python
# app/services/activity_users/user_activity_log_service.py — sudah ada!
class UserActivityLogService:
    @classmethod
    def log_activity(
        cls, session: Session, *, user_id, user_email, module, feature,
        action, description, ip_address=None, metadata_=None
    ):
        ...
```

Infrastruktur untuk audit logging sudah tersedia — hanya tidak dipanggil dari auth endpoints.

---

## Business Impact

| Dampak                               | Deskripsi                                                                           |
| ------------------------------------ | ----------------------------------------------------------------------------------- |
| **Tidak bisa investigasi insiden**   | Tidak ada data siapa yang login kapan, dari IP mana                                 |
| **Brute force tidak terdeteksi**     | Login gagal berulang tidak terekam (memperparah MEDIUM-009)                         |
| **Compliance failure**               | ISO 27001, SOC 2, dan banyak regulasi mensyaratkan audit trail untuk login events   |
| **Tidak bisa detect insider threat** | Tidak tahu apakah ada login di luar jam kerja atau dari lokasi tidak biasa          |
| **Forensik tidak valid**             | Jika ada data breach, investigasi tidak bisa menentukan kapan akses pertama terjadi |

---

## Real Use Case Scenario

### Skenario 1: Insiden Keamanan — Forensik Tidak Bisa Dilakukan

```
Situasi: Ditemukan data kontrak bocor ke pihak eksternal

Investigasi:
Q: "Siapa yang terakhir akses data kontrak tersebut?"
A: Tidak ada audit log login → tidak bisa tahu kapan user terakhir login

Q: "Apakah ada akses dari IP yang tidak biasa?"
A: Tidak ada logging IP di auth events

Q: "Berapa kali ada percobaan login gagal sebelum berhasil masuk?"
A: Login gagal tidak di-log sama sekali

Hasil: Investigasi buntu, tidak bisa menentukan vektor serangan
```

### Skenario 2: Brute Force Tidak Terdeteksi

```
1. Attacker mencoba 1000 kombinasi password untuk akun target
2. Semua percobaan gagal → HTTP 401 dikirim ke attacker
3. Percobaan ke-1001 berhasil → attacker masuk
4. Tanpa audit log: tidak ada catatan 1000 percobaan gagal
5. Security team tidak pernah tahu ada brute force yang terjadi
```

### Skenario 3: Akses Mencurigakan di Luar Jam Kerja

```
1. Akun karyawan digunakan login jam 03:00 pagi (dari luar negeri)
2. Akses data sensitif
3. Tanpa login audit log: tidak ada cara mendeteksi anomali ini
4. Dengan login audit log: bisa setup alert jika login di jam tidak biasa
```

---

## Root Cause Analysis

**Tipe masalah:** Missing audit instrumentation — infrastruktur ada, tidak digunakan di auth module

**Akar masalah:**

1. `UserActivityLogService` sudah ada dan berfungsi, tapi tidak di-import di `auth.py`
2. Auth endpoints (`auth.py`) dikembangkan secara terpisah dari logging infrastructure
3. Tidak ada coding standard atau checklist yang mensyaratkan auth event logging
4. IP address tidak di-pass ke `log_activity()` sehingga nilai forensiknya berkurang

---

## Evidence / Code Reference

| Item        | Detail                                                                                           |
| ----------- | ------------------------------------------------------------------------------------------------ |
| **File**    | `app/api/v1/auth.py` — `callback()`, `login_for_access_token()`, `logout()` — tidak ada log call |
| **Exists**  | `app/services/activity_users/user_activity_log_service.py` — logging service sudah ada           |
| **Exists**  | `tracking.user_activity_logs` — tabel sudah ada                                                  |
| **Missing** | Import `UserActivityLogService` di `auth.py`                                                     |
| **Missing** | `log_activity()` calls untuk login/logout events                                                 |

---

## Reproduction / Testing Steps

### Verifikasi Tidak Ada Auth Log

```bash
# Step 1: Login beberapa kali
for i in $(seq 1 3); do
  curl -s -X POST "http://localhost:8000/api/v1/auth/token" \
    -d "username=user@kpc.co.id&password=correct_pass" > /dev/null
done

# Step 2: Login gagal beberapa kali
for i in $(seq 1 3); do
  curl -s -X POST "http://localhost:8000/api/v1/auth/token" \
    -d "username=user@kpc.co.id&password=wrong_pass" > /dev/null
done

# Step 3: Logout
curl -s -X POST "http://localhost:8000/api/v1/auth/logout" \
  -H "Authorization: Bearer $TOKEN" > /dev/null

# Step 4: Verifikasi tidak ada log untuk events ini
psql $DATABASE_URL -c "
SELECT module, feature, action, user_email, created_at
FROM tracking.user_activity_logs
WHERE module = 'auth'
  AND action IN ('login_success', 'login_failed', 'logout')
ORDER BY created_at DESC
LIMIT 10;
"
# Expected (dengan logging): row per event
# Actual (tanpa logging): (0 rows)
```

---

## Risk Assessment

| Aspek                         | Nilai                                                                    |
| ----------------------------- | ------------------------------------------------------------------------ |
| **Severity**                  | MEDIUM                                                                   |
| **Urgency**                   | MEDIUM                                                                   |
| **Likelihood**                | CERTAIN — ini bukan "mungkin terjadi", ini SUDAH terjadi (tidak ada log) |
| **Impact if not fixed**       | Tidak bisa investigasi insiden, compliance failure                       |
| **Estimated Fix Complexity**  | LOW — tambah ~15 baris log calls ke auth.py                              |
| **Estimated Production Risk** | MEDIUM — compliance dan forensic risk                                    |

---

## Recommended Fix

### Tambahkan Logging ke Auth Endpoints

```python
# app/api/v1/auth.py
from app.services.activity_users.user_activity_log_service import UserActivityLogService

@router.post("/token", response_model=Token)
async def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    # Dapatkan IP address
    client_ip = request.client.host if request.client else None

    user = db.exec(
        select(User).where(User.email == form_data.username, User.is_active)
    ).first()

    if not user or not user.is_active or not user.password:
        # Log failed login
        UserActivityLogService.log_activity(
            session=db,
            user_id=None,
            user_email=form_data.username,
            module="auth",
            feature="authentication",
            action="login_failed",
            description=f"Login attempt failed for '{form_data.username}' — user not found or inactive",
            ip_address=client_ip,
            client_source="web",
        )
        raise HTTPException(status_code=401, detail="Incorrect username or password", ...)

    if not verify_password(form_data.password, user.password):
        # Log failed login
        UserActivityLogService.log_activity(
            session=db,
            user_id=user.id,
            user_email=user.email,
            module="auth",
            feature="authentication",
            action="login_failed",
            description=f"Login attempt failed for '{user.email}' — incorrect password",
            ip_address=client_ip,
            client_source="web",
        )
        raise HTTPException(status_code=401, detail="Incorrect username or password", ...)

    # ... create token ...

    # Log successful login
    UserActivityLogService.log_activity(
        session=db,
        user_id=user.id,
        user_email=user.email,
        module="auth",
        feature="authentication",
        action="login_success",
        description=f"User '{user.email}' logged in successfully via JWT",
        ip_address=client_ip,
        client_source="web",
    )

    return Token(...)
```

```python
# app/api/v1/auth.py — logout()
@router.post("/logout")
async def logout(
    request: Request,
    redirect_uri: str = Query(None),
    token: Optional[str] = Depends(oauth2_scheme),
    session: Session = Depends(get_db),
):
    client_ip = request.client.host if request.client else None
    user_email = None

    if token:
        try:
            payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
            user_email = payload.get("sub")
        except JWTError:
            pass

    if user_email:
        UserActivityLogService.log_activity(
            session=session,
            user_id=None,
            user_email=user_email,
            module="auth",
            feature="authentication",
            action="logout",
            description=f"User '{user_email}' logged out",
            ip_address=client_ip,
        )

    # ... return logout_url ...
```

---

## Refactor Recommendation

1. Buat `AuthAuditService` yang wraps `UserActivityLogService` khusus untuk auth events
2. Standarisasi action names: `login_success`, `login_failed`, `logout`, `token_refresh`, `password_reset`
3. Tambahkan field `device_info` di metadata untuk user-agent tracking

---

## Long-Term Improvement Recommendation

1. **SIEM Integration** — Kirim auth events ke Security Information and Event Management system
2. **Anomaly alerting** — Alert jika ada >5 login gagal dari IP yang sama dalam 10 menit
3. **Login from new location** — Notifikasi email ke user jika login dari IP/location yang belum pernah digunakan
4. **Session management dashboard** — Admin bisa melihat siapa yang sedang login dan dari mana

---

_Related Finding: MEDIUM-007 (Auto-create not logged), MEDIUM-009 (No rate limiting)_
_Related API: `POST /api/v1/auth/token`, `GET /api/v1/auth/callback`, `POST /api/v1/auth/logout`_
_Related Table: `tracking.user_activity_logs`, `auth.users`_
