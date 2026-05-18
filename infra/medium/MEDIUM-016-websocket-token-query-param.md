# MEDIUM-016 — Token JWT Dikirim via Query Parameter di WebSocket

![Severity](https://img.shields.io/badge/Severity-MEDIUM-yellow)
![Module](https://img.shields.io/badge/Module-WebSocket%20%2F%20Authentication-orange)
![Status](https://img.shields.io/badge/Status-Open-important)

---

## Executive Summary

Endpoint WebSocket chatbot (`/ws/chatbot/{session_id}`) dan PO Query chatbot (`/ws/po_query_chatbot/{session_id}`) mendukung pengiriman token JWT via **query parameter**:

```python
# Fallback: token di query parameter
token = websocket.query_params.get("token")
```

Token dalam query parameter berbahaya karena:

1. **Tersimpan di server access logs** — URL lengkap termasuk token terlog di Cloud Run, nginx, atau load balancer
2. **Tersimpan di browser history** — WebSocket URL dengan token tersimpan
3. **Tersimpan di Referrer header** — Jika ada redirect, token bocor ke pihak ketiga
4. **Tersimpan di CDN/proxy cache logs** — Token bisa dibaca dari log CDN/WAF
5. **Terekspos di network monitoring** — Network monitoring tools yang tidak TLS-aware bisa menangkap URL

---

## Technical Analysis

### Fallback ke Query Parameter

```python
# app/websockets/chatbot.py
@router.websocket("/ws/chatbot/{session_id}")
async def chatbot_ws(websocket: WebSocket, session_id: str):
    # Method 1: Token dari header (aman)
    protocol_header = websocket.headers.get("sec-websocket-protocol")
    token = None
    # ... extract from header ...

    # Method 2: Fallback ke query parameter (TIDAK AMAN)
    if not token:
        token = websocket.query_params.get("token")
        if token:
            app_logger.debug(
                f"Token picked from query params for session '{session_id}': {token[:20]}..."
            )
            # ↑ Token juga di-log (meski hanya 20 karakter pertama, ini masih bocor)
```

### URL yang Dihasilkan

Ketika client menggunakan fallback query param:

```
wss://api.kpc.com/ws/chatbot/session-123?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

URL ini tersimpan di:

- Cloud Run request logs: `GET /ws/chatbot/session-123?token=eyJ...`
- Browser WebSocket URL history
- Proxy/CDN access logs

### Token Juga Di-log (Partial)

```python
app_logger.debug(
    f"Token picked from query params for session '{session_id}': {token[:20]}..."
)
```

Meskipun hanya 20 karakter pertama, ini:

1. Mengkonfirmasi token di log bahwa query param digunakan
2. Header JWT (`eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9`) adalah base64 dari `{"alg":"HS256","typ":"JWT"}` — selalu sama. 20 karakter pertama selalu identik untuk semua token HS256.

---

## Business Impact

| Impact               | Detail                                                               |
| -------------------- | -------------------------------------------------------------------- |
| **Token Theft**      | Token bocor via server logs → session hijacking                      |
| **Log Retention**    | GCP Cloud Logging default retention 30 hari — token valid selama itu |
| **Audit Complexity** | Sulit membedakan legitimate log entry dari token yang bocor          |
| **Compliance**       | OWASP A02:2021 Cryptographic Failures — sensitive data di URL        |

---

## Root Cause Analysis

Query parameter fallback ditambahkan untuk kemudahan testing/development, lalu tidak dihapus sebelum production deployment. Metode ini sering digunakan di WebSocket karena WebSocket tidak mendukung custom Authorization header saat handshake secara langsung — tapi ada cara yang lebih aman.

---

## Evidence / Code Reference

```
app/websockets/chatbot.py          — Line ~47-52: token dari query_params
app/websockets/po_query_chatbot.py — Line ~47-52: token dari query_params (pattern yang sama)
```

---

## Reproduction / Testing Steps

```bash
# Connect dengan token di query parameter
wscat -c "wss://api.kpc.com/ws/chatbot/test-session?token=eyJ..."

# Setelah koneksi, cek server logs
gcloud logging read "resource.type=cloud_run_revision AND textPayload:token=" \
  --project=kpc-gen-ai-project-dev \
  --limit=10 \
  --format="value(textPayload)"

# Expected vulnerable output: Log entries dengan token dalam URL
```

---

## Risk Assessment

| Kriteria                    | Nilai                                |
| --------------------------- | ------------------------------------ |
| **CVSS Score**              | 5.4 (Medium)                         |
| **Attack Vector**           | Network (log access)                 |
| **Attack Complexity**       | Low                                  |
| **Privileges Required**     | Low (GCP log access or proxy access) |
| **Impact: Confidentiality** | Medium                               |
| **Exploitability**          | Medium                               |

---

## Recommended Fix

### Fix 1: Hapus Fallback Query Parameter

```python
# app/websockets/chatbot.py

@router.websocket("/ws/chatbot/{session_id}")
async def chatbot_ws(websocket: WebSocket, session_id: str):
    protocol_header = websocket.headers.get("sec-websocket-protocol")
    token = None

    if protocol_header:
        # ... extract token from header ...
        pass

    # ✅ HAPUS fallback query param:
    # if not token:
    #     token = websocket.query_params.get("token")  # ← HAPUS INI

    await websocket.accept(subprotocol="Bearer")

    if not token:
        await websocket.close(code=4401)
        return
```

### Fix 2: Jika Query Param Diperlukan (Edge Case), Gunakan One-Time Token

```python
# Jika benar-benar perlu mendukung token di query param,
# gunakan one-time token dari endpoint terpisah:

@router.post("/auth/ws-token")
async def get_ws_token(current_user = Depends(get_current_user)):
    # Generate short-lived one-time token
    ws_token = create_access_token(
        {"sub": current_user.email, "type": "ws"},
        expires_delta=timedelta(minutes=1)  # Hanya 1 menit
    )
    return {"ws_token": ws_token}
```

### Fix 3: GCP Log-Based Metric Alert

```bash
# Detect token-in-URL pattern in logs
gcloud logging metrics create websocket-token-in-url \
  --description="Detects when JWT token appears in WebSocket URL" \
  --log-filter='resource.type=cloud_run_revision AND textPayload=~"token=ey[A-Za-z0-9_-]+"'
```

---

## Long-Term Improvement Recommendation

1. **Remove query param fallback** — Primary fix, segera lakukan
2. **GCP Log exclusion filter** — Exclude WebSocket upgrade requests dari storage
3. **Token rotation** — Short-lived tokens (15 menit) mengurangi window of opportunity
4. **Log scrubbing** — Pipeline untuk meredact token dari log storage
