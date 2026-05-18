<!-- generated-by: gsd-doc-writer -->
# Structure

## Root Directory
- `/app`: Core application source.
- `/alembic`: Database migrations.
- `/tests`: Test suite.
- `/docs`: System documentation (including MASTER_SPEC.md).
- `/quality`: Quality artifacts and UAT cases.

## Application Structure (`/app`)
- `/api`: REST controllers and routers.
- `/crud`: Data access layer.
- `/libs`: Shared utilities (Audit logging, etc.).
- `/middleware`: API middleware (Auth, Idempotency, Limiter).
- `/models`: SQLAlchemy models.
- `/schemas`: Pydantic validation schemas.
- `celery_app.py`: Background task configuration.
- `tasks.py`: Celery task definitions.
