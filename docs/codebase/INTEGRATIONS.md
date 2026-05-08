# External Integrations

## Core Sections (Required)

### 1) Integration Inventory

| System | Type (API/DB/Queue/etc) | Purpose | Auth model | Criticality | Evidence |
|--------|---------------------------|---------|------------|-------------|----------|
| PostgreSQL | Database | Primary data store | Password/Connection URL | High | `pyproject.toml`, `.env.example` |
| Sentry | Error Monitoring | Tracking runtime errors | DSN (env var) | Medium | `pyproject.toml`, `app/main.py` |
| Snyk/SOOS | Security Scanning | Vulnerability checking in CI | API Key | Low | `.github/workflows/` |

### 2) Data Stores

| Store | Role | Access layer | Key risk | Evidence |
|-------|------|--------------|----------|----------|
| PostgreSQL | Persistent storage for tasks, users, etc. | `app/database.py` (SQLAlchemy) | Connection timeouts, data integrity | `app/database.py`, `app/models/` |
| SQLite (dev/test) | Local development and testing | `app/database.py` | Data persistence across sessions (if file-based) | `pyproject.toml` (databases[sqlite]) |

### 3) Secrets and Credentials Handling

- Credential sources: Environment variables (`.env` file)
- Hardcoding checks: None observed; configuration uses `pydantic-settings` to load from env.
- Rotation or lifecycle notes: [TODO]

### 4) Reliability and Failure Behavior

- Retry/backoff behavior: Not explicitly observed in code; likely handled by SQLAlchemy or external infrastructure.
- Timeout policy: [TODO] (Check SQLAlchemy engine configuration)
- Circuit-breaker or fallback behavior: None observed.

### 5) Observability for Integrations

- Logging around external calls: Handled by SQLAlchemy logging and custom application logs.
- Metrics/tracing coverage: Sentry integration provides basic tracing and error reporting.
- Missing visibility gaps: Detailed database query performance metrics.

### 6) Evidence

- `app/main.py` (Sentry initialization)
- `app/database.py` (SQLAlchemy setup)
- `.env.example`
- `pyproject.toml`

## Extended Sections (Optional)

- CI/CD Security: `soos-dast-scan.yml`, `apisec-scan.yml`.
