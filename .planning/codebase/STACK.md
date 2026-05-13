<!-- generated-by: gsd-doc-writer -->
# Technology Stack

**Analysis Date:** 2026-05-13

## Languages

**Primary:**
- Python 3.12+ - All application code, background tasks, and tests.

**Secondary:**
- Shell (sh) - Startup scripts and environment initialization (`start.sh`).

## Runtime

**Environment:**
- Python 3.12+
- Uvicorn 0.23.0+ (ASGI server)

**Package Manager:**
- **uv** - Primary package manager for high-performance dependency resolution and locking.
- **pip** - Used for compatibility and legacy environment support.
- **Lockfile:** `uv.lock`.

## Frameworks

**Core:**
- FastAPI 0.100.0+ - High-performance web framework.
- Pydantic V2 - State-of-the-art data validation and settings management.
- SQLAlchemy 2.0+ - Database abstraction with full async support.

**Testing:**
- Pytest 7.4+ - Extensible testing framework.
- pytest-asyncio - Async support for tests.
- pytest-cov - Coverage analysis.

**Build/Dev:**
- Ruff - Ultra-fast Python linter and formatter.
- Mypy - Static type checker.
- Alembic - Database migration tool.

## Key Dependencies

**Critical Core:**
- `sqlalchemy` 2.0+ - Core ORM.
- `pydantic` 2.0+ - Schema and validation.
- `python-jose` - JWT token handling.
- `argon2-cffi` - Secure password hashing.
- `slowapi` - Route rate limiting.

**Data & Infrastructure:**
- `asyncpg` - High-performance async PostgreSQL driver.
- `aiosqlite` - Async SQLite driver for testing/dev.
- `redis` 5.0+ - Cache and message broker.
- `celery` 5.3+ - Distributed task queue.
- `sentry-sdk` - Error tracking and performance monitoring.

**Specialized Integrations:**
- `b2sdk` - Backblaze B2 cloud storage integration.
- `pywebpush` - Web Push notification protocol support.
- `asgi-correlation-id` - Request traceability.

## Configuration

**Environment:**
- Handled via `pydantic-settings`.
- Configuration values defined in `.env` and mapped to `app.config.Config`.

**Project Config:**
- `pyproject.toml` - Central configuration for all tools (Ruff, Mypy, Pytest).
- `alembic.ini` - Database migration settings.

## Platform Requirements

**Development:**
- Cross-platform support (Linux, macOS, Windows).
- Docker recommended for local PostgreSQL, Redis, and Worker services.

**Production:**
- Containerized deployment using Docker.
- `Dockerfile` and `docker-compose.yml` provided for standardized deployment.

---

*Stack analysis: 2026-05-13*
*Update after major dependency changes*
