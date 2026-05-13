<!-- generated-by: gsd-doc-writer -->
# Architecture

**Analysis Date:** 2026-05-13

## Pattern Overview

**Overall:** Layered Monolith (FastAPI)

**Key Characteristics:**
- **Separation of Concerns:** Distinct layers for routing (API), business logic (CRUD), models (SQLAlchemy), and schemas (Pydantic).
- **Asynchronous IO:** Native `async`/`await` usage throughout the stack, from the database (asyncpg/aiosqlite) to external service calls.
- **Dependency Injection:** Extensive use of FastAPI's `Depends` with `Annotated` types for managing database sessions, authentication, and configuration.
- **Statelessness:** JWT-based authentication ensures the API remains stateless and scalable. The backend now sets JWTs in HttpOnly cookies for enhanced security.

## Layers

**API Layer (`app/api/`):**
- **Purpose:** Handles HTTP request/response lifecycle, input validation, and route orchestration.
- **Contains:** Router modules (`app/api/routers/`), dependency providers (`app/dependencies.py`).
- **Used by:** Frontend application, mobile apps, or external integrations.

**CRUD Layer (`app/crud/`):**
- **Purpose:** Encapsulates data persistence logic and business rules.
- **Contains:** Logic for `User`, `Task`, `Project`, `Notification`, `Tag`, and `AuditLog`.
- **Key Feature:** Integrated audit logging via decorators.

**Models Layer (`app/models/`):**
- **Purpose:** Defines the relational database schema.
- **Contains:** SQLAlchemy ORM models including `User`, `Task`, `SubTask`, `Project`, `Tag`, `Notification`, and `AuditLog`.
- **Infrastructure:** Managed via Alembic migrations.

**Schemas Layer (`app/schemas/`):**
- **Purpose:** Data validation, serialization, and API contract definition.
- **Contains:** Pydantic V2 models for request bodies and response structures.

## Data Flow

**HTTP Request Lifecycle:**

1. **Entry Point:** `app/main.py` receives request via Uvicorn.
2. **Routing:** FastAPI dispatches to specific routers (e.g., `app/api/routers/task.py`).
3. **Dependencies:** `app/dependencies.py` resolves the database session and authenticates the user.
4. **Validation:** Pydantic schemas in `app/schemas/` validate and parse incoming JSON.
5. **Business Logic:** Routers call CRUD functions in `app/crud/`.
6. **Persistence:** CRUD layer interacts with the database using SQLAlchemy models.
7. **Response:** Data is serialized through response schemas and returned to the client.

**Background Processing:**
- **Celery:** Primary engine for asynchronous work (e.g., sending emails, push notifications).
- **Broker/Backend:** Redis.
- **Task Definitions:** Located in `app/tasks.py`.

## Key Abstractions

**Database Session:**
- Managed via `get_db` dependency in `app/dependencies.py`.
- Supports asynchronous transactions with `AsyncSession`.

**Security & Auth:**
- Centralized in `app/security.py`.
- Uses Argon2 for hashing and JWT for session management via HttpOnly cookies.

**Audit Logging:**
- Implemented via `@audit_log` decorator in `app/libs/audit.py`.
- Automatically captures CREATE/UPDATE/DELETE actions with field-level diffs for updates.
- Stored in `AuditLog` model and exposed via `/api/v1/audit/`.

**Integrations Library (`app/libs/`):**
- Contains specialized helpers for `audit`, `email_templates`, and Backblaze `B2` storage.

## Entry Points

**Uvicorn Server:**
- `app.main:app` — Starts the FastAPI application with configured middleware (CORS, Sentry, Rate Limiting).

**Celery Worker:**
- `celery -A app.celery_app worker` — Processes background tasks from the Redis queue.

**Alembic:**
- Database migration CLI used for schema evolution.

---

*Architecture analysis: 2026-05-13*
*Update when major patterns or components are added*
