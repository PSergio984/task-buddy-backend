# Task Buddy Backend

## What This Is

A robust task management backend (Task Buddy) built with FastAPI, designed for high performance and reliability. It features a layered monolith architecture with comprehensive auditing, secure user authentication, and reliable external integrations for email and monitoring.

## Core Value

Reliable and auditable task management state for the Task Buddy ecosystem.

## Requirements

### Validated

- ✓ **AUTH-CORE** — JWT-based user authentication (signup/login) — existing
- ✓ **TASK-CORE** — Full CRUD for tasks with status/priority — existing
- ✓ **TAG-CORE** — Many-to-many tagging system for organization — existing
- ✓ **AUDIT-CORE** — Manual mutation logging for core entities — existing
- ✓ **EMAIL-DISPATCH** — Transactional emails via Brevo — existing
- ✓ **MONITOR-CORE** — Error tracking and monitoring via Sentry — existing

### Active

- [ ] **REFI-TRANSACTIONS** — Refactor CRUD to support external transaction management (remove commits from CRUD).
- [ ] **REFI-CONSTANTS** — Standardize API literals and statuses using Enums and Constants.
- [ ] **SECU-HARDEN** — Implement Argon2 password hashing and strict CORS/Security headers.
- [ ] **AUDI-AUTO** — Centralize and automate mutation logging via decorators or middleware.
- [ ] **RELI-QUEUE** — Migrate email dispatch to a background task queue (Celery/RabbitMQ) for data safety.
- [ ] **TEST-ADVANCED** — Implement integration tests for race conditions and concurrent access.

### Out of Scope

- **Frontend Features** — This repo is strictly for the backend API.
- **Third-party Auth (OAuth)** — Staying with email/password for the current phase.
- **Desktop/Mobile Apps** — Backend is API-first and agnostic.

## Context

- **Tech Stack**: FastAPI, SQLAlchemy 2.0, Pydantic v2, PostgreSQL (Prod), SQLite (Dev).
- **Environment**: Managed via `.env` with critical integrations (Brevo, Sentry).
- **Current State**: Stable but carries technical debt around transaction management and manual auditing.

## Constraints

- **Tech Stack**: Must remain compatible with Python 3.10+ and the existing library ecosystem. — Maintainability
- **Database**: Must support both SQLite (local) and PostgreSQL (production). — Environment parity
- **Security**: Must adhere to OWASP Top 10 for API security. — User data protection

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Layered Monolith | Clear separation of concerns (API/CRUD/Models) | ✓ Good |
| Manual Commits in CRUD | Initial speed (technical debt) | ⚠️ Revisit |
| Manual Audit Logging | Initial speed (technical debt) | ⚠️ Revisit |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-08 after initialization*
