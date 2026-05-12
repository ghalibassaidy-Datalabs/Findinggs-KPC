# MEDIUM-007 — Auto-Create User Tanpa Domain Validation dan Audit Log

![Severity](https://img.shields.io/badge/Severity-MEDIUM-yellow)
![Module](https://img.shields.io/badge/Module-Authentication%20%2F%20User%20Management-orange)
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

Saat user pertama kali login via Azure AD SSO dan tidak ditemukan di database lokal, sistem **otomatis membuat akun baru** tanpa validasi apapun — termasuk:

- Tidak ada **validasi domain email** (siapapun di Azure AD tenant bisa masuk, termasuk guest/contractor)
- Tidak ada **notifikasi ke admin** bahwa akun baru dibuat
- Tidak ada **audit log** yang mencatat event auto-create
- Tidak ada **approval workflow** sebelum akun aktif

Artinya setiap akun yang ada di Azure AD tenant secara otomatis mendapat akses ke aplikasi KPC.

---

## Technical Analysis

### Blok Auto-Create yang Bermasalah

```python
# app/api/v1/auth.py — dalam fungsi callback()
user = session.exec(
    select(User).where(
        User.email == user_email.lower(),
        User.is_active,
    )
).first()

# Create user if they don't exist
is_new_user = False
if not user:
    user = User(
        email=user_email.lower(),
        full_name=user_email,
        is_active=True,      # ← langsung aktif!
        password=None,
        extension_attributes=None,
    )
    is_new_user = True
    session.add(user)
    session.commit()
    session.refresh(user)
    # ← TIDAK ada: domain check, notifikasi admin, audit log
```

**Apa yang terjadi setelah auto-create:**

- User mendapat akses ke aplikasi dengan token JWT valid
- User dapat mengakses semua endpoint yang tidak memerlukan role/permission spesifik
- Tidak ada jejak bahwa akun baru telah dibuat secara otomatis

---

## Business Impact

| Dampak                  | Deskripsi                                                                             |
| ----------------------- | ------------------------------------------------------------------------------------- |
| **Unauthorized access** | Guest atau contractor di Azure AD tenant mendapat akses ke aplikasi tanpa persetujuan |
| **Data exposure**       | User baru bisa melihat data yang seharusnya hanya untuk internal KPC                  |
| **Audit tidak valid**   | Tidak ada rekam jejak siapa yang auto-dibuat dan kapan                                |
| **Compliance risk**     | Banyak regulasi mensyaratkan explicit user provisioning dan approval workflow         |
| **Admin tidak tahu**    | Admin tidak mengetahui ada user baru yang masuk ke sistem                             |

---

## Real Use Case Scenario

### Skenario 1: Vendor/Contractor Auto-Access

```
1. KPC mengundang vendor/contractor sebagai guest di Azure AD tenant
   (misalnya untuk kolaborasi dokumen di Microsoft 365)
2. Vendor mencoba URL aplikasi KPC → klik "Login via SSO"
3. Login berhasil via Azure AD (mereka memang bagian dari tenant)
4. Backend auto-create user vendor di database KPC App
5. Vendor mendapat JWT token dan bisa akses aplikasi
6. Admin KPC tidak mengetahui bahwa vendor sudah masuk ke sistem
```

### Skenario 2: Mantan Karyawan yang Masih di Azure AD

```
1. Karyawan X mengundurkan diri → HR minta IT untuk menonaktifkan akun
2. IT menonaktifkan User.is_active = False di KPC App
3. IT lupa menghapus akun di Azure AD (proses offboarding tidak lengkap)
4. Karyawan X login via SSO → query by is_active=True → user tidak ditemukan
5. Blok auto-create: user baru dibuat dengan is_active=True
6. Karyawan X mendapat akses baru ke aplikasi!
```

### Skenario 3: Email Typo / Wrong Account

```
1. User login dengan akun personal yang tidak sengaja terdaftar di Azure AD
2. Auto-create membuat akun di KPC App
3. Akun "ghost" ini tidak pernah dipantau dan tidak memiliki role apapun
4. Secara teknikal bisa akses endpoint yang tidak memerlukan role spesifik
```

---

## Root Cause Analysis

**Tipe masalah:** Missing validation + missing access control di user provisioning

**Akar masalah:**

1. Tidak ada domain whitelist — tidak ada pengecekan `email.endswith("@kpc.co.id")`
2. Auto-create langsung menetapkan `is_active=True` tanpa approval
3. Tidak ada panggilan ke `UserActivityLogService` atau logging apapun saat user baru dibuat
4. Logika dibuat terlalu permisif untuk kemudahan development, tidak diperketat untuk production

---

## Evidence / Code Reference

| Item             | Detail                                                                  |
| ---------------- | ----------------------------------------------------------------------- |
| **File**         | `app/api/v1/auth.py` — blok `if not user:` dalam `callback()`           |
| **Baris kritis** | `is_active=True` — user langsung aktif saat dibuat                      |
| **Missing**      | Domain validation sebelum auto-create                                   |
| **Missing**      | `UserActivityLogService.log_activity()` call untuk event "user_created" |
| **Missing**      | Notifikasi admin atau approval flow                                     |

---

## Reproduction / Testing Steps

### Pre-condition

- Aplikasi berjalan dengan Azure AD dikonfigurasi
- Tersedia akun di Azure AD tenant yang belum ada di database KPC App

### Langkah Reproduce

```bash
# Step 1: Verifikasi user belum ada di DB
psql $DATABASE_URL -c "SELECT email, is_active, created_at FROM auth.users WHERE email = 'guest@external.com';"
# Expected: (0 rows)

# Step 2: Lakukan SSO login dengan akun yang belum ada di DB
# (Ikuti flow SSO normal di browser dengan akun guest)

# Step 3: Verifikasi user otomatis dibuat
psql $DATABASE_URL -c "SELECT email, is_active, created_at FROM auth.users WHERE email = 'guest@external.com';"
# Actual: (1 row) — user terbuat otomatis dengan is_active=true

# Step 4: Verifikasi tidak ada audit log
psql $DATABASE_URL -c "
SELECT * FROM tracking.user_activity_logs
WHERE action = 'user_created' OR feature = 'auto_create'
ORDER BY created_at DESC LIMIT 5;
"
# Actual: (0 rows) — tidak ada log
```

---

## Risk Assessment

| Aspek                         | Nilai                                                          |
| ----------------------------- | -------------------------------------------------------------- |
| **Severity**                  | MEDIUM                                                         |
| **Urgency**                   | MEDIUM-HIGH                                                    |
| **Likelihood**                | HIGH — terjadi setiap ada akun baru di Azure AD tenant         |
| **Impact if not fixed**       | Akses tidak sah, compliance violation, audit trail tidak valid |
| **Estimated Fix Complexity**  | LOW — tambah whitelist check + log call                        |
| **Estimated Production Risk** | MEDIUM-HIGH                                                    |

---

## Recommended Fix

### Tambahkan Domain Validation

```python
# app/api/v1/auth.py — dalam callback(), setelah mendapat user_email

ALLOWED_EMAIL_DOMAINS = [
    "@kpc.co.id",
    # tambahkan domain lain jika diperlukan
]

def _is_email_domain_allowed(email: str) -> bool:
    return any(email.lower().endswith(domain) for domain in ALLOWED_EMAIL_DOMAINS)

# ... di dalam callback():
if not _is_email_domain_allowed(user_email):
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=AuthErrorResponse(
            error="unauthorized_domain",
            error_description=(
                f"Email domain from '{user_email}' is not authorized to access this application. "
                "Please contact your administrator."
            ),
        ).model_dump(),
    )
```

### Tambahkan Audit Log untuk Auto-Create

```python
# app/api/v1/auth.py
from app.services.activity_users.user_activity_log_service import UserActivityLogService

if not user:
    user = User(
        email=user_email.lower(),
        full_name=user_email,
        is_active=True,
        password=None,
        extension_attributes=None,
    )
    is_new_user = True
    session.add(user)
    session.commit()
    session.refresh(user)

    # Log event auto-create
    UserActivityLogService.log_activity(
        session=session,
        user_id=user.id,
        user_email=user.email,
        module="auth",
        feature="user_management",
        action="auto_create",
        description=f"User {user.email} auto-created via SSO login",
        metadata_={"source": "azure_sso", "is_new_user": True},
    )

    app_logger.info(f"Auto-created new user: {user.email}")
```

### Tambahkan Konfigurasi Domain Whitelist

```python
# app/core/config.py
allowed_email_domains: list[str] = Field(
    default=["@kpc.co.id"],
    alias="ALLOWED_EMAIL_DOMAINS"
)
```

```bash
# env.example
ALLOWED_EMAIL_DOMAINS=["@kpc.co.id"]
# Untuk development: ALLOWED_EMAIL_DOMAINS=["@kpc.co.id","@developer.com"]
```

---

## Refactor Recommendation

1. Pindahkan logika auto-create ke `UserService.provision_sso_user()` yang terpisah
2. Tambahkan flag `is_provisioned_via_sso` di tabel `auth.users` untuk tracking
3. Pertimbangkan `is_active=False` + kirim notifikasi email ke admin untuk approval sebelum user bisa login

---

## Long-Term Improvement Recommendation

1. **Admin approval workflow** — User baru masuk dengan status "pending" sampai admin approve
2. **Notifikasi email admin** — Kirim email ke admin saat ada user baru auto-dibuat
3. **User provisioning rules** — Konfigurasi rules berbeda per domain: `@kpc.co.id` langsung aktif, `@vendor.com` perlu approval
4. **Azure AD Group mapping** — Hanya izinkan user dari Azure AD group tertentu (bukan semua akun di tenant)

---

_Related Finding: MEDIUM-010 (Auth Events Not Logged)_
_Related API: `GET /api/v1/auth/callback`_
_Related Table: `auth.users`, `tracking.user_activity_logs`_
