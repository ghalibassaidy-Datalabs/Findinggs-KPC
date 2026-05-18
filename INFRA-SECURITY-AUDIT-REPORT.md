# KPC App Backend — Infrastructure & Deployment Security Audit Report

> **Audit Date**: May 2026  
> **Scope**: Infrastructure, Deployment, GCP Configuration, Container/Runtime, Observability, Authentication, Production Hardening, Operational Risk  
> **Auditor**: Infrastructure Security Review  
> **Status**: Active findings — remediation required

---

## 1. Executive Summary

Audit ini menemukan **14 temuan baru** (3 HIGH, 9 MEDIUM, 2 LOW) di luar 11 temuan yang sudah ada sebelumnya. Total combined: **25 temuan aktif** yang perlu remediation.

### Summary Matrix

| Severity  | Existing | New    | Total  |
| --------- | -------- | ------ | ------ |
| HIGH      | 6        | 3      | 9      |
| MEDIUM    | 5        | 9      | 14     |
| LOW       | 0        | 2      | 2      |
| **Total** | **11**   | **14** | **25** |

### Most Critical New Findings

| ID         | Finding                                                                         | Risk                           |
| ---------- | ------------------------------------------------------------------------------- | ------------------------------ |
| HIGH-013   | GCS uploads menggunakan `public_url` — dokumen sensitif berpotensi terpublikasi | Data Breach                    |
| HIGH-014   | Tidak ada startup validation untuk critical secrets                             | Auth Bypass / Misconfiguration |
| HIGH-012   | Container berjalan sebagai root                                                 | Privilege Escalation           |
| MEDIUM-012 | Swagger/OpenAPI docs terbuka publik                                             | Reconnaissance                 |
| MEDIUM-014 | GCP SA key di CI/CD variable                                                    | GCP Account Takeover           |
| MEDIUM-020 | DB superuser untuk application runtime                                          | Privilege Escalation           |

---

## 2. All New Findings Summary

### 2.1 HIGH Severity

| ID                                                        | Title                                                       | Area              | CVSS |
| --------------------------------------------------------- | ----------------------------------------------------------- | ----------------- | ---- |
| [HIGH-012](high/HIGH-012-container-running-as-root.md)    | Container berjalan sebagai root                             | Container/Runtime | 7.5  |
| [HIGH-013](high/HIGH-013-gcs-public-url-exposure.md)      | GCS `public_url` — dokumen sensitif berpotensi terpublikasi | GCS/Storage       | 8.6  |
| [HIGH-014](high/HIGH-014-no-startup-config-validation.md) | Tidak ada startup validation untuk critical secrets         | Configuration     | 9.1  |

### 2.2 MEDIUM Severity

| ID                                                                  | Title                                                     | Area               | CVSS |
| ------------------------------------------------------------------- | --------------------------------------------------------- | ------------------ | ---- |
| [MEDIUM-012](medium/MEDIUM-012-swagger-docs-public.md)              | Swagger/OpenAPI docs terbuka publik                       | API Exposure       | 5.3  |
| [MEDIUM-013](medium/MEDIUM-013-celery-debug-loglevel-production.md) | Celery worker `--loglevel=DEBUG` di production            | Container/Logging  | 5.5  |
| [MEDIUM-014](medium/MEDIUM-014-gcp-sa-key-cicd-variable.md)         | GCP SA key sebagai base64 di CI/CD variable               | CI/CD/GCP          | 6.5  |
| [MEDIUM-015](medium/MEDIUM-015-no-file-upload-validation.md)        | Tidak ada validasi file type dan size pada upload         | API/Security       | 6.1  |
| [MEDIUM-016](medium/MEDIUM-016-websocket-token-query-param.md)      | JWT token via query parameter di WebSocket                | WebSocket/Auth     | 5.4  |
| [MEDIUM-017](medium/MEDIUM-017-missing-security-headers.md)         | Missing security response headers (CSP, HSTS, etc.)       | HTTP Security      | 5.4  |
| [MEDIUM-018](medium/MEDIUM-018-verbose-error-messages.md)           | Verbose error messages mengekspos internal detail         | API/Error Handling | 5.0  |
| [MEDIUM-019](medium/MEDIUM-019-mailhog-default-true.md)             | `USE_MAILHOG=True` default — silent email failure di prod | Operational        | 4.3  |
| [MEDIUM-020](medium/MEDIUM-020-db-superuser-credentials.md)         | Database superuser digunakan untuk application runtime    | Database           | 6.2  |

### 2.3 LOW Severity (Additional Notes)

| ID      | Title                                            | Area         |
| ------- | ------------------------------------------------ | ------------ |
| LOW-001 | `X-Process-Time` header mengekspos timing info   | HTTP Headers |
| LOW-002 | Celery `--concurrency=1` — single job bottleneck | Operational  |

---

## 3. Complete Attack Surface Map

```
Internet
    │
    ▼
┌─────────────────────────────────────────────────────────────────────┐
│ ATTACK SURFACE                                                       │
│                                                                     │
│  ┌──────────────────────┐    ┌─────────────────────────────────┐   │
│  │ PUBLIC ENDPOINTS      │    │ AUTHENTICATION LAYER             │   │
│  │                       │    │                                 │   │
│  │ /docs          ← M012 │    │ JWT secret=""       ← M011/H014 │   │
│  │ /redoc         ← M012 │    │ JWT_AUTH=False      ← H014      │   │
│  │ /openapi.json  ← M012 │    │ PKCE in-memory      ← H001      │   │
│  │ /             (open)  │    │ No token blacklist  ← H002      │   │
│  │ /api/v1/auth/* (open) │    │ No domain validation ← M007     │   │
│  │                       │    │ JWKS not cached     ← M008      │   │
│  └──────────────────────┘    └─────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────┐    ┌─────────────────────────────────┐   │
│  │ WEBSOCKET ENDPOINTS   │    │ API SECURITY                    │   │
│  │                       │    │                                 │   │
│  │ /ws/jobs/{id}  ← H005 │    │ No rate limiting    ← M009      │   │
│  │ /ws/chatbot    (auth) │    │ No file validation  ← M015      │   │
│  │   + query param← M016│    │ Verbose errors      ← M018      │   │
│  └──────────────────────┘    │ No security headers ← M017      │   │
│                               │ Missing CSP/HSTS               │   │
│  ┌──────────────────────┐    └─────────────────────────────────┘   │
│  │ CONTAINER/RUNTIME     │                                          │
│  │                       │    ┌─────────────────────────────────┐   │
│  │ Root user     ← H012  │    │ GCP / CLOUD STORAGE              │   │
│  │ scripts/ bundled← H012│    │                                 │   │
│  │ Celery DEBUG  ← M013  │    │ public_url usage    ← H013      │   │
│  │ SA key to disk ← M014 │    │ Bucket access TBD  ← H013      │   │
│  └──────────────────────┘    │ SA key in variable  ← M014      │   │
│                               └─────────────────────────────────┘   │
│  ┌──────────────────────┐                                           │
│  │ DATABASE              │    ┌─────────────────────────────────┐   │
│  │                       │    │ OPERATIONAL RISK                │   │
│  │ Superuser creds← M020 │    │                                 │   │
│  │ Pool exhaustion← H004 │    │ Mailhog default    ← M019      │   │
│  │ No stmt timeout       │    │ No startup validation ← H014   │   │
│  │ Celery as broker      │    │ Auth events not logged ← M010  │   │
│  └──────────────────────┘    │ No anomaly detection           │   │
│                               └─────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. Prioritized Remediation Roadmap

### Phase 1 — Immediate (0-2 weeks) — Critical Quick Wins

```
Priority | Finding  | Action                                    | Effort
---------|----------|-------------------------------------------|--------
1        | H014     | Tambahkan startup validation config        | 1 day
2        | H013     | Verify GCS bucket access + fix public_url  | 1 day
3        | H012     | Tambahkan USER instruction di Dockerfile   | 2 hours
4        | M011     | Force non-empty JWT_SECRET_KEY             | 2 hours
5        | M012     | Disable Swagger di production              | 1 hour
6        | M019     | Ubah USE_MAILHOG default ke False          | 30 min
7        | M013     | Ubah Celery loglevel ke INFO/WARNING       | 30 min
```

### Phase 2 — Short-term (2-4 weeks) — High Impact

```
Priority | Finding  | Action                                    | Effort
---------|----------|-------------------------------------------|--------
8        | H001     | Migrasi PKCE state ke Redis/DB            | 3 days
9        | H002     | Implementasi token blacklist              | 2 days
10       | H005     | Tambahkan auth ke WebSocket /ws/jobs      | 1 day
11       | M017     | Tambahkan security headers middleware     | 4 hours
12       | M016     | Hapus WebSocket query param fallback      | 2 hours
13       | M018     | Sanitize error messages                   | 1 day
14       | M015     | Validasi file type dan size               | 1 day
```

### Phase 3 — Medium-term (1-2 months) — Security Hardening

```
Priority | Finding  | Action                                    | Effort
---------|----------|-------------------------------------------|--------
15       | M020     | Buat dedicated app DB user (non-superuser)| 2 days
16       | M014     | Migrasi ke Workload Identity Federation   | 3 days
17       | H006     | Fix CORS origins (non-wildcard)           | 1 day
18       | M009     | Implementasi rate limiting                | 2 days
19       | H004     | Refactor DB connection per request        | 1 week
20       | M007     | Domain validation untuk auto-create user  | 1 day
```

### Phase 4 — Long-term (2-3 months) — Architecture Improvement

```
Priority | Finding  | Action                                    | Effort
---------|----------|-------------------------------------------|--------
21       | All SA   | GCP Secret Manager untuk semua secrets    | 1 week
22       | Logging  | Structured logging + GCP Log-based alerts | 1 week
23       | Database | PostgreSQL Row-Level Security             | 2 weeks
24       | CI/CD    | Security scanning pipeline (Trivy, SAST)  | 1 week
25       | Monitor  | Cloud Run SLOs + alerting dashboard       | 1 week
```

---

## 5. Discovery Strategy & Audit Checklist

### 5.1 GCP Configuration Audit

```bash
# === IAM AUDIT ===

# Cek semua IAM bindings di project
gcloud projects get-iam-policy kpc-gen-ai-project-dev \
  --format=json | jq '.bindings[] | select(.members[] | test("allUsers|allAuthenticatedUsers"))'

# Cek service account permissions
gcloud iam service-accounts list --project=kpc-gen-ai-project-dev
gcloud projects get-iam-policy kpc-gen-ai-project-dev \
  --flatten="bindings[].members" --format="table(bindings.role,bindings.members)" \
  --filter="bindings.members:serviceAccount"

# === GCS BUCKET AUDIT ===

# List semua bucket
gsutil ls -p kpc-gen-ai-project-dev

# Cek public access tiap bucket
for bucket in $(gsutil ls -p kpc-gen-ai-project-dev); do
  echo "=== $bucket ==="
  gsutil iam get $bucket | grep -E "allUsers|allAuthenticatedUsers" || echo "Private"
done

# Cek uniform bucket-level access
gsutil uniformbucketlevelaccess get gs://kpc_app_attachements

# Cek public access prevention
gcloud storage buckets describe gs://kpc_app_attachements \
  --format="value(iamConfiguration.publicAccessPrevention)"

# === CLOUD RUN AUDIT ===

# Cek apakah service publicly accessible
gcloud run services describe kpc-api --region=asia-southeast2 --format=json | \
  jq '.status.address.url, .spec.template.spec.containerConcurrency'

# Cek apakah allow-unauthenticated
gcloud run services get-iam-policy kpc-api --region=asia-southeast2

# Cek environment variables yang di-inject (cari yang hardcoded)
gcloud run services describe kpc-api --region=asia-southeast2 --format=json | \
  jq '.spec.template.spec.containers[0].env[]'

# === CLOUD SQL AUDIT ===

# Cek apakah public IP enabled
gcloud sql instances describe kpc-db --format=json | \
  jq '.ipAddresses[] | select(.type == "PRIMARY")'

# Cek authorized networks
gcloud sql instances describe kpc-db --format=json | \
  jq '.settings.ipConfiguration.authorizedNetworks'
```

### 5.2 Container Security Audit

```bash
# === DOCKERFILE AUDIT ===

# Cek apakah container berjalan sebagai root
docker build -t kpc-test .
docker run --rm kpc-test id
# Harusnya: uid=1001(appuser) bukan uid=0(root)

# Scan image untuk vulnerability
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy image kpc-test

# Cek hardcoded secrets di image
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  trufflesecurity/trufflehog docker --image kpc-test

# Inspect image layers
docker history kpc-test --no-trunc
docker inspect kpc-test | jq '.[0].Config.Env'

# === CELERY WORKER AUDIT ===

docker build -t kpc-worker-test -f Dockerfile.worker .
docker run --rm kpc-worker-test sh -c "echo $CELERY_LOG_LEVEL"

# Verify loglevel yang digunakan
docker run --rm kpc-worker-test cat /proc/1/cmdline | tr '\0' ' '
```

### 5.3 API Security Audit

```bash
# === ENDPOINT DISCOVERY ===

# Download OpenAPI schema
curl -s https://YOUR_API/openapi.json > api-schema.json
cat api-schema.json | jq '.paths | keys'

# Test security headers
curl -sI https://YOUR_API/ | grep -E "strict-transport|x-frame|content-security|x-content-type"

# Test public endpoints
curl -s https://YOUR_API/docs -o /dev/null -w "%{http_code}"
curl -s https://YOUR_API/redoc -o /dev/null -w "%{http_code}"
curl -s https://YOUR_API/openapi.json -o /dev/null -w "%{http_code}"

# === AUTH TESTING ===

# Test endpoint tanpa auth
curl -s https://YOUR_API/api/v1/msd/equipment -o /dev/null -w "%{http_code}"
# Expected: 401 atau 403

# Test JWT dengan empty secret (jika applicable)
python3 -c "
import jwt
token = jwt.encode({'sub': 'test@kpc.com'}, '', algorithm='HS256')
print(token)
"
curl -H "Authorization: Bearer $FORGED_TOKEN" https://YOUR_API/api/v1/msd/equipment

# === FILE UPLOAD TESTING ===

# Test upload file tipe berbahaya
echo '<script>alert(1)</script>' > test.html
curl -X POST "https://YOUR_API/api/v1/scd/contracts/1/attachments" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@test.html;type=application/pdf"
```

### 5.4 Database Security Audit

```bash
# === PRIVILEGE AUDIT ===

# Cek user yang digunakan oleh aplikasi
psql -h DB_HOST -U postgres -c "\du"

# Cek permissions user kpc_app
psql -h DB_HOST -U postgres -c "
SELECT grantee, table_name, privilege_type
FROM information_schema.role_table_grants
WHERE grantee = 'kpc_app_user'
ORDER BY table_name;"

# Cek apakah superuser bisa CREATE EXTENSION
psql -h DB_HOST -U postgres -c "SHOW superuser_reserved_connections;"

# === CONNECTION AUDIT ===

# Cek max connections
psql -h DB_HOST -U postgres -c "SHOW max_connections;"

# Cek current connections
psql -h DB_HOST -U postgres -c "
SELECT count(*), state, wait_event_type
FROM pg_stat_activity
WHERE datname = 'kpc_app'
GROUP BY state, wait_event_type;"

# Cek statement_timeout
psql -h DB_HOST -U postgres -c "SHOW statement_timeout;"
```

### 5.5 Log Analysis Audit

```bash
# === GCP CLOUD LOGGING ===

# Cek apakah token muncul di logs
gcloud logging read \
  "resource.type=cloud_run_revision
   AND textPayload=~\"token=ey[A-Za-z0-9_-]+\"" \
  --project=kpc-gen-ai-project-dev \
  --limit=10

# Cek apakah password muncul di logs
gcloud logging read \
  "resource.type=cloud_run_revision
   AND textPayload=~\"password\"" \
  --project=kpc-gen-ai-project-dev \
  --limit=10

# Cek error rate
gcloud logging read \
  "resource.type=cloud_run_revision
   AND severity>=ERROR" \
  --project=kpc-gen-ai-project-dev \
  --limit=50 \
  --format="value(timestamp, textPayload)"
```

---

## 6. Tools & Commands Recommendation

### Static Analysis Tools

```bash
# Python SAST
pip install bandit
bandit -r app/ -f json -o bandit-report.json
bandit -r app/ -ll  # Show only medium and high severity

# Secret detection
pip install detect-secrets
detect-secrets scan --all-files > .secrets.baseline
detect-secrets audit .secrets.baseline

# Dependency vulnerability scan
pip install safety
safety check

# Code quality + security
pip install semgrep
semgrep --config "p/python" app/
semgrep --config "p/owasp-top-ten" app/
```

### Container Security Tools

```bash
# Trivy — vulnerability scanner
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy image asia-southeast2-docker.pkg.dev/kpc-gen-ai-project-dev/kpc-api/kpc-api:latest

# Hadolint — Dockerfile linter
docker run --rm -i hadolint/hadolint < Dockerfile
docker run --rm -i hadolint/hadolint < Dockerfile.worker

# Dockle — container image security check
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  goodwithtech/dockle asia-southeast2-docker.pkg.dev/...
```

### GCP Security Tools

```bash
# Security Health Analytics (built-in GCP)
gcloud services enable securitycenter.googleapis.com
gcloud scc findings list kpc-gen-ai-project-dev --filter="state=ACTIVE"

# GCP Config Validator
pip install gcp-config-validator

# Forseti Security (GCP IAM audit)
# https://forsetisecurity.org/

# ScoutSuite — multi-cloud security auditing
pip install scoutsuite
scout gcp --project-id kpc-gen-ai-project-dev
```

### Network/API Security Tools

```bash
# OWASP ZAP — API scanning
docker run -t owasp/zap2docker-stable zap-api-scan.py \
  -t https://YOUR_API/openapi.json -f openapi -r zap-report.html

# Nuclei — vulnerability scanner
nuclei -u https://YOUR_API -t ~/nuclei-templates/

# HTTPx — HTTP security headers check
httpx -u https://YOUR_API -title -tech-detect -status-code -follow-redirects
```

---

## 7. Hardening Best Practice Recommendations

### 7.1 Container Hardening

```dockerfile
# Dockerfile — Production Hardened Version
FROM python:3.11-slim-bookworm AS builder
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen --no-dev

FROM python:3.11-slim-bookworm AS production
WORKDIR /app

# System dependencies only (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client-16 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid 1001 --no-create-home appuser

# Copy only necessary files (no scripts/)
COPY --from=builder /build/.venv ./.venv
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini ./

# Set ownership
RUN chown -R 1001:1001 /app

USER appuser

EXPOSE 8080
ENV PORT=8080 HOST=0.0.0.0 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", \
     "--workers", "2", "--access-log"]
```

### 7.2 GCP Cloud Run Security

```yaml
# cloud-run-service.yaml
apiVersion: serving.knative.dev/v1
kind: Service
spec:
  template:
    metadata:
      annotations:
        # Require VPC for all egress
        run.googleapis.com/vpc-access-egress: private-ranges-only
        # Minimum instances to avoid cold start auth bypass
        autoscaling.knative.dev/minScale: "1"
    spec:
      # Service account dengan minimal permissions
      serviceAccountName: kpc-api-runtime@kpc-gen-ai-project-dev.iam.gserviceaccount.com
      containers:
        - image: ...
          securityContext:
            runAsNonRoot: true
            runAsUser: 1001
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
          resources:
            limits:
              cpu: "2"
              memory: "2Gi"
            requests:
              cpu: "0.5"
              memory: "512Mi"
          env:
            - name: ENVIRONMENT
              value: "production"
            # Secrets dari Secret Manager
            - name: JWT_SECRET_KEY
              valueFrom:
                secretKeyRef:
                  name: jwt-secret-key
                  key: latest
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: database-url
                  key: latest
```

### 7.3 GCP IAM Least Privilege

```bash
# Service account untuk runtime API (minimal permissions)
gcloud iam service-accounts create kpc-api-runtime \
  --description="KPC API runtime service account" \
  --display-name="KPC API Runtime"

# Hanya GCS access ke specific bucket
gsutil iam ch \
  serviceAccount:kpc-api-runtime@kpc-gen-ai-project-dev.iam.gserviceaccount.com:objectAdmin \
  gs://kpc_app_attachements

# Vertex AI untuk AI features
gcloud projects add-iam-policy-binding kpc-gen-ai-project-dev \
  --member="serviceAccount:kpc-api-runtime@..." \
  --role="roles/aiplatform.user"

# Secret Manager read-only
gcloud projects add-iam-policy-binding kpc-gen-ai-project-dev \
  --member="serviceAccount:kpc-api-runtime@..." \
  --role="roles/secretmanager.secretAccessor"

# Tidak ada: storage.admin, iam.admin, cloudrun.admin, etc.
```

### 7.4 GCP Secret Manager Integration

```python
# app/core/config.py — Secret Manager Integration

from google.cloud import secretmanager

def get_secret(secret_id: str, project_id: str) -> str:
    """Fetch secret from GCP Secret Manager."""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")

class Settings(BaseSettings):
    @model_validator(mode="after")
    def load_production_secrets(self) -> "Settings":
        if self.environment in ("production", "staging") and self.google_project_id:
            # Override dengan nilai dari Secret Manager
            if not self.jwt_secret_key:
                self.jwt_secret_key = get_secret("jwt-secret-key", self.google_project_id)
            if not self.database_url:
                self.database_url = get_secret("database-url", self.google_project_id)
        return self
```

### 7.5 Monitoring & Alerting

```bash
# GCP Cloud Monitoring — Create alerting policies

# Alert: High error rate
gcloud alpha monitoring policies create \
  --policy-from-file=monitoring/error-rate-policy.yaml

# Alert: Auth failures
gcloud logging metrics create auth-failures \
  --description="Count of authentication failures" \
  --log-filter='resource.type=cloud_run_revision AND textPayload=~"401|403|authentication failed"'

# Alert: Unusual file upload
gcloud logging metrics create large-file-upload \
  --description="File uploads over 10MB" \
  --log-filter='resource.type=cloud_run_revision AND httpRequest.responseSize>10485760'

# Alert: DB connection exhaustion
# Monitor: cloudsql.googleapis.com/database/postgresql/num_backends
```

---

## 8. Potential Quick Wins (Can be Fixed Today)

Urutan berdasarkan effort minimum dengan impact maksimum:

### 🔴 30 Menit

1. **Ubah `USE_MAILHOG` default ke `False`** — `app/core/config.py` 1 line
2. **Disable Swagger di production** — `app/main.py` 2 lines
3. **Ubah Celery loglevel ke `INFO`** — `Dockerfile.worker` 1 line

### 🔴 2-4 Jam

4. **Tambahkan USER ke Dockerfile** — 5 lines, no code change required
5. **Tambahkan startup validation** — `app/main.py` ~20 lines
6. **Hapus query param fallback di WebSocket** — `chatbot.py` & `po_query_chatbot.py` ~5 lines
7. **Tambahkan security headers middleware** — ~30 lines new middleware

### 🟡 1 Hari

8. **Fix GCS public_url → signed URL** — `app/core/storage.py` 2 method changes
9. **Sanitize error messages** — `app/api/v1/auth.py` ~10 lines change
10. **Tambahkan file upload validation** — `app/services/attachments_service.py` ~20 lines
11. **`trap cleanup EXIT` di db-commands.sh** — 5 lines

---

## 9. Risk Classification & Business Context

Untuk konteks KPC (Kaltim Prima Coal) yang menangani data:

- **Procurement contracts** (nilai miliaran rupiah)
- **Bid analysis** (informasi penawaran tender yang confidential)
- **Invoice OCR** (data vendor dan pembayaran)
- **Work order** dan **equipment maintenance** (data operasional tambang)

### Risk Classification

| Finding               | Business Risk                                       | Regulatory Risk               |
| --------------------- | --------------------------------------------------- | ----------------------------- |
| H013 (GCS public)     | KRITIS — dokumen tender KPC bisa diakses kompetitor | PDPA/data breach notification |
| H014 (no validation)  | TINGGI — produksi bisa jalan tanpa auth             | Internal audit finding        |
| H012 (root container) | TINGGI — RCE = kontrol penuh atas sistem            | -                             |
| M020 (DB superuser)   | TINGGI — SQL injection impact maximal               | -                             |
| M012 (Swagger public) | SEDANG — API structure tersedia untuk attacker      | -                             |

---

_Report ini disusun berdasarkan analisis source code statis. Validasi tambahan dengan dynamic testing (penetration testing) direkomendasikan sebelum production hardening dinyatakan complete._
