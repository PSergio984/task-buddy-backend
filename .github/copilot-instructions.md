# Copilot Instructions for Task Buddy Backend

## Quick Commands

### Development & Running
```bash
pip install -e ".[dev]"              # Install dependencies with dev extras
fastapi dev                           # Start dev server with auto-reload
uvicorn app.main:app --reload        # Alternative dev server startup
```

### Testing
```bash
pytest                                # Run all tests
pytest tests/routers/test_task.py    # Run single test file
pytest -k test_create_task           # Run tests matching pattern
pytest --cov=app                     # Run with coverage report
pytest tests/routers/test_task.py::test_create_task  # Run single test
```

### Code Quality
```bash
black app tests                       # Format code
ruff check app tests                  # Lint check
ruff check app tests --fix           # Fix linting issues
mypy app                              # Type checking
isort app tests                       # Sort imports
```

### Docker
```bash
docker-compose up                     # Run app + PostgreSQL locally
docker build -t task-buddy .         # Build image
```

---

## Architecture

### High-Level Structure
The application uses **FastAPI with async SQLAlchemy** and follows clean architecture:

- **Routers** (`app/api/routers/`): HTTP endpoints grouped by feature (tasks, users)
- **Database Layer** (`app/database.py`): SQLAlchemy table definitions and `databases` connection pool for async operations
- **Security** (`app/security.py`): JWT/OAuth2 token creation, password hashing (argon2), and user authentication
- **Configuration** (`app/config.py`): Environment-based config (Dev/Prod/Test) using Pydantic settings
- **Middleware**: CORS, correlation ID logging, custom exception handlers for HTTP and unhandled exceptions
- **Lifespan Management** (`app/main.py`): Database connection lifecycle tied to app startup/shutdown

### Key Patterns

#### Database Access
- Tables defined as SQLAlchemy `Table` objects, NOT ORM models
- All queries use `database.fetch_one()`, `database.fetch_all()`, `database.execute()` (async)
- FK constraints enforced: `tbl_subtask` → `tbl_task` → `tbl_users`
- Example: `query = tbl_task.select().where(tbl_task.c.id == task_id)`

#### Authentication
- OAuth2 with JWT (HS256)
- Token validated via `get_current_user()` dependency
- Passwords hashed with argon2 (`passlib[argon2]`)
- `get_current_user()` raises `HTTPException(401)` if token invalid/expired

#### Testing
- **Fixtures in `tests/conftest.py`**: `db`, `async_client`, `registered_user`, `logged_in_token`
- `@pytest.mark.anyio` for async tests; `asyncio_mode = "auto"` in pyproject.toml
- Database cleared per test (respecting FK order: subtasks → tasks → users)
- Example authenticated request:
  ```python
  await async_client.post(
      "/api/v1/tasks/", 
      json={"title": "Test"}, 
      headers={"Authorization": f"Bearer {logged_in_token}"}
  )
  ```

#### Dependency Injection
- Shared deps in `app/dependencies.py`; API-specific in `app/api/dependencies.py`
- Current auth: `Depends(get_current_user)` for protected routes
- Example: `current_user: Annotated[User, Depends(get_current_user)]`

---

## Key Conventions

### Response Models
- **Request schemas**: `TaskCreateRequest`, `UserIn` (Pydantic BaseModel)
- **Response schemas**: `TaskCreateResponse`, `SubTaskCreateResponse` (extend request with `user_id`, `id`, `created_at`)
- Models use `datetime` for timestamps; database auto-sets `created_at` server-side

### Error Handling
- Raise `HTTPException(status_code=404, detail="Task not found")` for resource not found
- Raise `HTTPException(status_code=400, detail="...")` for validation errors
- Unhandled exceptions → 500 with "Internal Server Error" + logged

### Logging
- `logger = logging.getLogger(__name__)` per module
- Log API operations: `logger.info("POST / - creating task title=%s", task.title)`
- Log warnings for expected errors: `logger.warning("PUT /%s - task not found", task_id)`

### Configuration
- **Dev mode**: `ENV_STATE=DEV`, unprefixed env vars, debug logging enabled
- **Prod mode**: `ENV_STATE=PROD`, requires `PROD_SECRET_KEY` (fail-fast validation)
- **Test mode**: `DATABASE_URL=sqlite:///./test.db`, `DB_FORCE_ROLL_BACK=True`
- Sentry initialized if `SENTRY_DSN` set; PII sent only in Dev

### Naming
- Tables prefixed: `tbl_tasks`, `tbl_subtasks`, `tbl_users`, `tbl_tags`
- Route constants as UPPER_SNAKE_CASE for clarity: `ROUTER_TAG`, `TASK_NOT_FOUND`, `SUBTASK_PATH`
- Use `type: ignore[...]` for SQLAlchemy mypy issues (not disallowed)

---

## Common Tasks

### Adding a New Endpoint
1. Create/update router in `app/api/routers/{feature}.py`
2. Define request/response Pydantic models in `app/models/{feature}.py`
3. Use `Depends(get_current_user)` for auth-protected routes
4. Query via `database.fetch_one(query)` or `database.fetch_all(query)`
5. Add tests in `tests/routers/test_{feature}.py` using fixtures
6. Endpoint auto-documented in `/docs` and `/redoc`

### Database Changes
1. Modify table definition in `app/database.py`
2. Table schema created on app startup (`metadata.create_all()`)
3. Update tests to clear new tables in proper FK order in conftest

### Modifying Authentication
- Token logic in `app/security.py`; routes must call `Depends(get_current_user)`
- Changes affect all protected endpoints; test via `logged_in_token` fixture

---

## Environment & Configuration
- `.env` file required (copy from `.env.example`)
- Key vars: `ENV_STATE`, `DATABASE_URL`, `SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES`
- Test db auto-uses SQLite; dev/prod use PostgreSQL by default
- Uvicorn default: `host=127.0.0.1`, `port=8000`

---

## Dependencies
- **Core**: FastAPI, Uvicorn, Pydantic, SQLAlchemy, databases (async DB abstraction)
- **Auth**: python-jose[cryptography], passlib[argon2], python-multipart
- **Utilities**: sentry-sdk, asgi-correlation-id, python-dotenv
- **Dev/Test**: pytest, pytest-asyncio, pytest-cov, black, ruff, mypy, httpx

---

## MCP Server Integrations

### PostgreSQL Database Manager
Useful for direct database queries and schema inspection during development.

**Configuration**:
```json
{
  "name": "PostgreSQL Database Manager",
  "type": "database",
  "host": "localhost",
  "port": 5432,
  "database": "task_buddy",
  "user": "postgres"
}
```

**Usage**: Query `tbl_tasks`, `tbl_subtasks`, `tbl_users` directly; inspect FK relationships; verify data during development.

**Note**: Use `docker-compose up` to spin up PostgreSQL locally.

---

### HTTP/REST API Testing Client
Test endpoints directly without running full Postman or curl manually.

**Configuration**:
```json
{
  "name": "HTTP Client",
  "type": "http",
  "base_url": "http://localhost:8000",
  "default_headers": {
    "Content-Type": "application/json"
  }
}
```

**Usage**:
- Test protected endpoints: `POST /api/v1/tasks/` with `Authorization: Bearer <token>`
- Test auth flow: `POST /api/v1/users/register`, then `POST /api/v1/users/token`
- Validate error responses (401, 404, 422)

---

### Git Integration
Track commits and changes during feature development.

**Usage**:
- Commit changes with trailers (Co-authored-by: Copilot)
- Review diffs before committing
- Link commits to task/PR

**Note**: All Copilot changes include the trailer: `
