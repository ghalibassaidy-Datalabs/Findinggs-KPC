# MEDIUM-017 — Missing Security Response Headers (CSP, HSTS, X-Frame-Options)

![Severity](https://img.shields.io/badge/Severity-MEDIUM-yellow)
![Module](https://img.shields.io/badge/Module-HTTP%20Security%20%2F%20Headers-orange)
![Status](https://img.shields.io/badge/Status-Open-important)

---

## Executive Summary

Aplikasi **tidak mengkonfigurasi security response headers** yang diperlukan. FastAPI tidak menambahkan security headers secara default, dan tidak ada middleware yang menangani hal ini. Headers yang hilang:

| Header                      | Risk Tanpa Header                                                              |
| --------------------------- | ------------------------------------------------------------------------------ |
| `Content-Security-Policy`   | XSS via inline scripts atau external resource injection                        |
| `X-Frame-Options`           | Clickjacking — Swagger UI bisa di-embed di iframe berbahaya                    |
| `X-Content-Type-Options`    | MIME sniffing — browser menginterpretasi file upload berbeda dari content-type |
| `Strict-Transport-Security` | Downgrade attack dari HTTPS ke HTTP                                            |
| `Referrer-Policy`           | Token bocor via Referer header ke third-party resources                        |
| `Permissions-Policy`        | Browser features (camera, mic) tidak dibatasi                                  |

---

## Technical Analysis

### Tidak Ada Security Headers Middleware

```python
# app/main.py — tidak ada security headers
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # ...
)
# ← Tidak ada: SecurityHeadersMiddleware
# ← Tidak ada: X-Frame-Options, CSP, HSTS, dll.
```

### Verifikasi via HTTP Response

```bash
curl -I https://your-api.run.app/

# Response headers (vulnerable):
HTTP/2 200
content-type: application/json
x-process-time: 0.012      # ← Timing info (lihat finding terpisah)
x-request-id: uuid

# Headers yang TIDAK ada:
# strict-transport-security: max-age=31536000; includeSubDomains
# x-frame-options: DENY
# x-content-type-options: nosniff
# content-security-policy: default-src 'none'
# referrer-policy: strict-origin-when-cross-origin
# permissions-policy: geolocation=(), camera=(), microphone=()
```

### X-Process-Time Header — Timing Leakage

```python
# app/core/middleware.py
def _add_response_headers(self, response, process_time, request_id):
    response.headers["X-Process-Time"] = str(process_time)  # ← Timing info!
    response.headers["X-Request-ID"] = request_id
```

`X-Process-Time` mengekspos response time ke client, membantu attacker:

- Profiling endpoint performance untuk targeted DoS
- Timing-based user enumeration (`/auth/token` lebih lambat untuk valid users)
- Mendeteksi database query complexity

---

## Business Impact

| Impact                 | Detail                                            |
| ---------------------- | ------------------------------------------------- |
| **Clickjacking**       | Swagger UI bisa di-embed di halaman berbahaya     |
| **MIME Confusion**     | Upload HTML file bisa di-serve sebagai HTML → XSS |
| **Protocol Downgrade** | Tanpa HSTS, koneksi pertama bisa di-intercept     |
| **Timing Attacks**     | X-Process-Time membantu user enumeration          |
| **Compliance**         | OWASP A05:2021 Security Misconfiguration          |

---

## Root Cause Analysis

FastAPI tidak menambahkan security headers secara default (berbeda dengan beberapa framework lain). Developer tidak menambahkan security headers middleware karena tidak ada automated security check yang menangkapnya.

---

## Evidence / Code Reference

```
app/main.py              — Tidak ada security headers middleware
app/core/middleware.py   — X-Process-Time header (timing leakage)
```

---

## Reproduction / Testing Steps

```bash
# Scan dengan securityheaders.com
# Atau manual:
curl -sI https://your-api.run.app/ | grep -i "strict-transport\|x-frame\|x-content\|content-security\|referrer"
# Expected: Empty output (vulnerable — headers tidak ada)

# Test timing leakage
for i in {1..5}; do
  curl -s -o /dev/null -w "%{time_total}\n" https://your-api.run.app/api/v1/auth/token \
    -d "username=valid@kpc.com&password=wrong"
done
# Compare dengan username yang tidak ada → timing difference = user enumeration
```

---

## Risk Assessment

| Kriteria                    | Nilai        |
| --------------------------- | ------------ |
| **CVSS Score**              | 5.4 (Medium) |
| **Attack Vector**           | Network      |
| **Attack Complexity**       | Low          |
| **Privileges Required**     | None         |
| **Impact: Confidentiality** | Low-Medium   |
| **Exploitability**          | Medium       |

---

## Recommended Fix

### Fix: Tambahkan Security Headers Middleware

```python
# app/core/middleware.py — tambahkan class baru

from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Force HTTPS
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )

        # Referrer policy — prevent token leakage via Referer header
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Disable browser features not needed by API
        response.headers["Permissions-Policy"] = (
            "geolocation=(), camera=(), microphone=(), payment=()"
        )

        # CSP untuk API (restrictive — API tidak serve HTML, hanya JSON)
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'"
        )

        # Remove X-Process-Time (timing leakage) — atau batasi ke non-production
        if settings.environment == "production":
            response.headers.pop("X-Process-Time", None)

        return response
```

```python
# app/main.py — register middleware
from app.core.middleware import RequestLoggingMiddleware, SecurityHeadersMiddleware

app.add_middleware(SecurityHeadersMiddleware)  # ✅ Tambahkan ini
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(CORSMiddleware, ...)
```

---

## Long-Term Improvement Recommendation

1. **Automated header testing** — Tambahkan test yang verifikasi security headers ada di setiap response
2. **Cloud Armor** — Google Cloud Armor dapat menambahkan headers di layer load balancer
3. **Security audit baseline** — Gunakan [securityheaders.com](https://securityheaders.com) untuk benchmark reguler
4. **Separate API vs UI headers** — Jika serving HTML (Swagger), gunakan CSP yang lebih permissive untuk `/docs` saja
