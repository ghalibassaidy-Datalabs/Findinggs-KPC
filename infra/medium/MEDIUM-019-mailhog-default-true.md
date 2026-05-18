# MEDIUM-019 — `USE_MAILHOG=True` Default — Email Tidak Terkirim di Production

![Severity](https://img.shields.io/badge/Severity-MEDIUM-yellow)
![Module](https://img.shields.io/badge/Module-Email%20%2F%20Configuration%20%2F%20Operational-orange)
![Status](https://img.shields.io/badge/Status-Open-important)

---

## Executive Summary

`USE_MAILHOG` dikonfigurasi dengan **default `True`**:

```python
use_mailhog: bool = Field(default=True, alias="USE_MAILHOG")
```

Jika environment variable `USE_MAILHOG=false` tidak di-set secara eksplisit di production, **semua email yang dikirim aplikasi akan diarahkan ke MailHog** (development email trap) — bukan ke penerima sebenarnya.

Ini berarti:

- Email notifikasi kontrak **tidak terkirim ke procurement team**
- Email approval workflow **tidak terkirim ke manager**
- Tidak ada error yang muncul — proses berjalan seolah-olah berhasil
- Ini adalah **silent operational failure** yang mungkin tidak dideteksi selama berhari-hari

---

## Technical Analysis

### Default Value yang Berbahaya

```python
# app/core/config.py
use_mailhog: bool = Field(default=True, alias="USE_MAILHOG")
mailhog_smtp_server: str = Field(default="localhost", alias="MAILHOG_SMTP_SERVER")
mailhog_smtp_port: int = Field(default=1025, alias="MAILHOG_SMTP_PORT")
```

### Email Service Logic

```python
# app/core/email.py
async def send_email(self, to, subject, ...):
    # Cek USE_MAILHOG — tanpa cek environment!
    if self.use_mailhog:
        return await self._send_to_mailhog(...)  # ← Ke MailHog, bukan recipient!

    # Production SMTP path (hanya dieksekusi jika USE_MAILHOG=false)
    if not self._validate_smtp_config():
        app_logger.error("SMTP configuration is incomplete")
        return False
    # ...
```

### Tidak Ada Guard untuk Production

```python
# Email service TIDAK mengecek:
# - Apakah kita di production?
# - Apakah MailHog tersedia?
# - Jika MailHog tidak tersedia (connection refused), email silently gagal

async def _send_to_mailhog(self, to, subject, ...):
    # Jika MailHog tidak running di production:
    # → ConnectionRefusedError yang tidak di-surface ke caller
    # → email_service.send_email() returns False
    # → Contract workflow tidak mengetahui email gagal
```

---

## Business Impact

| Impact                   | Detail                                                                      |
| ------------------------ | --------------------------------------------------------------------------- |
| **Silent Email Failure** | Kontrak notifications tidak terkirim tanpa error                            |
| **Workflow Disruption**  | Approval process terhenti karena email tidak sampai                         |
| **Data Loss**            | Email content ke MailHog (di production) akan hilang saat container restart |
| **SLA Breach**           | Procurement deadlines terlewat karena notifikasi tidak sampai               |
| **Operational Risk**     | Tim tidak tahu email tidak berjalan sampai ada complaint                    |

---

## Root Cause Analysis

`USE_MAILHOG=True` adalah default yang masuk akal untuk development, tapi tidak aman untuk production karena seharusnya default-nya `False` dengan explicit opt-in untuk development.

---

## Evidence / Code Reference

```
app/core/config.py   — use_mailhog: bool = Field(default=True, ...)
app/core/email.py    — _send_to_mailhog() dipanggil tanpa environment check
env.example          — USE_MAILHOG=true (development default)
```

---

## Recommended Fix

### Fix 1: Ubah Default ke False

```python
# app/core/config.py
use_mailhog: bool = Field(default=False, alias="USE_MAILHOG")  # ← Safe default
```

### Fix 2: Guard dengan Environment Check

```python
# app/core/email.py
async def send_email(self, to, subject, ...):
    if self.use_mailhog:
        if settings.environment == "production":
            # ✅ Jangan kirim ke MailHog di production
            app_logger.error(
                "USE_MAILHOG=True detected in production! "
                "Email will NOT be sent. Fix configuration immediately."
            )
            return False
        return await self._send_to_mailhog(...)
    # ...
```

### Fix 3: Startup Validation (terkait HIGH-014)

```python
# app/main.py — startup validation
if settings.environment == "production" and settings.use_mailhog:
    raise RuntimeError("USE_MAILHOG=True is not allowed in production")
```

---

## Long-Term Improvement Recommendation

1. **Email delivery monitoring** — Track email send success/failure dengan metrics
2. **Dead letter queue** — Jika email gagal, queue untuk retry
3. **Alert on email failure** — GCP Cloud Monitoring alert jika email error rate tinggi
4. **Test email endpoint** — Admin endpoint untuk test email configuration
