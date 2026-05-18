#!/usr/bin/env python3
"""
PoC: MEDIUM-012 — Swagger / API Docs Terbuka Secara Publik
===========================================================
Demonstrasi bahwa endpoint dokumentasi API dapat diakses oleh
siapapun tanpa autentikasi — termasuk dari luar jaringan internal.

TUJUAN DEMO:
  1. Membuktikan /docs, /redoc, /openapi.json accessible tanpa token
  2. Mengekstrak daftar semua endpoint yang terekspos
  3. Mengekstrak skema request/response dan OAuth2 client config

CARA MENJALANKAN:
  pip install requests
  python MEDIUM-012-swagger-public-access.py

SAFETY: Hanya melakukan HTTP GET read-only.
        Tidak mengubah data apapun. AMAN dijalankan di DEV.
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
API_BASE = "https://dev-api.genai.kpc.co.id"

ENDPOINTS_TO_CHECK = [
    "/docs",
    "/redoc",
    "/openapi.json",
    "/oauth2-redirect",
]


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


def check_public_access():
    separator("TEST 1: Cek Akses Tanpa Token")
    results = []

    for path in ENDPOINTS_TO_CHECK:
        url = f"{API_BASE}{path}"
        try:
            r = requests.get(url, timeout=10, allow_redirects=True)
            status = r.status_code
            accessible = status == 200
            results.append((path, status, accessible))

            icon = "🔴 EXPOSED" if accessible else "✅ Protected"
            print(f"  {icon}  {path}  →  HTTP {status}")
        except requests.exceptions.ConnectionError:
            print(f"  ⚠️  {path}  →  Connection failed")
        except requests.exceptions.Timeout:
            print(f"  ⚠️  {path}  →  Timeout")

    return results


def extract_endpoints():
    separator("TEST 2: Ekstrak Semua Endpoint dari OpenAPI Schema")
    url = f"{API_BASE}/openapi.json"

    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            print(f"  ℹ️  /openapi.json tidak accessible (HTTP {r.status_code})")
            print("  → Finding TIDAK terkonfirmasi untuk endpoint ini")
            return

        schema = r.json()
        paths = schema.get("paths", {})

        print(f"\n  Total endpoint terekspos: {len(paths)}")
        print()

        # Kelompokkan per module
        modules = {}
        for path, methods in paths.items():
            module = path.split("/")[3] if len(path.split("/")) > 3 else "root"
            if module not in modules:
                modules[module] = []
            for method in methods.keys():
                if method in ["get", "post", "put", "patch", "delete"]:
                    modules[module].append(f"  {method.upper():7} {path}")

        for module, endpoints in sorted(modules.items()):
            print(f"  [{module.upper()}]")
            for ep in endpoints:
                print(ep)
            print()

    except json.JSONDecodeError:
        print("  ⚠️  Response bukan JSON valid")
    except requests.exceptions.ConnectionError:
        print("  ⚠️  Tidak dapat terhubung ke server")


def extract_oauth_config():
    separator("TEST 3: Ekstrak Konfigurasi OAuth2 / Azure AD dari Swagger")
    url = f"{API_BASE}/openapi.json"

    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return

        schema = r.json()

        # Cari security schemes
        components = schema.get("components", {})
        security_schemes = components.get("securitySchemes", {})

        if security_schemes:
            print("\n  🔴 Security scheme terekspos:")
            print(json.dumps(security_schemes, indent=4))
        else:
            print("  ℹ️  Tidak ada security scheme ditemukan di schema")

        # Cari info sensitif di root schema
        info = schema.get("info", {})
        print(f"\n  App Name    : {info.get('title', 'N/A')}")
        print(f"  App Version : {info.get('version', 'N/A')}")
        print(f"  Description : {info.get('description', 'N/A')[:100]}")

    except Exception as e:
        print(f"  ⚠️  Error: {e}")


def summary(results):
    separator("HASIL SUMMARY")
    exposed = [r for r in results if r[2]]
    protected = [r for r in results if not r[2]]

    print(f"  Endpoint terekspos : {len(exposed)}")
    print(f"  Endpoint protected : {len(protected)}")

    if exposed:
        print(f"\n  🔴 FINDING TERKONFIRMASI — MEDIUM-012")
        print(f"  Dokumentasi API dapat diakses publik tanpa autentikasi.")
        print(f"\n  Rekomendasi:")
        print(f"  → Set docs_url=None dan redoc_url=None di FastAPI")
        print(f"     jika settings.environment == 'production'")
    else:
        print(f"\n  ✅ Swagger sudah diproteksi dengan benar")


if __name__ == "__main__":
    print("=" * 60)
    print("  PoC MEDIUM-012 — Swagger Public Access")
    print(f"  Target: {API_BASE}")
    print("  Mode  : READ-ONLY — Tidak mengubah data apapun")
    print("=" * 60)

    results = check_public_access()
    extract_endpoints()
    extract_oauth_config()
    summary(results)
