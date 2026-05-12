# HIGH-001 — PKCE State Disimpan di In-Memory Dict Python

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

State PKCE (Proof Key for Code Exchange) yang digunakan dalam alur login SSO Azure AD disimpan di dalam sebuah **dictionary Python biasa yang ada di memori aplikasi** (`auth_states: Dict[str, Dict[str, Any]] = {}`). Ini berarti:

- Setiap kali aplikasi di-restart atau di-deploy, **semua user yang sedang dalam proses login akan gagal** dan harus memulai ulang.
- Dalam arsitektur multi-instance (misalnya 2+ container berjalan bersamaan), **setiap instance memiliki state-nya sendiri** — request callback dari Azure bisa diterima oleh instance yang berbeda dari yang menerima request pertama, sehingga login selalu gagal.
- Tidak ada mekanisme expiry/cleanup, sehingga dictionary ini **terus membesar sepanjang waktu** (memory leak).

---

## Technical Analysis

Saat user memulai login SSO, aplikasi membuat `state` (token random 32 byte) dan menyimpan data terkait di `auth_states`:

```python
# app/api/v1/auth.py — module level (bukan database, bukan cache)
auth_states: Dict[str, Dict[str, Any]] = {}

@router.get("/get-azure-sso-url")
async def get_azure_sso_url(request: Request, redirect_uri: str = None):
    state = secrets.token_urlsafe(32)
    code_verifier = generate_code_verifier()
    ...
    auth_states[state] = {
        "redirect_uri": redirect_url,
        "code_verifier": code_verifier,
        "created_at": secrets.token_hex(16),  # ← bukan timestamp, tidak bisa di-expire
    }
```

Saat Azure mengembalikan callback, aplikasi mencari `state` di dictionary yang sama:

```python
@router.get("/callback")
async def callback(..., state: str = Query(...)):
    if state not in auth_states:       # ← gagal jika instance berbeda
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    stored_state = auth_states.pop(state)  # ← hanya di-pop dari memory lokal
```

**Masalah utama:**

- `auth_states` adalah **module-level variable** — hanya ada di memori satu proses Python
- `created_at` menyimpan **hex random**, bukan timestamp → tidak bisa menghitung expiry
- Tidak ada background task untuk membersihkan state yang sudah expired

---

## Business Impact

| Dampak                        | Deskripsi                                                                                             |
| ----------------------------- | ----------------------------------------------------------------------------------------------------- |
| **Login failure saat deploy** | Setiap rolling deploy atau restart container akan membuat semua user yang sedang login langsung gagal |
| **Tidak scalable**            | Sistem tidak bisa di-scale horizontal (multiple instances) karena state tidak dibagikan               |
| **Memory leak**               | State yang tidak pernah di-callback (abandoned flows) akan menumpuk selamanya                         |
| **User experience buruk**     | User yang mengalami gagal login tidak mendapat pesan error yang jelas, hanya "Invalid state"          |
| **Security risk**             | State yang tidak pernah dibersihkan bisa dieksploitasi dalam serangan replay jika ada kebocoran key   |

---

## Real Use Case Scenario

### Skenario 1: Rolling Deploy

```
1. User A di aplikasi frontend → klik "Login dengan SSO"
2. Backend (Instance 1) membuat state="abc123" → disimpan di auth_states Instance 1
3. Backend di-deploy → Instance 1 dimatikan, Instance 2 dijalankan
4. Azure AD selesai verifikasi → redirect ke /auth/callback?state=abc123
5. Instance 2 menerima request → auth_states Instance 2 KOSONG
6. Hasil: HTTP 400 "Invalid or expired state"
7. User harus login ulang dari awal
```

### Skenario 2: Load Balancer Multi-Instance

```
1. User B → Request ke Load Balancer → diteruskan ke Instance 1
   → state="xyz789" disimpan di Instance 1
2. Azure callback → Load Balancer → diteruskan ke Instance 2
   → auth_states Instance 2 tidak ada "xyz789"
3. Hasil: Login SELALU gagal dengan arsitektur horizontal scaling
```

### Skenario 3: Memory Leak

```
1. 1000 user membuka halaman login tapi tidak menyelesaikan login
   (tutup browser, timeout, dll)
2. auth_states terus bertambah: 1000 entri × ~500 bytes = ~500 KB
3. Setelah 1 bulan dengan 10.000 abandoned flows: ~5 MB wasted memory
4. Tidak ada cleanup → memory terus naik seiring waktu
```

---

## Root Cause Analysis

**Tipe masalah:** Architecture flaw — penggunaan in-memory state untuk flow yang membutuhkan persistence

**Akar masalah:**

1. State PKCE seharusnya disimpan di **persistent shared storage** (database/Redis), bukan di memori lokal proses
2. `created_at` menggunakan `secrets.token_hex(16)` (random hex) bukan `datetime.now()` sehingga expiry tidak bisa dihitung
3. Tidak ada `TTL` atau cleanup mechanism
4. Tidak ada pertimbangan untuk arsitektur multi-instance saat kode ini ditulis

---

## Evidence / Code Reference

| Item         | Detail                                                                                                                          |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| **File**     | `app/api/v1/auth.py`                                                                                                            |
| **Line**     | 40 — deklarasi `auth_states`                                                                                                    |
| **Function** | `get_azure_sso_url()` — menulis ke `auth_states`                                                                                |
| **Function** | `callback()` — membaca dan menghapus dari `auth_states`                                                                         |
| **Flow**     | `GET /auth/get-azure-sso-url` → `auth_states[state] = {...}` → Azure redirect → `GET /auth/callback` → `auth_states.pop(state)` |

**Code snippet yang bermasalah:**

```python
# app/api/v1/auth.py, line 40
auth_states: Dict[str, Dict[str, Any]] = {}  # ← in-memory, tidak persisten
```

```python
# app/api/v1/auth.py — dalam get_azure_sso_url()
auth_states[state] = {
    "redirect_uri": redirect_url,
    "code_verifier": code_verifier,
    "created_at": secrets.token_hex(16),  # ← bukan timestamp!
}
```

---

## Reproduction / Testing Steps

### Pre-condition

- Aplikasi berjalan dalam mode development single instance
- Azure AD SSO dikonfigurasi dan aktif

### Simulasi Instance Restart

```bash
# Step 1: Mulai flow login SSO
curl -X GET "http://localhost:8000/api/v1/auth/get-azure-sso-url" \
  -H "Accept: application/json"

# Response akan mengandung state, contoh:
# {"authorization_url": "https://login.microsoftonline.com/...", "state": "abc123xyz"}

# Step 2: Restart aplikasi (simulasi deploy)
# Ctrl+C server, lalu jalankan lagi

# Step 3: Simulate callback dengan state yang sama
curl -X GET "http://localhost:8000/api/v1/auth/callback?state=abc123xyz&code=dummy_code" \
  -H "Accept: application/json"

# Expected (seharusnya): valid state found, melanjutkan OAuth flow
# Actual (masalah): HTTP 400 {"error": "invalid_state", ...}
```

### Simulasi Multi-Instance

```bash
# Jalankan dua instance di port berbeda
uvicorn app.main:app --port 8000 &
uvicorn app.main:app --port 8001 &

# Get SSO URL dari Instance 1
curl -X GET "http://localhost:8000/api/v1/auth/get-azure-sso-url"
# state tersimpan hanya di Instance 1

# Kirim callback ke Instance 2
curl -X GET "http://localhost:8001/api/v1/auth/callback?state=<state_dari_instance1>&code=dummy"
# Hasil: HTTP 400 - Invalid state
```

### Simulasi Memory Leak

```bash
# Generate 1000 state tanpa callback
for i in $(seq 1 1000); do
  curl -s -X GET "http://localhost:8000/api/v1/auth/get-azure-sso-url" > /dev/null
done

# Cek memory usage process
ps aux | grep uvicorn
# Memory akan terus naik seiring iterasi
```

---

## Risk Assessment

| Aspek                         | Nilai                                                              |
| ----------------------------- | ------------------------------------------------------------------ |
| **Severity**                  | HIGH                                                               |
| **Urgency**                   | HIGH — akan menjadi masalah segera saat production di-scale        |
| **Likelihood**                | HIGH — terjadi setiap rolling deploy dan setiap horizontal scaling |
| **Impact if not fixed**       | Login gagal massal saat deploy, tidak bisa scale horizontal        |
| **Estimated Fix Complexity**  | MEDIUM — membutuhkan DB migration + refactor 2 fungsi              |
| **Estimated Production Risk** | HIGH — blocker untuk production stability                          |

---

## Recommended Fix

### Buat tabel `auth.pkce_states` di database:

```sql
CREATE TABLE auth.pkce_states (
    state         VARCHAR(64)  PRIMARY KEY,
    code_verifier TEXT         NOT NULL,
    redirect_uri  TEXT         NOT NULL,
    expires_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW() + INTERVAL '10 minutes',
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Index untuk cleanup expired states
CREATE INDEX idx_pkce_states_expires_at ON auth.pkce_states(expires_at);
```

### Update `get_azure_sso_url()`:

```python
from datetime import datetime, timezone, timedelta

@router.get("/get-azure-sso-url", response_model=AuthLoginResponse)
async def get_azure_sso_url(
    request: Request,
    redirect_uri: str = None,
    session: Session = Depends(get_db),
):
    state = secrets.token_urlsafe(32)
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)
    redirect_url = redirect_uri or str(request.base_url).rstrip("/") + "/api/v1/auth/callback"

    # Simpan ke database, bukan memory
    pkce_state = PKCEState(
        state=state,
        code_verifier=code_verifier,
        redirect_uri=redirect_url,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    session.add(pkce_state)
    session.commit()

    # ... build authorization_url ...
    return AuthLoginResponse(authorization_url=authorization_url, state=state)
```

### Update `callback()`:

```python
@router.get("/callback", response_model=Token)
async def callback(
    ...,
    state: str = Query(...),
    session: Session = Depends(get_db),
):
    # Query state dari database
    pkce_state = session.exec(
        select(PKCEState).where(
            PKCEState.state == state,
            PKCEState.expires_at > datetime.now(timezone.utc),
        )
    ).first()

    if not pkce_state:
        raise HTTPException(
            status_code=400,
            detail=AuthErrorResponse(
                error="invalid_state",
                error_description="Invalid or expired state parameter",
            ).model_dump(),
        )

    code_verifier = pkce_state.code_verifier
    redirect_url = pkce_state.redirect_uri

    # Hapus state setelah digunakan (one-time use)
    session.delete(pkce_state)
    session.commit()

    # ... lanjutkan token exchange ...
```

---

## Refactor Recommendation

1. Buat `PKCEState` sebagai SQLModel entity di `app/models/entities/auth/pkce_state.py`
2. Buat Alembic migration untuk tabel `auth.pkce_states`
3. Tambahkan background task atau cron job untuk membersihkan expired states:
   ```python
   # Jalankan setiap jam via Celery Beat
   @celery.task
   def cleanup_expired_pkce_states():
       with session_scope() as session:
           session.exec(
               delete(PKCEState).where(PKCEState.expires_at < datetime.now(timezone.utc))
           )
           session.commit()
   ```

---

## Long-Term Improvement Recommendation

1. **Redis sebagai alternatif** — Jika Redis sudah tersedia di stack, gunakan `redis.setex(state, 600, json.dumps(data))` untuk TTL otomatis
2. **Audit log** — Catat setiap PKCE state yang dibuat dan dikonsumsi ke `UserActivityLog`
3. **Rate limit** pada `/auth/get-azure-sso-url` untuk mencegah flood state (lihat MEDIUM-009)
4. **Monitoring** — Alert jika tabel `pkce_states` tumbuh tidak normal (indikasi abandoned flows yang tidak dibersihkan)

---

_Related Finding: MEDIUM-009 (No Rate Limiting on Auth Endpoints)_
_Related API: `GET /api/v1/auth/get-azure-sso-url`, `GET /api/v1/auth/callback`_
_Related Table: (akan dibuat) `auth.pkce_states`_
