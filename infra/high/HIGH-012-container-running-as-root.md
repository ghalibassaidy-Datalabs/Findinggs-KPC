# HIGH-012 — Container Berjalan Sebagai Root User

![Severity](https://img.shields.io/badge/Severity-HIGH-red)
![Module](https://img.shields.io/badge/Module-Container%20%2F%20Runtime-orange)
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

Kedua Dockerfile (`Dockerfile` dan `Dockerfile.worker`) **tidak memiliki instruksi `USER`**, sehingga container berjalan sebagai **root user (uid=0)** secara default. Ini berarti:

- Jika attacker berhasil melakukan Remote Code Execution (RCE) melalui vulnerability di aplikasi, mereka mendapatkan **akses root penuh di dalam container**.
- Proses berjalan sebagai root melanggar **CIS Docker Benchmark Rule 4.1** dan **NIST SP 800-190 (Application Container Security Guide)**.
- Di lingkungan GCP Cloud Run, container root dengan `--privileged` atau volume mount bisa digunakan untuk **container escape**.
- Jika container dapat menulis ke Docker socket (pada self-hosted build agent), root di container = root di host.

---

## Technical Analysis

### Dockerfile (API Service)

```dockerfile
# Dockerfile
FROM python:3.11-slim-bookworm

ARG ENVIRONMENT=production
ENV ENVIRONMENT=${ENVIRONMENT}

WORKDIR /app

# ... install dependencies ...

COPY app/ ./app/
COPY migrations/ ./migrations/
COPY scripts/ ./scripts/    # ← scripts/ termasuk admin tools, seeds, user management

EXPOSE 8080

CMD ["uv", "run", "python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
# ↑ Tidak ada USER instruction — berjalan sebagai root
```

### Dockerfile.worker (Celery Worker)

```dockerfile
# Dockerfile.worker
FROM python:3.11-slim-bookworm
# ...
CMD ["uv", "run", "celery", "-A", "app.core.celery_app", "worker", "--loglevel=DEBUG", "--concurrency=1"]
# ↑ Tidak ada USER instruction — berjalan sebagai root
# ↑ --loglevel=DEBUG di production adalah finding tersendiri (lihat MEDIUM-013)
```

### Verifikasi

Untuk memverifikasi bahwa container berjalan sebagai root:

```bash
# Inspect running container
docker exec <container_id> whoami
# Output: root

docker exec <container_id> id
# Output: uid=0(root) gid=0(root) groups=0(root)
```

### Masalah Tambahan: `scripts/` Di-copy ke Production Image

Production Dockerfile meng-copy `scripts/` yang berisi:

- `user_management.py` — admin user management script
- `auth_seeds/` — seeding scripts dengan role mapping
- `create_migration.py` — dapat membuat migration baru
- `db.py` — direct DB access script
- `cleanup_old_data.py` — destructive script

Script-script ini tidak diperlukan di production runtime dan memperluas attack surface jika RCE terjadi.

---

## Business Impact

| Impact                   | Detail                                                        |
| ------------------------ | ------------------------------------------------------------- |
| **Privilege Escalation** | RCE → root di container → potential container escape          |
| **Data Exfiltration**    | Root dapat mengakses semua file, env vars, secrets            |
| **Lateral Movement**     | Jika Docker socket di-mount, root container = root host       |
| **Compliance**           | Melanggar CIS Docker Benchmark, PCI-DSS requirement 6         |
| **Scope**                | Semua data KPC: invoice, kontrak, bid analysis, data karyawan |

---

## Real Use Case Scenario

### Skenario: SSRF → RCE → Privilege Escalation

1. Attacker menemukan SSRF vulnerability di endpoint upload/AI integration
2. Menggunakan SSRF untuk mengakses GCP metadata endpoint (`169.254.169.254`)
3. Mendapatkan service account token dari metadata
4. Token memberikan akses ke GCS bucket, Cloud Run, atau Artifact Registry
5. Karena proses berjalan sebagai root, semua operasi dalam container bisa dilakukan
6. Attacker dapat mengakses `/proc`, environment variables, dan mounted secrets

### Skenario: Dependency Chain Attack

1. Malicious Python package melalui supply chain attack
2. Package menjalankan post-install script sebagai root
3. Modifikasi binary system atau install backdoor
4. Root access tidak memiliki barrier untuk escalation

---

## Root Cause Analysis

`python:3.11-slim-bookworm` base image default-nya tidak mendeklarasikan non-root user. Developer tidak menambahkan `USER` instruction karena aplikasi bisa berjalan tanpa masalah sebagai root, dan tidak ada security review yang menangkap hal ini.

---

## Evidence / Code Reference

```
Dockerfile       — Line 53 (CMD): tidak ada USER instruction sebelumnya
Dockerfile.worker — Line 43 (CMD): tidak ada USER instruction sebelumnya
```

---

## Reproduction / Testing Steps

```bash
# Build image locally
docker build -t kpc-api-test .

# Run and check user
docker run --rm kpc-api-test whoami
# Expected (vulnerable): root
# Expected (fixed): appuser

# Check UID
docker run --rm kpc-api-test id
# Vulnerable output: uid=0(root) gid=0(root) groups=0(root)
```

### Validasi di GCP Cloud Run

```bash
# Cloud Run tidak mengizinkan privileged containers, tapi masih berbahaya
gcloud run services describe kpc-api --region=asia-southeast2 --format=json | \
  jq '.spec.template.spec.containers[0].securityContext'
```

---

## Risk Assessment

| Kriteria                    | Nilai                                        |
| --------------------------- | -------------------------------------------- |
| **CVSS Score**              | 7.5 (High)                                   |
| **Attack Vector**           | Network (requires app vulnerability first)   |
| **Attack Complexity**       | High (requires another vulnerability)        |
| **Privileges Required**     | None (after initial exploit)                 |
| **Impact: Confidentiality** | High                                         |
| **Impact: Integrity**       | High                                         |
| **Impact: Availability**    | High                                         |
| **Exploitability**          | Medium (requires chaining with another vuln) |

---

## Recommended Fix

### Fix 1: Tambahkan Non-Root User di Dockerfile

```dockerfile
# Dockerfile — AFTER dependency installation, BEFORE CMD
FROM python:3.11-slim-bookworm

ARG ENVIRONMENT=production
ENV ENVIRONMENT=${ENVIRONMENT}

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc make wget curl ca-certificates gnupg lsb-release \
 && rm -rf /var/lib/apt/lists/*

# ... (PostgreSQL repo dan client install) ...

# Copy dan install dependencies
COPY pyproject.toml uv.lock README.md Makefile ./
RUN pip install uv
RUN make install

# Copy application code
COPY app/ ./app/
COPY migrations/ ./migrations/
# ← JANGAN copy scripts/ ke production image

COPY Makefile ./
COPY alembic.ini ./

# ✅ Buat non-root user
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

# ✅ Set ownership
RUN chown -R appuser:appgroup /app

# ✅ Switch ke non-root user
USER appuser

EXPOSE 8080
ENV PORT=8080
ENV HOST=0.0.0.0

CMD ["uv", "run", "python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### Fix 2: Pisahkan Production Image dari Development/Scripts

```dockerfile
# Multi-stage build: exclude scripts dari production
FROM python:3.11-slim-bookworm AS production

# ... setup ...
COPY app/ ./app/
COPY migrations/ ./migrations/
# ← scripts/ tidak di-copy ke production stage

RUN useradd -u 1001 -m appuser
USER appuser
```

### Fix 3: Cloud Run Security Context

```yaml
# cloud-run-service.yaml
spec:
  template:
    spec:
      containers:
        - image: ...
          securityContext:
            runAsNonRoot: true
            runAsUser: 1001
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
```

---

## Long-Term Improvement Recommendation

1. **Implement rootless containers** — Use `runAsNonRoot: true` in Cloud Run/GKE security context
2. **Read-only root filesystem** — `readOnlyRootFilesystem: true`, mount only necessary writable volumes
3. **Distroless images** — Consider `gcr.io/distroless/python3` yang tidak memiliki shell sama sekali
4. **Container scanning** — Integrate Trivy or Snyk ke Azure Pipeline untuk scan image sebelum push
5. **Separate scripts** — Buat image terpisah untuk migration/seeding jobs, jangan bundle ke API image
