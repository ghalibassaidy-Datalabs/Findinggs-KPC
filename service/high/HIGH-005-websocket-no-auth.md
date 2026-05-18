# HIGH-005 — WebSocket `/ws/jobs/{job_id}` Tidak Memiliki Autentikasi

![Severity](https://img.shields.io/badge/Severity-HIGH-red)
![Module](https://img.shields.io/badge/Module-WebSocket%20%2F%20Jobs-orange)
![Status](https://img.shields.io/badge/Status-Open-critical)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Technical Analysis](#technical-analysis)
3. [Business Impact](#business-impact)
4. [Real Use Case Scenario](#real-use-case-scenario)
5. [Root Cause Analysis](#root-cause-analysis)
6. [Evidence / Code Reference](#evidence--code-reference)
7. [Reproduction / Testing Steps](#reproduction--testing-steps)
8. [Risk Assessment](#risk-assessment)
9. [Recommended Fix](#recommended-fix)
10. [Refactor Recommendation](#refactor-recommendation)
11. [Long-Term Improvement Recommendation](#long-term-improvement-recommendation)

---

## Executive Summary

Endpoint WebSocket `/ws/jobs/{job_id}` **tidak memiliki autentikasi sama sekali**. Siapapun yang mengetahui sebuah `job_id` dapat terhubung ke endpoint ini dan menerima seluruh data job result — termasuk output dari:

- **Invoice OCR** — dokumen invoice yang sudah diproses
- **Bid Analysis** — analisis harga penawaran tender
- **Negotiation Factsheet** — detail negosiasi kontrak
- **Proposal Entity Extraction** — data entitas dari proposal

Ini berbanding terbalik dengan WebSocket chatbot (`/ws/chatbot/{session_id}`) yang sudah memiliki validasi JWT.

---

## Technical Analysis

### WebSocket Jobs — Tidak Ada Autentikasi

```python
# app/websockets/jobs.py
@router.websocket("/ws/jobs/{job_id}")
async def job_status_ws(websocket: WebSocket, job_id: str):
    await websocket.accept()  # ← langsung accept tanpa cek token

    # Langsung ambil job result dari Celery
    result = AsyncResult(job_id, app=celery)
    info = result.info or {}

    try:
        await websocket.send_json({
            "type": "update",
            "job_id": job_id,
            "status": job_status,
            "progress": job_progress,
            "progress_report": job_report,
            "result": job_result,  # ← full job result dikirim tanpa cek authorization
        })
    except Exception as e:
        ...
```

### WebSocket Chatbot — Ada Autentikasi (Reference Implementation)

```python
# app/websockets/chatbot.py — ini yang BENAR
@router.websocket("/ws/chatbot/{session_id}")
async def chatbot_ws(websocket: WebSocket, session_id: str):
    # Baca token dari header atau query param
    token = None
    protocol_header = websocket.headers.get("sec-websocket-protocol")
    if protocol_header:
        # Parse "Bearer <token>" dari header
        ...
    if not token:
        token = websocket.query_params.get("token")

    await websocket.accept(subprotocol="Bearer")

    # Validasi token SEBELUM mengirim data
    if not token:
        await websocket.close(code=4401)  # ← close jika tidak ada token
        return

    try:
        current_user = await get_current_user_from_jwt(token)
        # ← hanya lanjut jika user valid
    except HTTPException:
        await websocket.close(code=4401)
        return
```

**Ketidakkonsistenan ini jelas:** `chatbot_ws` sudah aman, `job_status_ws` tidak.

---

## Business Impact

| Dampak                            | Deskripsi                                                                          |
| --------------------------------- | ---------------------------------------------------------------------------------- |
| **Data bocor ke publik**          | Job results dari invoice OCR, bid analysis, dan negosiasi bisa diakses tanpa login |
| **Competitive intelligence leak** | Data tender dan bid analysis sangat sensitif di konteks bisnis KPC                 |
| **Unauthorized monitoring**       | Attacker bisa monitor progress semua jobs yang berjalan                            |
| **Compliance violation**          | Data dokumen bisnis harus dilindungi dari akses tidak sah                          |
| **Audit trail tidak ada**         | Tidak ada log siapa yang mengakses job result mana                                 |

---

## Real Use Case Scenario

### Skenario 1: Enumerasi Job ID

```
1. Attacker mengamati traffic network saat user yang valid menggunakan aplikasi
2. Attacker melihat request: "wss://api.kpc.co.id/ws/jobs/abc-123-def-456"
3. Attacker menyimpan job_id tersebut
4. Attacker membuat koneksi WebSocket dari komputernya sendiri:
   wscat -c "wss://api.kpc.co.id/ws/jobs/abc-123-def-456"
5. Server langsung menerima koneksi dan mengirim seluruh job result
6. Data invoice OCR, hasil analisis bid, atau negosiasi factsheet bocor
```

### Skenario 2: Job ID Sequential/Predictable

```
Jika job_id menggunakan format yang mudah ditebak (UUID v1 berbasis timestamp,
atau ID sequential), attacker bisa:

1. Mendapatkan satu job_id yang valid (misalnya dari error message)
2. Mencoba job_id di sekitarnya secara sistematis
3. Mendapatkan data dari job-job lain yang tidak seharusnya bisa diakses
```

### Skenario 3: Insider yang Sudah Logout

```
1. Karyawan yang sudah logout masih mengetahui job_id dari sesi sebelumnya
2. WebSocket tidak butuh JWT token
3. Karyawan tersebut masih bisa melihat job result
```

---

## Root Cause Analysis

**Tipe masalah:** Missing authentication control pada WebSocket endpoint

**Akar masalah:**

1. Saat endpoint `/ws/jobs/{job_id}` dibuat, autentikasi tidak ditambahkan
2. Tidak ada mekanisme untuk mengirimkan JWT via WebSocket connection yang diterapkan pada endpoint ini
3. Ketidakkonsistenan dengan `chatbot_ws` yang sudah memiliki autentikasi — kemungkinan dikembangkan oleh developer yang berbeda atau pada waktu yang berbeda tanpa code review yang ketat
4. Tidak ada integration test atau security test yang mendeteksi endpoint unauthenticated ini

---

## Evidence / Code Reference

| Item               | Detail                                                                   |
| ------------------ | ------------------------------------------------------------------------ |
| **File**           | `app/websockets/jobs.py` — fungsi `job_status_ws()`                      |
| **Line**           | ~27 — `await websocket.accept()` tanpa validasi token                    |
| **Reference impl** | `app/websockets/chatbot.py` — `chatbot_ws()` menunjukkan cara yang benar |
| **Missing**        | Tidak ada token validation, tidak ada close(4401), tidak ada user check  |

---

## Reproduction / Testing Steps

### Pre-condition

- Aplikasi berjalan
- Celery worker berjalan (opsional, cukup untuk test akses endpoint)

### Cara Reproduce

```bash
# Install wscat (WebSocket client)
npm install -g wscat

# Step 1: Dapatkan job_id yang valid — bisa dari:
# - Browser DevTools Network tab saat user yang valid menggunakan fitur OCR/bid
# - Atau gunakan job_id dummy untuk test koneksi

JOB_ID="some-valid-job-uuid"  # ganti dengan UUID yang valid

# Step 2: Koneksi tanpa token
wscat -c "ws://localhost:8000/ws/jobs/$JOB_ID"

# Expected (secure): Connection refused atau close(4401)
# Actual (masalah): Server menerima koneksi dan mengirim job data
```

### Verifikasi dari Browser Console (Tanpa Token)

```javascript
// Buka browser baru (incognito, tidak ada session login)
// Buka DevTools > Console
const ws = new WebSocket("ws://localhost:8000/ws/jobs/SOME_JOB_ID");
ws.onmessage = (e) => console.log("Received:", JSON.parse(e.data));
ws.onopen = () => console.log("Connected!");
ws.onclose = (e) => console.log("Closed:", e.code, e.reason);

// Expected (secure): ws.onclose dipanggil dengan code 4401
// Actual (masalah): ws.onmessage menerima job data
```

---

## Risk Assessment

| Aspek                         | Nilai                                                          |
| ----------------------------- | -------------------------------------------------------------- |
| **Severity**                  | HIGH                                                           |
| **Urgency**                   | HIGH — endpoint dapat dieksploitasi sekarang tanpa prasyarat   |
| **Likelihood**                | HIGH — tidak membutuhkan keahlian khusus untuk mengeksploitasi |
| **Impact if not fixed**       | Data job sensitif dapat diakses siapapun yang tahu job_id      |
| **Estimated Fix Complexity**  | LOW — cukup tambahkan auth check yang sama seperti chatbot_ws  |
| **Estimated Production Risk** | HIGH — data exposure langsung                                  |

---

## Recommended Fix

Tambahkan validasi JWT yang identik dengan implementasi di `chatbot_ws`:

```python
# app/websockets/jobs.py

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.security import get_current_user_from_jwt
from app.core.logging import app_logger
import asyncio
from celery.result import AsyncResult
from fastapi import HTTPException
from app.core.celery_app import celery
from app.core.task_status import map_celery_state_to_status


def create_jobs_ws_router() -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/jobs/{job_id}")
    async def job_status_ws(websocket: WebSocket, job_id: str):
        # ── Autentikasi SEBELUM accept ──────────────────────────────
        token = None

        # Coba baca dari sec-websocket-protocol header (sama seperti chatbot)
        protocol_header = websocket.headers.get("sec-websocket-protocol")
        if protocol_header:
            raw_segments = [
                value.strip()
                for chunk in protocol_header.split(",")
                for value in chunk.strip().split(" ")
                if value.strip()
            ]
            for idx, segment in enumerate(raw_segments):
                if segment.lower() == "bearer" and idx + 1 < len(raw_segments):
                    token = raw_segments[idx + 1]
                    break

        # Fallback ke query param
        if not token:
            token = websocket.query_params.get("token")

        await websocket.accept()

        if not token:
            app_logger.warning(f"WebSocket /ws/jobs/{job_id}: Missing token")
            await websocket.close(code=4401)
            return

        try:
            current_user = await get_current_user_from_jwt(token)
        except HTTPException:
            app_logger.warning(f"WebSocket /ws/jobs/{job_id}: Invalid token")
            await websocket.close(code=4401)
            return

        app_logger.info(
            f"WebSocket /ws/jobs/{job_id}: Authenticated as {current_user.email}"
        )
        # ── Akhir autentikasi ────────────────────────────────────────

        # TODO (opsional): verifikasi bahwa job ini milik current_user
        # Ini memerlukan menyimpan user_id di job metadata saat job dibuat

        # ... sisa implementasi tidak berubah ...
        try:
            await websocket.send_json({"type": "ready", "job_id": job_id})
        except Exception as e:
            app_logger.error(f"WebSocket send failed during ready: {e}")
            await websocket.close()
            return

        # ... polling loop yang sudah ada ...
```

---

## Refactor Recommendation

1. **Job ownership check** — Saat job dibuat, simpan `user_id` di Celery task metadata. Di WebSocket, verifikasi bahwa `current_user.id` cocok dengan job owner.
2. **Ekstrak auth middleware** — Buat helper `authenticate_websocket(websocket)` yang bisa digunakan oleh semua WebSocket endpoints untuk menghindari duplikasi.
3. **Unit test** — Tambahkan test untuk memastikan unauthenticated connections ditolak.

---

## Long-Term Improvement Recommendation

1. **Permission check** — Selain autentikasi, verifikasi user memiliki permission untuk melihat job type tertentu (misal: `view_bid_analysis_jobs`)
2. **Job result encryption** — Enkripsi job result di Celery backend (Redis/RabbitMQ) untuk mencegah akses langsung via Redis CLI
3. **WebSocket rate limiting** — Batasi jumlah koneksi WebSocket per user untuk mencegah resource exhaustion
4. **Security test** — Tambahkan test case yang secara eksplisit verifikasi semua WebSocket endpoint memerlukan autentikasi

---

_Related Finding: HIGH-002 (No Token Blacklist)_
_Related API: `WebSocket /ws/jobs/{job_id}`, bandingkan dengan `WebSocket /ws/chatbot/{session_id}`_
_Related Module: `app/websockets/jobs.py`, `app/websockets/chatbot.py`_
_Related Jobs: Invoice OCR, Bid Analysis, Negotiation Factsheet, Proposal Entity Extraction_
