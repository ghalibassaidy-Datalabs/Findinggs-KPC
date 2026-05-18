# MEDIUM-020 — Database Superuser Digunakan untuk Aplikasi dan Migration

![Severity](https://img.shields.io/badge/Severity-MEDIUM-yellow)
![Module](https://img.shields.io/badge/Module-Database%20%2F%20Access%20Control-orange)
![Status](https://img.shields.io/badge/Status-Open-important)

---

## Executive Summary

Berdasarkan konfigurasi di pipeline scripts dan env.example, aplikasi dan migration jobs menggunakan **user `postgres`** (PostgreSQL superuser) untuk koneksi database:

```bash
# env.example
DATABASE_URL=postgresql://postgres:password@localhost:5432/kpc_app

# pipeline-scripts/db-commands.sh
DATABASE_URL="postgresql://postgres:$DB_PASSWORD@$DB_HOST:5432/$DB_NAME"
```

Penggunaan superuser `postgres` untuk application runtime melanggar prinsip **least privilege** dan memiliki implikasi keamanan serius:

1. Jika credentials bocor, attacker memiliki **full database control**
2. SQL injection (jika ada) bisa `DROP TABLE`, `CREATE EXTENSION`, atau `COPY TO FILE`
3. Tidak ada database-level access control yang membatasi tabel mana yang bisa diakses

---

## Technical Analysis

### PostgreSQL `postgres` User

User `postgres` adalah superuser bawaan PostgreSQL dengan kemampuan:

- `CREATE DATABASE` / `DROP DATABASE`
- `CREATE ROLE` / `DROP ROLE`
- Akses ke **semua tabel di semua schema**
- `COPY ... TO '/etc/passwd'` (file system access)
- `CREATE EXTENSION` (load arbitrary code di beberapa konfigurasi)
- Bypass Row-Level Security

### env.example

```bash
DATABASE_URL=postgresql://postgres:password@localhost:5432/kpc_app
#                          ^^^^^^^^ superuser
```

### CI/CD Pipeline

```bash
# pipeline-scripts/db-commands.sh
until psql -h "$DB_HOST" -p 5432 -U postgres -d "$DB_NAME" -c "SELECT 1;"; do
#                                    ^^^^^^^^ superuser untuk health check + migrations
```

### Tidak Ada Separation of Concerns

Seharusnya ada minimal 2 database roles:

- **`kpc_migrator`** — hanya untuk DDL (CREATE TABLE, ALTER TABLE) — digunakan oleh Alembic
- **`kpc_app`** — hanya DML (SELECT, INSERT, UPDATE, DELETE) — digunakan oleh aplikasi runtime

---

## Business Impact

| Impact                   | Detail                                                     |
| ------------------------ | ---------------------------------------------------------- |
| **Privilege Escalation** | SQL injection → DROP semua tabel                           |
| **Data Exfiltration**    | Superuser bisa baca tabel yang seharusnya tidak accessible |
| **Lateral Movement**     | Superuser bisa membuat user baru, grant permissions        |
| **Defense in Depth**     | Tidak ada DB-level barrier jika app layer dikompromis      |

---

## Root Cause Analysis

Menggunakan `postgres` superuser adalah pattern "easiest path" saat development. Tidak ada review yang menegakkan least privilege untuk database credentials.

---

## Evidence / Code Reference

```
env.example                      — postgres user di DATABASE_URL
pipeline-scripts/db-commands.sh — postgres user untuk migration
```

---

## Recommended Fix

### Fix: Buat Application-Specific Database User

```sql
-- Jalankan sebagai postgres superuser, sekali saja

-- 1. Create migrator role (hanya untuk Alembic migrations)
CREATE ROLE kpc_migrator WITH LOGIN PASSWORD 'strong-migrator-password';
GRANT CONNECT ON DATABASE kpc_app TO kpc_migrator;
GRANT CREATE ON SCHEMA public TO kpc_migrator;
-- Migrator butuh full DDL access
GRANT ALL ON ALL TABLES IN SCHEMA public TO kpc_migrator;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO kpc_migrator;

-- 2. Create app runtime role (hanya DML)
CREATE ROLE kpc_app_user WITH LOGIN PASSWORD 'strong-app-password';
GRANT CONNECT ON DATABASE kpc_app TO kpc_app_user;
GRANT USAGE ON SCHEMA public TO kpc_app_user;
-- Hanya DML, tidak DDL
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO kpc_app_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO kpc_app_user;

-- 3. Set default privileges untuk tabel baru (saat migration)
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO kpc_app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO kpc_app_user;
```

```bash
# env untuk application runtime
DATABASE_URL=postgresql://kpc_app_user:app-password@localhost:5432/kpc_app

# env untuk migration (CI/CD only)
MIGRATION_DATABASE_URL=postgresql://kpc_migrator:migrator-password@localhost:5432/kpc_app
```

### Fix Pipeline: Pisahkan Migration Credentials

```bash
# pipeline-scripts/db-commands.sh
# Gunakan migrator credentials untuk migration
docker run --rm \
  -e DATABASE_URL="postgresql://kpc_migrator:$MIGRATION_PASSWORD@$DB_HOST:5432/$DB_NAME" \
  "$APP_IMAGE_TAG" \
  sh -c "make db COMMAND=migrate"
```

---

## Long-Term Improvement Recommendation

1. **Row-Level Security (RLS)** — Implementasi RLS untuk data yang multi-tenant
2. **GCP Cloud SQL IAM Auth** — Gunakan IAM-based database auth alih-alih password
3. **Secret rotation** — Rotasi database password secara periodik via GCP Secret Manager
4. **Query timeout** — Set `statement_timeout` per role untuk mencegah long-running queries
5. **Audit logging** — Enable PostgreSQL audit logging untuk akses ke tabel sensitif
