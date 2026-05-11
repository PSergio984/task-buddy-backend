# Architecture

**Analysis Date:** 2026-05-08

## Pattern Overview

**Overall:** Layered Monolith (FastAPI)

**Key Characteristics:**
- **Separation of Concerns:** Distinct layers for routing (API), business logic (CRUD), and data modeling (Models/Schemas).
- **Asynchronous IO:** Full use of Python `async`/`await` for database and external integration calls.
- **Dependency Injection:** Leverages FastAPI's `Depends` for shared logic like authentication and database sessions.
- **Statelessness:** Request handling is stateless, relying on JWT for identity.

## Layers

**API Layer (`app/api/`):**
- **Purpose:** Handles HTTP requests and responses.
- **Contains:** Router modules (`app/api/routers/`), dependency providers (`app/api/dependencies.py`).
- **Used by:** External clients.

**CRUD Layer (`app/crud/`):**
- **Purpose:** Encapsulates database operations.
- **Contains:** Functions to create, read, update, and delete records for each model.
- **Depends on:** Models layer, Database session.

**Models Layer (`app/models/`):**
- **Purpose:** Defines database schema via SQLAlchemy.
- **Contains:** Class definitions for `User`, `Task`, `Tag`, `Audit`, `Stats`.
- **Used by:** CRUD and API layers.

**Schemas Layer (`app/schemas/`):**
- **Purpose:** Defines data validation and serialization via Pydantic.
- **Contains:** Request/Response models for API endpoints.
- **Used by:** API layer for input validation and output formatting.

## Data Flow

**HTTP Request Lifecycle:**

1. **Entry Point:** `app/main.py` receives request via Uvicorn.
2. **Routing:** FastAPI routes request to specific router in `app/api/routers/`.
3. **Dependencies:** `app/api/dependencies.py` verifies JWT or gets DB session.
4. **Validation:** Pydantic schemas in `app/schemas/` validate request body.
5. **Logic:** Router calls function in `app/crud/` to interact with database.
6. **Persistence:** `app/crud/` uses SQLAlchemy models in `app/models/` to query/update DB.
7. **Response:** Router returns data, serialized via Pydantic schema back to JSON.

**Background Tasks:**
- **Celery:** Used for distributed task processing (email dispatch, heavy data processing) via Redis broker.
- **Worker:** Separate process runs `celery -A app.celery_app worker`.
- **Location:** `app/celery_app.py` and `app/tasks.py`.

## Key Abstractions

**Database Session:**
- Provided via `get_db` dependency in `app/database.py`.
- Ensures proper connection pooling and cleanup.

**Authentication:**
- Encapsulated in `app/security.py`.
- Handles password hashing (Argon2) and JWT generation/verification.

**Rate Limiting:**
- Implemented via `slowapi` in `app/limiter.py`.
- Applied per-route to prevent abuse.

**Audit Logging:**
- Standardized system for tracking user actions (CREATE, UPDATE, DELETE).
- Implemented via `@audit_log` decorator in the CRUD layer.
- Logs are stored in the `Audit` model and accessible via `/api/v1/audit/`.

## Entry Points

**Uvicorn Server:**
- **Location:** `app/main:app`
- **Responsibilities:** Initialize FastAPI app, register routers, add middleware (CORS, Sentry), set up lifespan events.

**Alembic:**
- **Location:** `alembic/env.py`
- **Responsibilities:** Handle database schema migrations.

---

*Architecture analysis: 2026-05-08*
*Update when major patterns change*
