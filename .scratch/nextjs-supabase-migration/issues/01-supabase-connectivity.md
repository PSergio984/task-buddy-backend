# B-01 — Supabase connectivity facts for FastAPI/SQLAlchemy

Type: research
Status: resolved
Blocked by: —

## Question

What are the facts needed to point the existing FastAPI + SQLAlchemy 2.0 backend (Alembic migrations, Celery worker, SQLite dev / Postgres prod) at Supabase Cloud Postgres?

- Connection string formats (direct vs PgBouncer/transaction pooler), SSL modes required by Supabase.
- Pooling recommendation for SQLAlchemy (session-mode PgBouncer implications for `pgbouncer.transaction_mode`, prepared statements).
- Running Alembic migrations against Supabase Postgres (roles, permissions, `alter system` restrictions, extensions like `pgcrypto`/`uuid-ossp`/`pgvector`).
- Which extensions the schema actually needs (check `alembic/` migrations + models first), and how to enable `pgvector` on Supabase for the future agent seam.
- pg_dump/restore mechanics from a source Postgres into Supabase (roles/owners, sequences, `--no-owner` needs), and from SQLite dev via SQLAlchemy `create_all` + copy.
- Realtime requirements: `wal_level` on Supabase (is it already logical? what does Realtime need?), enabling publications/tables for Realtime, and the role used for the Realtime connection.

Resolve via primary sources (Supabase docs, PostgreSQL docs). Record answer under `## Answer` and save findings to `task-buddy-backend/.scratch/nextjs-supabase-migration/research/b01-supabase-connectivity.md`, then link from here.

## Answer

Findings: `research/b01-supabase-connectivity.md`. Key facts: persistent FastAPI + Celery → direct connection (port 5432), session pooler as IPv4 fallback; transaction pooler (6543) for serverless only. SQLAlchemy: `pool_pre_ping=True`, defaults fine. Celery: NullPool per worker task (fresh connection; no cross-fork pool sharing — supersedes any `engine.dispose(close=False)` guidance). Alembic as `postgres` role; `ALTER SYSTEM` not in Supabase's config surface. pgvector = `vector` extension; uuid-ossp enabled by default. Realtime: tables must be added to `supabase_realtime` publication; logical replication already on. Open: Render IPv6 egress to direct endpoint (determines direct vs session pooler), psycopg2/pooler prepared-statement behavior, SQLite→Postgres copy translation.
