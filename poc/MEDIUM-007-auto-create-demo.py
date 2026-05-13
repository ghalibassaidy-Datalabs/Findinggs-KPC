#!/usr/bin/env python3
"""
PoC: MEDIUM-007 — Auto-Create User Tanpa Domain Validation
==========================================================
Demonstrasi bahwa siapapun yang memiliki akun di Azure AD tenant
(termasuk guest/vendor/contractor) secara otomatis mendapat akun
di aplikasi KPC tanpa persetujuan admin.

TUJUAN DEMO:
  Membuktikan bahwa karyawan yang di-deactivate bisa mendapat akun baru,
  dan vendor yang diundang ke Azure AD bisa masuk ke KPC App.

CARA MENJALANKAN:
  (Ini adalah demonstration script — tidak memanggil API langsung)
  python MEDIUM-007-auto-create-demo.py

SAFETY: Script ini murni demonstrasi — menampilkan flow dan logic.
        Tidak memanggil endpoint manapun secara otomatis.
"""

import sys

# ──────────────────────────────────────────────
# KONFIGURASI
# ──────────────────────────────────────────────
API_BASE = "http://localhost:8000/api/v1"


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def demo_flow(title: str, steps: list, is_vulnerable: bool = True):
    """Tampilkan flow demo secara visual."""
    status = "\033[91m[VULNERABLE]\033[0m" if is_vulnerable else "\033[92m[EXPECTED]\033[0m"
    print(f"\n  {status} {title}")
    print(f"  {'─'*50}")
    for i, (icon, step) in enumerate(steps, 1):
        color = "\033[91m" if icon == "✗" else ("\033[92m" if icon == "✓" else "")
        reset = "\033[0m" if color else ""
        print(f"  {i}. {color}{icon} {step}{reset}")


def show_vulnerable_code():
    """Tampilkan code yang bermasalah."""
    print(
        """
  CODE YANG BERMASALAH (app/api/v1/auth.py):
  ─────────────────────────────────────────
  user = session.exec(
      select(User).where(
          User.email == user_email.lower(),
          User.is_active,
      )
  ).first()

  # Create user if they don't exist
  if not user:
      user = User(
          email=user_email.lower(),
          full_name=user_email,
          is_active=True,   # ← LANGSUNG AKTIF, tanpa approval
          password=None,
      )
      session.add(user)
      session.commit()
      # ← TIDAK ADA: domain validation
      # ← TIDAK ADA: admin notification
      # ← TIDAK ADA: audit log
      # ← TIDAK ADA: approval workflow
"""
    )


def show_manual_test_steps():
    """Langkah manual testing yang bisa dilakukan saat demo ke client."""
    separator("LANGKAH MANUAL TESTING (Demo ke Client)")
    print(
        """
  PRASYARAT:
  • Akses ke Azure AD tenant yang sama dengan KPC App
  • Akun yang TIDAK terdaftar di KPC App (bisa buat akun test baru)
  • Atau: akun vendor/guest yang diundang ke Azure AD tenant

  LANGKAH REPRODUKSI:
  ─────────────────────────────────────────────────────────

  SKENARIO A: Vendor/Guest mendapat akses otomatis
  ─────────────────────────────────────────────────
  1. Minta KPC IT buat akun guest di Azure AD (simulasi vendor)
     → pergi ke portal.azure.com → Users → New guest user
     → email: vendor.test@external-company.com

  2. Coba login ke KPC App DEV dengan akun guest:
     → Buka: https://ptkpc-dev.outsystems.app/KPC_WORKBENCH/
     → Klik "Login dengan SSO"
     → Login dengan akun guest

  3. Observasi:
     → Jika berhasil login → akun baru terbuat di DB
     → Admin tidak mendapat notifikasi apapun
     → User langsung aktif

  SKENARIO B: Karyawan yang di-nonaktifkan mendapat akun baru
  ────────────────────────────────────────────────────────────
  1. Pastikan ada akun test dengan is_active = False di DB DEV
     (atau buat via admin: nonaktifkan user X)

  2. Coba login dengan akun yang di-nonaktifkan:
     → Login via SSO

  3. Observasi:
     → Query: WHERE email = ? AND is_active = TRUE → NOT FOUND
     → Auto-create: user baru dibuat dengan is_active = TRUE
     → User berhasil login PADAHAL seharusnya sudah diblokir!

  SKENARIO C: Verifikasi via Database (setelah demo)
  ────────────────────────────────────────────────────
  Cek database setelah demo:
  SELECT * FROM auth.users ORDER BY created_at DESC LIMIT 5;
  → Lihat bahwa user baru terbuat tanpa approval

  Cek user_activity_logs:
  SELECT * FROM tracking.user_activity_logs
  WHERE action = 'auto_create';
  → TIDAK ADA log → tidak ada audit trail!
"""
    )


def show_curl_commands():
    """Tunjukkan bagaimana hasil bisa diverifikasi via API."""
    separator("VERIFIKASI VIA API (Butuh Admin Token)")
    print(
        """
  # 1. Lihat daftar user terbaru (perlu admin token)
  curl -s -H "Authorization: Bearer ADMIN_TOKEN" \\
    http://localhost:8000/api/v1/users/ | \\
    python3 -m json.tool | head -50

  # 2. Cek apakah ada user yang created_at hari ini
  curl -s -H "Authorization: Bearer ADMIN_TOKEN" \\
    "http://localhost:8000/api/v1/users/?sort_by=created_at&order=desc" | \\
    python3 -m json.tool

  # 3. Cek activity log untuk verifikasi ketidakhadiran audit trail
  curl -s -H "Authorization: Bearer ADMIN_TOKEN" \\
    "http://localhost:8000/api/v1/activity-logs/?action=login" | \\
    python3 -m json.tool
"""
    )


def main():
    separator("MEDIUM-007 PoC — Auto-Create User Without Domain Validation")
    print(
        """
  SKENARIO:
  Setiap akun Azure AD yang masuk ke tenant KPC (termasuk guest)
  secara otomatis mendapat akun di KPC App tanpa persetujuan admin.

  YANG AKAN DIBUKTIKAN:
  1. Vendor yang diundang ke Azure AD bisa akses KPC App
  2. Karyawan yang di-nonaktifkan mendapat akun baru via re-login
  3. Tidak ada audit trail untuk event auto-create
"""
    )

    show_vulnerable_code()

    separator("SKENARIO 1 — Vendor Auto-Access")
    demo_flow(
        "Vendor mendapat akses KPC App tanpa persetujuan admin",
        [
            ("→", "KPC mengundang vendor sebagai guest di Microsoft 365"),
            ("→", "Vendor mencoba buka URL KPC App DEV"),
            ("→", "Vendor klik 'Login via SSO'"),
            ("→", "Azure AD berhasil autentikasi (mereka memang bagian tenant)"),
            ("→", "Backend cek: ada user di DB? → TIDAK ADA"),
            ("✗", "Backend AUTO-CREATE: user baru dibuat, is_active=True"),
            ("✗", "Vendor mendapat JWT token valid"),
            ("✗", "Admin KPC tidak mendapat notifikasi APAPUN"),
            ("✗", "Tidak ada approval, tidak ada audit log"),
        ],
    )

    separator("SKENARIO 2 — Bypassing User Deactivation")
    demo_flow(
        "Karyawan yang di-nonaktifkan mendapat akun baru",
        [
            ("→", "Admin KPC: set is_active = False untuk user X (resign)"),
            ("✓", "User X coba login normal → DITOLAK (is_active = False)"),
            ("→", "... tapi user X masih ada di Azure AD tenant!"),
            ("→", "User X logout dan login ulang via SSO flow"),
            ("→", "Backend query: WHERE email = ? AND is_active = TRUE → NOT FOUND"),
            ("✗", "Backend AUTO-CREATE: akun BARU dibuat untuk email yang sama!"),
            ("✗", "User X berhasil login PADAHAL sudah di-nonaktifkan admin"),
            ("✗", "Admin tidak tahu ada bypass ini"),
        ],
    )

    separator("SKENARIO 3 — No Audit Trail")
    demo_flow(
        "Admin tidak bisa track siapa yang auto-masuk ke sistem",
        [
            ("→", "10 akun external masuk ke aplikasi selama 1 bulan"),
            ("→", "Admin KPC ingin audit: siapa saja yang masuk?"),
            ("→", "Cek user_activity_logs → tidak ada event 'auto_create'"),
            ("✗", "Admin tidak bisa bedakan user yang di-approve vs auto-created"),
            ("✗", "Audit compliance gagal — tidak ada trail yang valid"),
            ("✗", "Ketika terjadi insiden, tidak bisa trace asal-usul akun"),
        ],
    )

    show_manual_test_steps()
    show_curl_commands()

    separator("RINGKASAN RISK")
    print(
        """
  SEVERITY: MEDIUM (tapi kombinasinya bisa CRITICAL)

  ATTACK CHAIN:
  MEDIUM-007 + HIGH-002 + MEDIUM-010:
  → Vendor auto-masuk → tidak ada audit trail login
  → Vendor logout → token masih valid 24 jam (HIGH-002)
  → Tidak ada log kapan vendor aktif/logout (MEDIUM-010)
  → Admin tidak bisa track akses vendor sama sekali

  REKOMENDASI:
  1. Whitelist domain email: hanya @kpc.co.id yang boleh
  2. Auto-create tapi status pending (is_active=False) → butuh admin approval
  3. Kirim email notifikasi ke admin saat ada akun baru terbuat
  4. Log semua event auto-create di user_activity_logs
"""
    )


if __name__ == "__main__":
    main()
