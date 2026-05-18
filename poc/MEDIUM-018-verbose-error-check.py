#!/usr/bin/env python3
"""
PoC: MEDIUM-018 — Verbose Error Messages Mengekspos Detail Internal
====================================================================
Demonstrasi bahwa endpoint autentikasi mengembalikan raw exception
message (str(e)) yang mengekspos detail infrastruktur internal.

TUJUAN DEMO:
  1. Trigger error di auth endpoint dengan input tidak valid
  2. Tangkap response — tunjukkan apakah ada detail internal yang bocor
  3. Dokumentasikan informasi apa yang bisa didapat attacker dari error

CARA MENJALANKAN:
  pip install requests
  python MEDIUM-018-verbose-error-check.py

SAFETY: Hanya kirim request dengan credential palsu/tidak valid.
        Tidak brute force — hanya 1 request per test case.
        Jalankan HANYA di environment DEV.
"""

import sys
import json

try:
    import requests
except ImportError:
    print("Install dulu: pip install requests")
    sys.exit(1)

# ──────────────────────────────────────────────
# KONFIGURASI
# ──────────────────────────────────────────────
API_BASE = "https://dev-api.genai.kpc.co.id/api/v1"

# Keyword yang menandakan bocornya info internal
SENSITIVE_KEYWORDS = [
    "traceback", "exception", "error:", "connectionerror",
    "timeout", "httpsconnectionpool", "microsoftonline",
    "login.microsoft", "sqlalchemy", "psycopg", "database",
    "internal server", "stack trace", "file \"", "line ",
    "at line", "caused by", "urllib", "httpx",
]


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


def analyze_response(response_body: str) -> list:
    """Cek apakah response mengandung info internal yang sensitif."""
    found = []
    body_lower = response_body.lower()
    for keyword in SENSITIVE_KEYWORDS:
        if keyword.lower() in body_lower:
            found.append(keyword)
    return found


def test_invalid_token_endpoint():
    separator("TEST 1: Token Exchange dengan Authorization Code Palsu")
    print("  Kirim code=INVALID_CODE ke /auth/token\n")

    url = f"{API_BASE}/auth/token"
    payload = {
        "code"         : "INVALID_AUTH_CODE_POC_TEST",
        "code_verifier": "INVALID_VERIFIER",
        "redirect_uri" : "https://attacker.example.com/callback",
        "state"        : "INVALID_STATE",
    }

    try:
        r = requests.post(url, json=payload, timeout=15)
        body = r.text

        print(f"  HTTP Status : {r.status_code}")
        print(f"  Response    :\n")

        try:
            parsed = json.loads(body)
            print(f"  {json.dumps(parsed, indent=4)[:800]}")
        except json.JSONDecodeError:
            print(f"  {body[:800]}")

        leaked = analyze_response(body)
        print()
        if leaked:
            print(f"  🔴 INFORMASI INTERNAL TERDETEKSI DI RESPONSE:")
            for kw in leaked:
                print(f"     - '{kw}' ditemukan")
            print(f"\n  Finding TERKONFIRMASI — MEDIUM-018")
        else:
            print(f"  ✅ Response generic — tidak ada info internal bocor")

    except requests.exceptions.ConnectionError:
        print(f"  ⚠️  Tidak dapat terhubung ke server")


def test_invalid_jwt_token():
    separator("TEST 2: Request dengan JWT yang Malformed")
    print("  Kirim JWT malformed ke endpoint protected\n")

    url   = f"{API_BASE}/users/me"
    token = "eyJhbGciOiJIUzI1NiJ9.INVALID_PAYLOAD.INVALID_SIGNATURE"

    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    body = r.text

    print(f"  HTTP Status : {r.status_code}")
    print(f"  Response    :\n")

    try:
        parsed = json.loads(body)
        print(f"  {json.dumps(parsed, indent=4)[:500]}")
    except json.JSONDecodeError:
        print(f"  {body[:500]}")

    leaked = analyze_response(body)
    if leaked:
        print(f"\n  🔴 Info bocor: {', '.join(leaked)}")
    else:
        print(f"\n  ✅ Error message generic dan aman")


def test_callback_with_invalid_state():
    separator("TEST 3: SSO Callback dengan State yang Tidak Ada")
    print("  Kirim callback dengan state=INVALID_STATE\n")

    url    = f"{API_BASE}/auth/callback"
    params = {
        "code" : "some_code",
        "state": "NONEXISTENT_STATE_POC_12345",
    }

    try:
        r = requests.get(url, params=params, timeout=15)
        body = r.text

        print(f"  HTTP Status : {r.status_code}")
        print(f"  Response    :\n")

        try:
            parsed = json.loads(body)
            print(f"  {json.dumps(parsed, indent=4)[:600]}")
        except json.JSONDecodeError:
            print(f"  {body[:600]}")

        leaked = analyze_response(body)
        if leaked:
            print(f"\n  🔴 Info internal bocor: {', '.join(leaked)}")
        else:
            print(f"\n  ✅ Response tidak mengandung info internal")

    except requests.exceptions.ConnectionError:
        print(f"  ⚠️  Tidak dapat terhubung ke server")


def show_impact():
    separator("CONTOH DAMPAK NYATA")
    print("""
  Jika server mengembalikan pesan seperti:
  ┌─────────────────────────────────────────────────────────────────┐
  │ "error_description": "Failed to exchange code for tokens:       │
  │  HTTPSConnectionPool(host='login.microsoftonline.com',          │
  │  port=443): Read timed out. (read timeout=30)"                  │
  └─────────────────────────────────────────────────────────────────┘

  Attacker mendapat informasi:
  → Internal timeout value (30 detik) → bisa craft timing attack
  → Library yang digunakan (httpx/requests) → cari known CVE
  → Internal service URL (login.microsoftonline.com) → peta infra
  → Request dapat di-timeout → potential DoS vector

  REKOMENDASI FIX:
  → app/api/v1/auth.py — ganti str(e) dengan pesan generic:
    raise HTTPException(status_code=400, detail={
        "error": "authentication_failed",
        "error_description": "Authentication failed. Please try again."
    })
  → Log detail asli hanya ke logger.exception() (server-side)
    """)


if __name__ == "__main__":
    print("=" * 60)
    print("  PoC MEDIUM-018 — Verbose Error Information Disclosure")
    print(f"  Target  : {API_BASE}")
    print("  Mode    : DEV ONLY — Input tidak valid (bukan brute force)")
    print("=" * 60)

    test_invalid_token_endpoint()
    test_invalid_jwt_token()
    test_callback_with_invalid_state()
    show_impact()
