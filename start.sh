#!/bin/bash
set -e

echo "Starting migration process..."

# Pre-flight: detect any partially-created or fully-missing schema.
# Checks all critical tables — if ANY is missing, clears alembic_version
# and the orphaned enum so alembic upgrade head runs a clean migration.
# This must run BEFORE alembic upgrade head because alembic returns exit 0
# ("already at head") even when tables don't exist, masking broken state.
python -c "
import os, sqlalchemy as sa
url = os.environ.get('DATABASE_URL') or os.environ.get('PROD_DATABASE_URL')
if not url: raise SystemExit('DATABASE_URL not set')
url = url.replace('postgres://', 'postgresql://', 1)
engine = sa.create_engine(url)
REQUIRED_TABLES = ['tbl_users', 'tbl_projects', 'tbl_tasks', 'tbl_tags', 'tbl_subtasks', 'tbl_task_tags', 'tbl_audit_logs']
with engine.begin() as conn:
    try:
        rows = conn.execute(sa.text(
            \"SELECT table_name FROM information_schema.tables \"
            \"WHERE table_schema='public' AND table_name = ANY(:names)\"
        ), {'names': REQUIRED_TABLES}).fetchall()
        existing = {r[0] for r in rows}
    except Exception:
        existing = set()
    missing = [t for t in REQUIRED_TABLES if t not in existing]
    if missing:
        print(f'Pre-flight: missing tables {missing} — clearing stale migration state.')
        conn.execute(sa.text('''
            CREATE TABLE IF NOT EXISTS alembic_version (
                version_num VARCHAR(32) NOT NULL,
                CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
            )
        '''))
        conn.execute(sa.text('DELETE FROM alembic_version'))
        conn.execute(sa.text('DROP TYPE IF EXISTS taskpriority'))
    else:
        print('Pre-flight: all required tables present, proceeding normally.')
engine.dispose()
" || { echo "FATAL: pre-flight check failed"; exit 1; }

# Run migration; if it fails (e.g. stale revision with existing tables), stamp and retry.
if ! alembic upgrade head 2>&1; then
    echo "Migration failed. Attempting stale-revision recovery..."
    python -c "
import os, sqlalchemy as sa
url = os.environ.get('DATABASE_URL') or os.environ.get('PROD_DATABASE_URL')
if not url: raise KeyError('DATABASE_URL or PROD_DATABASE_URL not found')
engine = sa.create_engine(url)
with engine.begin() as conn:
    conn.execute(sa.text('''
        CREATE TABLE IF NOT EXISTS alembic_version (
            version_num VARCHAR(32) NOT NULL,
            CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
        )
    '''))
    conn.execute(sa.text('DELETE FROM alembic_version'))
    print('Cleared alembic_version for stamp.')
engine.dispose()
" || { echo "FATAL: could not reset alembic_version"; exit 1; }
    alembic stamp head
    alembic upgrade head
fi

# Idempotent seed — skipped in production unless SEED_ALLOWED=true
# Use || true so a blocked/skipped seed does not abort startup via set -e
echo "Running seeding script..."
python scripts/seed.py || true

# Start app
echo "Starting web server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*"
