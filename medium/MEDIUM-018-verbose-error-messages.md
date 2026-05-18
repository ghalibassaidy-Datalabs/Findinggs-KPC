# MEDIUM-018 — Verbose Error Messages Mengekspos Internal Detail

![Severity](https://img.shields.io/badge/Severity-MEDIUM-yellow)
![Module](https://img.shields.io/badge/Module-API%20%2F%20Error%20Handling-orange)
![Status](https://img.shields.io/badge/Status-Open-important)

---

## Executive Summary

Beberapa endpoint mengembalikan **raw exception messages** (`str(e)`) dalam API response body. Ini mengekspos detail internal seperti:

- Internal library names dan versi
- Network timeout messages (bocorkan internal service URLs)
- Database error messages (bocorkan schema/table names jika query error)
- Stack trace hints di debug mode

Selain itu, `DEBUG=True` di FastAPI menyebabkan **full Python stack trace** dikembalikan dalam response untuk unhandled exceptions.

---

## Technical Analysis

### Auth Endpoint — Raw Exception dalam Response

```python
# app/api/v1/auth.py

# 1. Token exchange error
except httpx.HTTPError as e:
    raise HTTPException(
        status_code=400,
        detail=AuthErrorResponse(
            error="token_exchange_failed",
            error_description=f"Failed to exchange code for tokens: {str(e)}",
            # ↑ str(e) bisa berisi: "ConnectTimeout: HTTPSConnectionPool(host='login.microsoftonline.com', port=443)"
            # → Bocorkan bahwa internal timeout terjadi, dan URL internal
        ).model_dump(),
    )

# 2. Token decode error
except Exception as e:
    raise HTTPException(
        status_code=400,
        detail=AuthErrorResponse(
            error="token_decode_failed",
            error_description=f"Failed to decode access token: {str(e)}",
            # ↑ str(e) bisa berisi: "JWTError: Signature verification failed"
            # → Bocorkan library yang digunakan (python-jose)
        ).model_dump(),
    )
```

### DEBUG=True — Full Stack Trace

```python
# app/core/config.py
debug: bool = Field(default=False, alias="DEBUG")

# app/main.py
app = FastAPI(
    debug=settings.debug,  # ← Jika DEBUG=True, unhandled exceptions → full traceback
)
```

Jika `DEBUG=True` di production (risk dari HIGH-014):

```json
// Response untuk unhandled exception
{
  "detail": "Internal Server Error",
  "traceback": [
    "  File '/app/app/services/scd/contracts_service.py', line 45, in create_contract",
    "    session.add(contract)",
    "  ...",
    "sqlalchemy.exc.IntegrityError: (psycopg2.errors.UniqueViolation) duplicate key value violates unique constraint"
  ]
}
```

### Verbose SQLAlchemy Error Messages

```python
# Jika database constraint violation terjadi dan tidak di-catch:
# "DETAIL:  Key (email)=(test@example.com) already exists." → bocorkan database field names
```

---

## Business Impact

| Impact                     | Detail                                                           |
| -------------------------- | ---------------------------------------------------------------- |
| **Information Disclosure** | Internal libraries, service URLs, DB schema details terekspos    |
| **Reconnaissance**         | Attacker memahami tech stack dan dependency versions             |
| **Targeted Exploitation**  | Dengan library version info, attacker bisa cari CVE yang relevan |
| **Debug Mode Risk**        | Stack trace → full codebase structure terekspos                  |

---

## Root Cause Analysis

Developer menggunakan `f"...{str(e)}"` untuk kemudahan debugging, tanpa mempertimbangkan bahwa exception message tidak boleh dikembalikan ke client di production.

---

## Evidence / Code Reference

```
app/api/v1/auth.py — callback(): 4 tempat menggunakan str(e) dalam response
app/core/config.py — debug default=False (tapi env.example DEBUG=true)
```

---

## Recommended Fix

### Fix: Sanitize Error Messages

```python
# app/api/v1/auth.py

import logging
logger = logging.getLogger(__name__)

# BEFORE (vulnerable)
except httpx.HTTPError as e:
    raise HTTPException(
        status_code=400,
        detail={"error": "token_exchange_failed", "error_description": f"Failed: {str(e)}"}
    )

# AFTER (fixed)
except httpx.HTTPError as e:
    logger.error(f"Token exchange failed: {e}", exc_info=True)  # ← Log internally
    raise HTTPException(
        status_code=400,
        detail={"error": "token_exchange_failed",
                "error_description": "Authentication service temporarily unavailable"}
        # ← Generic message untuk client
    )
```

### Fix: Disable Debug di Production (terkait HIGH-014)

```python
# app/main.py atau startup validation
if settings.environment == "production" and settings.debug:
    raise RuntimeError("DEBUG=True is not allowed in production")
```

### Fix: Global Exception Handler

```python
# app/main.py
from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Log detail error secara internal
    app_logger.error(f"Unhandled exception: {exc}", exc_info=True)

    # Return generic error ke client (tanpa detail internal)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. Please try again later."},
    )
```

---

## Long-Term Improvement Recommendation

1. **Error ID** — Return opaque error ID di response, log detail dengan ID tersebut
2. **Sentry/OpenTelemetry** — Error tracking yang tidak mengekspos ke client
3. **Error taxonomy** — Pisahkan user-facing messages dari technical details
4. **Security linting** — Lint rule untuk detect `str(e)` dalam HTTPException
