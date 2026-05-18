#!/usr/bin/env python3
"""
PoC: MEDIUM-016 — Token JWT Bocor via WebSocket Query Parameter
===============================================================
Demonstrasi bahwa WebSocket chatbot menerima token via URL query
parameter — token tersimpan di server access log, browser history,
dan CDN/proxy log.

TUJUAN DEMO:
  1. Buktikan koneksi WS berhasil dengan token di query param (?token=)
  2. Simulasikan bagaimana token akan muncul di access log server
  3. Buktikan bahwa ini berbeda (lebih berbahaya) dari header-based auth

CARA MENJALANKAN:
  pip install websockets requests
  python MEDIUM-016-websocket-token-query-param.py

SAFETY: Hanya membuka koneksi WebSocket dan langsung menutup.
        Tidak mengirim pesan atau mengakses data sensitif.
        Jalankan HANYA di environment DEV.
"""

import os
import sys
import asyncio
import urllib.parse

try:
    import websockets
except ImportError:
    print("Install dulu: pip install websockets")
    sys.exit(1)

# ──────────────────────────────────────────────
# KONFIGURASI
# ──────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(".env.poc")

DEV_TOKEN = os.getenv("DEV_TOKEN", "")
WS_BASE   = "wss://dev-api.genai.kpc.co.id"

# Ganti dengan session_id yang valid atau UUID random
TEST_SESSION_ID = "poc-test-session-001"


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


async def test_token_in_query_param():
    separator("TEST 1: Koneksi WS dengan Token di Query Parameter")

    url = f"{WS_BASE}/ws/chatbot/{TEST_SESSION_ID}?token={DEV_TOKEN}"

    # Sembunyikan sebagian token di output (tapi tunjukkan format URL-nya)
    token_preview = DEV_TOKEN[:20] + "..." if len(DEV_TOKEN) > 20 else DEV_TOKEN
    display_url = f"{WS_BASE}/ws/chatbot/{TEST_SESSION_ID}?token={token_preview}"

    print(f"\n  URL yang digunakan:")
    print(f"  {display_url}")
    print()
    print(f"  ⚠️  URL ini akan muncul PERSIS di:")
    print(f"     - Cloud Run access logs")
    print(f"     - Nginx/reverse proxy logs")
    print(f"     - Browser history")
    print(f"     - CDN/WAF logs")
    print(f"     - Network monitoring tools")
    print()

    try:
        async with websockets.connect(url, subprotocols=["Bearer"], open_timeout=10) as ws:
            print(f"  🔴 KONEKSI BERHASIL — token diterima via query parameter")
            print(f"  Status  : Connected")
            print(f"  Finding : TERKONFIRMASI — server menerima token dari URL")
            # Langsung tutup tanpa kirim pesan
            await ws.close()
            print(f"  Koneksi ditutup dengan aman")

    except websockets.exceptions.ConnectionClosed as e:
        code = getattr(e.rcvd, 'code', None) if e.rcvd else None
        if code == 4401:
            print(f"  ✅ Ditolak (4401) — Server menolak query param token")
        else:
            print(f"  ℹ️  Koneksi ditutup oleh server: code={code}")
    except websockets.exceptions.WebSocketException as e:
        status = getattr(e, 'status_code', None)
        if status in (401, 403):
            print(f"  ✅ HTTP {status} — Akses ditolak")
        else:
            print(f"  ℹ️  WebSocket exception: {e}")
    except OSError:
        print(f"  ⚠️  Tidak dapat terhubung — cek apakah DEV server aktif")


async def test_token_in_header():
    separator("TEST 2: Perbandingan — Koneksi WS dengan Token di Header (AMAN)")

    url = f"{WS_BASE}/ws/chatbot/{TEST_SESSION_ID}"

    print(f"\n  URL yang digunakan:")
    print(f"  {url}")
    print()
    print(f"  ✅ Token dikirim via Sec-WebSocket-Protocol header")
    print(f"     Tidak muncul di URL → tidak tersimpan di access log")
    print()

    try:
        # Kirim token via Sec-WebSocket-Protocol header: "Bearer, <token>"
        async with websockets.connect(
            url,
            subprotocols=["Bearer", DEV_TOKEN],
            open_timeout=10,
        ) as ws:
            print(f"  ✅ Koneksi via header berhasil")
            print(f"  Token tidak terekspos di URL")
            await ws.close()

    except websockets.exceptions.ConnectionClosed as e:
        code = getattr(e.rcvd, 'code', None) if e.rcvd else None
        print(f"  ℹ️  Koneksi ditutup: code={code}")
    except websockets.exceptions.WebSocketException as e:
        print(f"  ℹ️  WebSocket exception: {e}")
    except OSError:
        print(f"  ⚠️  Tidak dapat terhubung ke server")


def simulate_log_exposure():
    separator("TEST 3: Simulasi Log Exposure")

    fake_token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyQGtwYy5jby5pZCJ9.SIGNATURE"

    print("""
  Contoh baris yang akan muncul di Cloud Run access log
  jika token dikirim via query parameter:

  ┌─────────────────────────────────────────────────────────────────┐
  │ 2026-05-18T10:23:41Z GET                                        │
  │ /ws/chatbot/abc123?token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOi...   │
  │ "Mozilla/5.0..." 101 0                                          │
  └─────────────────────────────────────────────────────────────────┘

  Setiap engineer/operator dengan akses Cloud Logging dapat:
  → Copy token dari log
  → Gunakan token selama masih valid (24 jam)
  → Akses API sebagai user tersebut

  REKOMENDASI FIX:
  → app/websockets/chatbot.py & po_query_chatbot.py
  → Hapus: token = websocket.query_params.get("token")
  → Wajibkan hanya via sec-websocket-protocol header
    """)


async def main():
    if not DEV_TOKEN:
        print("❌ DEV_TOKEN belum di-set di .env.poc")
        print("   Jalankan: python setup.py")
        sys.exit(1)

    print("=" * 60)
    print("  PoC MEDIUM-016 — WebSocket Token via Query Parameter")
    print(f"  Target  : {WS_BASE}")
    print("  Mode    : DEV ONLY — Koneksi langsung ditutup tanpa aksi")
    print("=" * 60)

    await test_token_in_query_param()
    await test_token_in_header()
    simulate_log_exposure()


if __name__ == "__main__":
    asyncio.run(main())
