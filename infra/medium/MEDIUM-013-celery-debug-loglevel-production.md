# MEDIUM-013 — Celery Worker Berjalan dengan `--loglevel=DEBUG` di Production

![Severity](https://img.shields.io/badge/Severity-MEDIUM-yellow)
![Module](https://img.shields.io/badge/Module-Container%20%2F%20Worker%20%2F%20Logging-orange)
![Status](https://img.shields.io/badge/Status-Open-important)

---

## Executive Summary

`Dockerfile.worker` hardcode `--loglevel=DEBUG` untuk Celery worker:

```dockerfile
CMD ["uv", "run", "celery", "-A", "app.core.celery_app", "worker", "--loglevel=DEBUG", "--concurrency=1"]
```

Ini berarti di production, Celery worker akan mendump:

- **Full task arguments** — termasuk file content yang di-upload (invoice OCR, proposal extraction)
- **SQL queries** lengkap dengan parameter (termasuk data sensitif dari result)
- **AI prompt dan response** dari Gemini integration
- **Internal task state** dan metadata

Data sensitif ini masuk ke container stdout/stderr, dan jika GCP Cloud Logging aktif, tersimpan di **Google Cloud Logging** yang mungkin memiliki retention lama dan akses yang kurang dikontrol.

---

## Technical Analysis

### Dockerfile.worker CMD

```dockerfile
# Dockerfile.worker — Line 43
CMD ["uv", "run", "celery", "-A", "app.core.celery_app", "worker",
     "--loglevel=DEBUG",   # ← Hardcoded DEBUG
     "--concurrency=1"]
```

### Data yang Dilog di DEBUG Level

Celery dengan `--loglevel=DEBUG` melogging:

```
# Contoh log output yang akan terlihat:

[DEBUG/MainProcess] Task received: app.jobs.tasks.process_invoice_ocr[uuid]
{
  "args": [{"file_content": "base64_encoded_invoice_content..."}],  # ← File content!
  "kwargs": {}
}

[DEBUG/Worker-1] Task app.jobs.tasks.process_invoice_ocr[uuid] started
[DEBUG/Worker-1] Sending to Gemini: "Extract invoice data from: {full_invoice_text}"  # ← AI prompt

[DEBUG/Worker-1] Gemini response: {
  "invoice_number": "INV-2024-001",
  "vendor": "PT. Vendor ABC",
  "amount": 15000000,   # ← Financial data
  "items": [...]
}
```

### Juga: SQLAlchemy DEBUG Logging

Karena `DATABASE_ECHO` bisa True dan Celery menggunakan DB sebagai broker, semua SQL queries dari worker terlog:

```sql
-- DEBUG SQL log dari Celery result backend
SELECT celery_taskmeta.task_id, celery_taskmeta.result, ...
INSERT INTO celery_taskmeta (task_id, result, status, ...)
VALUES ('uuid', '{"invoice_number": "INV-001", "amount": 15000000}', 'SUCCESS', ...)
```

---

## Business Impact

| Impact                | Detail                                                               |
| --------------------- | -------------------------------------------------------------------- |
| **Data Leakage**      | Invoice content, financial figures, vendor data masuk ke logs        |
| **AI Prompt Leakage** | Prompt engineering strategy dan data sensitif di Gemini calls        |
| **Compliance**        | Log retention policy mungkin tidak sesuai dengan data classification |
| **Log Volume**        | DEBUG logs menyebabkan log volume tinggi → biaya Cloud Logging naik  |
| **SIEM Noise**        | Signal-to-noise ratio buruk jika semua SQL queries dilog             |

---

## Root Cause Analysis

Nilai `--loglevel=DEBUG` dipilih untuk kemudahan debugging selama development, lalu di-copy ke Dockerfile.worker tanpa pertimbangan bahwa ini adalah production image.

---

## Evidence / Code Reference

```
Dockerfile.worker — Line 43 (CMD instruction)
```

---

## Reproduction / Testing Steps

```bash
# Build dan run worker container
docker build -t kpc-worker-test -f Dockerfile.worker .
docker run -e DATABASE_URL="..." kpc-worker-test 2>&1 | head -100

# Cari output sensitif
docker run -e DATABASE_URL="..." kpc-worker-test 2>&1 | grep -i "invoice\|amount\|contract\|result"
```

---

## Risk Assessment

| Kriteria                    | Nilai                                                      |
| --------------------------- | ---------------------------------------------------------- |
| **CVSS Score**              | 5.5 (Medium)                                               |
| **Attack Vector**           | Local (log access) / Network (if logging endpoint exposed) |
| **Attack Complexity**       | Low                                                        |
| **Privileges Required**     | Low (log access)                                           |
| **Impact: Confidentiality** | Medium-High (financial/procurement data in logs)           |
| **Exploitability**          | Low (requires log access)                                  |

---

## Recommended Fix

### Fix: Gunakan Environment Variable untuk Log Level

```dockerfile
# Dockerfile.worker — BEFORE
CMD ["uv", "run", "celery", "-A", "app.core.celery_app", "worker",
     "--loglevel=DEBUG", "--concurrency=1"]

# Dockerfile.worker — AFTER
ENV CELERY_LOG_LEVEL=INFO

CMD ["sh", "-c", "uv run celery -A app.core.celery_app worker --loglevel=${CELERY_LOG_LEVEL} --concurrency=${CELERY_CONCURRENCY:-1}"]
```

Kemudian di CI/CD, inject:

```yaml
# production Cloud Run service
env:
  - name: CELERY_LOG_LEVEL
    value: "WARNING" # Production: only warnings and errors
  - name: CELERY_CONCURRENCY
    value: "2"
```

### Fix Tambahan: Custom Task Logger yang Tidak Log Sensitive Data

```python
# app/jobs/base_job.py
import logging

class BaseJob:
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

    def log_task_start(self, task_id: str, record_id: int):
        # ✅ Log hanya metadata, bukan content
        self.logger.info(f"Task {task_id} started for record_id={record_id}")
        # ← Tidak log file content atau AI prompts
```

---

## Long-Term Improvement Recommendation

1. **Structured logging** — JSON format dengan field masking untuk data sensitif
2. **Log level per component** — `WARNING` untuk Celery, `INFO` untuk app, `ERROR` untuk SQLAlchemy
3. **GCP Cloud Logging filter** — Setup exclusion filters untuk menghindari log sensitif tersimpan
4. **Log data classification** — Classify log output berdasarkan sensitivity level
