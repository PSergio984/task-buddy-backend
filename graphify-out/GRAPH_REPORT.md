# Graph Report - .  (2026-05-07)

## Corpus Check
- Corpus is ~10,603 words - fits in a single context window. You may not need a graph.

## Summary
- 262 nodes · 326 edges · 28 communities (15 shown, 13 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 27 edges (avg confidence: 0.79)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Database Migrations|Database Migrations]]
- [[_COMMUNITY_User Authentication|User Authentication]]
- [[_COMMUNITY_SQLAlchemy Models|SQLAlchemy Models]]
- [[_COMMUNITY_Task Creation Logic|Task Creation Logic]]
- [[_COMMUNITY_Audit Logging System|Audit Logging System]]
- [[_COMMUNITY_App Configuration|App Configuration]]
- [[_COMMUNITY_User Profile API|User Profile API]]
- [[_COMMUNITY_Background Tasks & Email|Background Tasks & Email]]
- [[_COMMUNITY_Pytest Fixtures|Pytest Fixtures]]
- [[_COMMUNITY_FastAPI Dependencies|FastAPI Dependencies]]
- [[_COMMUNITY_Seed Data Scripts|Seed Data Scripts]]
- [[_COMMUNITY_Migration Tests|Migration Tests]]
- [[_COMMUNITY_Project Metadata|Project Metadata]]
- [[_COMMUNITY_App Main Package|App Main Package]]
- [[_COMMUNITY_API Package|API Package]]
- [[_COMMUNITY_API Routers|API Routers]]
- [[_COMMUNITY_CRUD Layer|CRUD Layer]]
- [[_COMMUNITY_Internal Modules|Internal Modules]]
- [[_COMMUNITY_Model Layer|Model Layer]]
- [[_COMMUNITY_Schema Layer|Schema Layer]]
- [[_COMMUNITY_Tests Suite|Tests Suite]]
- [[_COMMUNITY_Security Validation|Security Validation]]
- [[_COMMUNITY_Docker Configuration|Docker Configuration]]

## God Nodes (most connected - your core abstractions)
1. `log_action()` - 11 edges
2. `FastAPI Framework` - 11 edges
3. `send_confirmation_email()` - 10 edges
4. `get_task()` - 9 edges
5. `register_user()` - 6 edges
6. `SQLAlchemy ORM` - 6 edges
7. `GlobalConfig` - 5 edges
8. `create_confirm_token()` - 5 edges
9. `get_subject_for_token_type()` - 5 edges
10. `authenticate_user()` - 5 edges

## Surprising Connections (you probably didn't know these)
- `seed_data()` --calls--> `get_password_hash()`  [INFERRED]
  seed.py → app/security.py
- `test_send_confirmation_email()` --calls--> `send_confirmation_email()`  [INFERRED]
  tests/test_tasks.py → app/tasks.py
- `test_send_confirmation_email_api_error()` --calls--> `send_confirmation_email()`  [INFERRED]
  tests/test_tasks.py → app/tasks.py
- `test_send_confirmation_email_falls_back_to_api()` --calls--> `send_confirmation_email()`  [INFERRED]
  tests/test_tasks.py → app/tasks.py
- `test_seed_data()` --calls--> `seed_data()`  [INFERRED]
  tests/test_seed.py → seed.py

## Communities (28 total, 13 thin omitted)

### Community 0 - "Database Migrations"
Cohesion: 0.06
Nodes (20): Run migrations in 'offline' mode.      This configures the context with just a U, Run migrations in 'online' mode.      In this scenario we need to create an Engi, run_migrations_offline(), run_migrations_online(), get_query_token(), API-specific dependencies.  These dependencies are specific to the API routers, Optional query token validation for API routes.          This is a simple quer, Claude Code Guidance (+12 more)

### Community 1 - "User Authentication"
Cohesion: 0.13
Nodes (25): access_token_expire_time(), authenticate_user(), confirm_token_expire_time(), create_access_token(), create_confirm_token(), create_credentials_exception(), get_current_user(), get_password_hash() (+17 more)

### Community 2 - "SQLAlchemy Models"
Cohesion: 0.12
Nodes (22): BaseModel, AuditLog, AuditLogCreate, SystemOverview, TagDistribution, TaskStats, TagCreate, TagResponse (+14 more)

### Community 3 - "Task Creation Logic"
Cohesion: 0.09
Nodes (7): create_subtask(), create_tag(), create_task(), created_subtask(), created_tag(), created_task(), test_reuse_tag_across_tasks()

### Community 4 - "Audit Logging System"
Cohesion: 0.2
Nodes (18): log_action(), Log an action performed by a user on a specific target resource., create_subtask(), create_tag(), create_task(), delete_subtask(), delete_tag(), delete_task() (+10 more)

### Community 6 - "App Configuration"
Cohesion: 0.13
Nodes (10): BaseConfig, DevConfig, GlobalConfig, ProdConfig, TestConfig, configure_logging(), EmailObfuscationFilter, obfuscated() (+2 more)

### Community 7 - "User Profile API"
Cohesion: 0.13
Nodes (6): register_user(), test_confirm_user(), test_confirm_user_expired_token(), test_register_user(), test_register_user_duplicate_email(), test_update_username_taken()

### Community 8 - "Background Tasks & Email"
Cohesion: 0.2
Nodes (15): APIResponseError, _get_confirmation_content(), _is_valid_url(), Helper to mark a user as having a failed email confirmation in the database., Send a confirmation email with SMTP and Brevo API fallback.      The logic is br, Helper to validate that a URL starts with https://., Helper to generate subject and body from confirmation URL or direct inputs., _record_confirmation_failure() (+7 more)

### Community 10 - "FastAPI Dependencies"
Cohesion: 0.33
Nodes (5): get_query_token(), get_token_header(), Shared dependencies used across multiple routes and modules.  This module cont, Validate X-Token header.          This is a simple token validation dependency, Validate query token parameter.          Optional query parameter for basic to

### Community 11 - "Seed Data Scripts"
Cohesion: 0.4
Nodes (3): seed_data(), Test that the seeding script successfully populates a confirmed user,     with r, test_seed_data()

## Knowledge Gaps
- **39 isolated node(s):** `Project structure overview and getting started guide.  This file provides a qu`, `Run migrations in 'offline' mode.      This configures the context with just a U`, `Run migrations in 'online' mode.      In this scenario we need to create an Engi`, `Initial migration  Revision ID: a6e267909ed1 Revises:  Create Date: 2026-05-`, `Add audit logs table  Revision ID: e7d04c90bc13 Revises: a6e267909ed1 Create Dat` (+34 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **13 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `FastAPI Framework` connect `Database Migrations` to `User Authentication`, `Audit Logging System`, `App Configuration`, `User Profile API`, `FastAPI Dependencies`?**
  _High betweenness centrality (0.290) - this node is a cross-community bridge._
- **Why does `get_system_overview()` connect `SQLAlchemy Models` to `Database Migrations`?**
  _High betweenness centrality (0.100) - this node is a cross-community bridge._
- **Are the 9 inferred relationships involving `log_action()` (e.g. with `create_task()` and `update_task()`) actually correct?**
  _`log_action()` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `send_confirmation_email()` (e.g. with `test_send_confirmation_email()` and `test_send_confirmation_email_api_error()`) actually correct?**
  _`send_confirmation_email()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Project structure overview and getting started guide.  This file provides a qu`, `Run migrations in 'offline' mode.      This configures the context with just a U`, `Run migrations in 'online' mode.      In this scenario we need to create an Engi` to the rest of the system?**
  _39 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Database Migrations` be split into smaller, more focused modules?**
  _Cohesion score 0.06 - nodes in this community are weakly interconnected._
- **Should `User Authentication` be split into smaller, more focused modules?**
  _Cohesion score 0.13 - nodes in this community are weakly interconnected._