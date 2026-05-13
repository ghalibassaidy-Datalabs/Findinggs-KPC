#!/usr/bin/env python3
"""
PoC: HIGH-004 — Database Connection Pool Exhaustion
====================================================
Simulasi concurrency test yang menyebabkan DB connection pool
habis sehingga request legitimate gagal dengan HTTP 500.

TUJUAN DEMO:
  Membuktikan bahwa dengan hanya 6 concurrent user, sistem sudah
  mengalami cascading failures karena setiap request mengonsumsi
  3-4 DB connections (pool size 5, max overflow 10 = 15 max).

CARA MENJALANKAN:
  pip install requests
  python HIGH-004-db-pool-exhaustion.py

SAFETY: Menggunakan GET requests read-only. Tidak menghapus/mengubah data.
        Hanya menunjukkan degradasi performa. Aman di DEV.
        Gunakan --safe-mode untuk mengurangi jumlah concurrent requests.
"""

import threading
import time
import sys
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
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

# Endpoint ringan yang butuh auth (butuh 3 DB connections via get_current_user)
# Ganti dengan endpoint yang tersedia di DEV environment
PROTECTED_ENDPOINTS = [
    "/auth/me",             # 3 DB connections: user lookup, roles, custodian divisions
]

# Token valid dari DEV (diperlukan untuk hit endpoint protected)
# Jalankan tanpa token untuk melihat error berbeda
VALID_TOKEN = "REPLACE_WITH_DEV_JWT_TOKEN"  # atau None untuk test tanpa auth


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def make_request(
    endpoint: str, token: str, request_id: int, results: list, lock: threading.Lock
):
    """Kirim satu request dan catat hasilnya."""
    url = f"{API_BASE}{endpoint}"
    headers = {}
    if token and token != "REPLACE_WITH_DEV_JWT_TOKEN":
        headers["Authorization"] = f"Bearer {token}"

    start = time.time()
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        elapsed = time.time() - start
        result = {
            "id": request_id,
            "status": resp.status_code,
            "elapsed": round(elapsed, 3),
            "success": resp.status_code == 200,
            "error": None,
        }
        if resp.status_code != 200:
            try:
                body = resp.json()
                result["error"] = body.get("detail", str(body))[:100]
            except Exception:
                result["error"] = resp.text[:100]
    except requests.exceptions.Timeout:
        elapsed = time.time() - start
        result = {
            "id": request_id,
            "status": 0,
            "elapsed": round(elapsed, 3),
            "success": False,
            "error": "TIMEOUT",
        }
    except requests.exceptions.ConnectionError as e:
        elapsed = time.time() - start
        result = {
            "id": request_id,
            "status": 0,
            "elapsed": round(elapsed, 3),
            "success": False,
            "error": f"CONNECTION_ERROR: {str(e)[:50]}",
        }

    with lock:
        results.append(result)
        icon = "\033[92m✓\033[0m" if result["success"] else "\033[91m✗\033[0m"
        status_color = "\033[91m" if not result["success"] else ""
        reset = "\033[0m"
        print(
            f"  {icon} Request #{request_id:3d} → "
            f"{status_color}HTTP {result['status']}{reset} "
            f"({result['elapsed']}s)"
            + (f" — {result['error']}" if result["error"] else "")
        )


def run_concurrent_test(n_concurrent: int, endpoint: str, token: str) -> list:
    """Jalankan N request secara bersamaan."""
    results = []
    lock = threading.Lock()

    print(f"\n  Mengirim {n_concurrent} request BERSAMAAN ke {endpoint}...")
    print(f"  (Setiap request = ~3 DB connections, pool max = 15)")
    print()

    start_time = time.time()

    with ThreadPoolExecutor(max_workers=n_concurrent) as executor:
        futures = [
            executor.submit(make_request, endpoint, token, i + 1, results, lock)
            for i in range(n_concurrent)
        ]
        for future in as_completed(futures):
            future.result()  # Propagate exceptions

    total_time = time.time() - start_time

    success_count = sum(1 for r in results if r["success"])
    fail_count = sum(1 for r in results if not r["success"])
    avg_time = sum(r["elapsed"] for r in results) / len(results) if results else 0

    print(f"\n  Selesai dalam {total_time:.2f}s total")
    print(f"  Berhasil: {success_count}/{n_concurrent}")
    print(f"  Gagal   : {fail_count}/{n_concurrent}")
    print(f"  Avg latency: {avg_time:.3f}s")

    return results


def analyze_results(all_results: dict):
    """Analisis hasil keseluruhan untuk presentasi."""
    separator("ANALISIS — HIGH-004 DB Connection Pool Exhaustion")

    print("\n  Summary per skenario:")
    print(f"  {'Concurrent':>12} | {'Success':>8} | {'Failed':>8} | {'Avg (s)':>8} | Status")
    print(f"  {'-'*12}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+--------")

    any_failure = False
    for n_concurrent, results in sorted(all_results.items()):
        success = sum(1 for r in results if r["success"])
        fail = sum(1 for r in results if not r["success"])
        avg = sum(r["elapsed"] for r in results) / len(results)

        if fail > 0:
            any_failure = True
            status = "\033[91mPOOL EXHAUSTED\033[0m"
        elif avg > 2.0:
            status = "\033[93mSLOW\033[0m"
        else:
            status = "\033[92mOK\033[0m"

        print(
            f"  {n_concurrent:>12} | {success:>8} | {fail:>8} | {avg:>8.3f} | {status}"
        )

    print()
    if any_failure:
        print("  \033[91m╔══════════════════════════════════════════════════╗\033[0m")
        print("  \033[91m║  VULNERABILITY CONFIRMED: Pool Exhaustion!      ║\033[0m")
        print("  \033[91m╚══════════════════════════════════════════════════╝\033[0m")

    print(
        """
  PENJELASAN TEKNIS:
  ┌─ Request ke endpoint protected (/auth/me, dll)
  │    └─ get_current_user() dipanggil
  │         ├─ session_scope() #1 → DB Connection untuk load user
  │         ├─ session_scope() #2 → DB Connection untuk roles/permissions
  │         └─ session_scope() #3 → DB Connection untuk custodian divisions
  │
  ├─ Pool size  = 5  koneksi
  ├─ Max overflow = 10 koneksi
  └─ TOTAL MAX   = 15 koneksi
  
  15 koneksi ÷ 3 per request = HANYA 5 REQUEST BERSAMAAN sebelum error!
  
  BUSINESS RISK:
  • Jam 08:00 — 10 karyawan buka dashboard → server error untuk 5 user
  • Saat audit/reporting — banyak user export data → cascade failures
  • Refresh browser saat error → lebih banyak request → makin parah
"""
    )


def main():
    parser = argparse.ArgumentParser(description="HIGH-004 DB Pool Exhaustion PoC")
    parser.add_argument(
        "--safe-mode",
        action="store_true",
        help="Gunakan jumlah request yang lebih rendah (max 10 concurrent)",
    )
    parser.add_argument(
        "--token",
        default=VALID_TOKEN,
        help="JWT token untuk autentikasi",
    )
    args = parser.parse_args()

    separator("HIGH-004 PoC — DB Connection Pool Exhaustion")
    print(
        """
  SKENARIO:
  Simulasi multiple user mengakses aplikasi bersamaan.
  Setiap request ke endpoint protected = 3 DB connections.
  
  PARAMETER:
  • DB Pool size: 5 (konfigurasi default)
  • Max overflow: 10 (konfigurasi default)
  • Total kapasitas: 15 koneksi
  • Threshold failure: 6+ concurrent requests
"""
    )

    endpoint = PROTECTED_ENDPOINTS[0]
    all_results = {}

    # Skenario bertahap: dari normal sampai exhausted
    if args.safe_mode:
        test_levels = [2, 4, 6, 8, 10]
    else:
        test_levels = [2, 5, 8, 12, 20]

    for n in test_levels:
        separator(f"Skenario: {n} Concurrent Users")
        print(
            f"  Harapan: {'OK (di bawah threshold)' if n * 3 <= 15 else 'GAGAL — pool exhausted!'}"
        )
        results = run_concurrent_test(n, endpoint, args.token)
        all_results[n] = results
        time.sleep(2)  # Cooldown sebelum test berikutnya

    analyze_results(all_results)

    separator("REKOMENDASI")
    print(
        """
  1. JANGKA PENDEK: Gabungkan 3 session_scope() menjadi 1 per request
     → Kapasitas meningkat dari 5 → 15 concurrent requests

  2. JANGKA MENENGAH: Naikkan pool_size dan max_overflow sesuai kebutuhan
     pool_size=20, max_overflow=40 → 60 koneksi total

  3. JANGKA PANJANG: Cache user data di Redis (TTL 5 menit)
     → DB query hanya untuk pertama kali, selanjutnya dari cache
     → Kapasitas jauh lebih tinggi
"""
    )


if __name__ == "__main__":
    main()
