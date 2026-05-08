# Coding Conventions

## Core Sections (Required)

### 1) Naming Rules

| Item | Rule | Example | Evidence |
|------|------|---------|----------|
| Files | Snake case | `task_router.py` | Directory listing |
| Functions/methods | Snake case | `get_current_user()` | `app/security.py` |
| Types/interfaces | Pascal case (Pydantic models, SQLAlchemy classes) | `TaskCreate`, `User` | `app/schemas/task.py`, `app/models/user.py` |
| Constants/env vars | Upper snake case | `SECRET_KEY` | `app/config.py` |

### 2) Formatting and Linting

- Formatter: Black (configured in `pyproject.toml`)
- Linter: Ruff (configured in `pyproject.toml`)
- Most relevant enforced rules: Line length (default 88 for Black), strict type hinting.
- Run commands:
  ```bash
  black app tests
  ruff check app tests
  isort app tests
  mypy app
  ```

### 3) Import and Module Conventions

- Import grouping/order: Standard library, third-party, local app imports (enforced by `isort`).
- Alias vs relative import policy: Prefers absolute imports for `app` modules, e.g., `from app.models.user import User`.
- Public exports/barrel policy: `__init__.py` files are mostly empty or used for simple exports.

### 4) Error and Logging Conventions

- Error strategy by layer: FastAPI's `HTTPException` used in routers for client errors. Custom exception handlers can be registered in `main.py`.
- Logging style and required context fields: Uses `python-json-logger` for structured JSON logs. Correlation ID included in all logs via `asgi-correlation-id`.
- Sensitive-data redaction rules: Redaction of passwords and tokens in logs (assumed standard practice, evidenced by presence of security-focused dependencies).

### 5) Testing Conventions

- Test file naming/location rule: Prefixed with `test_`, located in `tests/` directory mirroring `app/` structure.
- Mocking strategy norm: Uses `pytest-mock` and `httpx.AsyncClient` for async API testing.
- Coverage expectation: Uses `pytest-cov` to measure coverage (target typically >80%).

### 6) Evidence

- `pyproject.toml`
- `CLAUDE.md`
- `app/logging_conf.py`
- `tests/conftest.py`

## Extended Sections (Optional)

- Layer-specific error handling: Routers handle `4xx` and `5xx` responses; CRUD layer raises exceptions that routers catch.
