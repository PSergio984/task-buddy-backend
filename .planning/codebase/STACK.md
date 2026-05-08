# Technology Stack

**Analysis Date:** 2026-05-08

## Languages

**Primary:**
- Python 3.9+ - All application code, scripts, and tests.

**Secondary:**
- Shell (sh) - Startup scripts (`start.sh`).

## Runtime

**Environment:**
- Python 3.9+
- Uvicorn 0.23.0+ (ASGI server)

**Package Manager:**
- pip - Using `requirements.txt` and `pyproject.toml`.
- uv - `uv.lock` present, indicating usage of the `uv` package manager for performance.
- Lockfile: `uv.lock` and `requirements.txt` present.

## Frameworks

**Core:**
- FastAPI 0.100.0+ - Web framework for building APIs.
- Pydantic 2.0+ - Data validation and settings management.
- SQLAlchemy 2.0+ - SQL Toolkit and Object Relational Mapper.

**Testing:**
- Pytest 7.4+ - Testing framework.
- pytest-asyncio - Async support for pytest.
- pytest-cov - Coverage reporting.

**Build/Dev:**
- Ruff 0.1+ - Fast Python linter.
- Black 23.0+ - Deterministic code formatter.
- Mypy 1.5+ - Static type checker.
- Alembic 1.12+ - Database migrations.

## Key Dependencies

**Critical:**
- `sqlalchemy` 2.0.0+ - Core ORM and database abstraction.
- `pydantic` 2.0.0+ - Schema definition and validation.
- `python-jose` 3.3.0+ - JWT token generation and verification.
- `passlib` 1.7.4+ - Password hashing with argon2 support.
- `slowapi` 0.1.9+ - Rate limiting for FastAPI.

**Infrastructure:**
- `psycopg2-binary` 2.9.0+ - PostgreSQL database adapter.
- `aiosqlite` 0.19.0+ - Async SQLite support for local development/testing.
- `sentry-sdk` 1.30.0+ - Error tracking and monitoring.
- `asgi-correlation-id` 4.2.0+ - Request ID tracking across services.

## Configuration

**Environment:**
- `.env` files - Handled via `pydantic-settings`.
- Key configs: `DATABASE_URL`, `SECRET_KEY`, `SENTRY_DSN`, `DEV_MAIL_*` (Brevo).

**Build:**
- `pyproject.toml` - Main configuration for build system, dependencies, and tools (black, ruff, mypy).
- `alembic.ini` - Database migration configuration.

## Platform Requirements

**Development:**
- Cross-platform (Windows/macOS/Linux).
- Requires Python 3.9+ and optionally Docker for PostgreSQL/Sentry.

**Production:**
- Docker - `Dockerfile` and `docker-compose.yml` present for containerized deployment.
- Deployment targets: Any container-orchestration platform (Kubernetes, AWS ECS, etc.).

---

*Stack analysis: 2026-05-08*
*Update after major dependency changes*
