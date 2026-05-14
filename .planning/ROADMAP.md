# Roadmap: Task Buddy Backend

## Overview

The journey starts with refining the architectural core (transaction management and constants) to ensure a stable foundation. We then move into security hardening and automated auditing to protect user data and ensure accountability. Finally, we scale the reliability by implementing background task queues and advanced integration tests.

## Phases
- [x] **Phase 1: Architecture Refinement** - Decouple CRUD from transaction commits and standardize API constants.
- [x] **Phase 2: Security Hardening** - Implement industry-standard security practices for data and networking.
- [x] **Phase 3: Auditing & Task Management** - Ensure state change accountability and enhance task organization.
- [x] **Phase 3.5: Premium UI & Projects** - Backend terminology alignment and data seeding.
- [ ] **Phase 3.8: Notification & Reminder System** - Multi-channel notifications (Email, In-App, Push).
- [ ] **Phase 3.9: Idempotency & Reliability** - Middleware for request de-duplication and server-side stability.
- [ ] **Phase 4: Reliability & Scale** - Modernize integration handling and verify system resilience.


## Phase Details

### Phase 1: Architecture Refinement
**Goal**: Decouple CRUD from transaction commits and standardize API constants.
**Status**: COMPLETED
**Depends on**: Nothing
**Requirements**: REFI-01, REFI-02, REFI-03
**Success Criteria**:
  1. [x] CRUD functions can be composed into a single transaction.
  2. [x] No hardcoded status strings in routers.
  3. [x] All SQLAlchemy models use 2.0 type hints.
**Plans**: 2 plans

Plans:
- [x] 01-01: Refactor CRUD methods to remove `db.commit()` and `db.refresh()`.
- [x] 01-02: Standardize Enums and Constants across all routers.

### Phase 2: Security Hardening
**Goal**: Implement industry-standard security practices for data and networking.
**Status**: COMPLETED
**Depends on**: Phase 1
**Requirements**: SECU-01, SECU-02, SECU-03
**Success Criteria**:
  1. [x] Argon2 hashing used for all new passwords.
  2. [x] CORS limited to configured trusted origins.
  3. [x] API responses include standard security headers.
**Plans**: 1 plan

Plans:
- [x] 02-01: Security middleware and password hashing upgrade.

### Phase 3: Auditing & Task Management
**Goal**: Ensure state change accountability and enhance task organization.
**Status**: COMPLETED
**Depends on**: Phase 2
**Requirements**: AUDI-01, AUDI-02, TASK-01, TASK-02
**Success Criteria**:
  1. [x] Mutation logging happens automatically on CRUD calls.
  2. [x] Audit logs capture field-level diffs.
  3. [x] Dynamic relational task grouping is implemented (Projects).
  4. [x] Precise due time selection and display is supported end-to-end.
**Plans**: 2 plans

Plans:
- [x] 03-01: Implement automated audit logging decorator/middleware.
- [x] 03-02: Relational task grouping (Projects) and enhanced due time support.

### Phase 3.5: Premium UI & Projects
**Goal**: Align terminology and seed database for premium frontend.
**Status**: COMPLETED
**Depends on**: Phase 3
**Requirements**: PRJT-01, SEED-01
**Success Criteria**:
  1. [x] All 'Group' references in models, schemas, and routes migrated to 'Project'.
  2. [x] Seed script updated to generate reliable data for the new 'Project' structure.
**Plans**: 2 plans

Plans:
- [x] 03.5-01: Backend terminology refactor (Group -> Project).
- [x] 03.5-02: Seed script hardening and UI criteria.

### Phase 3.8: Notification & Reminder System
**Goal**: Implement multi-channel reminders and in-app notifications.
**Status**: PLANNING
**Depends on**: Phase 3.5
**Requirements**: NOTI-01, NOTI-02, NOTI-03
**Success Criteria**:
  1. Users receive email reminders for upcoming tasks.
  2. In-app notifications are visible and markable as read.
  3. Push notifications work on supported browsers.
**Plans**: 4 plans

Plans:
- [ ] 03.8-01: Setup Notification and PushSubscription models and CRUD layer.
- [ ] 03.8-02: Implement API endpoints for notification management and push registration.
- [ ] 03.8-03: Configure Celery Beat and implement reminder scanning logic.
- [ ] 03.8-04: End-to-end testing and verification of the notification system.

### Phase 3.9: Idempotency & Reliability
**Goal**: Implement a robust idempotency mechanism to prevent duplicate side effects.
**Status**: PLANNING
**Depends on**: Phase 3.5
**Success Criteria**:
  1. `POST`, `PUT`, `PATCH`, `DELETE` requests with `X-Idempotency-Key` are de-duplicated.
  2. Responses are cached in Redis for 1 hour.
  3. Re-sent requests return the same response without re-executing logic.

### Phase 4: Reliability & Scale
**Goal**: Modernize integration handling and verify system resilience.
**Status**: PLANNED
**Depends on**: Phase 3.8
**Requirements**: RELI-01, RELI-02, RELI-03
**Success Criteria**:
  1. Emails are sent via background worker without blocking request.
  2. Database migrations are verified reversible.
  3. No deadlocks or race conditions found under concurrent load.
**Plans**: 2 plans

Plans:
- [ ] 04-01: Set up background worker (e.g., Celery/Redis) for emails.
- [ ] 04-02: Stress and concurrency integration test suite.

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Architecture Refinement | 2/2 | Completed | 2026-05-08 |
| 2. Security Hardening | 1/1 | Completed | 2026-05-08 |
| 3. Auditing & Task Management | 2/2 | Completed | 2026-05-09 |
| 3.5. Premium UI & Projects | 2/2 | Completed | 2026-05-10 |
| 3.8. Notifications | 0/4 | Planning | - |
| 4. Reliability & Scale | 0/2 | Not started | - |

---
*Roadmap defined: 2026-05-08*
*Last updated: 2026-05-12*
