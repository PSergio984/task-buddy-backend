# Graph Report - task-buddy-backend  (2026-05-09)

## Corpus Check
- 74 files · ~20,931 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 753 nodes · 986 edges · 73 communities (48 shown, 25 thin omitted)
- Extraction: 87% EXTRACTED · 13% INFERRED · 0% AMBIGUOUS · INFERRED: 129 edges (avg confidence: 0.7)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `39f61e47`
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
- [[_COMMUNITY_User Profile API|User Profile API]]
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
- [[_COMMUNITY_Tests Suite|Tests Suite]]
- [[_COMMUNITY_Misc Utils|Misc Utils]]
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
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]

## God Nodes (most connected - your core abstractions)
1. `SQLAlchemy ORM` - 28 edges
2. `log_action()` - 25 edges
3. `Task Buddy Backend` - 15 edges
4. `TaskPriority` - 14 edges
5. `FastAPI Framework` - 14 edges
6. `send_confirmation_email()` - 13 edges
7. `get_task()` - 13 edges
8. `Task` - 13 edges
9. `update_password()` - 12 edges
10. `Tag` - 12 edges

## Surprising Connections (you probably didn't know these)
- `test_url_transformation_extended()` --calls--> `get_async_database_url()`  [INFERRED]
  test_db_url_extended.py → app/database.py
- `test_reset_password_success()` --calls--> `create_reset_token()`  [INFERRED]
  tests/routers/test_password_reset.py → app/security.py
- `test_reset_password_expired_token()` --calls--> `create_reset_token()`  [INFERRED]
  tests/routers/test_password_reset.py → app/security.py
- `test_reset_password_too_short()` --calls--> `create_reset_token()`  [INFERRED]
  tests/routers/test_password_reset.py → app/security.py
- `seed_data()` --calls--> `get_password_hash()`  [INFERRED]
  scripts/seed.py → app/security.py

## Communities (73 total, 25 thin omitted)

### Community 0 - "Database Migrations"
Cohesion: 0.05
Nodes (62): AsyncAttrs, Base, BaseModel, create_tag(), create_subtask(), create_task(), update_task(), DeclarativeBase (+54 more)

### Community 1 - "User Authentication"
Cohesion: 0.08
Nodes (37): create_audit_log(), log_action(), Log an action performed by a user on a specific target resource., Log an action performed by a user on a specific target resource., Log an action performed by a user on a specific target resource., create_group(), delete_group(), get_group() (+29 more)

### Community 2 - "SQLAlchemy Models"
Cohesion: 0.04
Nodes (46): 📚 API Documentation, 🔍 Available Endpoints, Build Docker image, 📝 Code Quality, code:block1 (task-buddy-backend/), code:bash (pytest --cov=app --cov-report=html), code:bash (black app tests), code:bash (ruff check app tests) (+38 more)

### Community 3 - "Task Creation Logic"
Cohesion: 0.05
Nodes (34): get_query_token(), API-specific dependencies.  These dependencies are specific to the API routers, Optional query token validation for API routes.      This is a simple query-ba, Optional query token validation for API routes.          This is a simple quer, get_db(), get_query_token(), get_token_header(), Shared dependencies used across multiple routes and modules.  This module contai (+26 more)

### Community 4 - "Audit Logging System"
Cohesion: 0.08
Nodes (7): get_user_by_email(), get_user_by_id(), test_authenticate_user_lazy_migration(), test_get_subject_for_token_type_valid_access_token(), test_get_subject_for_token_type_valid_confirm_token(), test_get_user(), test_get_user_not_found()

### Community 5 - "Security Tests"
Cohesion: 0.09
Nodes (9): create_subtask(), create_tag(), create_task(), created_subtask(), created_tag(), created_task(), test_get_tasks_filtered_by_group(), test_get_tasks_filtered_by_project() (+1 more)

### Community 6 - "App Configuration"
Cohesion: 0.12
Nodes (24): APIResponseError, _get_confirmation_content(), _is_valid_url(), Helper to mark a user as having a failed email confirmation in the database., Helper to mark a user as having a failed email confirmation in the database., Send a confirmation email with SMTP and Brevo API fallback.      The logic is br, Send a confirmation email with SMTP and Brevo API fallback.      The logic is br, Send a confirmation email with SMTP and Brevo API fallback.      The logic is br (+16 more)

### Community 7 - "User Profile API"
Cohesion: 0.11
Nodes (10): BaseConfig, DevConfig, GlobalConfig, ProdConfig, TestConfig, configure_logging(), EmailObfuscationFilter, obfuscated() (+2 more)

### Community 8 - "Background Tasks & Email"
Cohesion: 0.1
Nodes (20): code:bash (git add src/components/audit-trail.tsx), code:bash (git add src/components/auth/RegisterForm.tsx), code:bash (git add src/components/sidebar.tsx), code:bash (git add src/components/system-overview.tsx), code:bash (git add src/components/task-card.tsx), code:bash (git add src/components/topnav.tsx), code:bash (git add src/contexts/ProtectedRoute.tsx), code:bash (git add src/pages/LoginPage.tsx) (+12 more)

### Community 9 - "Pytest Fixtures"
Cohesion: 0.1
Nodes (20): code:python (from __future__ import annotations), code:python (from app.api.routers import group), code:bash (git add app/api/routers/ app/main.py), code:typescript (export interface Group {), code:bash (git add src/hooks/useApi.ts), code:bash (git add src/components/), code:python (# Add to imports if needed), code:python (# Inside Task class:) (+12 more)

### Community 10 - "FastAPI Dependencies"
Cohesion: 0.13
Nodes (6): register_user(), test_confirm_user(), test_confirm_user_expired_token(), test_register_user(), test_register_user_duplicate_email(), test_update_username_taken()

### Community 11 - "Seed Data Scripts"
Cohesion: 0.11
Nodes (18): 1. Overview, 2. Objectives, 3.1. Models (`app/models/task.py` and new `app/models/group.py`), 3.2. Schemas (`app/schemas/group.py` and update `app/schemas/task.py`), 3.3. API Endpoints, 3. Backend Design (`task-buddy-backend`), 4.1. API Integration (`src/hooks/useApi.ts`), 4.2. UI Components (+10 more)

### Community 12 - "Audit Log Tests"
Cohesion: 0.24
Nodes (16): access_token_expire_time(), authenticate_user(), confirm_token_expire_time(), create_access_token(), create_confirm_token(), create_credentials_exception(), get_current_user(), _get_secret_key() (+8 more)

### Community 13 - "Statistics Tests"
Cohesion: 0.12
Nodes (17): get_my_profile(), Retrieve the current user's profile information., Update the current user's username.     Checks for uniqueness and length., Retrieve the current user's profile information., Retrieve the current user's profile information., Retrieve the current user's profile information., Retrieve the current user's profile information., Update the current user's username.     Checks for uniqueness and length. (+9 more)

### Community 14 - "Migration Tests"
Cohesion: 0.13
Nodes (5): mock_httpx_client(), Mock httpx.AsyncClient to prevent real HTTP requests during tests., Mock httpx.AsyncClient to prevent real HTTP requests during tests., Mock httpx.AsyncClient to prevent real HTTP requests during tests., Mock httpx.AsyncClient to prevent real HTTP requests during tests.

### Community 15 - "Project Metadata"
Cohesion: 0.15
Nodes (12): 1) Architectural Style, 2) System Flow, 3) Layer/Module Responsibilities, 4) Reused Patterns, 5) Graphify Insights (Core Abstractions), 5) Known Architectural Risks, 6) Evidence, 6) Known Architectural Risks (+4 more)

### Community 16 - "App Main Package"
Cohesion: 0.18
Nodes (10): Run migrations in 'offline' mode.      This configures the context with just a U, Run migrations in 'offline' mode.      This configures the context with just a U, Run migrations in 'offline' mode.      This configures the context with just a U, Run migrations in 'offline' mode.      This configures the context with just a U, Run migrations in 'online' mode.      In this scenario we need to create an Engi, Run migrations in 'online' mode.      In this scenario we need to create an Engi, Run migrations in 'online' mode.      In this scenario we need to create an Engi, Run migrations in 'online' mode.      In this scenario we need to create an Engi (+2 more)

### Community 17 - "API Package"
Cohesion: 0.2
Nodes (10): get_password_hash(), confirm_email(), Update the current user's password securely.     Verifies the current password, Update the current user's password securely.     Verifies the current password, Update the current user's password securely.     Verifies the current password, Update the current user's password securely.     Verifies the current password, Update the current user's password securely.     Verifies the current password, Update the current user's password securely.     Verifies the current password (+2 more)

### Community 18 - "API Routers"
Cohesion: 0.31
Nodes (8): create_project(), test_delete_project(), test_get_project(), test_list_project_tasks(), test_list_projects(), test_project_idor_protection(), test_task_project_idor_protection(), test_update_project()

### Community 19 - "CRUD Layer"
Cohesion: 0.18
Nodes (10): 1) Naming Rules, 2) Formatting and Linting, 3) Import and Module Conventions, 4) Error and Logging Conventions, 5) Testing Conventions, 6) Evidence, code:bash (black app tests), Coding Conventions (+2 more)

### Community 20 - "Internal Modules"
Cohesion: 0.18
Nodes (10): 1) Test Stack and Commands, 2) Test Layout, 3) Test Scope Matrix, 4) Mocking and Isolation Strategy, 5) Coverage and Quality Signals, 6) Evidence, code:bash (pytest), Core Sections (Required) (+2 more)

### Community 21 - "Model Layer"
Cohesion: 0.31
Nodes (8): create_group(), test_delete_group(), test_get_group(), test_group_idor_protection(), test_list_group_tasks(), test_list_groups(), test_task_group_idor_protection(), test_update_group()

### Community 23 - "Tests Suite"
Cohesion: 0.2
Nodes (9): 1) Top Risks (Prioritized), 2) Technical Debt, 3) Security Concerns, 4) Performance and Scaling Concerns, 5) Fragile/High-Churn Areas, 6) `[ASK USER]` Questions, 7) Evidence, Codebase Concerns (+1 more)

### Community 24 - "Misc Utils"
Cohesion: 0.2
Nodes (9): 1) Integration Inventory, 2) Data Stores, 3) Secrets and Credentials Handling, 4) Reliability and Failure Behavior, 5) Observability for Integrations, 6) Evidence, Core Sections (Required), Extended Sections (Optional) (+1 more)

### Community 25 - "Security Validation"
Cohesion: 0.2
Nodes (9): 1) Runtime Summary, 2) Production Frameworks and Dependencies, 3) Development Toolchain, 4) Key Commands, 5) Environment and Config, 6) Evidence, code:bash (pip install -e ".[dev]"), Core Sections (Required) (+1 more)

### Community 26 - "Misc Init"
Cohesion: 0.28
Nodes (5): create_reset_token(), reset_token_expire_time(), test_reset_password_expired_token(), test_reset_password_success(), test_reset_password_too_short()

### Community 27 - "Docker Configuration"
Cohesion: 0.22
Nodes (3): attach_tag_to_task(), Attaches a tag to a task. Returns True if a new link was created., Attaches a tag to a task. Returns True if a new link was created.

### Community 28 - "Community 28"
Cohesion: 0.22
Nodes (8): 1) Top-Level Map, 2) Entry Points, 3) Module Boundaries, 4) Naming and Organization Rules, 5) Evidence, Codebase Structure, Core Sections (Required), Extended Sections (Optional)

### Community 29 - "Community 29"
Cohesion: 0.25
Nodes (8): logout(), Logout the current user.     Since the application uses stateless JWTs, the cli, Logout the current user.     Since the application uses stateless JWTs, the cli, Update the current user's password securely.     Verifies the current password, Logout the current user.     Since the application uses stateless JWTs, the cli, Logout the current user.     Since the application uses stateless JWTs, the cli, Logout the current user., Logout the current user. Clears the session cookie regardless of authentication

### Community 30 - "Community 30"
Cohesion: 0.25
Nodes (8): Placeholder for the reset password page.     In a real app, this would be handl, Placeholder for the reset password page.     In a real app, this would be handl, Update the current user's password securely.     Verifies the current password, Initiate password reset flow by sending an email with a reset token., Placeholder for the reset password page.     In a real app, this would be handl, Placeholder for the reset password page.     In a real app, this would be handl, Placeholder for the reset password page.     In a real app, this would be handl, reset_password_page()

### Community 31 - "Community 31"
Cohesion: 0.43
Nodes (6): blacklist_token(), Blacklist a JWT token in Redis with a TTL., Enum, AuditAction, TaskStatus, str

### Community 32 - "Community 32"
Cohesion: 0.29
Nodes (7): Reset user password using a valid reset token., Reset user password using a valid reset token., Reset user password using a valid reset token., Reset user password using a valid reset token., Reset user password using a valid reset token., Reset user password using a valid reset token., reset_password()

### Community 33 - "Community 33"
Cohesion: 0.29
Nodes (7): forgot_password(), Initiate password reset flow by sending an email with a reset token., Initiate password reset flow by sending an email with a reset token., Initiate password reset flow by sending an email with a reset token., Logout the current user., Initiate password reset flow by sending an email with a reset token., Initiate password reset flow by sending an email with a reset token.

### Community 34 - "Community 34"
Cohesion: 0.29
Nodes (3): AuditLogCreate, SQLAlchemy ORM, add priority to tasks  Revision ID: 2935b98be508 Revises: 38d622ba3db7 Create Da

### Community 35 - "Community 35"
Cohesion: 0.29
Nodes (5): get_async_database_url(), Ensures the database URL uses an async driver., Ensures the database URL uses an async driver and handles driver-specific query, Ensures the database URL uses an async driver., test_url_transformation_extended()

### Community 36 - "Community 36"
Cohesion: 0.33
Nodes (6): Resend a confirmation email for an existing, unconfirmed user., Resend a confirmation email for an existing, unconfirmed user.      The endpoi, Resend a confirmation email for an existing, unconfirmed user.      The endpoi, Resend a confirmation email for an existing, unconfirmed user., Resend a confirmation email for an existing, unconfirmed user., resend_confirmation()

### Community 37 - "Community 37"
Cohesion: 0.47
Nodes (4): get_system_overview(), SystemOverview, TagDistribution, TaskStats

### Community 38 - "Community 38"
Cohesion: 0.33
Nodes (4): code:block1 (DATABASE_URL=postgresql://user:password@localhost/task_buddy), Common Development Commands, Environment Variables, High‑Level Architecture

### Community 39 - "Community 39"
Cohesion: 0.47
Nodes (5): downgrade(), get_fk_name(), add_group_model_v2  Revision ID: 38d622ba3db7 Revises: e7d04c90bc13 Create Date:, Helper to find foreign key name dynamically., upgrade()

### Community 43 - "Community 43"
Cohesion: 0.83
Nodes (3): b2_api(), b2_get_bucket(), b2_upload_file()

### Community 44 - "Community 44"
Cohesion: 0.5
Nodes (3): Test that alembic migration can run against a clean database successfully., Test that alembic migration can run against a clean database successfully., test_alembic_migrations()

## Knowledge Gaps
- **248 isolated node(s):** `Project structure overview and getting started guide.  This file provides a qu`, `Run migrations in 'offline' mode.      This configures the context with just a U`, `Run migrations in 'online' mode.      In this scenario we need to create an Engi`, `Initial migration with Projects  Revision ID: 67fff7e05b96 Revises:  Create Date`, `Fail-fast in production when SECRET_KEY is not set.` (+243 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **25 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `SQLAlchemy ORM` connect `Community 34` to `Database Migrations`, `User Authentication`, `Task Creation Logic`, `Audit Logging System`, `Migration Tests`, `App Main Package`, `API Routers`, `Model Layer`, `Schema Layer`, `Docker Configuration`, `Community 35`, `Community 37`, `Community 39`, `Community 40`, `Community 41`, `Community 47`, `Community 48`, `Community 49`, `Community 50`, `Community 51`?**
  _High betweenness centrality (0.207) - this node is a cross-community bridge._
- **Why does `FastAPI Framework` connect `Task Creation Logic` to `User Authentication`, `User Profile API`, `FastAPI Dependencies`, `Audit Log Tests`, `API Package`, `Misc Init`?**
  _High betweenness centrality (0.147) - this node is a cross-community bridge._
- **Why does `TaskPriority` connect `Database Migrations` to `Community 31`?**
  _High betweenness centrality (0.051) - this node is a cross-community bridge._
- **Are the 21 inferred relationships involving `log_action()` (e.g. with `create_project()` and `update_project()`) actually correct?**
  _`log_action()` has 21 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `str` (e.g. with `blacklist_token()` and `is_token_blacklisted()`) actually correct?**
  _`str` has 12 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Project structure overview and getting started guide.  This file provides a qu`, `Run migrations in 'offline' mode.      This configures the context with just a U`, `Run migrations in 'online' mode.      In this scenario we need to create an Engi` to the rest of the system?**
  _248 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Database Migrations` be split into smaller, more focused modules?**
  _Cohesion score 0.05 - nodes in this community are weakly interconnected._