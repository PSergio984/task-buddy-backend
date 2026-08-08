# B-02 — Create Supabase project and migrate all data

Type: task
Status: resolved
Blocked by: B-01 (01-supabase-connectivity)

## Question

Manual work that must happen before the data-migration decision can be finalized: create the Supabase Cloud project and move all existing data into it (no real users affected, everything moves — dev and prod data).

- User checklist (HITL): create Supabase project, enable `pgvector` (per B-01), share the connection string + project credentials location with the agent (never commit secrets).
- Dump current Postgres (Render prod, if running) and/or SQLite dev (`test.db`) per B-01's mechanics; load into Supabase; reset sequences; verify row counts table-by-table.
- Record what was done + resulting facts (project URL, connection-string location, row counts, any schema drift found) under `## Answer`.

## Answer

1. **Project created** by user: `xqbdfphgcexixgitkstu` (Supabase Cloud, ap-northeast-1). `vector` extension enabled by user (pgvector available for the future agent seam).
2. **Connection**: direct endpoint (`db.<ref>.supabase.co`) is IPv6-only (AAAA only) — unreachable from this machine. Session pooler used instead: `aws-0-ap-northeast-1.pooler.supabase.com:5432` (IPv4), user `postgres.<ref>`. Verified working via asyncpg + SQLAlchemy (PostgreSQL 17.6). Connection string now in backend `.env` as `DEV_DATABASE_URL` (password never committed/echoed).
3. **Schema**: `alembic upgrade head` ran clean against Supabase — 9 tables (`tbl_users`, `tbl_tasks`, `tbl_subtasks`, `tbl_projects`, `tbl_tags`, `tbl_task_tags`, `tbl_notifications`, `tbl_push_subscriptions`, `tbl_audit_logs`) + `alembic_version` at head `ed27f78207cd`. No drift.
4. **Data**: nothing to copy at migration time — `test.db` empty, local docker Postgres offline. No production data present (`.env` has no `PROD_DATABASE_URL`). If the Render prod DB ever holds data, dump it before cutover.
5. **Tests**: `TEST_DATABASE_URL=sqlite:///./test.db` already configured — testing scripts keep SQLite per user instruction.
