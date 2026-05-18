# MEDIUM-009 — Tidak Ada Rate Limiting di Auth Endpoints

![Severity](https://img.shields.io/badge/Severity-MEDIUM-yellow)
![Module](https://img.shields.io/badge/Module-Authentication%20%2F%20Security-orange)
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

Tidak ada **rate limiting** di seluruh auth endpoints (`/auth/token`, `/auth/get-azure-sso-url`, `/auth/callback`). Ini memungkinkan:

1. **Brute force** pada `/auth/token` — attacker bisa mencoba ribuan password untuk satu akun tanpa batas
2. **State flooding** pada `/auth/get-azure-sso-url` — attacker bisa mengisi in-memory `auth_states` dict dengan jutaan entry, menyebabkan memory exhaustion (memperparah HIGH-001)
3. **DoS via callback** — attacker bisa spam request ke `/auth/callback` dengan state/code palsu, mengonsumsi koneksi database

---

## Technical Analysis

### Tidak Ada Rate Limiting

```python
# app/api/v1/auth.py — semua endpoint, tidak ada @limiter.limit() decorator

@router.get("/get-azure-sso-url", response_model=AuthLoginResponse)
async def get_azure_sso_url(request: Request, redirect_uri: str = None):
    # ← Tidak ada rate limit
    state = secrets.token_urlsafe(32)
    auth_states[state] = {...}  # ← Entry baru setiap request, tanpa batas
    ...

@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    # ← Tidak ada rate limit, tidak ada lockout setelah N gagal
    ...
    if not verify_password(form_data.password, user.password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
        # ← Response identik untuk username tidak ada vs password salah
        # (ini baik, tapi tanpa rate limit tetap vulnerable ke brute force)

@router.get("/callback")
async def callback(...):
    # ← Tidak ada rate limit
    # Setiap request ke sini query DB dan buat HTTP request ke Azure
    ...
```

### Tidak Ada Account Lockout

Tidak ada mekanisme untuk mengunci akun setelah N percobaan login gagal. Attacker bisa mencoba password tanpa batas.

---

## Business Impact

| Dampak                     | Deskripsi                                                                  |
| -------------------------- | -------------------------------------------------------------------------- |
| **Credential brute force** | Password akun bisa di-crack dengan automated tool tanpa batas              |
| **Memory exhaustion**      | State flooding di `auth_states` bisa menghabiskan RAM server               |
| **Database overload**      | Spam ke `/auth/callback` mengonsumsi DB connections (memperparah HIGH-004) |
| **DoS attack**             | Server tidak responsif untuk user legitimate karena resource habis         |
| **OWASP A07 violation**    | Authentication failure tidak dilindungi dari automated attacks             |

---

## Real Use Case Scenario

### Skenario 1: Credential Stuffing Attack

```
1. Attacker memiliki database email/password dari breach di website lain
2. Menjalankan tool seperti Hydra atau credential stuffing script:

   hydra -L emails.txt -P passwords.txt \
     http-post-form localhost:8000/api/v1/auth/token \
     "username=^USER^&password=^PASS^:Incorrect username"

3. 10.000 kombinasi dapat dicoba per menit tanpa rate limit
4. Beberapa akun yang menggunakan password yang sama di beberapa situs akan berhasil
5. Attacker mendapat akses ke data invoice, kontrak, dll.
```

### Skenario 2: State Flooding (Memory DoS)

```
1. Attacker menjalankan script sederhana:

   while true; do
     curl -s http://api.kpc.co.id/api/v1/auth/get-azure-sso-url > /dev/null
   done

2. Setiap request menambah entry baru ke auth_states dict
3. auth_states tumbuh tanpa batas: 1M entry × ~500 bytes = ~500 MB
4. Server kehabisan memory → OOM killer → aplikasi crash
```

### Skenario 3: Rate Limiting Abuse via Callback Spam

```
1. Attacker mengirim 1000 request ke /auth/callback dengan state/code palsu
2. Setiap request: query DB untuk lookup state + request ke Azure untuk token exchange
3. DB connection pool habis (memperparah HIGH-004)
4. User legitimate mendapat HTTP 500 saat melakukan request yang valid
```

---

## Root Cause Analysis

**Tipe masalah:** Missing security control — tidak ada protection terhadap automated attacks

**Akar masalah:**

1. Tidak ada `slowapi` atau middleware rate limiting yang diterapkan di auth endpoints
2. Tidak ada account lockout mechanism setelah gagal login berulang
3. Tidak ada IP-based blocking atau throttling
4. Tidak ada CAPTCHA untuk login endpoint

---

## Evidence / Code Reference

| Item           | Detail                                                                   |
| -------------- | ------------------------------------------------------------------------ |
| **File**       | `app/api/v1/auth.py` — semua endpoint, tidak ada rate limiting decorator |
| **File**       | `app/core/middleware.py` — cek apakah ada rate limiting middleware       |
| **Missing**    | `from slowapi import Limiter` atau equivalent                            |
| **Missing**    | Account lockout / failed attempt tracking                                |
| **Dependency** | `slowapi` tidak ada di `pyproject.toml`                                  |

---

## Reproduction / Testing Steps

### Simulasi Brute Force

```bash
# Menggunakan curl loop sederhana (bukan alat attacker profesional)
for i in $(seq 1 100); do
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "http://localhost:8000/api/v1/auth/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=target@kpc.co.id&password=wrong_password_$i")
  echo "Attempt $i: HTTP $HTTP_CODE"
done

# Expected (dengan rate limit): HTTP 429 setelah percobaan ke-5
# Actual (tanpa rate limit): HTTP 401 terus menerus, semua request dilayani
```

### Simulasi State Flooding

```bash
# Jalankan di background, monitor memory
for i in $(seq 1 1000); do
  curl -s "http://localhost:8000/api/v1/auth/get-azure-sso-url" > /dev/null
done

# Monitor memory process
while true; do
  ps aux | grep uvicorn | awk '{print $6}' # RSS memory
  sleep 1
done
```

### Verifikasi Tidak Ada Rate Limit Header

```bash
curl -v -X POST "http://localhost:8000/api/v1/auth/token" \
  -d "username=a@b.com&password=wrong" 2>&1 | grep -i "x-ratelimit\|retry-after\|429"

# Expected (dengan rate limit): headers X-RateLimit-Remaining, X-RateLimit-Reset
# Actual (tanpa rate limit): tidak ada header rate limit, tidak ada HTTP 429
```

---

## Risk Assessment

| Aspek                         | Nilai                                                         |
| ----------------------------- | ------------------------------------------------------------- |
| **Severity**                  | MEDIUM                                                        |
| **Urgency**                   | MEDIUM-HIGH                                                   |
| **Likelihood**                | MEDIUM — bots dan automated scanners selalu aktif di internet |
| **Impact if not fixed**       | Brute force berhasil, memory exhaustion, DoS                  |
| **Estimated Fix Complexity**  | LOW-MEDIUM — tambah slowapi ~20 baris kode                    |
| **Estimated Production Risk** | MEDIUM-HIGH                                                   |

---

## Recommended Fix

### Implementasi Rate Limiting dengan `slowapi`

```bash
# Tambahkan dependensi
poetry add slowapi
```

```python
# app/core/limiter.py (file baru)
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
```

```python
# app/main.py
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.limiter import limiter

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

```python
# app/api/v1/auth.py
from app.core.limiter import limiter

@router.post("/token", response_model=Token)
@limiter.limit("5/minute")  # ← 5 percobaan per menit per IP
async def login_for_access_token(
    request: Request,  # ← required untuk slowapi
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    ...

@router.get("/get-azure-sso-url", response_model=AuthLoginResponse)
@limiter.limit("20/minute")  # ← 20 SSO URL request per menit per IP
async def get_azure_sso_url(request: Request, redirect_uri: str = None):
    ...

@router.get("/callback", response_model=Token)
@limiter.limit("10/minute")  # ← Protect dari callback spam
async def callback(request: Request, ...):
    ...
```

### Implementasi Failed Login Tracking

```python
# app/api/v1/auth.py — dalam login_for_access_token()
from datetime import datetime, timezone, timedelta

# (Menggunakan Redis atau tabel DB sederhana)
FAILED_LOGIN_MAX = 5
LOCKOUT_DURATION_MINUTES = 15

async def _check_account_lockout(email: str, db: Session) -> None:
    """Cek apakah akun sedang di-lockout karena terlalu banyak gagal login."""
    # Hitung percobaan gagal dalam 15 menit terakhir
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=LOCKOUT_DURATION_MINUTES)
    failed_count = db.exec(
        select(func.count(UserActivityLog.id)).where(
            UserActivityLog.user_email == email,
            UserActivityLog.action == "login_failed",
            UserActivityLog.created_at >= cutoff,
        )
    ).one()

    if failed_count >= FAILED_LOGIN_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Account temporarily locked due to {failed_count} failed login attempts. "
                f"Try again in {LOCKOUT_DURATION_MINUTES} minutes."
            ),
        )
```

---

## Refactor Recommendation

1. Pisahkan rate limiting config ke `app/core/limiter.py`
2. Buat custom key function yang menggunakan kombinasi IP + email untuk bypass-resistant limiting
3. Pertimbangkan progressive backoff: setelah 3 gagal → 1 menit wait, setelah 5 gagal → 15 menit

---

## Long-Term Improvement Recommendation

1. **API Gateway Rate Limiting** — Implementasi rate limiting di level Azure API Management atau Nginx, bukan di aplikasi (lebih efisien untuk menangani traffic tinggi)
2. **CAPTCHA** — Tambahkan CAPTCHA untuk form login setelah N percobaan gagal
3. **Anomaly detection** — Alert jika ada IP yang melakukan >50 request/menit ke auth endpoints
4. **IP allowlist untuk `/auth/token`** — Jika JWT auth hanya untuk internal/staging, batasi via IP

---

_Related Finding: HIGH-001 (PKCE state flooding), HIGH-004 (DB pool exhaustion)_
_Related API: `POST /api/v1/auth/token`, `GET /api/v1/auth/get-azure-sso-url`, `GET /api/v1/auth/callback`_
_Related Table: `tracking.user_activity_logs` (untuk failed login tracking)_
