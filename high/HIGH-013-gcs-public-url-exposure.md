# HIGH-013 — GCS Upload Menggunakan `public_url` — Dokumen Sensitif Berpotensi Terpublikasi

![Severity](https://img.shields.io/badge/Severity-HIGH-red)
![Module](https://img.shields.io/badge/Module-Storage%20%2F%20GCS-orange)
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
10. [Long-Term Improvement Recommendation](#long-term-improvement-recommendation)

---

## Executive Summary

`GCSStorageBackend` menggunakan **`blob.public_url`** untuk mendapatkan URL file setelah upload. Property `public_url` di Google Cloud Storage SDK mengembalikan URL format:

```
https://storage.googleapis.com/{bucket_name}/{object_name}
```

URL ini **hanya dapat diakses jika bucket dikonfigurasi sebagai public** (dengan IAM binding `allUsers: roles/storage.objectViewer`). Ini berarti:

1. **Jika bucket bersifat public** — semua dokumen sensitif (invoice, kontrak, proposal, bid analysis) dapat diakses oleh siapapun yang mengetahui URL-nya (atau menebaknya)
2. **Jika bucket bersifat private** — URL yang disimpan di database tidak akan berfungsi, menyebabkan broken functionality
3. Seharusnya menggunakan **Signed URL** (URL sementara dengan ekspirasi) untuk akses file sensitif

---

## Technical Analysis

### Kode yang Bermasalah

```python
# app/core/storage.py — GCSStorageBackend

def upload(
    self,
    record_type: str,
    record_id: int,
    blob_id: int,
    file_path: str,
    filename: str,
    content_type: str,
):
    blob_key = self._build_key(record_type, record_id, blob_id, filename)
    blob = self.bucket.blob(blob_key)
    blob.upload_from_filename(file_path, content_type=content_type)
    return blob.public_url, blob_key  # ← Menggunakan public_url!

def upload_bytes(
    self,
    content: bytes,
    key: str,
    content_type: str | None = None,
) -> str:
    blob = self.bucket.blob(key)
    blob.upload_from_string(content, content_type=content_type)
    return blob.public_url  # ← Menggunakan public_url!
```

### Signed URL (yang sudah ada tapi tidak digunakan untuk upload result)

```python
# app/core/storage.py — GCSStorageBackend
def signed_url_for(self, attachment: Attachment, expires_in=3600):
    # ← Ini sudah benar — tapi hanya dipanggil untuk serving, bukan sebagai default
    blob = self.bucket.blob(blob_key)
    return blob.generate_signed_url(expiration=timedelta(seconds=expires_in))
```

`signed_url_for()` sudah ada dan benar, tapi `upload()` dan `upload_bytes()` masih mengembalikan `public_url`.

### `upload_bytes()` Digunakan di Background Jobs

```python
# app/jobs/reference_document_processing_job.py (likely)
# app/jobs/bid_analysis_job.py (likely)
# app/jobs/invoice_ocr_job.py (likely)
# app/jobs/negotiation_factsheet_job.py (likely)
```

Background jobs yang memproses dokumen sensitif menggunakan `upload_bytes()` dan menyimpan `public_url` sebagai hasil kerja.

### Perbedaan `public_url` vs `signed_url`

| Property  | `blob.public_url`                                  | `blob.generate_signed_url()`                                            |
| --------- | -------------------------------------------------- | ----------------------------------------------------------------------- |
| Format    | `https://storage.googleapis.com/{bucket}/{object}` | `https://storage.googleapis.com/{bucket}/{object}?X-Goog-Signature=...` |
| Akses     | Hanya jika bucket public                           | Siapapun dengan URL (time-limited)                                      |
| Expired   | Tidak pernah                                       | Bisa dikonfigurasi (misal 1 jam)                                        |
| Revocable | Tidak                                              | Secara otomatis expired                                                 |
| Auth      | Tidak butuh auth                                   | Tidak butuh auth (tapi time-limited)                                    |

---

## Business Impact

| Impact                       | Detail                                                                   |
| ---------------------------- | ------------------------------------------------------------------------ |
| **Data Exposure**            | Dokumen invoice, kontrak, proposal, bid analysis KPC terpublikasi        |
| **Regulatory Risk**          | Pelanggaran data protection policy untuk data pengadaan/procurement      |
| **Business Confidentiality** | Informasi harga penawaran (bid analysis) bisa dilihat kompetitor         |
| **PII Exposure**             | Dokumen invoice mengandung data vendor, jumlah transaksi, detail kontrak |
| **Irreversible**             | URL yang sudah tersebar tidak bisa di-revoke jika bucket public          |

---

## Real Use Case Scenario

### Skenario 1: Bucket Dikonfigurasi Public (Worst Case)

1. Tim DevOps mengkonfigurasi GCS bucket sebagai public untuk "kemudahan development"
2. Semua file yang di-upload (invoice, kontrak, proposal bid) memiliki URL publik
3. Seseorang berbagi URL dokumen invoice via chat/email
4. URL tersebut bisa diakses oleh siapapun tanpa authentication
5. Kompetitor atau pihak tidak berwenang bisa mengakses semua dokumen procurement KPC

### Skenario 2: URL Bocor via Log

1. `public_url` disimpan di database sebagai `blob.key` atau dilog
2. Log atau database leak mengekspos URL-URL tersebut
3. Karena URL bersifat permanen (tidak ada expiry), URL tersebut tetap valid
4. Attacker dapat mengakses dokumen selamanya

### Skenario 3: Enumerasi Object

1. Attacker mengetahui struktur path: `{record_type}/{record_id}/{blob_id}/{filename}`
2. Melakukan brute force dengan increment `record_id` dan `blob_id`
3. Mengunduh seluruh dokumen dari GCS bucket

---

## Root Cause Analysis

Developer menggunakan `blob.public_url` yang merupakan convenience property di GCS SDK, tanpa memahami bahwa property ini hanya bermakna jika bucket bersifat public. Seharusnya menggunakan `generate_signed_url()` yang sudah ada di kode yang sama.

---

## Evidence / Code Reference

```
app/core/storage.py
  Line ~470: return blob.public_url, blob_key  (dalam upload())
  Line ~486: return blob.public_url            (dalam upload_bytes())
  Line ~451: return blob.generate_signed_url(...)  (dalam signed_url_for() — sudah benar)
```

---

## Reproduction / Testing Steps

### Step 1: Verifikasi Bucket Access Level

```bash
# Cek apakah bucket public
gcloud storage buckets get-iam-policy gs://kpc_app_attachements

# Cari: allUsers atau allAuthenticatedUsers
# Jika ada — bucket public dan SEMUA file bisa diakses

# Alternatif
gsutil iam get gs://kpc_app_attachements | grep allUsers
```

### Step 2: Test Direct URL Access

```bash
# Ambil salah satu URL dari database
# SELECT key FROM blobs LIMIT 5;

# Test akses tanpa authentication
curl -I "https://storage.googleapis.com/kpc_app_attachements/{blob_key}"
# HTTP 200 = PUBLIC (vulnerable)
# HTTP 403 = Private (tapi URL di app tidak akan berfungsi)
```

### Step 3: Verifikasi di GCP Console

```
GCP Console → Cloud Storage → Buckets → kpc_app_attachements
→ Permissions tab → Check for "allUsers" binding
```

---

## Risk Assessment

| Kriteria                    | Nilai                                  |
| --------------------------- | -------------------------------------- |
| **CVSS Score**              | 8.6 (High) — jika bucket memang public |
| **Attack Vector**           | Network                                |
| **Attack Complexity**       | Low                                    |
| **Privileges Required**     | None                                   |
| **Impact: Confidentiality** | High                                   |
| **Impact: Integrity**       | None                                   |
| **Impact: Availability**    | None                                   |
| **Exploitability**          | High (jika bucket public)              |

---

## Recommended Fix

### Fix Immediate: Ganti `public_url` dengan Signed URL di `upload()`

```python
# app/core/storage.py — GCSStorageBackend

def upload(
    self,
    record_type: str,
    record_id: int,
    blob_id: int,
    file_path: str,
    filename: str,
    content_type: str,
):
    blob_key = self._build_key(record_type, record_id, blob_id, filename)
    blob = self.bucket.blob(blob_key)
    blob.upload_from_filename(file_path, content_type=content_type)
    # ✅ Jangan kembalikan public URL — kembalikan blob_key saja
    # URL akan di-generate on-demand via signed_url_for()
    internal_url = f"gs://{self.bucket.name}/{blob_key}"
    return internal_url, blob_key

def upload_bytes(
    self,
    content: bytes,
    key: str,
    content_type: str | None = None,
) -> str:
    blob = self.bucket.blob(key)
    blob.upload_from_string(content, content_type=content_type)
    # ✅ Kembalikan internal GCS path, bukan public URL
    return f"gs://{self.bucket.name}/{key}"
```

### Fix GCS Bucket: Pastikan Bucket Private

```bash
# Pastikan uniform bucket-level access AKTIF
gsutil uniformbucketlevelaccess set on gs://kpc_app_attachements
gsutil uniformbucketlevelaccess set on gs://kpc-data-landing-bucket
gsutil uniformbucketlevelaccess set on gs://kpc-explainability-bucket

# Hapus public access jika ada
gsutil iam ch -d allUsers gs://kpc_app_attachements
gsutil iam ch -d allAuthenticatedUsers gs://kpc_app_attachements

# Block public access di GCP level
gcloud storage buckets update gs://kpc_app_attachements \
  --no-public-access-prevention  # Verify this is false first
```

### Fix GCP Project Level: Block Public Access

```bash
# Di GCP Console:
# IAM & Admin → Organization Policies → Cloud Storage →
# "Prevent public access" → Enforce
```

---

## Long-Term Improvement Recommendation

1. **Uniform Signed URLs** — Semua akses file via signed URL dengan TTL pendek (5-15 menit)
2. **VPC Service Controls** — Batasi GCS akses hanya dari Cloud Run VPC
3. **Object-level IAM** — Gunakan fine-grained IAM bukan public access
4. **Audit existing objects** — Cek semua object yang sudah ada apakah ada yang public
5. **CMEK** — Customer-Managed Encryption Keys untuk data sensitif procurement
