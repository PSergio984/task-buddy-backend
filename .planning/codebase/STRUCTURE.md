<!-- generated-by: gsd-doc-writer -->
# Structure

**Analysis Date:** 2026-05-12

## Directory Layout

```text
task-buddy-backend/
├── alembic/              # Database migration history and env
├── app/                  # Application root
│   ├── api/              # API Layer
│   │   └── routers/      # Route handlers (task, user, project, notifications, etc.)
│   ├── crud/             # Persistence logic (CREATE/READ/UPDATE/DELETE)
│   ├── libs/             # Reusable internal libraries (B2, Audit, Templates)
│   ├── models/           # SQLAlchemy ORM models
│   ├── schemas/          # Pydantic validation & serialization models
│   ├── internal/         # Admin and internal-only utilities
│   ├── celery_app.py     # Celery worker configuration
│   ├── config.py         # Type-safe configuration (Pydantic Settings)
│   ├── database.py       # DB engine and session factory
│   ├── dependencies.py   # FastAPI dependency providers
│   ├── main.py           # Application entry point & middleware
│   ├── tasks.py          # Background task definitions
│   └── security.py       # Auth, hashing, and JWT logic
├── docs/                 # General documentation & diagrams
├── tests/                # Automated test suite
│   ├── routers/          # API integration tests
│   └── conftest.py       # Pytest fixtures and mocks
├── scripts/              # Utility scripts (seed, vapid gen)
├── .planning/            # GSD documentation and project state
├── pyproject.toml        # Project metadata & tool settings
└── uv.lock               # Deterministic dependency lockfile
```

## Key Locations

| Location | Purpose |
|----------|---------|
| `app/main.py` | FastAPI app initialization and global middleware |
| `app/api/routers/` | Business domain endpoints |
| `app/models/` | Definitive database schema definitions |
| `app/schemas/` | Definitive API contract definitions |
| `app/crud/` | Core data manipulation logic |
| `app/libs/` | External service integrations (B2, Email) |
| `tests/` | Comprehensive test coverage (Unit, Integration, E2E) |

## Naming Conventions

- **Directories:** Snake case (`app/api/routers`).
- **Files:** Snake case (`project_router.py`).
- **Classes:** Pascal case (`NotificationRead`, `ProjectCreate`).
- **Functions/Variables:** Snake case (`get_db`, `current_user`).
- **Schemas:** Suffix with `Request` or `Response` where appropriate for clarity.

---

*Structure analysis: 2026-05-12*
*Update when directories are reorganized or new top-level folders are added*
