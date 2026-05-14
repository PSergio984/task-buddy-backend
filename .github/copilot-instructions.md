# Copilot Instructions for Task Buddy Backend

## Build, test, and lint commands

### Setup and run
```bash
pip install -e ".[dev]"
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
celery -A app.celery_app worker --loglevel=info
docker-compose up --build
```

### Tests
```bash
pytest
pytest tests/routers/test_task.py
pytest tests/routers/test_task.py::test_create_task
pytest -k test_create_task
pytest --cov=app --cov-report=html
```

### Lint/format/type-check
```bash
black app tests
ruff check app tests
isort app tests
mypy app
```

## High-level architecture

- `app/main.py` is the composition root: it initializes Sentry/logging, installs middleware (correlation ID, idempotency, CORS, security headers), registers rate-limit and global exception handlers, and mounts routers under `/api/v1/*`.
- Request flow is **router -> CRUD -> SQLAlchemy async ORM models**:
  - Routers in `app/api/routers/` own HTTP behavior and user-facing errors.
  - CRUD modules in `app/crud/` own DB queries/mutations.
  - ORM models in `app/models/` define `tbl_*` tables, relationships, and constraints.
- `app/database.py` centralizes `AsyncSessionLocal` and normalizes DB URLs to async drivers (`sqlite+aiosqlite`, `postgresql+asyncpg`), including PostgreSQL query-param sanitization.
- Auth is split between:
  - `app/security.py` for JWT creation/verification, password hashing, Redis-backed token blacklist, and `get_current_user`.
  - `app/api/routers/user.py` for login/logout/register/reset endpoints, cookie handling, and token issuance.
- Background work is offloaded through Celery:
  - `app/celery_app.py` configures Redis broker/backend plus scheduled reminder processing.
  - Routers queue email/push jobs via `app.tasks.*.delay(...)`.
- Test architecture (`tests/conftest.py`) swaps app DB/session to a temp SQLite DB, overrides `get_db`, and auto-mocks Redis/token blacklist + outbound task side effects.

## Key conventions for this repository

- Use `Annotated[..., Depends(...)]` for dependencies across routers.
- Protected endpoints consistently use `Depends(get_current_user)`, and ownership checks are enforced by filtering with `user_id` in CRUD/query paths (IDOR prevention pattern).
- Mutating CRUD functions are decorated with `@audit_log(...)` (`app/libs/audit.py`); audit details/diffs are generated there, not in routers.
- Routers generally handle transaction boundaries (`await db.commit()` / `await db.refresh(...)`), while CRUD functions usually `flush` and return ORM objects.
- Endpoint decorators include `responses={...}` for expected error codes; keep OpenAPI error docs explicit when adding/changing routes.
- Rate-limited endpoints use `@limiter.limit(...)` and include `request: Request` in the signature.
- Task responses requiring relationships explicitly load async attrs before serialization (e.g., `await db_task.awaitable_attrs.tags` and `subtasks`).
- Auth token extraction supports both OAuth2 bearer header and `access_token` HttpOnly cookie (`get_token` in `app/security.py`).
- SQLAlchemy metadata uses naming conventions in `app/models/base.py`; preserve them for new constraints/migrations.

## graphify

For any question about this repo's architecture, structure, components, or how to add/modify/find
code, your **first tool call must be** to read `graphify-out/GRAPH_REPORT.md` (if it exists).

Triggers: "how do I…", "where is…", "what does … do", "add/modify a <component>",
"explain the architecture", or anything that depends on how files or classes relate.

After reading the report (and `graphify-out/wiki/index.md` for deep questions), answer from the
graph. Only read source files when (a) modifying/debugging specific code, (b) the graph lacks
the needed detail, or (c) the graph is missing or stale.

Type `/graphify` in Copilot Chat to build or update the graph.
