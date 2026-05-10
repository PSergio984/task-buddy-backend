#!/bin/bash
set -e

# Auto migrate db on startup
echo "Starting migration process..."
if ! alembic upgrade head; then
    echo "Migration failed (likely due to missing revision). Attempting to synchronize by stamping head..."
    alembic stamp head
    alembic upgrade head
fi

# Idempotent seed (no-ops if records already exist)
echo "Running seeding script..."
python scripts/seed.py

# Start app
echo "Starting web server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*"
