#!/usr/bin/env python3
"""
PoC: HIGH-013 — GCS Bucket Public Access Verification
======================================================
Verifikasi apakah GCS bucket yang digunakan menyimpan dokumen KPC
bersifat public — sehingga siapapun bisa mengakses file tanpa auth.

TUJUAN DEMO:
  1. Cek apakah bucket accessible tanpa credentials
  2. Coba akses file via public_url format
  3. Verifikasi apakah Public Access Prevention sudah aktif

CARA MENJALANKAN:
  pip install requests google-cloud-storage
  python HIGH-013-gcs-bucket-access.py

SAFETY: Hanya HTTP GET ke GCS public endpoint.
        Tidak mengupload atau mengubah data apapun.
        Jalankan HANYA dengan izin dari tim DevOps/Cloud.
"""

import sys
import os

try:
    import requests
except ImportError:
    print("Install dulu: pip install requests")
    sys.exit(1)

# ──────────────────────────────────────────────
# KONFIGURASI — sesuaikan dengan nama bucket DEV
# ──────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(".env.poc")

GCP_PROJECT   = os.getenv("GCP_PROJECT", "kpc-gen-ai-project-dev")
BUCKET_NAMES  = [
    os.getenv("GCS_SCD_BUCKET_NAME", "kpc_app_attachements-dev"),
    # Tambahkan bucket lain jika ada
]

# Contoh blob key format (sesuaikan dengan data DEV)
# Format dari kode: {record_type}/{record_id}/{blob_id}/{filename}
SAMPLE_BLOB_KEYS = [
    "contracts/1/1/sample.pdf",
    "purchase_orders/1/1/sample.pdf",
    "invoices/1/1/sample.pdf",
]


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


def check_bucket_listing(bucket_name: str):
    """Cek apakah bucket listing accessible tanpa auth."""
    separator(f"TEST 1: Bucket Listing — gs://{bucket_name}")

    # GCS JSON API untuk list objects
    url = f"https://storage.googleapis.com/storage/v1/b/{bucket_name}/o"

    try:
        r = requests.get(url, timeout=10)

        print(f"  URL     : {url}")
        print(f"  Status  : HTTP {r.status_code}\n")

        if r.status_code == 200:
            data = r.json()
            items = data.get("items", [])
            print(f"  🔴 BUCKET LISTING ACCESSIBLE — {len(items)} object ditemukan")
            if items:
                print(f"\n  Contoh file yang terekspos:")
                for item in items[:5]:
                    print(f"     - {item.get('name')} ({item.get('size', '?')} bytes)")
                if len(items) > 5:
                    print(f"     ... dan {len(items)-5} file lainnya")
        elif r.status_code == 403:
            print(f"  ✅ HTTP 403 — Bucket listing tidak accessible publik")
        elif r.status_code == 404:
            print(f"  ℹ️  HTTP 404 — Bucket tidak ditemukan atau nama berbeda")
        else:
            print(f"  ℹ️  HTTP {r.status_code}: {r.text[:200]}")

    except requests.exceptions.ConnectionError:
        print(f"  ⚠️  Connection error")


def check_direct_file_access(bucket_name: str):
    """Coba akses file langsung via public URL."""
    separator(f"TEST 2: Direct File Access via public_url — gs://{bucket_name}")
    print("  Mencoba akses file via format public_url yang ada di kode:\n")
    print("  Format: https://storage.googleapis.com/{bucket}/{blob_key}\n")

    found_accessible = False

    for blob_key in SAMPLE_BLOB_KEYS:
        url = f"https://storage.googleapis.com/{bucket_name}/{blob_key}"

        try:
            r = requests.get(url, timeout=10)

            if r.status_code == 200:
                found_accessible = True
                size = len(r.content)
                print(f"  🔴 ACCESSIBLE  {blob_key}  ({size} bytes)")
            elif r.status_code == 403:
                print(f"  ✅ Protected   {blob_key}  → HTTP 403")
            elif r.status_code == 404:
                print(f"  ℹ️  Not found   {blob_key}  → HTTP 404 (file tidak ada atau private)")
            else:
                print(f"  ℹ️  HTTP {r.status_code}  {blob_key}")

        except requests.exceptions.ConnectionError:
            print(f"  ⚠️  {blob_key}  → Connection error")

    if not found_accessible:
        print(f"\n  ✅ Tidak ada file yang accessible via public URL")
        print(f"  Kemungkinan: bucket sudah private atau file tidak ada")

    return found_accessible


def check_gcs_metadata(bucket_name: str):
    """Cek metadata bucket untuk info IAM/access control."""
    separator(f"TEST 3: Cek Metadata Bucket — gs://{bucket_name}")

    url = f"https://storage.googleapis.com/storage/v1/b/{bucket_name}"

    try:
        r = requests.get(url, timeout=10)

        print(f"  Status: HTTP {r.status_code}\n")

        if r.status_code == 200:
            data = r.json()
            iam_config    = data.get("iamConfiguration", {})
            uniform_access = iam_config.get("uniformBucketLevelAccess", {})
            pub_access    = iam_config.get("publicAccessPrevention", "")

            print(f"  Bucket Location         : {data.get('location', 'N/A')}")
            print(f"  Storage Class           : {data.get('storageClass', 'N/A')}")
            print(f"  Uniform Bucket Access   : {uniform_access.get('enabled', False)}")
            print(f"  Public Access Prevention: {pub_access}")

            if not uniform_access.get("enabled", False):
                print(f"\n  ⚠️  Uniform Bucket-Level Access TIDAK aktif")
                print(f"     Masing-masing object mungkin punya ACL sendiri")

            if pub_access != "enforced":
                print(f"\n  ⚠️  Public Access Prevention TIDAK enforced")
                print(f"     Bucket bisa dikonfigurasi public kapanpun")

        elif r.status_code == 403:
            print(f"  ✅ Metadata tidak accessible tanpa credentials")
        else:
            print(f"  ℹ️  HTTP {r.status_code}: {r.text[:200]}")

    except requests.exceptions.ConnectionError:
        print(f"  ⚠️  Connection error")


def show_remediation():
    separator("REKOMENDASI FIX")
    print("""
  1. GCP Console — Set Public Access Prevention:
     Cloud Storage → Bucket → Permissions → Public Access Prevention → Enforced

  2. gcloud CLI:
     gcloud storage buckets update gs://kpc_app_attachements \\
       --public-access-prevention

  3. Enable Uniform Bucket-Level Access:
     gsutil uniformbucketlevelaccess set on gs://kpc_app_attachements

  4. Verifikasi tidak ada allUsers binding:
     gsutil iam get gs://kpc_app_attachements | grep allUsers

  5. Perbaiki kode di app/core/storage.py:
     Ganti: return blob.public_url, blob_key
     Dengan: return blob_key  (simpan key saja, URL via signed_url_for())
    """)


if __name__ == "__main__":
    print("=" * 60)
    print("  PoC HIGH-013 — GCS Bucket Public Access Check")
    print(f"  Project : {GCP_PROJECT}")
    print(f"  Buckets : {', '.join(BUCKET_NAMES)}")
    print("  Mode    : READ-ONLY — Tidak mengubah data apapun")
    print("  WARNING : Jalankan dengan izin tim DevOps/Cloud")
    print("=" * 60)

    for bucket in BUCKET_NAMES:
        check_bucket_listing(bucket)
        check_direct_file_access(bucket)
        check_gcs_metadata(bucket)

    show_remediation()

    separator("SUMMARY")
    print(f"  Jalankan script ini setelah melakukan hardening GCP")
    print(f"  untuk konfirmasi bahwa semua test mengembalikan ✅")
