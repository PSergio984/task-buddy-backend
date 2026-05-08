# Phase 1: Architecture Refinement - Research

## Objective
Answer: "What do I need to know to PLAN this phase well?"

## Current State Analysis
- **Database Library**: Currently using `databases` (async wrapper) with SQLAlchemy Core imperative table definitions in `app/database.py`.
- **Transaction Management**: Routers currently handle database logic and commits directly (e.g., `await database.execute(query)`).
- **Models**: `app/models/` currently contains Pydantic models (DTOs), which is confusing if we move ORM models there.
- **Enums**: Hardcoded strings like "Task not found" and status names are prevalent in routers.

## Technical Approach: SQLAlchemy 2.0 ORM

### 1. ORM Migration
- **Declarative Base**: Move from `Table` objects to classes inheriting from `DeclarativeBase`.
- **Type Hints**: Use `Mapped` and `mapped_column` for type-safe models.
- **Naming**: Move existing Pydantic models to `app/schemas/` and place ORM models in `app/models/`.

### 2. Async Session & Dependency Injection
- **Engine**: Use `create_async_engine`.
- **Session**: Use `async_sessionmaker(expire_on_commit=False)`.
- **Dependency**: Implement `get_db` in `app/dependencies.py`.
  ```python
  async def get_db():
      async with async_session_factory() as session:
          yield session
  ```

### 3. Decoupled CRUD Pattern
- **Logic**: CRUD functions in `app/crud/` take `AsyncSession` and `Schema` objects.
- **Transactions**: CRUD functions must **not** call `db.commit()`. The router calls `db.commit()` to allow for multiple CRUD operations within one transaction.

### 4. Enum Standardization
- Create `app/schemas/enums.py` for:
  - Task Status (e.g., `todo`, `in_progress`, `done`)
  - Audit Actions (e.g., `create`, `update`, `delete`, `attach`, `detach`)
  - Target Types (e.g., `task`, `subtask`, `tag`)

## Validation Architecture
- **Unit Tests**: Test CRUD functions with a mock or separate test `AsyncSession`.
- **Integration Tests**: Verify routers correctly handle commits and error rollbacks.
- **Manual Verification**: Use Swagger UI to verify all end-to-end flows.

---
*Research gathered: 2026-05-08*
