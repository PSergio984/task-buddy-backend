# Graph Report - task-buddy-backend  (2026-05-07)

## Corpus Check
- 45 files · ~10,603 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 315 nodes · 377 edges · 31 communities (18 shown, 13 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 27 edges (avg confidence: 0.79)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `eeac524f`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Database Migrations|Database Migrations]]
- [[_COMMUNITY_User Authentication|User Authentication]]
- [[_COMMUNITY_SQLAlchemy Models|SQLAlchemy Models]]
- [[_COMMUNITY_Task Creation Logic|Task Creation Logic]]
- [[_COMMUNITY_Audit Logging System|Audit Logging System]]
- [[_COMMUNITY_Security Tests|Security Tests]]
- [[_COMMUNITY_App Configuration|App Configuration]]
- [[_COMMUNITY_Background Tasks & Email|Background Tasks & Email]]
- [[_COMMUNITY_Pytest Fixtures|Pytest Fixtures]]
- [[_COMMUNITY_FastAPI Dependencies|FastAPI Dependencies]]
- [[_COMMUNITY_Seed Data Scripts|Seed Data Scripts]]
- [[_COMMUNITY_Audit Log Tests|Audit Log Tests]]
- [[_COMMUNITY_Statistics Tests|Statistics Tests]]
- [[_COMMUNITY_Migration Tests|Migration Tests]]
- [[_COMMUNITY_API Package|API Package]]
- [[_COMMUNITY_API Routers|API Routers]]
- [[_COMMUNITY_CRUD Layer|CRUD Layer]]
- [[_COMMUNITY_Internal Modules|Internal Modules]]
- [[_COMMUNITY_Model Layer|Model Layer]]
- [[_COMMUNITY_Schema Layer|Schema Layer]]
- [[_COMMUNITY_Tests Suite|Tests Suite]]
- [[_COMMUNITY_Misc Utils|Misc Utils]]
- [[_COMMUNITY_Security Validation|Security Validation]]
- [[_COMMUNITY_Misc Init|Misc Init]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 30|Community 30]]

## God Nodes (most connected - your core abstractions)
1. `Task Buddy Backend` - 15 edges
2. `log_action()` - 11 edges
3. `FastAPI Framework` - 11 edges
4. `send_confirmation_email()` - 10 edges
5. `get_task()` - 9 edges
6. `register_user()` - 6 edges
7. `SQLAlchemy ORM` - 6 edges
8. `GlobalConfig` - 5 edges
9. `create_confirm_token()` - 5 edges
10. `get_subject_for_token_type()` - 5 edges

## Surprising Connections (you probably didn't know these)
- `test_send_confirmation_email()` --calls--> `send_confirmation_email()`  [INFERRED]
  tests/test_tasks.py → app/tasks.py
- `test_send_confirmation_email_api_error()` --calls--> `send_confirmation_email()`  [INFERRED]
  tests/test_tasks.py → app/tasks.py
- `test_send_confirmation_email_falls_back_to_api()` --calls--> `send_confirmation_email()`  [INFERRED]
  tests/test_tasks.py → app/tasks.py
- `seed_data()` --calls--> `get_password_hash()`  [INFERRED]
  seed.py → app/security.py
- `test_seed_data()` --calls--> `seed_data()`  [INFERRED]
  tests/test_seed.py → seed.py

## Communities (31 total, 13 thin omitted)

### Community 0 - "Database Migrations"
Cohesion: 0.1
Nodes (28): access_token_expire_time(), authenticate_user(), confirm_token_expire_time(), create_access_token(), create_confirm_token(), create_credentials_exception(), get_current_user(), get_password_hash() (+20 more)

### Community 1 - "User Authentication"
Cohesion: 0.07
Nodes (18): get_query_token(), API-specific dependencies.  These dependencies are specific to the API routers, Optional query token validation for API routes.          This is a simple quer, get_query_token(), get_token_header(), Shared dependencies used across multiple routes and modules.  This module cont, Validate X-Token header.          This is a simple token validation dependency, Validate query token parameter.          Optional query parameter for basic to (+10 more)

### Community 2 - "SQLAlchemy Models"
Cohesion: 0.12
Nodes (22): BaseModel, AuditLog, AuditLogCreate, SystemOverview, TagDistribution, TaskStats, TagCreate, TagResponse (+14 more)

### Community 3 - "Task Creation Logic"
Cohesion: 0.09
Nodes (7): create_subtask(), create_tag(), create_task(), created_subtask(), created_tag(), created_task(), test_reuse_tag_across_tasks()

### Community 4 - "Audit Logging System"
Cohesion: 0.08
Nodes (24): 📚 API Documentation, 🔍 Available Endpoints, Build Docker image, code:block1 (task-buddy-backend/), code:bash (pytest --cov=app --cov-report=html), code:env (# Database), code:bash (docker build -t task-buddy-backend:latest .), code:bash (docker run -p 8000:8000 task-buddy-backend:latest) (+16 more)

### Community 5 - "Security Tests"
Cohesion: 0.2
Nodes (18): log_action(), Log an action performed by a user on a specific target resource., create_subtask(), create_tag(), create_task(), delete_subtask(), delete_tag(), delete_task() (+10 more)

### Community 6 - "App Configuration"
Cohesion: 0.1
Nodes (11): Run migrations in 'offline' mode.      This configures the context with just a U, Run migrations in 'online' mode.      In this scenario we need to create an Engi, run_migrations_offline(), run_migrations_online(), Claude Code Guidance, Docker Compose Configuration, PostgreSQL Database, SQLAlchemy ORM (+3 more)

### Community 8 - "Background Tasks & Email"
Cohesion: 0.13
Nodes (6): register_user(), test_confirm_user(), test_confirm_user_expired_token(), test_register_user(), test_register_user_duplicate_email(), test_update_username_taken()

### Community 9 - "Pytest Fixtures"
Cohesion: 0.2
Nodes (15): APIResponseError, _get_confirmation_content(), _is_valid_url(), Helper to mark a user as having a failed email confirmation in the database., Send a confirmation email with SMTP and Brevo API fallback.      The logic is br, Helper to validate that a URL starts with https://., Helper to generate subject and body from confirmation URL or direct inputs., _record_confirmation_failure() (+7 more)

### Community 10 - "FastAPI Dependencies"
Cohesion: 0.15
Nodes (13): code:bash (git clone https://github.com/yourusername/task-buddy-backend), code:bash (# On Windows), code:bash (pip install -e ".[dev]"), code:bash (fastapi dev), code:bash (uvicorn app.main:app --reload), code:bash (fastapi run), code:bash (uvicorn app.main:app --host 0.0.0.0 --port 8000), Development Mode (+5 more)

### Community 12 - "Audit Log Tests"
Cohesion: 0.33
Nodes (6): BaseConfig, DevConfig, GlobalConfig, ProdConfig, TestConfig, BaseSettings

### Community 13 - "Statistics Tests"
Cohesion: 0.22
Nodes (9): 📝 Code Quality, code:bash (black app tests), code:bash (ruff check app tests), code:bash (mypy app), code:bash (isort app tests), Format code with Black, Lint with ruff, Sort imports with isort (+1 more)

### Community 14 - "Migration Tests"
Cohesion: 0.33
Nodes (4): code:block1 (DATABASE_URL=postgresql://user:password@localhost/task_buddy), Common Development Commands, Environment Variables, High‑Level Architecture

## Knowledge Gaps
- **70 isolated node(s):** `Project structure overview and getting started guide.  This file provides a qu`, `Run migrations in 'offline' mode.      This configures the context with just a U`, `Run migrations in 'online' mode.      In this scenario we need to create an Engi`, `Initial migration  Revision ID: a6e267909ed1 Revises:  Create Date: 2026-05-`, `Add audit logs table  Revision ID: e7d04c90bc13 Revises: a6e267909ed1 Create Dat` (+65 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **13 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `FastAPI Framework` connect `User Authentication` to `Database Migrations`, `Background Tasks & Email`, `Security Tests`, `App Configuration`?**
  _High betweenness centrality (0.201) - this node is a cross-community bridge._
- **Why does `get_system_overview()` connect `SQLAlchemy Models` to `App Configuration`?**
  _High betweenness centrality (0.069) - this node is a cross-community bridge._
- **Are the 9 inferred relationships involving `log_action()` (e.g. with `create_task()` and `update_task()`) actually correct?**
  _`log_action()` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `send_confirmation_email()` (e.g. with `test_send_confirmation_email()` and `test_send_confirmation_email_api_error()`) actually correct?**
  _`send_confirmation_email()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Project structure overview and getting started guide.  This file provides a qu`, `Run migrations in 'offline' mode.      This configures the context with just a U`, `Run migrations in 'online' mode.      In this scenario we need to create an Engi` to the rest of the system?**
  _70 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Database Migrations` be split into smaller, more focused modules?**
  _Cohesion score 0.1 - nodes in this community are weakly interconnected._
- **Should `User Authentication` be split into smaller, more focused modules?**
  _Cohesion score 0.07 - nodes in this community are weakly interconnected._