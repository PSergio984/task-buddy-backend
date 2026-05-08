# Codebase Structure

## Core Sections (Required)

### 1) Top-Level Map

List only meaningful top-level directories and files.

| Path | Purpose | Evidence |
|------|---------|----------|
| `app/` | Main application source code | Project Structure in README |
| `tests/` | Test suite | Project Structure in README |
| `alembic/` | Database migrations | Directory listing |
| `docs/` | Documentation (including codebase docs) | Directory listing |
| `.agents/` | Agent-specific skills and rules | Directory listing |
| `pyproject.toml` | Project configuration and dependencies | File presence |
| `README.md` | Project overview | File presence |

### 2) Entry Points

- Main runtime entry: `app/main.py`
- Secondary entry points (worker/cli/jobs): `seed.py` (Database seeding), `PROJECT_STRUCTURE.py` (Utility)
- How entry is selected (script/config): Configured in `pyproject.toml` as `tool.fastapi.entrypoint = "app.main:app"`

### 3) Module Boundaries

| Boundary | What belongs here | What must not be here |
|----------|-------------------|------------------------|
| `app/api/routers/` | Endpoint definitions and request handling | Complex business logic, direct DB queries (should use CRUD/models) |
| `app/models/` | SQLAlchemy ORM models | Pydantic schemas, API logic |
| `app/schemas/` | Pydantic request/response schemas | DB models, business logic |
| `app/crud/` | Database CRUD operations | API response formatting |
| `app/internal/` | Admin and internal utility modules | Public API endpoints |

### 4) Naming and Organization Rules

- File naming pattern: Snake case (`snake_case.py`)
- Directory organization pattern: Layered (`api/`, `models/`, `schemas/`, `crud/`)
- Import aliasing or path conventions: Relative imports within `app/` package

### 5) Evidence

- `README.md` (Project Structure section)
- `pyproject.toml` (Entrypoint configuration)
- `app/main.py` (FastAPI app initialization)
- `CLAUDE.md` (High-Level Architecture section)

## Extended Sections (Optional)

- `app/api/routers/` deep map: `task.py`, `user.py`, `audit.py`, `stats.py`.
- `app/models/` deep map: `task.py`, `user.py`, `tag.py`, `audit.py`, `stats.py`.
