#!/bin/bash
set -e

# Auto migrate db on startup
alembic upgrade head

# Idempotent seed (no-ops if records already exist)
python seed.py

# Start app
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*"
