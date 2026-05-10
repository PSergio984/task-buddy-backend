#!/bin/bash
set -e

echo "Starting migration process..."

# Pre-flight: if critical tables are missing (e.g. alembic was stamped to head
# but the DDL never completed), wipe migration state so we start fresh.
# This must run BEFORE alembic upgrade head, because alembic returns exit 0
# ("already at head") even when tables don't exist, masking the broken state.
python -c "
import os, sqlalchemy as sa
url = os.environ.get('DATABASE_URL') or os.environ.get('PROD_DATABASE_URL')
if not url: raise SystemExit('DATABASE_URL not set')
engine = sa.create_engine(url)
with engine.begin() as conn:
    try:
        count = conn.execute(sa.text(
            \"SELECT COUNT(*) FROM information_schema.tables \"
            \"WHERE table_schema='public' AND table_name='tbl_tasks'\"
        )).scalar()
    except Exception:
        count = 0
    if count == 0:
        conn.execute(sa.text('''
            CREATE TABLE IF NOT EXISTS alembic_version (
                version_num VARCHAR(32) NOT NULL,
                CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
            )
        '''))
        conn.execute(sa.text('DELETE FROM alembic_version'))
        conn.execute(sa.text('DROP TYPE IF EXISTS taskpriority'))
        print('Pre-flight: tables missing — cleared stale migration state.')
    else:
        print('Pre-flight: schema OK, proceeding normally.')
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

# Idempotent seed (no-ops if records already exist)
echo "Running seeding script..."
python scripts/seed.py

# Start app
echo "Starting web server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*"
