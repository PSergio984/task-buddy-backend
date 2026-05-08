# Graph Report - task-buddy-backend  (2026-05-08)

## Corpus Check
- 55 files · ~13,844 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 423 nodes · 489 edges · 41 communities (27 shown, 14 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 33 edges (avg confidence: 0.79)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `7577c200`
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
- [[_COMMUNITY_Project Metadata|Project Metadata]]
- [[_COMMUNITY_App Main Package|App Main Package]]
- [[_COMMUNITY_API Package|API Package]]
- [[_COMMUNITY_API Routers|API Routers]]
- [[_COMMUNITY_CRUD Layer|CRUD Layer]]
- [[_COMMUNITY_Internal Modules|Internal Modules]]
- [[_COMMUNITY_Model Layer|Model Layer]]
- [[_COMMUNITY_Security Validation|Security Validation]]
- [[_COMMUNITY_Misc Init|Misc Init]]
- [[_COMMUNITY_Docker Configuration|Docker Configuration]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]

## God Nodes (most connected - your core abstractions)
1. `Task Buddy Backend` - 15 edges
2. `FastAPI Framework` - 12 edges
3. `send_confirmation_email()` - 11 edges
4. `log_action()` - 11 edges
5. `get_task()` - 9 edges
6. `Core Sections (Required)` - 8 edges
7. `create_reset_token()` - 7 edges
8. `Core Sections (Required)` - 7 edges
9. `Core Sections (Required)` - 7 edges
10. `Core Sections (Required)` - 7 edges

## Surprising Connections (you probably didn't know these)
- `seed_data()` --calls--> `get_password_hash()`  [INFERRED]
  seed.py → app/security.py
- `test_reset_password_success()` --calls--> `create_reset_token()`  [INFERRED]
  tests/routers/test_password_reset.py → app/security.py
- `test_reset_password_expired_token()` --calls--> `create_reset_token()`  [INFERRED]
  tests/routers/test_password_reset.py → app/security.py
- `test_reset_password_too_short()` --calls--> `create_reset_token()`  [INFERRED]
  tests/routers/test_password_reset.py → app/security.py
- `test_send_confirmation_email()` --calls--> `send_confirmation_email()`  [INFERRED]
  tests/test_tasks.py → app/tasks.py

## Communities (41 total, 14 thin omitted)

### Community 0 - "Database Migrations"
Cohesion: 0.07
Nodes (42): access_token_expire_time(), authenticate_user(), confirm_token_expire_time(), create_access_token(), create_confirm_token(), create_credentials_exception(), create_reset_token(), get_current_user() (+34 more)

### Community 1 - "User Authentication"
Cohesion: 0.06
Nodes (33): 📚 API Documentation, 🔍 Available Endpoints, Build Docker image, 📝 Code Quality, code:block1 (task-buddy-backend/), code:bash (pytest --cov=app --cov-report=html), code:bash (black app tests), code:bash (ruff check app tests) (+25 more)

### Community 2 - "SQLAlchemy Models"
Cohesion: 0.07
Nodes (18): get_query_token(), API-specific dependencies.  These dependencies are specific to the API routers, Optional query token validation for API routes.          This is a simple quer, get_query_token(), get_token_header(), Shared dependencies used across multiple routes and modules.  This module cont, Validate X-Token header.          This is a simple token validation dependency, Validate query token parameter.          Optional query parameter for basic to (+10 more)

### Community 3 - "Task Creation Logic"
Cohesion: 0.11
Nodes (24): BaseModel, AuditLog, AuditLogCreate, SystemOverview, TagDistribution, TaskStats, TagCreate, TagResponse (+16 more)

### Community 4 - "Audit Logging System"
Cohesion: 0.09
Nodes (7): create_subtask(), create_tag(), create_task(), created_subtask(), created_tag(), created_task(), test_reuse_tag_across_tasks()

### Community 5 - "Security Tests"
Cohesion: 0.15
Nodes (20): APIResponseError, _get_confirmation_content(), _is_valid_url(), Helper to mark a user as having a failed email confirmation in the database., Helper to mark a user as having a failed email confirmation in the database., Send a confirmation email with SMTP and Brevo API fallback.      The logic is br, Send a confirmation email with SMTP and Brevo API fallback.      The logic is br, Send a password reset email with SMTP and Brevo API fallback. (+12 more)

### Community 6 - "App Configuration"
Cohesion: 0.2
Nodes (18): log_action(), Log an action performed by a user on a specific target resource., create_subtask(), create_tag(), create_task(), delete_subtask(), delete_tag(), delete_task() (+10 more)

### Community 8 - "Background Tasks & Email"
Cohesion: 0.1
Nodes (11): Run migrations in 'offline' mode.      This configures the context with just a U, Run migrations in 'online' mode.      In this scenario we need to create an Engi, run_migrations_offline(), run_migrations_online(), Claude Code Guidance, Docker Compose Configuration, PostgreSQL Database, SQLAlchemy ORM (+3 more)

### Community 9 - "Pytest Fixtures"
Cohesion: 0.13
Nodes (6): register_user(), test_confirm_user(), test_confirm_user_expired_token(), test_register_user(), test_register_user_duplicate_email(), test_update_username_taken()

### Community 10 - "FastAPI Dependencies"
Cohesion: 0.15
Nodes (13): code:bash (git clone https://github.com/yourusername/task-buddy-backend), code:bash (# On Windows), code:bash (pip install -e ".[dev]"), code:bash (fastapi dev), code:bash (uvicorn app.main:app --reload), code:bash (fastapi run), code:bash (uvicorn app.main:app --host 0.0.0.0 --port 8000), Development Mode (+5 more)

### Community 11 - "Seed Data Scripts"
Cohesion: 0.18
Nodes (10): 1) Architectural Style, 2) System Flow, 3) Layer/Module Responsibilities, 4) Reused Patterns, 5) Known Architectural Risks, 6) Evidence, Architecture, code:text ([HTTP Request] -> [app/main.py] -> [app/api/routers/*] -> [a) (+2 more)

### Community 12 - "Audit Log Tests"
Cohesion: 0.18
Nodes (10): 1) Naming Rules, 2) Formatting and Linting, 3) Import and Module Conventions, 4) Error and Logging Conventions, 5) Testing Conventions, 6) Evidence, code:bash (black app tests), Coding Conventions (+2 more)

### Community 13 - "Statistics Tests"
Cohesion: 0.18
Nodes (10): 1) Test Stack and Commands, 2) Test Layout, 3) Test Scope Matrix, 4) Mocking and Isolation Strategy, 5) Coverage and Quality Signals, 6) Evidence, code:bash (pytest), Core Sections (Required) (+2 more)

### Community 15 - "Project Metadata"
Cohesion: 0.2
Nodes (9): 1) Top Risks (Prioritized), 2) Technical Debt, 3) Security Concerns, 4) Performance and Scaling Concerns, 5) Fragile/High-Churn Areas, 6) `[ASK USER]` Questions, 7) Evidence, Codebase Concerns (+1 more)

### Community 16 - "App Main Package"
Cohesion: 0.2
Nodes (9): 1) Integration Inventory, 2) Data Stores, 3) Secrets and Credentials Handling, 4) Reliability and Failure Behavior, 5) Observability for Integrations, 6) Evidence, Core Sections (Required), Extended Sections (Optional) (+1 more)

### Community 17 - "API Package"
Cohesion: 0.2
Nodes (9): 1) Runtime Summary, 2) Production Frameworks and Dependencies, 3) Development Toolchain, 4) Key Commands, 5) Environment and Config, 6) Evidence, code:bash (pip install -e ".[dev]"), Core Sections (Required) (+1 more)

### Community 18 - "API Routers"
Cohesion: 0.33
Nodes (6): BaseConfig, DevConfig, GlobalConfig, ProdConfig, TestConfig, BaseSettings

### Community 19 - "CRUD Layer"
Cohesion: 0.22
Nodes (8): 1) Top-Level Map, 2) Entry Points, 3) Module Boundaries, 4) Naming and Organization Rules, 5) Evidence, Codebase Structure, Core Sections (Required), Extended Sections (Optional)

### Community 20 - "Internal Modules"
Cohesion: 0.33
Nodes (4): code:block1 (DATABASE_URL=postgresql://user:password@localhost/task_buddy), Common Development Commands, Environment Variables, High‑Level Architecture

### Community 21 - "Model Layer"
Cohesion: 0.4
Nodes (3): seed_data(), Test that the seeding script successfully populates a confirmed user,     with r, test_seed_data()

## Knowledge Gaps
- **130 isolated node(s):** `Project structure overview and getting started guide.  This file provides a qu`, `Run migrations in 'offline' mode.      This configures the context with just a U`, `Run migrations in 'online' mode.      In this scenario we need to create an Engi`, `Initial migration  Revision ID: a6e267909ed1 Revises:  Create Date: 2026-05-`, `Add audit logs table  Revision ID: e7d04c90bc13 Revises: a6e267909ed1 Create Dat` (+125 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **14 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `FastAPI Framework` connect `SQLAlchemy Models` to `Database Migrations`, `Background Tasks & Email`, `App Configuration`, `Pytest Fixtures`?**
  _High betweenness centrality (0.147) - this node is a cross-community bridge._
- **Why does `get_system_overview()` connect `Task Creation Logic` to `Background Tasks & Email`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `send_confirmation_email()` (e.g. with `test_send_confirmation_email()` and `test_send_confirmation_email_api_error()`) actually correct?**
  _`send_confirmation_email()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `log_action()` (e.g. with `create_task()` and `update_task()`) actually correct?**
  _`log_action()` has 9 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Project structure overview and getting started guide.  This file provides a qu`, `Run migrations in 'offline' mode.      This configures the context with just a U`, `Run migrations in 'online' mode.      In this scenario we need to create an Engi` to the rest of the system?**
  _130 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Database Migrations` be split into smaller, more focused modules?**
  _Cohesion score 0.07 - nodes in this community are weakly interconnected._
- **Should `User Authentication` be split into smaller, more focused modules?**
  _Cohesion score 0.06 - nodes in this community are weakly interconnected._