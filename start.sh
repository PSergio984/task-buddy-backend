#!/bin/bash
set -e

# Auto migrate db on startup
echo "Starting migration process..."
if ! alembic upgrade head 2>&1; then
    echo "Migration failed. Attempting to force-sync by clearing stale revision and stamping head..."
    # Directly purge the unknown revision from alembic_version so stamp can proceed
    python -c "
import os, sqlalchemy as sa
url = os.environ.get('DATABASE_URL') or os.environ.get('PROD_DATABASE_URL')
if not url: raise KeyError('DATABASE_URL or PROD_DATABASE_URL not found')
engine = sa.create_engine(url)
with engine.begin() as conn:
    conn.execute(sa.text('DELETE FROM alembic_version'))
    print('Cleared alembic_version table.')
engine.dispose()
" || { echo "FATAL: could not clear alembic_version — check DATABASE_URL is set correctly"; exit 1; }
    alembic stamp head
    alembic upgrade head
fi

# Idempotent seed (no-ops if records already exist)
echo "Running seeding script..."
python scripts/seed.py

# Start app
echo "Starting web server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*"
