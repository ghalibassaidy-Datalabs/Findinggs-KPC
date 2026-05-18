#!/usr/bin/env python3
"""
PoC: MEDIUM-017 — Missing Security Response Headers
====================================================
Verifikasi bahwa API tidak mengirimkan security headers standar
yang diperlukan untuk proteksi browser-level.

TUJUAN DEMO:
  1. Scan semua security headers yang seharusnya ada
  2. Identifikasi header yang missing
  3. Tunjukkan impact nyata dari setiap header yang hilang

CARA MENJALANKAN:
  pip install requests
  python MEDIUM-017-security-headers-check.py

SAFETY: Hanya HTTP GET — tidak mengubah data apapun.
"""

import sys

try:
    import requests
except ImportError:
    print("Install dulu: pip install requests")
    sys.exit(1)

# ──────────────────────────────────────────────
# KONFIGURASI
# ──────────────────────────────────────────────
API_BASE = "https://dev-api.genai.kpc.co.id"

# Header yang WAJIB ada beserta dampak jika tidak ada
REQUIRED_HEADERS = {
    "strict-transport-security": {
        "desc"   : "HSTS — Paksa HTTPS",
        "impact" : "Downgrade attack: attacker bisa paksa browser pakai HTTP dan intercept traffic",
        "example": "max-age=31536000; includeSubDomains",
    },
    "content-security-policy": {
        "desc"   : "CSP — Batasi sumber script/resource",
        "impact" : "XSS bebas load script dari domain manapun — injected script bisa curi data user",
        "example": "default-src 'self'; script-src 'self'",
    },
    "x-frame-options": {
        "desc"   : "Cegah Clickjacking via iframe",
        "impact" : "Halaman bisa di-embed di iframe — attacker buat overlay transparan untuk trick klik user",
        "example": "DENY",
    },
    "x-content-type-options": {
        "desc"   : "Cegah MIME Sniffing",
        "impact" : "Browser bisa interpretasikan file upload sebagai tipe berbeda — JS tersembunyi di PDF bisa dieksekusi",
        "example": "nosniff",
    },
    "referrer-policy": {
        "desc"   : "Kontrol informasi Referer header",
        "impact" : "URL sensitif (termasuk token di query param) bocor ke third-party resources via Referer header",
        "example": "strict-origin-when-cross-origin",
    },
    "permissions-policy": {
        "desc"   : "Batasi akses browser feature",
        "impact" : "Halaman dapat mengakses kamera, mikrofon, geolokasi tanpa izin eksplisit",
        "example": "camera=(), microphone=(), geolocation=()",
    },
    "x-process-time": {
        "desc"   : "Header internal timing (SEHARUSNYA TIDAK ADA)",
        "impact" : "Bocorkan waktu pemrosesan — membantu timing attack untuk user enumeration",
        "example": "Seharusnya DIHAPUS dari response",
        "should_be_absent": True,
    },
}

# Endpoint yang ditest
TEST_ENDPOINTS = [
    "/",
    "/api/v1/health",
    "/docs",
    "/openapi.json",
]


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


def check_headers_for_endpoint(url: str) -> dict:
    try:
        r = requests.get(url, timeout=10, allow_redirects=True)
        return dict(r.headers)
    except requests.exceptions.ConnectionError:
        return None
    except requests.exceptions.Timeout:
        return None


def analyze_headers(headers: dict, url: str):
    print(f"\n  URL: {url}\n")

    missing  = []
    present  = []
    warnings = []

    for header_name, info in REQUIRED_HEADERS.items():
        header_lower   = header_name.lower()
        found_in_resp  = None

        for k, v in headers.items():
            if k.lower() == header_lower:
                found_in_resp = v
                break

        should_be_absent = info.get("should_be_absent", False)

        if should_be_absent:
            if found_in_resp:
                warnings.append((header_name, found_in_resp, info))
                print(f"  ⚠️  HARUSNYA TIDAK ADA  {header_name}: {found_in_resp}")
                print(f"       Impact: {info['impact']}")
            else:
                print(f"  ✅ Tidak ada         {header_name}")
        else:
            if found_in_resp:
                present.append(header_name)
                print(f"  ✅ Ada               {header_name}: {found_in_resp[:60]}")
            else:
                missing.append((header_name, info))
                print(f"  🔴 MISSING           {header_name}")
                print(f"       Impact: {info['impact']}")

    return missing, present, warnings


def full_scan():
    separator("SCAN SECURITY HEADERS")

    all_missing = set()

    for path in TEST_ENDPOINTS:
        url     = f"{API_BASE}{path}"
        headers = check_headers_for_endpoint(url)

        if headers is None:
            print(f"\n  ⚠️  {url} — tidak dapat diakses, skip")
            continue

        missing, present, warnings = analyze_headers(headers, url)
        for m in missing:
            all_missing.add(m[0])

    return all_missing


def show_fix_recommendation(missing_headers: set):
    separator("REKOMENDASI FIX")

    if not missing_headers:
        print("  ✅ Semua security headers sudah terpasang dengan benar!")
        return

    print(f"  🔴 {len(missing_headers)} header missing — perlu ditambahkan\n")
    print("  Tambahkan middleware berikut di app/core/middleware.py:\n")
    print("  ┌─────────────────────────────────────────────────────┐")
    print("  │ class SecurityHeadersMiddleware(BaseHTTPMiddleware): │")
    print("  │   async def dispatch(self, request, call_next):     │")
    print("  │       response = await call_next(request)           │")
    print("  │       response.headers['X-Frame-Options'] = 'DENY'  │")
    print("  │       response.headers['X-Content-Type-Options'] =  │")
    print("  │           'nosniff'                                  │")
    print("  │       response.headers['Referrer-Policy'] =         │")
    print("  │           'strict-origin-when-cross-origin'         │")
    print("  │       response.headers['Strict-Transport-Security']  │")
    print("  │           = 'max-age=31536000; includeSubDomains'   │")
    print("  │       # Hapus X-Process-Time jika ada               │")
    print("  │       return response                               │")
    print("  └─────────────────────────────────────────────────────┘")
    print("\n  Daftarkan di app/main.py:")
    print("  app.add_middleware(SecurityHeadersMiddleware)")


if __name__ == "__main__":
    print("=" * 60)
    print("  PoC MEDIUM-017 — Security Headers Check")
    print(f"  Target  : {API_BASE}")
    print("  Mode    : READ-ONLY — Hanya HTTP GET")
    print("=" * 60)

    missing = full_scan()
    show_fix_recommendation(missing)

    separator("SUMMARY")
    print(f"  Header missing : {len(missing)}")
    if missing:
        print(f"  Finding        : 🔴 TERKONFIRMASI — MEDIUM-017")
    else:
        print(f"  Finding        : ✅ Tidak aktif — headers sudah ada")
