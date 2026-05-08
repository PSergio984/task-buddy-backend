# Codebase Concerns

## Core Sections (Required)

### 1) Top Risks (Prioritized)

| Severity | Concern | Evidence | Impact | Suggested action |
|----------|---------|----------|--------|------------------|
| High | Security: Stateless JWT Logout | `app/api/routers/user.py` | Logout is purely client-side; no server-side invalidation. | Implement a token blacklist or use short-lived tokens with rotation. |
| High | Fragility: Untested Email Fallback | `app/tasks.py` | SMTP -> Brevo fallback logic is partially untested and risky. | Add comprehensive tests for the fallback mechanism and isolation. |
| Med | Quality: Coverage Gaps | `app/tasks.py` (76%), `app/logging_conf.py` (42%) | Potential bugs in critical background or logging paths. | Prioritize unit tests for these low-coverage modules. |
| Med | Security: Hardcoded values / Weak config | `app/config.py` (Default values) | Potential exposure of secrets if `.env` is missing | Ensure strict environment variable validation and no sensitive defaults in production. |

### 2) Technical Debt

List the most important debt items only.

| Debt item | Why it exists | Where | Risk if ignored | Suggested fix |
|-----------|---------------|-------|-----------------|---------------|
| `[TODO]` comments | Unfinished features or edge case handling | Grep for `TODO` | Incomplete logic or bugs | Systematically address and clear `TODO` items. |
| Inconsistent CRUD usage | Some logic in routers, some in `crud/` | `app/api/routers/` | Harder to test and maintain | Refactor all DB logic into dedicated CRUD modules. |
| Manual Background Tasks | Direct DB calls in tasks | `app/tasks.py` | Harder to scale or isolate | Move task logic to a service layer or use a proper task queue (Celery/RQ). |

### 3) Security Concerns

| Risk | OWASP category (if applicable) | Evidence | Current mitigation | Gap |
|------|--------------------------------|----------|--------------------|-----|
| Insecure JWT Secret | A01: Broken Access Control | `.env.example` | Use of `SECRET_KEY` env var | Ensure rotation policy and high entropy secrets in production. |
| Mass Assignment | A03: Injection (Data Integrity) | `app/schemas/` | Pydantic validation | Ensure `Extra.forbid` or strict schema filtering on all inputs. |
| Stateless Auth | A01: Broken Access Control | `app/security.py` | JWT encryption | No server-side control over active sessions. |

### 4) Performance and Scaling Concerns

| Concern | Evidence | Current symptom | Scaling risk | Suggested improvement |
|---------|----------|-----------------|-------------|-----------------------|
| N+1 Fetching | `app/api/routers/task.py` | Subtasks fetched per task | UI lag with many tasks | Use joined loads or bulk fetching for sub-entities. |
| Synchronous Blockers | [TODO] | [TODO] | High latency under load | Ensure no blocking I/O or heavy CPU tasks on the main async loop. |

### 5) Fragile/High-Churn Areas

| Area | Why fragile | Churn signal | Safe change strategy |
|------|-------------|-------------|----------------------|
| `app/api/routers/task.py` | Core feature, frequent changes | High Complexity Node | Comprehensive integration tests before any change. |
| `app/tasks.py` | Critical but low coverage | Fallback Logic | Isolate logic and add edge-case testing. |

### 6) `[ASK USER]` Questions

Add unresolved intent-dependent questions as a numbered list.

1. [ASK USER] What is the preferred database for production (PostgreSQL or other)?
2. [ASK USER] Are there specific compliance requirements (GDPR, HIPAA, etc.)?
3. [ASK USER] Should we implement server-side session management (Redis) for JWT blacklisting?

### 7) Evidence

- `app/config.py`
- `pyproject.toml`
- `grep "TODO" -r app`
- `gsd-codebase-mapper` summary report
