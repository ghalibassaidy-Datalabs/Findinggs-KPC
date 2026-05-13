#!/usr/bin/env python3
"""
PoC Scripts — Setup & Token Generator
======================================
Jalankan SEKALI sebelum demo:

    python3 setup.py

Script ini akan:
  1. Install semua dependencies yang dibutuhkan
  2. Login ke DEV API dan dapatkan JWT token
  3. Inject token ke semua PoC scripts yang butuh auth
  4. Simpan token ke .env.poc untuk referensi
"""

import subprocess
import sys
import os
import re

# ──────────────────────────────────────────────
# KONFIGURASI — sesuaikan jika kredensial berubah
# ──────────────────────────────────────────────
API_BASE = "https://dev-api.genai.kpc.co.id/api/v1"
TEST_EMAIL = "test.fa.supervisor@gmail.com"
TEST_PASSWORD = "kpcprima"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

REQUIREMENTS = """requests>=2.31.0
PyJWT>=2.8.0
websockets>=12.0
"""

# ──────────────────────────────────────────────
# HELPER
# ──────────────────────────────────────────────
def banner(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")

def ok(msg):   print(f"  \033[92m✓\033[0m {msg}")
def fail(msg): print(f"  \033[91m✗\033[0m {msg}")
def info(msg): print(f"    {msg}")

# ──────────────────────────────────────────────
# STEP 1: Buat requirements.txt dan install
# ──────────────────────────────────────────────
banner("STEP 1 — Install Dependencies")

with open("requirements.txt", "w") as f:
    f.write(REQUIREMENTS)
ok("requirements.txt dibuat")

result = subprocess.run(
    [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"],
    capture_output=True, text=True
)
if result.returncode != 0:
    # Fallback: sistem Python yang tidak mengizinkan pip tanpa flag
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q",
         "--break-system-packages"],
        capture_output=True, text=True
    )
if result.returncode == 0:
    ok("Semua packages terinstall: requests, PyJWT, websockets")
else:
    fail("Install gagal — coba manual: pip3 install -r requirements.txt")
    info(result.stderr[-300:])
    sys.exit(1)

# ──────────────────────────────────────────────
# STEP 2: Login dan dapatkan token
# ──────────────────────────────────────────────
banner("STEP 2 — Login ke DEV API → Generate Token")

import requests  # noqa: E402 (import setelah install)

info(f"URL    : {API_BASE}/auth/token")
info(f"Email  : {TEST_EMAIL}")
info(f"Password: {'*' * len(TEST_PASSWORD)}")
print()

try:
    resp = requests.post(
        f"{API_BASE}/auth/token",
        data={"username": TEST_EMAIL, "password": TEST_PASSWORD},
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": BROWSER_UA,
        },
        timeout=15,
    )
except requests.exceptions.ConnectionError:
    fail("Tidak bisa terhubung ke DEV API. Cek koneksi internet.")
    sys.exit(1)

if resp.status_code != 200:
    fail(f"Login gagal: HTTP {resp.status_code}")
    info(resp.text[:200])
    sys.exit(1)

data = resp.json()
TOKEN = data["access_token"]
expires_in = data.get("expires_in", 86400)
user_info = data.get("user", {})

ok(f"Login berhasil!")
ok(f"User   : {user_info.get('full_name', TEST_EMAIL)}")
ok(f"Role   : {user_info.get('roles', ['N/A'])[0] if user_info.get('roles') else 'N/A'}")
ok(f"Token  : {TOKEN[:40]}...")
ok(f"Berlaku: {expires_in // 3600} jam ({expires_in} detik)")

# ──────────────────────────────────────────────
# STEP 3: Simpan token ke .env.poc
# ──────────────────────────────────────────────
banner("STEP 3 — Simpan Token ke .env.poc")

env_content = f"""# Token DEV — di-generate oleh setup.py
# Berlaku {expires_in // 3600} jam sejak login terakhir
# Re-generate dengan: python3 setup.py

DEV_TOKEN={TOKEN}
API_BASE={API_BASE}
TEST_EMAIL={TEST_EMAIL}
"""

with open(".env.poc", "w") as f:
    f.write(env_content)
ok(".env.poc tersimpan")
info("Gunakan di terminal: export $(cat .env.poc | grep -v '#' | xargs)")

# ──────────────────────────────────────────────
# STEP 4: Inject token ke scripts yang butuh auth
# ──────────────────────────────────────────────
banner("STEP 4 — Inject Token ke PoC Scripts")

def inject_token_in_file(filepath: str, pattern: str, replacement: str) -> bool:
    """Ganti satu baris config di file Python menggunakan regex."""
    if not os.path.exists(filepath):
        fail(f"File tidak ditemukan: {filepath}")
        return False
    with open(filepath, "r") as f:
        content = f.read()
    new_content, count = re.subn(pattern, replacement, content)
    if count == 0:
        fail(f"Pattern tidak ditemukan di {filepath} — skip")
        return False
    with open(filepath, "w") as f:
        f.write(new_content)
    return True

# HIGH-004: Inject ke variabel VALID_TOKEN
if inject_token_in_file(
    "HIGH-004-db-pool-exhaustion.py",
    r'VALID_TOKEN\s*=\s*"[^"]*"',
    f'VALID_TOKEN = "{TOKEN}"',
):
    ok("HIGH-004-db-pool-exhaustion.py  → VALID_TOKEN diupdate")

# HIGH-005: Tidak butuh token (justru demo TANPA token)
info("HIGH-005-websocket-no-auth.py    → skip (demo tanpa token, by design)")

# HIGH-002: Login sendiri pakai TEST_EMAIL/TEST_PASSWORD (sudah hardcoded, tidak perlu inject)
info("HIGH-002-token-still-valid-after-logout.py → skip (login otomatis via script)")

# MEDIUM-009: Login sendiri pakai password list (tidak butuh token valid)
info("MEDIUM-009-no-rate-limiting.py   → skip (tidak butuh token)")

# MEDIUM-011: Generate token palsu sendiri (tidak butuh token valid)
info("MEDIUM-011-jwt-token-forgery.py  → skip (generate token sendiri)")

# HIGH-006: Token dipass via argumen command line
info("HIGH-006-cors-demo.sh            → token dipass sebagai argumen CLI")

# ──────────────────────────────────────────────
# STEP 5: Ringkasan cara menjalankan
# ──────────────────────────────────────────────
banner("SETUP SELESAI — Cara Menjalankan Demo")

TOKEN_SHORT = TOKEN[:40] + "..."

print(f"""
  Token aktif: {TOKEN_SHORT}
  Berlaku    : {expires_in // 3600} jam

  ┌─────────────────────────────────────────────────────────┐
  │  URUTAN DEMO (Tier 1 — Paling Impactful)                │
  └─────────────────────────────────────────────────────────┘

  1. Token valid setelah logout (HIGH-002):
     python3 HIGH-002-token-still-valid-after-logout.py

  2. CORS wildcard + credentials (HIGH-006):
     bash HIGH-006-cors-demo.sh https://dev-api.genai.kpc.co.id \\
       "$(cat .env.poc | grep DEV_TOKEN | cut -d= -f2)"

  3. WebSocket tanpa auth (HIGH-005):
     python3 HIGH-005-websocket-no-auth.py
     (Butuh job_id dari browser DevTools — Network > WS tab)

  4. JWT forgery risk (MEDIUM-011):
     python3 MEDIUM-011-jwt-token-forgery.py

  ┌─────────────────────────────────────────────────────────┐
  │  URUTAN DEMO (Tier 2 — Lanjutan)                        │
  └─────────────────────────────────────────────────────────┘

  5. DB pool exhaustion (HIGH-004):
     python3 HIGH-004-db-pool-exhaustion.py --safe-mode

  6. No rate limiting (MEDIUM-009):
     python3 MEDIUM-009-no-rate-limiting.py --mode brute --attempts 10

  7. Auto-create user (MEDIUM-007):
     python3 MEDIUM-007-auto-create-demo.py

  ─────────────────────────────────────────────────────────
  Jika token expired (> {expires_in // 3600} jam), jalankan ulang: python3 setup.py
""")
