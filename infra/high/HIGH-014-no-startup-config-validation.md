# HIGH-014 — Tidak Ada Startup Validation untuk Critical Secrets

![Severity](https://img.shields.io/badge/Severity-HIGH-red)
![Module](https://img.shields.io/badge/Module-Configuration%20%2F%20Secrets-orange)
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
10. [Long-Term Improvement Recommendation](#long-term-improvement-recommendation)

---

## Executive Summary

Aplikasi **tidak memiliki validasi startup** untuk memastikan secret-secret kritis telah dikonfigurasi sebelum menerima request. Ini menyebabkan dua kategori masalah berbahaya:

1. **Silent Fail dengan Secret Kosong**: Jika `JWT_SECRET_KEY=""` (sudah didokumentasikan di MEDIUM-011), `AZURE_APP_CLIENT_SECRET=""`, atau `PASSWORD_DIGEST=""`, aplikasi tetap berjalan — hanya saja dengan nilai yang tidak aman.

2. **Misconfiguration Tidak Terdeteksi**: Tidak ada mekanisme yang mencegah aplikasi berjalan di production dengan konfigurasi development (misal `DEBUG=True`, `USE_MAILHOG=True`, `CORS_ORIGINS=["*"]`).

Kombinasi keduanya berarti **deployment yang salah konfigurasi bisa berjalan di production tanpa ada peringatan atau kegagalan yang terlihat**.

---

## Technical Analysis

### 1. Semua Secret Punya Default Kosong

```python
# app/core/config.py
class Settings(BaseSettings):
    # Semua ini bisa kosong di production tanpa error startup
    jwt_secret_key: str = Field(default="", alias="JWT_SECRET_KEY")          # ← forge JWT
    password_digest: str = Field(default="", alias="PASSWORD_DIGEST")         # ← weak hashing
    azure_app_client_id: str = Field(default="", alias="AZURE_APP_CLIENT_ID") # ← auth bypass
    azure_app_client_secret: str = Field(default="", alias="AZURE_APP_CLIENT_SECRET") # ← impersonation
    azure_tenant_id: str = Field(default="", alias="AZURE_TENANT_ID")        # ← auth disabled
    azure_api_client_id: str = Field(default="", alias="AZURE_API_CLIENT_ID")
    azure_api_client_secret: str = Field(default="", alias="AZURE_API_CLIENT_SECRET")
    gcs_scd_bucket_name: str = Field(default="", alias="GCS_SCD_BUCKET_NAME") # ← storage fails silently
    google_project_id: str = Field(default="", alias="GOOGLE_PROJECT_ID")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")             # ← email fails silently
```

### 2. Tidak Ada Startup Validation di `lifespan()`

```python
# app/main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    app_logger.info("🚀 KPC App Backend starting up...")
    app_logger.info(f"Environment: {settings.environment}")
    app_logger.info(f"Debug mode: {settings.debug}")
    app_logger.info(f"Log level: {settings.log_level}")
    # ← Tidak ada pengecekan: "apakah JWT_SECRET_KEY kosong?"
    # ← Tidak ada pengecekan: "apakah kita di production dengan DEBUG=True?"
    # ← Tidak ada pengecekan: "apakah CORS_ORIGINS masih ['*'] di production?"

    yield
```

### 3. `JWT_AUTH_ENABLED` Default `False` — Auth Bisa Termatikan

```python
# app/core/config.py
jwt_auth_enabled: bool = Field(default=False, alias="JWT_AUTH_ENABLED")
# ← Jika env var ini tidak di-set di production, JWT auth TIDAK berjalan!
```

```python
# app/core/security.py (kemungkinan implementasi)
# Jika jwt_auth_enabled=False, semua endpoint mungkin tidak terproteksi
```

### 4. `DEBUG=True` di `env.example` — Risk of Accidental Production Deployment

```bash
# env.example
ENVIRONMENT=development
DEBUG=true          # ← FastAPI debug mode: full stack traces di response error
LOG_LEVEL=DEBUG     # ← Semua SQL queries dan request bodies dilog
USE_MAILHOG=true    # ← Email tidak terkirim ke real recipient
```

Jika developer menggunakan `env.example` langsung di server staging/production (skenario umum), semua setting berbahaya ini aktif.

---

## Business Impact

| Impact                         | Detail                                                           |
| ------------------------------ | ---------------------------------------------------------------- |
| **Auth Bypass**                | `jwt_auth_enabled=False` → seluruh API tanpa autentikasi         |
| **Token Forgery**              | `jwt_secret_key=""` → siapapun bisa forge token valid            |
| **Stack Trace Leakage**        | `debug=True` → internal code structure terekspos di API response |
| **Email Failure**              | `use_mailhog=True` di prod → notifikasi kontrak tidak terkirim   |
| **Invisible Misconfiguration** | Tidak ada alert → masalah diketahui setelah insiden              |

---

## Real Use Case Scenario

### Skenario: Staging Config Masuk ke Production

1. Developer set `JWT_AUTH_ENABLED=false` di staging untuk testing tanpa auth
2. Deployment ke production menggunakan variable group yang sama (Azure DevOps: `app-variables`)
3. Production berjalan tanpa JWT auth enforcement
4. Semua endpoint `/api/v1/...` dapat diakses tanpa token
5. Tidak ada error, tidak ada alert — hanya log "application started"

### Skenario: Env.Example Digunakan Langsung

1. Pipeline checkout kode dan menjalankan migration
2. `.env` file tidak ada, tapi `env.example` ter-copy sebagai `.env` (script error)
3. `JWT_SECRET_KEY=""`, `DEBUG=true`, `USE_MAILHOG=true` aktif di production
4. Semua JWT tokens bisa diforge
5. Stack traces dari exception muncul di API response

---

## Root Cause Analysis

Pydantic `BaseSettings` tidak memiliki mekanisme "required" field — semua field memiliki default value. Developer tidak mengimplementasikan `model_post_init` atau `@validator` untuk memvalidasi bahwa critical secrets telah dikonfigurasi.

---

## Evidence / Code Reference

```
app/core/config.py    — All secrets with default=""
app/main.py           — lifespan() tidak memiliki startup validation
env.example           — DEBUG=true, JWT_AUTH_ENABLED=False, USE_MAILHOG=true
```

---

## Reproduction / Testing Steps

```bash
# Test 1: Start app tanpa JWT_SECRET_KEY
export DATABASE_URL="postgresql://..."
# Tidak set JWT_SECRET_KEY
uvicorn app.main:app --host 0.0.0.0 --port 8080
# Result: App starts successfully ← VULNERABLE

# Test 2: Test dengan JWT_AUTH_ENABLED=false
export JWT_AUTH_ENABLED=false
# Akses protected endpoint
curl http://localhost:8080/api/v1/some-endpoint
# Result: Mungkin 200 OK tanpa Authorization header

# Test 3: Test DEBUG=true leak
export DEBUG=true
curl http://localhost:8080/api/v1/non-existent-endpoint
# Result: Full stack trace dalam response body
```

---

## Risk Assessment

| Kriteria                    | Nilai                                                      |
| --------------------------- | ---------------------------------------------------------- |
| **CVSS Score**              | 9.1 (Critical) — jika JWT_AUTH_ENABLED=false di production |
| **Attack Vector**           | Network                                                    |
| **Attack Complexity**       | Low                                                        |
| **Privileges Required**     | None                                                       |
| **Impact: Confidentiality** | High                                                       |
| **Impact: Integrity**       | High                                                       |
| **Impact: Availability**    | Low                                                        |
| **Exploitability**          | High                                                       |

---

## Recommended Fix

### Fix 1: Tambahkan Startup Validation di `lifespan()`

```python
# app/main.py
from fastapi import FastAPI
from contextlib import asynccontextmanager

def _validate_production_config():
    """Fail fast jika critical config tidak di-set di production."""
    errors = []

    if settings.environment in ("production", "staging"):
        # Critical secrets
        if not settings.jwt_secret_key:
            errors.append("JWT_SECRET_KEY harus di-set di production")
        if len(settings.jwt_secret_key) < 32:
            errors.append("JWT_SECRET_KEY harus minimal 32 karakter")
        if not settings.password_digest:
            errors.append("PASSWORD_DIGEST harus di-set di production")
        if not settings.azure_app_client_id:
            errors.append("AZURE_APP_CLIENT_ID harus di-set di production")
        if not settings.azure_app_client_secret:
            errors.append("AZURE_APP_CLIENT_SECRET harus di-set di production")
        if not settings.azure_tenant_id:
            errors.append("AZURE_TENANT_ID harus di-set di production")

        # Dangerous defaults
        if settings.debug:
            errors.append("DEBUG=True tidak boleh aktif di production")
        if settings.cors_origins == ["*"]:
            errors.append("CORS_ORIGINS tidak boleh ['*'] di production")
        if settings.use_mailhog:
            errors.append("USE_MAILHOG=True tidak boleh aktif di production")
        if not settings.jwt_auth_enabled:
            errors.append("JWT_AUTH_ENABLED=False tidak boleh di production")

    if errors:
        for err in errors:
            app_logger.critical(f"❌ STARTUP VALIDATION FAILED: {err}")
        raise RuntimeError(
            f"Application startup failed due to {len(errors)} configuration error(s). "
            "Check logs for details."
        )

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ✅ Validate config before starting
    _validate_production_config()

    app_logger.info("✅ Configuration validation passed")
    app_logger.info("🚀 KPC App Backend starting up...")
    # ...
    yield
```

### Fix 2: Gunakan Pydantic Validators untuk Critical Fields

```python
# app/core/config.py
from pydantic import Field, field_validator, model_validator

class Settings(BaseSettings):
    jwt_secret_key: str = Field(default="", alias="JWT_SECRET_KEY")

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret_not_empty_in_prod(cls, v, info):
        # Ini akan divalidasi saat startup jika ada logic environment-aware
        return v

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.environment in ("production", "staging"):
            required_secrets = {
                "JWT_SECRET_KEY": self.jwt_secret_key,
                "PASSWORD_DIGEST": self.password_digest,
                "AZURE_APP_CLIENT_SECRET": self.azure_app_client_secret,
                "AZURE_TENANT_ID": self.azure_tenant_id,
            }
            missing = [k for k, v in required_secrets.items() if not v]
            if missing:
                raise ValueError(
                    f"Critical secrets not configured for {self.environment}: "
                    f"{', '.join(missing)}"
                )
        return self
```

### Fix 3: Pisahkan env.example untuk Production

```bash
# .env.example.production — template untuk production
ENVIRONMENT=production
DEBUG=false
USE_MAILHOG=false
JWT_AUTH_ENABLED=true
CORS_ORIGINS=["https://kpc-app.yourdomain.com"]
# JWT_SECRET_KEY=<MUST_BE_SET_FROM_SECRET_MANAGER>
# etc.
```

---

## Long-Term Improvement Recommendation

1. **GCP Secret Manager** — Semua secret diambil dari Secret Manager saat startup, bukan dari env vars
2. **Secret rotation** — Implementasi rotasi JWT_SECRET_KEY dengan grace period
3. **Infrastructure as Code** — Terraform/Pulumi untuk mendefinisikan required env vars
4. **Startup probe** — Cloud Run startup probe yang memvalidasi konfigurasi sebelum menerima traffic
5. **Config audit log** — Log konfigurasi (tanpa nilai secret) saat startup untuk audit trail
