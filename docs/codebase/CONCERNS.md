# Codebase Concerns

## Core Sections (Required)

### 1) Top Risks (Prioritized)

| Severity | Concern | Evidence | Impact | Suggested action |
|----------|---------|----------|--------|------------------|
| High | Security: Hardcoded values / Weak config | `app/config.py` (Default values) | Potential exposure of secrets if `.env` is missing | Ensure strict environment variable validation and no sensitive defaults in production. |
| Med | Database: Async connection leaks | [TODO] | Potential app hang or database exhaustion | Implement thorough connection pooling monitoring. |
| Med | API: Lack of Rate Limiting on critical routes | `app/limiter.py` present but check usage | Potential DOS or brute force on auth endpoints | Verify `slowapi` decorators are applied to all sensitive routes. |

### 2) Technical Debt

List the most important debt items only.

| Debt item | Why it exists | Where | Risk if ignored | Suggested fix |
|-----------|---------------|-------|-----------------|---------------|
| `[TODO]` comments | Unfinished features or edge case handling | Grep for `TODO` | Incomplete logic or bugs | Systematically address and clear `TODO` items. |
| Inconsistent CRUD usage | Some logic in routers, some in `crud/` | `app/api/routers/` | Harder to test and maintain | Refactor all DB logic into dedicated CRUD modules. |

### 3) Security Concerns

| Risk | OWASP category (if applicable) | Evidence | Current mitigation | Gap |
|------|--------------------------------|----------|--------------------|-----|
| Insecure JWT Secret | A01: Broken Access Control | `.env.example` | Use of `SECRET_KEY` env var | Ensure rotation policy and high entropy secrets in production. |
| Mass Assignment | A03: Injection (Data Integrity) | `app/schemas/` | Pydantic validation | Ensure `Extra.forbid` or strict schema filtering on all inputs. |

### 4) Performance and Scaling Concerns

| Concern | Evidence | Current symptom | Scaling risk | Suggested improvement |
|---------|----------|-----------------|-------------|-----------------------|
| Synchronous Blockers | [TODO] | [TODO] | High latency under load | Ensure no blocking I/O or heavy CPU tasks on the main async loop. |

### 5) Fragile/High-Churn Areas

| Area | Why fragile | Churn signal | Safe change strategy |
|------|-------------|-------------|----------------------|
| `app/api/routers/task.py` | Core feature, frequent changes | [TODO] | Comprehensive integration tests before any change. |

### 6) `[ASK USER]` Questions

Add unresolved intent-dependent questions as a numbered list.

1. [ASK USER] What is the preferred database for production (PostgreSQL or other)?
2. [ASK USER] Are there specific compliance requirements (GDPR, HIPAA, etc.)?

### 7) Evidence

- `app/config.py`
- `pyproject.toml`
- `grep "TODO" -r app`
