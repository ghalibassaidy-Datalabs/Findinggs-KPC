# MEDIUM-008 — JWKS Azure Tidak Di-Cache (Fetch Ulang Setiap Login)

![Severity](https://img.shields.io/badge/Severity-MEDIUM-yellow)
![Module](https://img.shields.io/badge/Module-Authentication%20%2F%20Performance-orange)
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

Setiap kali user login via Azure AD SSO, backend melakukan **HTTP request ke endpoint Azure JWKS** (`login.microsoftonline.com/.../discovery/v2.0/keys`) untuk mengambil public keys yang digunakan untuk verifikasi JWT. Request ini dilakukan **setiap login, setiap kali**, tanpa caching.

Implikasinya: jika endpoint Azure JWKS **down, lambat, atau mengalami gangguan**, **seluruh login di aplikasi akan gagal** — termasuk semua user yang baru saja membuka aplikasi. Ini adalah **single point of failure** untuk seluruh fitur autentikasi.

---

## Technical Analysis

### Fungsi Fetch JWKS (Tidak Ada Cache)

```python
# app/core/security.py
async def get_azure_public_keys() -> Dict[str, Any]:
    """
    Fetch Azure AD public keys from JWKS endpoint for JWT verification.
    """
    jwks_url = f"https://login.microsoftonline.com/{settings.azure_tenant_id}/discovery/v2.0/keys"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(jwks_url)  # ← HTTP request ke Azure SETIAP KALI
            response.raise_for_status()
            return response.json()
    except Exception as e:
        app_logger.error(f"Failed to fetch Azure public keys: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch Azure public keys for token verification",
        )
        # ← TIDAK ada fallback ke cache lama jika fetch gagal
```

### Dipanggil Setiap Login

```python
# app/core/security.py
async def decode_azure_access_token(token: str) -> dict:
    ...
    jwks = await get_azure_public_keys()  # ← dipanggil setiap kali user login
    public_key = get_public_key_from_jwks(jwks, kid)
    ...
```

### Frekuensi Perubahan JWKS

Azure AD **jarang sekali merotasi keys** (biasanya setiap beberapa minggu hingga bulan). Namun aplikasi fetch setiap login, yang berarti:

- Setiap hari ada 100 login → 100 HTTP requests ke Azure yang tidak perlu
- JWKS response bisa di-cache aman selama minimal 1 jam tanpa risiko

---

## Business Impact

| Dampak                               | Deskripsi                                                                                  |
| ------------------------------------ | ------------------------------------------------------------------------------------------ |
| **Login down saat Azure bermasalah** | Gangguan sementara di Azure JWKS endpoint → semua user tidak bisa login                    |
| **Latency login meningkat**          | Setiap login menunggu HTTP roundtrip ke Microsoft (biasanya 200-500ms tambahan)            |
| **Unnecessary network dependency**   | Login menjadi bergantung pada koneksi internet ke Microsoft, bukan hanya ke server KPC     |
| **Resource waste**                   | Ribuan request identik ke Azure per hari yang bisa dihindari                               |
| **SLA tidak dapat dipenuhi**         | Jika Azure mengalami outage, KPC tidak bisa login meskipun infrastruktur KPC sendiri sehat |

---

## Real Use Case Scenario

### Skenario 1: Azure JWKS Endpoint Down

```
Jam 09:00 — semua karyawan mulai bekerja, buka aplikasi
    │
    ├─ Azure login.microsoftonline.com mengalami gangguan (ini memang terjadi)
    │   Lihat: https://status.azure.com/en-us/status
    │
    ├─ Setiap user yang mencoba login:
    │   GET https://login.microsoftonline.com/.../discovery/v2.0/keys
    │   → Connection timeout atau 503 Service Unavailable
    │
    ├─ Backend langsung throw HTTP 500:
    │   {"detail": "Failed to fetch Azure public keys for token verification"}
    │
    └─ SEMUA user tidak bisa login
       Padahal server KPC sendiri sehat 100%
```

### Skenario 2: Slow Response dari Azure (Bukan Down)

```
1. Azure JWKS endpoint lambat: response time 3-5 detik (biasanya ~100ms)
2. Setiap login user menunggu 3-5 detik hanya untuk fetch JWKS
3. Banyak user login bersamaan (pagi hari) → banyak koneksi ke Azure menggantung
4. Connection pool httpx habis atau request timeout
5. Login experience buruk / intermittent failure
```

### Skenario 3: Jaringan KPC ke Azure Terputus

```
1. Firewall atau router KPC bermasalah → koneksi ke external internet terputus
2. Semua fetch JWKS gagal
3. Semua login gagal
4. Tidak ada yang bisa masuk ke aplikasi
5. Jika JWKS di-cache: user yang sudah login bisa lanjut, dan login baru masih bisa
   menggunakan cached keys (yang valid karena Azure jarang rotasi)
```

---

## Root Cause Analysis

**Tipe masalah:** Missing caching — external dependency tanpa resilience

**Akar masalah:**

1. `get_azure_public_keys()` tidak menyimpan hasil fetch ke memory cache
2. Tidak ada TTL mechanism untuk menentukan kapan perlu fetch ulang
3. Tidak ada fallback: jika fetch gagal, langsung throw 500 tanpa mencoba dari cache
4. JWKS keys sangat stabil (berubah jarang) sehingga caching sangat aman diterapkan

---

## Evidence / Code Reference

| Item        | Detail                                                                                                    |
| ----------- | --------------------------------------------------------------------------------------------------------- |
| **File**    | `app/core/security.py` — fungsi `get_azure_public_keys()`                                                 |
| **File**    | `app/core/security.py` — fungsi `decode_azure_access_token()`                                             |
| **Pattern** | `async with httpx.AsyncClient() as client: response = await client.get(jwks_url)` — tidak ada cache layer |
| **Missing** | `cachetools.TTLCache` atau `functools.lru_cache` dengan TTL                                               |
| **Missing** | Fallback ke cached value jika fetch gagal                                                                 |

---

## Reproduction / Testing Steps

### Simulasi Azure JWKS Endpoint Down

```bash
# Step 1: Block akses ke Azure JWKS endpoint
sudo iptables -A OUTPUT -d login.microsoftonline.com -j DROP
# Atau di /etc/hosts: tambahkan "127.0.0.1 login.microsoftonline.com"

# Step 2: Coba login
curl -X GET "http://localhost:8000/api/v1/auth/callback?state=...&code=..."

# Expected (dengan caching): login berhasil menggunakan cached keys
# Actual (tanpa caching): HTTP 500 "Failed to fetch Azure public keys"

# Step 3: Restore
sudo iptables -D OUTPUT -d login.microsoftonline.com -j DROP
```

### Monitor Request ke Azure

```bash
# Monitor outgoing HTTP requests ke Azure
tcpdump -i any -n host login.microsoftonline.com

# Kirim beberapa request login
for i in $(seq 1 5); do
  curl -s "http://localhost:8000/api/v1/auth/callback?state=...&code=..." > /dev/null
done

# Expected (dengan cache): hanya 1 request ke Azure (subsequent dari cache)
# Actual (tanpa cache): 5 requests ke Azure untuk 5 login
```

---

## Risk Assessment

| Aspek                         | Nilai                                                   |
| ----------------------------- | ------------------------------------------------------- |
| **Severity**                  | MEDIUM                                                  |
| **Urgency**                   | MEDIUM — terjadi saat Azure mengalami gangguan          |
| **Likelihood**                | MEDIUM — Azure mengalami outage beberapa kali per tahun |
| **Impact if not fixed**       | Seluruh login gagal saat Azure JWKS bermasalah          |
| **Estimated Fix Complexity**  | LOW — tambahkan `cachetools.TTLCache` ~10 baris kode    |
| **Estimated Production Risk** | MEDIUM — availability risk                              |

---

## Recommended Fix

### Implementasi TTL Cache dengan Fallback

```python
# app/core/security.py
from cachetools import TTLCache
from threading import Lock
import time

# Cache JWKS selama 1 jam, maksimal 10 entries (biasanya cukup 1-2 per tenant)
_jwks_cache: TTLCache = TTLCache(maxsize=10, ttl=3600)
_jwks_fallback: dict = {}  # Cache fallback jika fetch gagal
_jwks_lock = Lock()

async def get_azure_public_keys() -> Dict[str, Any]:
    """
    Fetch Azure AD public keys from JWKS endpoint with TTL caching.
    - Cache TTL: 1 hour (keys change rarely)
    - Fallback: use last known good keys if fetch fails
    """
    cache_key = settings.azure_tenant_id

    # Cek cache terlebih dahulu
    with _jwks_lock:
        if cache_key in _jwks_cache:
            app_logger.debug("JWKS: served from cache")
            return _jwks_cache[cache_key]

    # Cache miss — fetch dari Azure
    jwks_url = (
        f"https://login.microsoftonline.com/{settings.azure_tenant_id}"
        "/discovery/v2.0/keys"
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(jwks_url)
            response.raise_for_status()
            jwks = response.json()

        # Simpan ke cache dan fallback
        with _jwks_lock:
            _jwks_cache[cache_key] = jwks
            _jwks_fallback[cache_key] = jwks

        app_logger.debug("JWKS: fetched from Azure and cached")
        return jwks

    except Exception as e:
        app_logger.error(f"Failed to fetch Azure public keys: {e}")

        # Coba gunakan fallback (last known good)
        if cache_key in _jwks_fallback:
            app_logger.warning(
                "JWKS: fetch failed, using cached fallback keys. "
                "This is acceptable if Azure is temporarily unavailable."
            )
            return _jwks_fallback[cache_key]

        # Tidak ada fallback — ini login pertama dan Azure down
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Authentication service temporarily unavailable. "
                "Please try again in a few minutes."
            ),
        )
```

### Tambahkan `cachetools` ke Dependencies

```toml
# pyproject.toml
[tool.poetry.dependencies]
cachetools = ">=5.3.0"
```

---

## Refactor Recommendation

1. Buat `JWKSClient` class yang encapsulates caching logic, lebih mudah di-mock dalam tests
2. Tambahkan metric untuk monitoring cache hit/miss rate
3. Pertimbangkan pre-warming cache saat aplikasi startup (`lifespan` event handler)

---

## Long-Term Improvement Recommendation

1. **Persist cache ke Redis** — Jika Redis sudah tersedia, gunakan sebagai JWKS cache yang shared antar instances
2. **Background key rotation detection** — Cek secara periodik (setiap jam) apakah keys berubah, bukan hanya saat ada login
3. **Health check endpoint** — Tambahkan `GET /health/auth` yang verifikasi koneksi ke Azure JWKS bisa dicapai
4. **Alerting** — Alert jika JWKS fetch gagal lebih dari N kali berturut-turut

---

_Related Finding: HIGH-001 (PKCE in-memory), HIGH-004 (DB Connection Pool)_
_Related API: `GET /api/v1/auth/callback`_
_Related External Service: `login.microsoftonline.com` Azure AD JWKS endpoint_
