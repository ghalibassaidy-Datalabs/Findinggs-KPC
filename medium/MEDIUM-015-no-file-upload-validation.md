# MEDIUM-015 — Tidak Ada Validasi File Type dan Ukuran pada Upload Endpoint

![Severity](https://img.shields.io/badge/Severity-MEDIUM-yellow)
![Module](https://img.shields.io/badge/Module-API%20%2F%20File%20Upload%20%2F%20Security-orange)
![Status](https://img.shields.io/badge/Status-Open-important)

---

## Executive Summary

Endpoint upload file **tidak memvalidasi** tipe file maupun ukuran file dari sisi server. Service `AttachmentsService.create_attachment()` menggunakan `file.content_type` secara langsung dari request — yaitu nilai yang **sepenuhnya dikontrol oleh client** dan mudah dimanipulasi.

Risiko utama:

1. **Unrestricted file upload** — Attacker bisa mengupload file tipe apapun (executable, HTML, SVG dengan XSS)
2. **No size limit** — Tidak ada batas ukuran, memungkinkan DoS via large file upload
3. **Content-type spoofing** — Attacker bisa kirim `.exe` dengan `content_type="image/jpeg"`
4. **Storage cost abuse** — Upload unlimited besar-besaran menguras GCS storage

---

## Technical Analysis

### AttachmentsService — Tidak Ada Validasi

```python
# app/services/attachments_service.py
def create_attachment(
    self, record, file, attachment_name: str, storage: StorageBackend
):
    with tempfile.NamedTemporaryFile(delete=True) as tmp:
        shutil.copyfileobj(file.file, tmp)  # ← File langsung ditulis ke disk, tanpa cek size
        tmp.flush()

        tmp.seek(0, os.SEEK_END)
        byte_size = tmp.tell()  # ← Size dihitung, tapi tidak divalidasi

        # Checksum
        sha256 = hashlib.sha256()
        tmp.seek(0)
        for chunk in iter(lambda: tmp.read(4096), b""):
            sha256.update(chunk)

        # Create blob dengan content_type DARI CLIENT
        blob = Blob(
            key="",
            filename=file.filename,           # ← Filename dari client
            content_type=file.content_type,   # ← Content-type dari client (tidak diverifikasi!)
            # ...
        )
```

### Content-Type Spoofing

```python
# Attacker bisa melakukan ini:
import requests

with open("malicious.html", "rb") as f:
    requests.post(
        "https://api.kpc.com/api/v1/scd/contracts/1/attachments",
        headers={"Authorization": "Bearer valid_token"},
        files={"file": ("invoice.pdf", f, "application/pdf")},  # ← .html tapi claim PDF
    )
```

### Tidak Ada FastAPI Upload Size Limit

```python
# app/main.py — tidak ada konfigurasi max request size
app = FastAPI(...)
# ← Tidak ada: app.add_middleware(TrustedHostMiddleware, ...)
# ← Tidak ada: uvicorn --limit-max-requests atau --limit-concurrency
# ← Tidak ada: nginx/Cloud Run max body size yang dikonfigurasi eksplisit
```

---

## Business Impact

| Impact              | Detail                                                                   |
| ------------------- | ------------------------------------------------------------------------ |
| **Stored XSS**      | Upload HTML/SVG file, jika served back bisa execute JavaScript           |
| **DoS via Storage** | Upload 10GB file berulang kali → GCS cost explosion + storage exhaustion |
| **Malware Storage** | GCS bucket menjadi hosting untuk malware/phishing files                  |
| **Data Integrity**  | File tipe berbahaya tersimpan bersama dokumen legitimate                 |
| **Compliance**      | File procurement seharusnya dibatasi ke PDF, Office docs, images         |

---

## Root Cause Analysis

`AttachmentsService` didesain sebagai generic service tanpa domain-specific validation. Endpoint yang menggunakannya tidak menambahkan validasi sebelum memanggil service.

---

## Evidence / Code Reference

```
app/services/attachments_service.py — create_attachment(): tidak ada validasi type/size
```

---

## Reproduction / Testing Steps

```bash
# Test 1: Upload file tanpa extension / tipe berbahaya
curl -X POST "https://api.kpc.com/api/v1/scd/contracts/1/attachments" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@malicious.html;type=application/pdf"

# Test 2: Upload large file (DoS test - gunakan hati-hati di production!)
dd if=/dev/zero bs=1M count=100 | \
  curl -X POST "https://api.kpc.com/api/v1/.../attachments" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/dev/stdin;type=application/octet-stream"

# Test 3: Verify content-type tidak divalidasi
file_ext_mismatch="image.jpg"
# Kirim executable tapi claim image
```

---

## Risk Assessment

| Kriteria                    | Nilai                         |
| --------------------------- | ----------------------------- |
| **CVSS Score**              | 6.1 (Medium)                  |
| **Attack Vector**           | Network                       |
| **Attack Complexity**       | Low                           |
| **Privileges Required**     | Low (authenticated user)      |
| **Impact: Confidentiality** | Low                           |
| **Impact: Integrity**       | Medium                        |
| **Impact: Availability**    | Medium (DoS via large upload) |
| **Exploitability**          | High (easy to execute)        |

---

## Recommended Fix

### Fix 1: Validasi di AttachmentsService

```python
# app/services/attachments_service.py

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/gif",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
    "text/csv",
}

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

def create_attachment(self, record, file, attachment_name: str, storage: StorageBackend):
    # ✅ Validasi file size
    file.file.seek(0, 2)  # Seek to end
    file_size = file.file.tell()
    file.file.seek(0)  # Reset

    if file_size > MAX_FILE_SIZE_BYTES:
        raise ValidationException(
            f"File size {file_size} bytes exceeds maximum allowed {MAX_FILE_SIZE_BYTES} bytes"
        )

    # ✅ Validasi content-type
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise ValidationException(
            f"File type '{file.content_type}' is not allowed. "
            f"Allowed types: {', '.join(sorted(ALLOWED_MIME_TYPES))}"
        )

    # ✅ Validasi magic bytes (actual file content, bukan hanya MIME claim)
    import magic
    content_header = file.file.read(2048)
    file.file.seek(0)
    detected_type = magic.from_buffer(content_header, mime=True)

    if detected_type not in ALLOWED_MIME_TYPES:
        raise ValidationException(
            f"File content does not match declared type. "
            f"Detected: {detected_type}"
        )

    # ... rest of implementation
```

### Fix 2: Uvicorn Request Size Limit

```python
# app/main.py atau uvicorn config
# Atau via Cloud Run max request body size
```

```yaml
# cloud-run-service.yaml
spec:
  template:
    metadata:
      annotations:
        run.googleapis.com/container-dependencies: ...
    spec:
      containers:
        - args: ["--limit-max-requests", "1000"]
```

---

## Long-Term Improvement Recommendation

1. **python-magic** — Server-side MIME detection dari file content, bukan header
2. **AV scanning** — Integrasikan ClamAV atau GCP Security Command Center untuk scan upload
3. **File quarantine** — Upload ke staging bucket dulu, scan, baru pindah ke production bucket
4. **Upload size quota per user** — Batasi total upload per user per hari
5. **CDN dengan WAF** — Google Cloud Armor dapat melindungi dari large upload attacks
