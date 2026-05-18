# MEDIUM-014 — GCP Service Account Key Disimpan sebagai Base64 di CI/CD Variable

![Severity](https://img.shields.io/badge/Severity-MEDIUM-yellow)
![Module](https://img.shields.io/badge/Module-CI%2FCD%20%2F%20GCP%20%2F%20Secrets-orange)
![Status](https://img.shields.io/badge/Status-Open-important)

---

## Executive Summary

Pipeline Azure DevOps menyimpan GCP Service Account key JSON sebagai **base64-encoded string** di variable group `app-variables`:

```bash
echo "$(GCP_SERVICE_ACCOUNT_BASE64)" | base64 -d > gcp-sa.json
gcloud auth activate-service-account --key-file=gcp-sa.json
```

Pendekatan ini memiliki beberapa risiko:

1. **Service Account key adalah long-lived credential** — tidak expired kecuali di-revoke manual
2. **Key tersimpan permanen di Azure DevOps variable group** — siapapun dengan akses variable group bisa mendapatkan full GCP access
3. **Key tertulis ke disk** di self-hosted build agent (`gcp-sa.json`) — file ini bisa tertinggal jika cleanup step gagal
4. **Scope permission tidak diketahui** — service account yang digunakan untuk deploy kemungkinan memiliki overly broad permissions (push ke Artifact Registry, deploy Cloud Run, update Cloud SQL)

---

## Technical Analysis

### Pipeline: Service Account Key Handling

```yaml
# azure-pipelines/dev.yml
- script: |
    echo "Creating GCP service account file..."
    echo "$(GCP_SERVICE_ACCOUNT_BASE64)" | base64 -d > gcp-sa.json  # ← Key ke disk
    echo "Service account file created successfully"
  displayName: "Create GCP Service Account File"

- script: |
    gcloud auth activate-service-account --key-file=gcp-sa.json
    gcloud config set project $(GCP_PROJECT_ID)
  displayName: "Setup GCP Authentication"

# ... build, push images, deploy ...

- script: |
    rm -f gcp-sa.json  # ← Cleanup di akhir pipeline
    echo "Cleaned up service account file"
  displayName: "Cleanup"
```

**Problem**: Cleanup hanya berjalan jika semua step sebelumnya sukses (atau jika pipeline menggunakan `condition: always()`). Jika step deployment gagal, `gcp-sa.json` **tertinggal di disk build agent**.

### Pipeline: db-commands.sh — SA Key Juga Digunakan

```bash
# pipeline-scripts/db-commands.sh
SERVICE_ACCOUNT_BASE64="$2"
echo "$SERVICE_ACCOUNT_BASE64" | base64 -d > gcp-sa.json
gcloud auth activate-service-account --key-file=gcp-sa.json
# ... runs migrations ...
# ← TIDAK ada cleanup step di akhir script ini!
```

Script `db-commands.sh` tidak memiliki cleanup untuk `gcp-sa.json`, sehingga file ini **selalu tertinggal** setelah migration runs.

### Masalah Tambahan: DB Password di Environment Variable Docker Run

```bash
# pipeline-scripts/db-commands.sh
docker run --rm \
  --network host \
  -e DATABASE_URL="postgresql://postgres:$DB_PASSWORD@$DB_HOST:5432/$DB_NAME" \
  # ↑ Password plaintext di command line — visible di `docker inspect` dan process list
  "$APP_IMAGE_TAG" \
  sh -c "make install && make db COMMAND=seed_users"
```

DB password sebagai environment variable di `docker run` terekspos di:

- `docker inspect <container_id>` output
- `/proc/{pid}/environ` di Linux
- Azure DevOps pipeline logs (jika logging tidak di-mask)

---

## Business Impact

| Impact                          | Detail                                                              |
| ------------------------------- | ------------------------------------------------------------------- |
| **GCP Account Takeover**        | Jika variable group bocor, attacker mendapat full GCP access        |
| **Data Exfiltration**           | Service account dengan akses GCS bisa unduh semua dokumen           |
| **Infrastructure Manipulation** | Deploy malicious container, update Cloud Run config                 |
| **DB Access**                   | Jika SA memiliki Cloud SQL access, seluruh database bisa diakses    |
| **Persistence**                 | Long-lived key = persistent access bahkan setelah password rotation |

---

## Root Cause Analysis

Penggunaan service account key file adalah pattern lama. GCP sekarang merekomendasikan **Workload Identity Federation** yang tidak memerlukan key file sama sekali.

---

## Evidence / Code Reference

```
azure-pipelines/dev.yml              — Baris 56-65: SA key handling
azure-pipelines/scheduled-runs-dev.yaml — Baris 8-9: SA key di parameter
pipeline-scripts/db-commands.sh     — Baris 13-18: SA key ke disk, no cleanup
```

---

## Reproduction / Testing Steps

```bash
# Cek apakah file tertinggal di build agent (jika ada akses)
ls -la /home/buildagent/gcp-sa.json  # atau path agent working directory
find / -name "gcp-sa.json" 2>/dev/null

# Verifikasi scope service account
# Decode base64 dan cek email
echo "$GCP_SERVICE_ACCOUNT_BASE64" | base64 -d | jq '.client_email'

# Cek permissions SA tersebut di GCP
gcloud projects get-iam-policy kpc-gen-ai-project-dev \
  --flatten="bindings[].members" \
  --format="table(bindings.role)" \
  --filter="bindings.members:sa-email@..."
```

---

## Risk Assessment

| Kriteria                    | Nilai                                               |
| --------------------------- | --------------------------------------------------- |
| **CVSS Score**              | 6.5 (Medium)                                        |
| **Attack Vector**           | Network (Azure DevOps access) / Local (build agent) |
| **Attack Complexity**       | Low                                                 |
| **Privileges Required**     | Medium (Azure DevOps variable group access)         |
| **Impact: Confidentiality** | High (if SA has broad permissions)                  |
| **Exploitability**          | Medium                                              |

---

## Recommended Fix

### Fix 1: Workload Identity Federation (Best Practice)

Tidak perlu service account key file sama sekali:

```yaml
# azure-pipelines/dev.yml — menggunakan Workload Identity Federation
- task: GoogleCloudAuth@0 # Atau gunakan oidc token exchange
  inputs:
    workloadIdentityProvider: "projects/123/locations/global/workloadIdentityPools/azure-pool/providers/azure-provider"
    serviceAccount: "deploy-sa@kpc-gen-ai-project-dev.iam.gserviceaccount.com"
```

Atau dengan OIDC:

```bash
# Exchange Azure DevOps OIDC token untuk GCP SA token
curl -X POST "https://sts.googleapis.com/v1/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=urn:ietf:params:oauth:grant-type:token-exchange&..."
```

### Fix 2: Cleanup Menggunakan `trap` (Short-term Fix)

```bash
# pipeline-scripts/db-commands.sh
set -e

# ✅ Cleanup on exit (bahkan jika error)
cleanup() {
    rm -f gcp-sa.json
    echo "Cleaned up service account file"
}
trap cleanup EXIT

echo "$SERVICE_ACCOUNT_BASE64" | base64 -d > gcp-sa.json
# ... rest of script ...
# cleanup() dipanggil otomatis saat exit
```

### Fix 3: GCP Secret Manager untuk DB Password

```bash
# Ganti: -e DATABASE_URL="postgresql://postgres:$DB_PASSWORD@..."
# Dengan:
DB_PASSWORD=$(gcloud secrets versions access latest --secret="db-password-prod")
```

---

## Long-Term Improvement Recommendation

1. **Workload Identity Federation** — Eliminasi service account key files sepenuhnya
2. **Least Privilege SA** — Pisahkan SA untuk deploy, untuk migration, untuk monitoring
3. **Key rotation policy** — Jika tetap menggunakan key, rotasi setiap 90 hari
4. **Azure DevOps secret scanning** — Enable scanning untuk mendeteksi secrets di pipeline logs
5. **GCP Audit Logging** — Log semua penggunaan service account untuk deteksi anomali
