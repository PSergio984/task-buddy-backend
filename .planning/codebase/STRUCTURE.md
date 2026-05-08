# Structure

**Analysis Date:** 2026-05-08

## Directory Layout

```text
task-buddy-backend/
├── alembic/              # Database migration scripts
├── app/                  # Application source code
│   ├── api/              # API layer
│   │   ├── routers/      # Endpoint route handlers
│   │   └── dependencies.py # Shared API dependencies (Auth, DB)
│   ├── crud/             # Database CRUD logic
│   ├── internal/         # Internal modules (admin, audit logic)
│   ├── models/           # SQLAlchemy database models
│   ├── schemas/          # Pydantic validation schemas
│   ├── config.py         # Application configuration/settings
│   ├── database.py       # Database connection and session management
│   ├── limiter.py        # Rate limiting configuration
│   ├── logging_conf.py   # Logging setup
│   ├── main.py           # Application entry point
│   ├── security.py       # Auth and security utilities
│   └── tasks.py          # Background tasks (email, etc.)
├── docs/                 # Documentation files
├── tests/                # Automated test suite
│   ├── routers/          # Integration tests for API routes
│   └── conftest.py       # Pytest fixtures and global setup
├── .planning/            # GSD planning and state tracking
├── pyproject.toml        # Project metadata and tool config
├── requirements.txt      # Production dependencies
└── uv.lock               # Dependency lockfile
```

## Key Locations

| Location | Purpose |
|----------|---------|
| `app/main.py` | App initialization and middleware setup |
| `app/api/routers/` | Business endpoints (tasks, users, etc.) |
| `app/models/` | Source of truth for database schema |
| `app/schemas/` | Source of truth for API request/response shapes |
| `app/crud/` | Data persistence logic |
| `tests/conftest.py` | Shared test setup (test DB, client) |
| `alembic/versions/` | Historical database migration files |

## Naming Conventions

- **Directories:** Snake case (`app/api/routers`).
- **Files:** Snake case (`user_router.py`, `task_model.py`).
- **Classes:** Pascal case (`UserCreate`, `TaskBase`).
- **Functions:** Snake case (`get_user_by_email`, `create_task`).
- **Variables:** Snake case (`access_token`, `db_session`).

---

*Structure analysis: 2026-05-08*
*Update when directories are reorganized*
