# MEDIUM-011 — `JWT_SECRET_KEY` Default Value String Kosong `""`

![Severity](https://img.shields.io/badge/Severity-MEDIUM-yellow)
![Module](https://img.shields.io/badge/Module-Authentication%20%2F%20Configuration-orange)
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

`JWT_SECRET_KEY` dikonfigurasi dengan **default value string kosong `""`**. Jika environment variable ini tidak di-set, aplikasi tetap berjalan normal dan akan **menandatangani semua JWT menggunakan secret key yang kosong**.

Ini berarti:

- Siapapun yang mengetahui format JWT bisa **memalsukan (forge) token** yang valid
- Token palsu dengan email user manapun bisa dibuat tanpa memiliki akun atau password
- Tidak ada error yang muncul — aplikasi berjalan seolah-olah aman

Hal yang sama berlaku untuk `PASSWORD_DIGEST` yang juga memiliki default `""`.

---

## Technical Analysis

### Default Value yang Bermasalah

```python
# app/core/config.py
class Settings(BaseSettings):
    # JWT Auth
    jwt_secret_key: str = Field(default="", alias="JWT_SECRET_KEY")
    # ↑ Default string kosong — TIDAK aman
    # Jika JWT_SECRET_KEY tidak di-set di .env, ini digunakan

    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_access_token_expire_minutes: int = Field(
        default=60 * 24, alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES"
    )
    jwt_auth_enabled: bool = Field(default=False, alias="JWT_AUTH_ENABLED")

    # Password Security
    password_digest: str = Field(default="", alias="PASSWORD_DIGEST")
    # ↑ Sama — default kosong
```

### Bagaimana Token Ditandatangani

```python
# app/core/security.py
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (...)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key,  # ← jika kosong "", digunakan string kosong sebagai secret
        algorithm=settings.jwt_algorithm
    )
    return encoded_jwt
```

**Jika `jwt_secret_key = ""`:**

```python
# Siapapun bisa memalsukan token dengan:
import jwt
from datetime import datetime, timezone, timedelta

fake_token = jwt.encode(
    {"sub": "admin@kpc.co.id", "exp": datetime.now(timezone.utc) + timedelta(days=365)},
    "",           # ← secret kosong yang sama!
    algorithm="HS256"
)
# fake_token akan diterima sebagai valid oleh backend
```

---

## Business Impact

| Dampak                          | Deskripsi                                                                             |
| ------------------------------- | ------------------------------------------------------------------------------------- |
| **Token forgery**               | Attacker bisa membuat token valid untuk akun siapapun tanpa password                  |
| **Total authentication bypass** | Seluruh sistem auth menjadi tidak berguna                                             |
| **Full data access**            | Dengan token palsu untuk admin, semua data bisa diakses                               |
| **Tidak ada indikasi**          | Tidak ada error log, tidak ada warning — sistem berjalan normal                       |
| **Password digest kosong**      | Hash password menjadi tidak environment-specific, melemahkan proteksi database breach |

---

## Real Use Case Scenario

### Skenario 1: Secret Key Tidak Di-set di Production

```
1. Developer baru deploy ke server staging baru
2. Copy .env.example, lupa set JWT_SECRET_KEY (field tidak ada di env.example atau dikosongkan)
3. Aplikasi start tanpa error
4. Semua token di-sign dengan secret ""
5. Attacker membuat token palsu untuk admin@kpc.co.id:

   import jwt
   token = jwt.encode(
     {"sub": "admin@kpc.co.id", "exp": ...},
     "",
     algorithm="HS256"
   )
   # Token diterima sebagai valid!

6. Attacker akses seluruh data dengan privilege admin
```

### Skenario 2: Secret Key Bocor/Lemah

```
Bahkan jika JWT_SECRET_KEY di-set, tapi:
- Menggunakan nilai pendek (misal "mysecret")
- Nilai mudah ditebak

Attacker bisa brute force secret key:
- Decode token (tanpa verifikasi): eyJ...
- Coba berbagai secret key sampai signature cocok
- Dengan empty string sebagai default: langsung berhasil

Tool seperti hashcat bisa crack weak JWT secrets dalam hitungan detik
```

---

## Root Cause Analysis

**Tipe masalah:** Insecure default configuration — fail-open by design

**Akar masalah:**

1. Field didefinisikan dengan `Field(default="", ...)` alih-alih `Field(...)` yang berarti required
2. Tidak ada `@validator` atau startup check yang memverifikasi key memiliki panjang dan entropi yang cukup
3. `jwt_auth_enabled = False` secara default — developer mungkin berasumsi JWT auth hanya aktif jika di-enable, namun token masih bisa dibuat/divalidasi meski flag ini False (SSO flow juga menggunakan `create_access_token`)
4. Masalah yang sama di `password_digest` — tanpa digest, hash password tidak environment-specific

---

## Evidence / Code Reference

| Item        | Detail                                                                                          |
| ----------- | ----------------------------------------------------------------------------------------------- |
| **File**    | `app/core/config.py` — `jwt_secret_key: str = Field(default="", ...)`                           |
| **File**    | `app/core/config.py` — `password_digest: str = Field(default="", ...)`                          |
| **File**    | `app/core/security.py` — `create_access_token()` menggunakan `settings.jwt_secret_key` langsung |
| **Missing** | Validator yang mensyaratkan minimum key length                                                  |
| **Missing** | Startup warning/error jika key kosong atau lemah                                                |

---

## Reproduction / Testing Steps

### Simulasi Token Forgery dengan Empty Secret

```bash
# Step 1: Verifikasi aplikasi menggunakan empty secret
python3 -c "
from app.core.config import settings
print(f'JWT_SECRET_KEY: \"{settings.jwt_secret_key}\"')
print(f'Length: {len(settings.jwt_secret_key)}')
"
# Output jika tidak di-set: JWT_SECRET_KEY: ""  Length: 0

# Step 2: Buat token palsu dengan secret kosong
python3 -c "
from jose import jwt
from datetime import datetime, timezone, timedelta

fake_token = jwt.encode(
    {
        'sub': 'admin@kpc.co.id',
        'exp': datetime.now(timezone.utc) + timedelta(hours=24)
    },
    '',  # secret kosong
    algorithm='HS256'
)
print('Forged token:', fake_token)
"

# Step 3: Gunakan token palsu
FORGED_TOKEN="<token dari step 2>"
curl -X GET "http://localhost:8000/api/v1/activity-logs" \
  -H "Authorization: Bearer $FORGED_TOKEN"

# Expected (secure): HTTP 401 Unauthorized
# Actual (vulnerable): HTTP 200 dengan data admin — AUTHENTICATION BYPASS!
```

### Verifikasi dengan `jwt_auth_enabled=False`

```bash
# Bahkan jika jwt_auth_enabled=False, SSO flow masih membuat token:
# Cek fungsi create_access_token dipanggil dari callback() SSO flow
grep -n "create_access_token" app/api/v1/auth.py
# Output menunjukkan token selalu dibuat untuk SSO login, terlepas dari jwt_auth_enabled
```

---

## Risk Assessment

| Aspek                         | Nilai                                                                          |
| ----------------------------- | ------------------------------------------------------------------------------ |
| **Severity**                  | MEDIUM (HIGH jika JWT_SECRET_KEY tidak di-set di production)                   |
| **Urgency**                   | HIGH — perlu divalidasi segera bahwa production sudah set nilai yang kuat      |
| **Likelihood**                | MEDIUM — bergantung pada kelengkapan environment setup                         |
| **Impact if not fixed**       | Total authentication bypass jika secret tidak di-set                           |
| **Estimated Fix Complexity**  | LOW — ubah `default=""` ke `Field(...)` + tambah validator                     |
| **Estimated Production Risk** | HIGH jika JWT_SECRET_KEY tidak di-set, LOW jika sudah di-set dengan nilai kuat |

---

## Recommended Fix

### Jadikan `JWT_SECRET_KEY` Required dengan Minimum Length

```python
# app/core/config.py
from pydantic import Field, field_validator, model_validator
import secrets

class Settings(BaseSettings):
    # JWT Auth
    jwt_secret_key: str = Field(
        default="",
        alias="JWT_SECRET_KEY",
        # Jangan pakai Field(...) agar tidak break test environment
        # Gunakan validator di bawah
    )

    password_digest: str = Field(
        default="",
        alias="PASSWORD_DIGEST",
    )

    @model_validator(mode="after")
    def validate_secrets(self) -> "Settings":
        # Validasi JWT_SECRET_KEY
        if self.environment not in ("test",):
            if not self.jwt_secret_key:
                raise ValueError(
                    "JWT_SECRET_KEY must be set. "
                    "Generate with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
                )
            if len(self.jwt_secret_key) < 32:
                raise ValueError(
                    f"JWT_SECRET_KEY is too short ({len(self.jwt_secret_key)} chars). "
                    "Minimum 32 characters required for security. "
                    "Generate with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
                )

            # Validasi PASSWORD_DIGEST
            if not self.password_digest:
                raise ValueError(
                    "PASSWORD_DIGEST must be set. "
                    "Generate with: python3 -c \"import secrets; print(secrets.token_hex(16))\""
                )

        return self
```

### Update `env.example` dengan Instruksi Jelas

```bash
# env.example

# JWT Secret Key — WAJIB di-set, minimum 32 karakter
# Generate: python3 -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET_KEY=GANTI_DENGAN_RANDOM_SECRET_MINIMAL_32_KARAKTER

# Password Digest — WAJIB di-set, minimum 16 karakter
# Generate: python3 -c "import secrets; print(secrets.token_hex(16))"
PASSWORD_DIGEST=GANTI_DENGAN_RANDOM_DIGEST_MINIMAL_16_KARAKTER
```

### Tambahkan Startup Warning untuk Development

```python
# app/main.py — dalam lifespan handler
@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.jwt_secret_key:
        app_logger.critical(
            "SECURITY WARNING: JWT_SECRET_KEY is not set! "
            "All JWT tokens can be forged. Set JWT_SECRET_KEY immediately."
        )
    elif len(settings.jwt_secret_key) < 32:
        app_logger.warning(
            f"SECURITY WARNING: JWT_SECRET_KEY is too short "
            f"({len(settings.jwt_secret_key)} chars, minimum 32). "
            "Please update JWT_SECRET_KEY to a stronger value."
        )
    yield
```

---

## Refactor Recommendation

1. Buat utility script untuk generate secrets: `python scripts/generate_secrets.py`
2. Tambahkan `make generate-secrets` di `Makefile`
3. Tambahkan check di CI/CD pipeline: pastikan production env tidak menggunakan default values

---

## Long-Term Improvement Recommendation

1. **Secret rotation** — Implementasi kemampuan untuk merotasi JWT_SECRET_KEY tanpa downtime (menggunakan multiple valid keys)
2. **HashiCorp Vault / Azure Key Vault** — Simpan secrets di dedicated secret manager, bukan environment variables
3. **Secrets scanning** — Gunakan tool seperti `detect-secrets` dalam pre-commit hooks untuk mencegah secret bocor ke repository
4. **Security checklist for deployments** — Buat deployment checklist yang mencakup verifikasi semua secrets telah di-set

---

_Related Finding: HIGH-002 (No Token Blacklist), HIGH-003 (JWT localStorage)_
_Related File: `app/core/config.py`, `app/core/security.py`, `env.example`_
_Related Table: N/A_
