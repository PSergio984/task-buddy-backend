# Technology Stack

**Analysis Date:** 2025-05-14

## Languages

**Primary:**
- Python 3.9+ - Core backend logic and API implementation.

## Runtime

**Environment:**
- Python 3.13 (detected in venv) - The current execution environment.

**Package Manager:**
- `pip` with `pyproject.toml` and `uv.lock` - Dependency management.
- Lockfile: `uv.lock` present.

## Frameworks

**Core:**
- FastAPI >=0.100.0 - Web framework for building APIs.

**Testing:**
- Pytest >=7.4.0 - Test runner.
- Pytest-Asyncio >=0.21.0 - Support for testing async code.
- Pytest-Cov >=4.1.0 - Coverage reporting.

**Build/Dev:**
- Uvicorn >=0.23.0 - ASGI server.
- Black >=23.0.0 - Code formatter.
- Ruff >=0.1.0 - Linter.
- Mypy >=1.5.0 - Static type checker.

## Key Dependencies

**Critical:**
- SQLAlchemy >=2.0.0 - SQL Toolkit and ORM (used via Core).
- Pydantic >=2.0.0 - Data validation and settings management.
- Databases[sqlite] >=0.8.0 - Async database support.
- Python-Jose[cryptography] >=3.3.0 - JWT implementation.
- Passlib[argon2] >=1.7.4 - Password hashing.

**Infrastructure:**
- Slowapi >=0.1.9 - Rate limiting.
- Sentry-SDK >=1.30.0 - Error monitoring and tracking.
- ASGI-Correlation-ID >=4.2.0 - Request correlation for logging.
- Alembic >=1.12.0 - Database migrations.

## Configuration

**Environment:**
- Configured using `pydantic-settings` in `app/config.py`.
- Loads from `.env` file with environment-specific overrides (Dev, Prod, Test).

**Build:**
- `pyproject.toml` - Main project configuration.
- `alembic.ini` - Migration configuration.

## Platform Requirements

**Development:**
- Python 3.9+
- SQLite (local development)

**Production:**
- PostgreSQL (supported via `psycopg2-binary`)
- Sentry for monitoring.

---

*Stack analysis: 2025-05-14*
