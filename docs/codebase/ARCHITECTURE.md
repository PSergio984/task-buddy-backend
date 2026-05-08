# Architecture

## Core Sections (Required)

### 1) Architectural Style

- Primary style: Layered Architecture
- Why this classification: The project follows a clear separation of concerns with distinct layers for API routing, data validation (schemas), database models, and CRUD operations.
- Primary constraints:
  - Strict separation between ORM models and Pydantic schemas.
  - Async-first database operations using SQLAlchemy's async engine.
  - Environment-driven configuration using Pydantic Settings.

### 2) System Flow

```text
[HTTP Request] -> [app/main.py] -> [app/api/routers/*] -> [app/crud/*] -> [app/models/*] -> [Database]
```

1. **Entry**: `app/main.py` initializes the FastAPI application and includes routers.
2. **Routing**: `app/api/routers/` handles incoming HTTP requests and validates data using Pydantic schemas in `app/schemas/`.
3. **Business Logic/CRUD**: Routers call functions in `app/crud/` (or directly use models if CRUD is thin) to perform operations.
4. **Data Layer**: SQLAlchemy models in `app/models/` map to database tables.
5. **Response**: Data is returned through the layers, validated/filtered by Pydantic schemas, and sent as a JSON response.

### 3) Layer/Module Responsibilities

| Layer or module | Owns | Must not own | Evidence |
|-----------------|------|--------------|----------|
| `app/main.py` | App lifecycle, middleware, router registration | Business logic, DB models | `app/main.py` |
| `app/api/routers/` | Endpoint definitions, request validation, dependency injection | Direct DB table manipulation | `app/api/routers/` |
| `app/schemas/` | Request/Response data contracts (Pydantic) | Database connection logic | `app/schemas/` |
| `app/models/` | Database table definitions (SQLAlchemy) | API logic, data validation | `app/models/` |
| `app/crud/` | Data persistence and retrieval logic | HTTP status codes, request objects | `app/crud/` |

### 4) Reused Patterns

| Pattern | Where found | Why it exists |
|---------|-------------|---------------|
| Dependency Injection | `app/api/dependencies.py` | To provide database sessions and current user authentication to routes. |
| Repository/CRUD | `app/crud/` | To centralize data access logic and keep routers clean. |
| Lifespan Context Manager | `app/main.py` | To manage database engine connection/disconnection during app startup/shutdown. |

### 5) Graphify Insights (Core Abstractions)

According to `graphify-out/GRAPH_REPORT.md`, the following are the most connected "God Nodes" and key communities in the backend:

**God Nodes (Core Abstractions):**
1. `Task Buddy Backend` (System Root)
2. `FastAPI Framework` (Core Infrastructure)
3. `send_confirmation_email()` (Critical Communication Path)
4. `log_action()` (Cross-cutting Audit Logging)
5. `get_task()` (Primary Domain Query)

**Key Communities:**
- **Database Migrations**: High volume of nodes (42), weakly interconnected (Cohesion: 0.07).
- **User Authentication**: Core security logic, includes JWT and OAuth2 integration.
- **SQLAlchemy Models**: Pydantic-to-ORM mapping and data definitions.
- **Audit Logging System**: Centralized tracking of user actions.

### 6) Known Architectural Risks

- **Database Connection Pooling**: Potential bottlenecks if async connections are not managed correctly under high load.
- **Circular Dependencies**: Risks when importing between models, schemas, and routers if not carefully structured.

### 6) Evidence

- `app/main.py`
- `app/api/routers/task.py`
- `app/models/task.py`
- `app/schemas/` (Pydantic schemas directory)
- `CLAUDE.md` (Architecture section)

## Extended Sections (Optional)

- Startup order: `main.py` -> `lifespan` -> `database.py` (engine initialization).
