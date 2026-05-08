# Technology Stack

## Core Sections (Required)

### 1) Runtime Summary

| Area | Value | Evidence |
|------|-------|----------|
| Primary language | Python | pyproject.toml |
| Runtime + version | Python >=3.9 | pyproject.toml |
| Package manager | pip / uv (uv.lock present) | uv.lock, pyproject.toml |
| Module/build system | setuptools | pyproject.toml |

### 2) Production Frameworks and Dependencies

List only high-impact production dependencies (frameworks, data, transport, auth).

| Dependency | Version | Role in system | Evidence |
|------------|---------|----------------|----------|
| fastapi | >=0.100.0 | Web framework | pyproject.toml |
| uvicorn | >=0.23.0 | ASGI server | pyproject.toml |
| sqlalchemy | >=2.0.0 | SQL Toolkit and ORM | pyproject.toml |
| pydantic | >=2.0.0 | Data validation | pyproject.toml |
| pydantic-settings | >=2.0.0 | Settings management | pyproject.toml |
| python-jose | >=3.3.0 | JWT implementation | pyproject.toml |
| passlib | >=1.7.4 | Password hashing | pyproject.toml |
| slowapi | >=0.1.9 | Rate limiting | pyproject.toml |
| sentry-sdk | >=1.30.0 | Error monitoring | pyproject.toml |
| asgi-correlation-id | >=4.2.0 | Request correlation | pyproject.toml |

### 3) Development Toolchain

| Tool | Purpose | Evidence |
|------|---------|----------|
| pytest | TESTING | pyproject.toml |
| black | FORMAT | pyproject.toml |
| ruff | LINT | pyproject.toml |
| mypy | TYPE CHECKING | pyproject.toml |
| isort | FORMAT (imports) | pyproject.toml |

### 4) Key Commands

```bash
pip install -e ".[dev]"
uvicorn app.main:app --reload
pytest
ruff check app tests
black app tests
mypy app
```

### 5) Environment and Config

- Config sources: `.env`, `app/config.py`
- Required env vars: `DATABASE_URL`, `SECRET_KEY`, `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`
- Deployment/runtime constraints: Python 3.9+, PostgreSQL (optional, can use SQLite)

### 6) Evidence

- `pyproject.toml`
- `app/config.py`
- `README.md`
