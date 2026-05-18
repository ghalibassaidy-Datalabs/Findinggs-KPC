# MEDIUM-012 — Swagger / OpenAPI Documentation Terbuka Secara Public

![Severity](https://img.shields.io/badge/Severity-MEDIUM-yellow)
![Module](https://img.shields.io/badge/Module-API%20%2F%20Exposure-orange)
![Status](https://img.shields.io/badge/Status-Open-important)

---

## Executive Summary

FastAPI secara otomatis mengekspos dokumentasi API di:

- `/docs` — Swagger UI (interaktif, bisa execute request)
- `/redoc` — ReDoc (read-only documentation)
- `/openapi.json` — Raw OpenAPI schema

**Tidak ada proteksi apapun** pada ketiga endpoint ini. Siapapun yang bisa mengakses base URL aplikasi — termasuk internet publik jika Cloud Run service dikonfigurasi `--allow-unauthenticated` — dapat melihat:

- Semua endpoint tersedia beserta HTTP method-nya
- Seluruh request/response schema (field names, types, validations)
- Authentication requirements dan OAuth2 flow detail
- Azure AD client configuration (OAuth2 scopes, client ID dari swagger init)
- Error response format (membantu reconnaissance)

---

## Technical Analysis

### FastAPI Default Behavior

```python
# app/main.py
app = FastAPI(
    title=settings.app_name,
    description="Backend API for KPC Application",
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
    swagger_ui_oauth2_redirect_url="/oauth2-redirect",
    swagger_ui_init_oauth={
        "usePkceWithAuthorizationCodeGrant": True,
        "clientId": settings.azure_openapi_client_id,  # ← Azure client ID terpublikasi
    },
)
# docs_url="/docs" dan redoc_url="/redoc" adalah default — tidak di-disable
```

### Informasi yang Terekspos

```json
// GET /openapi.json — contoh output
{
  "info": {"title": "KPC App Backend", "version": "0.1.0"},
  "paths": {
    "/api/v1/msd/equipment": {"get": {...}, "post": {...}},
    "/api/v1/scd/contracts": {"get": {...}, "post": {...}},
    "/api/v1/fin/invoices": {"get": {...}},
    "/api/v1/auth/token": {"post": {"requestBody": {"content": {...}}}},
    // ... semua endpoint dengan detail schema
  },
  "components": {
    "schemas": {
      "InvoiceCreate": {...},  // ← struktur data invoice
      "ContractCreate": {...}, // ← struktur data kontrak
      // ...
    }
  }
}
```

### Azure Client ID Terekspos di Swagger UI

```python
swagger_ui_init_oauth={
    "clientId": settings.azure_openapi_client_id,  # ← Exposed to public
}
```

Meskipun `azure_openapi_client_id` bukan secret (ini public client ID), eksposur ini memberikan informasi untuk Azure AD tenant reconnaissance.

---

## Business Impact

| Impact                | Detail                                                          |
| --------------------- | --------------------------------------------------------------- |
| **Reconnaissance**    | Attacker mendapatkan peta lengkap API surface tanpa perlu probe |
| **Schema Discovery**  | Struktur data internal (invoice, kontrak, equipment) terekspos  |
| **Auth Flow Mapping** | OAuth2 flow dan scopes yang digunakan terpublikasi              |
| **Targeted Attack**   | Attacker dapat merancang serangan yang tepat sasaran            |
| **Compliance**        | Best practice menyarankan docs tidak public di production       |

---

## Evidence / Code Reference

```
app/main.py — Line 40-53: FastAPI() tanpa docs_url=None, redoc_url=None
```

Endpoints yang accessible tanpa auth:

- `GET /docs`
- `GET /redoc`
- `GET /openapi.json`
- `GET /oauth2-redirect`

---

## Reproduction / Testing Steps

```bash
# Akses Swagger UI
curl -I https://your-production-url.run.app/docs
# Expected: HTTP 200 (vulnerable)

# Download full API schema
curl https://your-production-url.run.app/openapi.json | jq '.paths | keys'
# Output: List semua endpoint API
```

---

## Risk Assessment

| Kriteria                    | Nilai                          |
| --------------------------- | ------------------------------ |
| **CVSS Score**              | 5.3 (Medium)                   |
| **Attack Vector**           | Network                        |
| **Attack Complexity**       | Low                            |
| **Privileges Required**     | None                           |
| **Impact: Confidentiality** | Medium (API structure exposed) |
| **Impact: Integrity**       | None                           |
| **Exploitability**          | High (trivial to access)       |

---

## Recommended Fix

### Fix Option A: Disable Docs di Production

```python
# app/main.py
app = FastAPI(
    title=settings.app_name,
    # ✅ Disable docs di production
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url="/redoc" if settings.environment != "production" else None,
    openapi_url="/openapi.json" if settings.environment != "production" else None,
)
```

### Fix Option B: Proteksi dengan Authentication

```python
# app/main.py
from fastapi import Depends
from app.core.security import get_current_user

# Custom docs endpoint dengan auth
@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui(current_user=Depends(get_current_user)):
    from fastapi.openapi.docs import get_swagger_ui_html
    return get_swagger_ui_html(openapi_url="/openapi.json", title="KPC API")

app = FastAPI(
    docs_url=None,   # Disable default
    redoc_url=None,  # Disable default
)
```

### Fix Option C: IP Whitelist via Infrastructure

```yaml
# Cloud Run dengan Cloud Armor / Load Balancer
# Restrict /docs dan /redoc ke IP kantor saja
```

---

## Long-Term Improvement Recommendation

1. **Environment-based docs** — Docs hanya di development/staging, disable di production
2. **Internal-only URL** — Docs hanya accessible via VPN atau internal network
3. **Version in URL** — Gunakan `/v1/docs` sehingga lebih mudah dikontrol aksesnya
