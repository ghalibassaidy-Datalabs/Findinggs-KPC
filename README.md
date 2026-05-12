# KPC App Backend — Security Audit Findings

> **Audit Date:** May 12, 2026
> **Scope:** Authentication module, WebSocket endpoints, CORS configuration, DB session management
> **Codebase:** `app/api/v1/auth.py`, `app/core/security.py`, `app/core/config.py`, `app/websockets/`
> **Total Findings:** 11 (6 HIGH, 5 MEDIUM)

---

## Table of Contents

- [Executive Summary](#executive-summary)
- [Severity Overview](#severity-overview)
- [Findings Summary Table](#findings-summary-table)
- [HIGH Findings](#high-findings)
- [MEDIUM Findings](#medium-findings)
- [Risk Matrix](#risk-matrix)
- [Recommended Fix Priority](#recommended-fix-priority)
- [Client-Friendly Summary](#client-friendly-summary)

---

## Executive Summary

Audit source code dilakukan terhadap modul autentikasi dan keamanan aplikasi KPC App Backend. Ditemukan **11 temuan** yang terbagi dalam 2 tingkat severity: **6 HIGH** dan **5 MEDIUM**.

Temuan HIGH utama meliputi:

- **PKCE state** tidak persisten (login bisa gagal massal saat deploy)
- **JWT tidak bisa di-revoke** setelah logout (akses masih aktif 24 jam)
- **Token disimpan di localStorage** (rentan XSS)
- **3 koneksi DB per request** di `get_current_user` (performance bottleneck)
- **WebSocket jobs** tidak ter-autentikasi (data sensitif bocor ke publik)
- **CORS wildcard + credentials** (konfigurasi berbahaya dan tidak valid)

Seluruh temuan HIGH bersifat **blocker untuk production** jika tidak ditangani.

---

## Severity Overview

```
HIGH   ████████████████████████  6 findings  (55%)
MEDIUM ████████████████████      5 findings  (45%)
LOW    ░░░░░░░░░░░░░░░░░░░░░░░░  0 findings  ( 0%)
```

---

## Findings Summary Table

| ID                                                                  | Severity  | Judul                                    | Modul              | Fix Complexity | Production Risk          |
| ------------------------------------------------------------------- | --------- | ---------------------------------------- | ------------------ | -------------- | ------------------------ |
| [HIGH-001](high/HIGH-001-pkce-state-in-memory.md)                   | 🔴 HIGH   | PKCE State di In-Memory Dict             | Auth / SSO         | MEDIUM         | HIGH                     |
| [HIGH-002](high/HIGH-002-jwt-no-token-blacklist.md)                 | 🔴 HIGH   | Logout Tidak Invalidate JWT              | Auth / Security    | MEDIUM         | HIGH                     |
| [HIGH-003](high/HIGH-003-jwt-localstorage.md)                       | 🔴 HIGH   | JWT Token di localStorage Browser        | Auth / Frontend    | HIGH           | HIGH                     |
| [HIGH-004](high/HIGH-004-db-connection-pool-exhaustion.md)          | 🔴 HIGH   | 3 DB Connection Per Request              | Performance / DB   | MEDIUM         | HIGH                     |
| [HIGH-005](high/HIGH-005-websocket-no-auth.md)                      | 🔴 HIGH   | WebSocket Jobs Tanpa Autentikasi         | WebSocket          | LOW            | HIGH                     |
| [HIGH-006](high/HIGH-006-cors-wildcard-credentials.md)              | 🔴 HIGH   | CORS Wildcard + credentials=True         | CORS / Security    | LOW            | HIGH                     |
| [MEDIUM-007](medium/MEDIUM-007-auto-create-no-domain-validation.md) | 🟡 MEDIUM | Auto-Create User Tanpa Domain Validation | Auth / User Mgmt   | LOW            | MEDIUM-HIGH              |
| [MEDIUM-008](medium/MEDIUM-008-jwks-not-cached.md)                  | 🟡 MEDIUM | JWKS Azure Tidak Di-Cache                | Auth / Performance | LOW            | MEDIUM                   |
| [MEDIUM-009](medium/MEDIUM-009-no-rate-limiting.md)                 | 🟡 MEDIUM | Tidak Ada Rate Limiting Auth Endpoints   | Auth / Security    | LOW-MEDIUM     | MEDIUM-HIGH              |
| [MEDIUM-010](medium/MEDIUM-010-auth-events-not-logged.md)           | 🟡 MEDIUM | Auth Events Tidak Tercatat di Audit Log  | Auth / Audit       | LOW            | MEDIUM                   |
| [MEDIUM-011](medium/MEDIUM-011-jwt-secret-empty-default.md)         | 🟡 MEDIUM | JWT_SECRET_KEY Default String Kosong     | Auth / Config      | LOW            | HIGH (jika tidak di-set) |

---

## HIGH Findings

### 🔴 HIGH-001 — PKCE State di In-Memory Dict

**File:** `app/api/v1/auth.py` — `auth_states: Dict[str, Dict[str, Any]] = {}`

State PKCE untuk SSO login disimpan di memori Python lokal. Setiap restart atau deploy menyebabkan semua user yang sedang di flow login gagal. Tidak bisa di-scale horizontal.

**Fix:** Pindahkan ke tabel `auth.pkce_states` di PostgreSQL dengan kolom `expires_at`.

> [→ Detail lengkap](high/HIGH-001-pkce-state-in-memory.md)

---

### 🔴 HIGH-002 — Logout Tidak Invalidate JWT

**File:** `app/api/v1/auth.py` — `logout()` function

Logout hanya return Azure logout URL. JWT internal tetap valid 24 jam meski user logout. Tidak ada token blacklist.

**Fix:** Tambahkan tabel `auth.revoked_tokens`, simpan `jti` saat logout, cek di setiap request.

> [→ Detail lengkap](high/HIGH-002-jwt-no-token-blacklist.md)

---

### 🔴 HIGH-003 — JWT Token di localStorage Browser

**File:** `app/api/v1/auth.py` — response `Token(access_token=...)`

Token dikembalikan di JSON response body → frontend menyimpan di localStorage → accessible oleh JavaScript → rentan XSS.

**Fix:** Kirim token via `Set-Cookie` dengan flag `HttpOnly; Secure; SameSite=Strict`.

> [→ Detail lengkap](high/HIGH-003-jwt-localstorage.md)

---

### 🔴 HIGH-004 — 3 DB Connection Per Request

**File:** `app/core/security.py` — `get_current_user()` dan helper functions

Setiap request membuka 3 `session_scope()` terpisah. Pool size 5 + overflow 10 = hanya 5 concurrent requests sebelum timeout.

**Fix:** Refactor `get_current_user()` untuk menerima satu `Session = Depends(get_db)` dan teruskan ke semua helper.

> [→ Detail lengkap](high/HIGH-004-db-connection-pool-exhaustion.md)

---

### 🔴 HIGH-005 — WebSocket Jobs Tanpa Autentikasi

**File:** `app/websockets/jobs.py` — `job_status_ws()`

`/ws/jobs/{job_id}` langsung `accept()` tanpa cek token. Siapapun yang tahu `job_id` bisa melihat hasil job (invoice OCR, bid analysis, dll).

**Fix:** Tambahkan validasi JWT sama seperti `chatbot_ws()` di `chatbot.py`.

> [→ Detail lengkap](high/HIGH-005-websocket-no-auth.md)

---

### 🔴 HIGH-006 — CORS Wildcard + credentials=True

**File:** `app/core/config.py` — `cors_origins=["*"]`, `cors_allow_credentials=True`

Default CORS mengizinkan semua origin dengan credentials. Melanggar CORS spec dan membuka potensi CSRF. Tidak ada startup validation.

**Fix:** Ubah default ke `[]`, tambahkan validator yang block startup di non-dev jika CORS_ORIGINS kosong atau `*`.

> [→ Detail lengkap](high/HIGH-006-cors-wildcard-credentials.md)

---

## MEDIUM Findings

### 🟡 MEDIUM-007 — Auto-Create User Tanpa Domain Validation

**File:** `app/api/v1/auth.py` — blok `if not user:` dalam `callback()`

Guest/contractor di Azure AD tenant otomatis dibuat di database tanpa validasi domain `@kpc.co.id` dan tanpa audit log.

**Fix:** Tambahkan domain whitelist check + `UserActivityLogService.log_activity()` saat auto-create.

> [→ Detail lengkap](medium/MEDIUM-007-auto-create-no-domain-validation.md)

---

### 🟡 MEDIUM-008 — JWKS Azure Tidak Di-Cache

**File:** `app/core/security.py` — `get_azure_public_keys()`

JWKS Azure di-fetch setiap login. Jika Azure bermasalah → semua login gagal. Tidak ada fallback ke cached keys.

**Fix:** Implementasi `cachetools.TTLCache` dengan TTL 1 jam + fallback ke last known good keys.

> [→ Detail lengkap](medium/MEDIUM-008-jwks-not-cached.md)

---

### 🟡 MEDIUM-009 — Tidak Ada Rate Limiting

**File:** `app/api/v1/auth.py` — semua auth endpoints

`/auth/token` bisa di-brute force. `/auth/get-azure-sso-url` bisa di-flood untuk memory DoS. Tidak ada account lockout.

**Fix:** Implementasi `slowapi` dengan limit `5/minute` untuk `/token`, `20/minute` untuk SSO endpoints.

> [→ Detail lengkap](medium/MEDIUM-009-no-rate-limiting.md)

---

### 🟡 MEDIUM-010 — Auth Events Tidak Di-log

**File:** `app/api/v1/auth.py` — `callback()`, `login_for_access_token()`, `logout()`

Login berhasil, login gagal, dan logout tidak dicatat di `tracking.user_activity_logs`. Infrastruktur logging sudah ada tapi tidak digunakan di auth module.

**Fix:** Panggil `UserActivityLogService.log_activity()` di setiap auth event dengan IP address.

> [→ Detail lengkap](medium/MEDIUM-010-auth-events-not-logged.md)

---

### 🟡 MEDIUM-011 — JWT_SECRET_KEY Default Kosong

**File:** `app/core/config.py` — `jwt_secret_key: str = Field(default="", ...)`

Jika `JWT_SECRET_KEY` tidak di-set di environment, aplikasi berjalan dengan secret kosong. Token bisa dipalsukan oleh siapapun.

**Fix:** Tambahkan validator yang mensyaratkan minimum 32 karakter di non-test environment. Startup error jika tidak di-set.

> [→ Detail lengkap](medium/MEDIUM-011-jwt-secret-empty-default.md)

---

## Risk Matrix

```
                    HIGH IMPACT    MEDIUM IMPACT   LOW IMPACT
HIGH LIKELIHOOD  │  H-001 H-004   H-006            -
                 │  H-005 M-009
MEDIUM LIKELIHOOD│  H-002 H-003   M-007 M-011      -
                 │  M-010
LOW LIKELIHOOD   │  M-008         -                 -
```

---

## Recommended Fix Priority

### Sprint 1 — Critical (1-2 minggu)

| Priority | Finding    | Kompleksitas | Alasan                                             |
| -------- | ---------- | ------------ | -------------------------------------------------- |
| P1       | HIGH-005   | LOW          | Immediate data exposure, fix mudah                 |
| P2       | HIGH-006   | LOW          | Fix konfigurasi sederhana                          |
| P3       | MEDIUM-011 | LOW          | Fix validasi sederhana, critical jika belum di-set |
| P4       | HIGH-001   | MEDIUM       | Login failure di setiap deploy                     |

### Sprint 2 — High Priority (2-4 minggu)

| Priority | Finding    | Kompleksitas | Alasan                              |
| -------- | ---------- | ------------ | ----------------------------------- |
| P5       | HIGH-004   | MEDIUM       | Performance bottleneck, scale issue |
| P6       | MEDIUM-007 | LOW          | Security + compliance               |
| P7       | MEDIUM-009 | LOW-MEDIUM   | Brute force protection              |
| P8       | MEDIUM-010 | LOW          | Audit trail untuk compliance        |

### Sprint 3 — Important (4-8 minggu)

| Priority | Finding    | Kompleksitas | Alasan                                |
| -------- | ---------- | ------------ | ------------------------------------- |
| P9       | HIGH-002   | MEDIUM       | Token revocation (butuh DB migration) |
| P10      | MEDIUM-008 | LOW          | Resilience improvement                |
| P11      | HIGH-003   | HIGH         | Koordinasi frontend diperlukan        |

---

## Client-Friendly Summary

### Apa yang Kami Temukan?

Tim engineering telah melakukan review mendalam terhadap kode sumber aplikasi KPC. Kami menemukan **11 area yang perlu diperbaiki** untuk meningkatkan keamanan dan performa sistem.

### Temuan Paling Penting

**1. Tombol "Logout" Belum Benar-Benar Logout**
Saat user menekan tombol logout, akun mereka sebenarnya masih bisa diakses oleh siapapun yang memiliki sesi login tersebut selama 24 jam ke depan. Bayangkan seperti meninggalkan kantor tapi pintu masih terbuka.

**2. Data Sensitif Bisa Dilihat Tanpa Login**
Proses pemrosesan dokumen (invoice, analisis harga tender) dapat dipantau oleh siapapun yang mengetahui nomor prosesnya — tanpa perlu login ke sistem.

**3. Semua Website Bisa Akses Data Kita**
Konfigurasi keamanan yang ada memungkinkan website manapun di internet untuk mengakses API kita menggunakan identitas user yang sedang login. Ini ibarat memberikan kunci rumah ke semua orang.

**4. Sistem Bisa Lambat/Down Saat Banyak Pengguna**
Setiap satu permintaan ke sistem membuka 3 koneksi ke database secara bersamaan. Dengan kapasitas yang ada, sistem bisa mengalami gangguan saat hanya 5 orang menggunakannya bersamaan.

**5. Kode Akses Bisa Kosong**
Ada risiko bahwa sistem berjalan tanpa kode rahasia untuk keamanan login — ibarat mengunci brankas dengan kata sandi kosong.

### Apa yang Perlu Dilakukan?

Semua temuan ini **bisa diperbaiki** dengan effort yang terukur. Sebagian besar perbaikan bisa diselesaikan dalam **2-4 minggu** sprint kerja. Tidak ada yang memerlukan perombakan total sistem.

Kami merekomendasikan untuk mulai dari temuan yang mudah diperbaiki namun berisiko tinggi (HIGH-005, HIGH-006, MEDIUM-011) di sprint pertama.

---

_Dokumen ini bersifat confidential — ditujukan untuk tim internal KPC dan vendor pengembang._
_Dilarang mendistribusikan tanpa izin._
