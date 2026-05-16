#!/bin/bash
set -e

echo "Starting migration process..."

# Pre-flight: detect any partially-created or fully-missing schema.
# Checks all critical tables — if ANY is missing, clears alembic_version
# and the orphaned enum so alembic upgrade head runs a clean migration.
python -c "
import os, sqlalchemy as sa
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
url = os.environ.get('DATABASE_URL') or os.environ.get('PROD_DATABASE_URL') or os.environ.get('DEV_DATABASE_URL')
if not url: raise SystemExit('DATABASE_URL, PROD_DATABASE_URL, or DEV_DATABASE_URL not set')
url = url.replace('postgres://', 'postgresql://', 1)
engine = sa.create_engine(url)
REQUIRED_TABLES = [
    'tbl_users', 'tbl_projects', 'tbl_tasks', 'tbl_tags', 
    'tbl_subtasks', 'tbl_task_tags', 'tbl_audit_logs',
    'tbl_notifications', 'tbl_push_subscriptions'
]
with engine.begin() as conn:
    try:
        # Check for tables in public schema
        res = conn.execute(sa.text(\"SELECT table_name FROM information_schema.tables WHERE table_schema='public'\")).fetchall()
        existing = {r[0] for r in res}
        print(f'Pre-flight: Found tables: {existing}')
    except Exception as e:
        print(f'Pre-flight: Error checking tables: {e}')
        existing = set()

    missing = [t for t in REQUIRED_TABLES if t not in existing]
    if missing:
        print(f'Pre-flight: Missing tables {missing} — clearing stale migration state.')
        conn.execute(sa.text('''
            CREATE TABLE IF NOT EXISTS alembic_version (
                version_num VARCHAR(32) NOT NULL,
                CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
            )
        '''))
        conn.execute(sa.text('DELETE FROM alembic_version'))
        # Also drop the enums if they exist to avoid DuplicateObject error on fresh migration.
        # Use CASCADE to ensure they are dropped even if some tables still exist.
        conn.execute(sa.text('DROP TYPE IF EXISTS taskpriority CASCADE'))
        conn.execute(sa.text('DROP TYPE IF EXISTS notificationtype CASCADE'))
    else:
        print('Pre-flight: All required tables present.')
engine.dispose()
" || { echo "FATAL: pre-flight check failed"; exit 1; }

# Run migration
echo "Running alembic upgrade head..."
if ! alembic upgrade head; then
    echo "Migration failed. Checking if we need to stamp head..."
    # Recovery: only stamp head if tables ALREADY exist but version is missing/stale
    python -c "
import os, sqlalchemy as sa
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
url = os.environ.get('DATABASE_URL') or os.environ.get('PROD_DATABASE_URL') or os.environ.get('DEV_DATABASE_URL')
if not url: raise SystemExit('DATABASE_URL, PROD_DATABASE_URL, or DEV_DATABASE_URL not set')
url = url.replace('postgres://', 'postgresql://', 1)
engine = sa.create_engine(url)
REQUIRED_TABLES = [
    'tbl_users', 'tbl_projects', 'tbl_tasks', 'tbl_tags', 
    'tbl_subtasks', 'tbl_task_tags', 'tbl_audit_logs',
    'tbl_notifications', 'tbl_push_subscriptions'
]
with engine.begin() as conn:
    res = conn.execute(sa.text(\"SELECT table_name FROM information_schema.tables WHERE table_schema='public'\")).fetchall()
    existing = {r[0] for r in res}
    missing = [t for t in REQUIRED_TABLES if t not in existing]
    if not missing:
        print('Tables exist but migration failed. Stamping head for recovery.')
        conn.execute(sa.text('''
            CREATE TABLE IF NOT EXISTS alembic_version (
                version_num VARCHAR(32) NOT NULL,
                CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
            )
        '''))
        conn.execute(sa.text('DELETE FROM alembic_version'))
        # We return exit 0 to tell bash to run stamp
        exit(0)
    else:
        print(f'Tables {missing} are missing. Cannot stamp head. Migration must fix this.')
        exit(1)

" && {
    alembic stamp head
    alembic upgrade head
} || { echo "FATAL: Migration failed and recovery not possible."; exit 1; }
fi

# Idempotent seed — skipped in production unless SEED_ALLOWED=true
echo "Running seeding script..."
python scripts/seed.py || true

# Start Celery worker in the background
# We limit concurrency to 1 and use a single worker process to save memory on constrained environments like Render (512MB).
# CELERY_CONCURRENCY and CELERY_POOL can be overridden via environment variables.
CELERY_CONCURRENCY=${CELERY_CONCURRENCY:-1}
CELERY_POOL=${CELERY_POOL:-prefork}

echo "Starting Celery worker (pool: $CELERY_POOL, concurrency: $CELERY_CONCURRENCY)..."
celery -A app.celery_app worker --loglevel=info --concurrency="$CELERY_CONCURRENCY" --pool="$CELERY_POOL" &

# Start app
# We explicitly set workers to 1 (or WEB_CONCURRENCY if set) to ensure memory stability.
WORKERS=${WEB_CONCURRENCY:-1}
echo "Starting web server with $WORKERS worker(s)..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "$WORKERS" --proxy-headers --forwarded-allow-ips="*" "$@"
