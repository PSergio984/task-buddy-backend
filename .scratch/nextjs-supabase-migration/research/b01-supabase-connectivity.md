# B01 — Supabase Connectivity Research

Research ticket: FastAPI/SQLAlchemy 2.0 backend → Supabase Cloud Postgres.
Primary sources are preferred (supabase.com/docs, postgresql.org/docs/15, docs.sqlalchemy.org/en/20, alembic.sqlalchemy.org, pgbouncer.org); secondary sources and practical guidance are labeled inline. No code modified.

---

## 1. Connection string formats & SSL

Four connection modes (host:port table in [Connecting to Postgres](https://supabase.com/docs/guides/database/connecting-to-postgres)):

| Mode | Host:Port | Reachability | Best for |
|---|---|---|---|
| Direct connection | `db.[project-ref].supabase.co:5432` | IPv6 by default; IPv4 only with [IPv4 add-on](https://supabase.com/docs/guides/platform/ipv4-address) (not dual-stack — enabling swaps AAAA for A record) | Migrations, `pg_dump`, backup/restore, long-lived backend (VMs, long-running containers); also required for replication setup |
| Shared pooler (Supavisor) — session mode | `aws-[region].pooler.supabase.com:5432` (user `postgres.[ref]`) | IPv4 on every tier | Persistent backend on IPv4-only networks (only recommended as alternative to direct when IPv4 is needed) |
| Shared pooler (Supavisor) — transaction mode | `aws-[region].pooler.supabase.com:6543` (user `postgres.[ref]`) | IPv4 on every tier | Serverless/edge functions, transient clients; does NOT support prepared statements |
| Dedicated pooler (PgBouncer) — transaction mode | `db.[project-ref].supabase.co:6543` | IPv6; IPv4 with add-on; **paid plans only** | High-performance app traffic on paid tiers; transaction mode only |

- Supabase's own decision flow: persistent backend → **direct connection** if IPv6 (or IPv4 add-on) is available, otherwise Supavisor session mode; serverless/short-lived → dedicated pooler or Supavisor transaction mode. ([Connecting to Postgres](https://supabase.com/docs/guides/database/connecting-to-postgres#how-to-choose-the-right-connection-method))
- Format examples: direct `postgresql://postgres:[PW]@db.<ref>.supabase.co:5432/postgres`; pooler `postgres://postgres.<ref>:[PW]@aws-<region>.pooler.supabase.com:6543/postgres`. ([Connecting to Postgres](https://supabase.com/docs/guides/database/connecting-to-postgres))
- Ports route mode: 5432 = direct or session-mode pooler, 6543 = transaction mode. ([Connecting to Postgres FAQ](https://supabase.com/docs/guides/database/connecting-to-postgres#why-do-connection-strings-have-different-ports))
- The Postgres→Supabase migration guide uses **session pooler on 5432** for pg_dump/restore tasks ("Use Supavisor session mode for the database migration tasks"). ([Migrate from Postgres](https://supabase.com/docs/guides/platform/migrating-to-supabase/postgres#connection-modes))

SSL:
- SSL is **not enforced by default**; can be enforced via dashboard ("Enforce SSL on incoming connections"), Management API, or CLI `supabase ssl-enforcement`. Enforcement change triggers a brief DB reboot. ([SSL Enforcement](https://supabase.com/docs/guides/platform/ssl-enforcement))
- sslmode semantics: `require` = always SSL but **no certificate/hostname verification**; `verify-ca` = verifies CA; `verify-full` = verifies CA + hostname, "the mode you most likely want when SSL enforcement is enabled". ([SSL Enforcement](https://supabase.com/docs/guides/platform/ssl-enforcement))
- For `verify-full`: download CA cert (`prod-ca-2021.crt`) from dashboard SSL Configuration; example: `psql "postgresql://...?sslmode=verify-full"`. ([SSL Enforcement](https://supabase.com/docs/guides/platform/ssl-enforcement), [Connecting with PSQL](https://supabase.com/docs/guides/database/psql))
- `sslmode=require` is adequate where cert pinning is impractical (most connection-string libs); **production should use `sslmode=verify-full` with the Supabase CA certificate** (`prod-ca-2021.crt`, dashboard → SSL Configuration); treat `require` as a documented exception only, never the default for prod.

---

## 2. Pooling (SQLAlchemy settings, PgBouncer implications, Celery)

SQLAlchemy basics ([Connection Pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html)):
- Pool defaults are dialect-dependent: SQLAlchemy's synchronous `QueuePool` defaults to `pool_size=5`, `max_overflow=10`; the **asyncpg dialect defaults to `NullPool`** (no pooling) unless configured - relevant because this app uses asyncpg via `create_async_engine` and sets explicit pool options.
- `pool_pre_ping=True` = pessimistic disconnect handling: emits a liveness check at checkout, recycles stale connections; recommended pattern ("Modern SQLAlchemy tends to favor the pessimistic approach" — [FAQ](https://docs.sqlalchemy.org/en/20/faq/connections.html)).
- `pool_recycle` = optimistic: drops connections older than N seconds at next checkout; the doc's rationale is backends that close idle connections ([Pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html#setting-pool-recycle)) — Postgres itself does not idle-close, so this is optional against Supabase.
- `pool_use_lifo=True` pairs with `pool_pre_ping` to let server-side timeouts reclaim idle connections ([Pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html#using-fifo-vs-lifo)).

Supabase-side pool sizing ([Connection management](https://supabase.com/docs/guides/database/connection-management), [Connecting to Postgres FAQ](https://supabase.com/docs/guides/database/connecting-to-postgres#how-does-the-default-pool-size-work)):
- Supavisor pool size is set in dashboard (Database Settings → Connection pooling); guidance: ~80% of DB max connections to the pool if not heavily using PostgREST, ~40% if you are.
- Pooler backend connections (pool_size) are shared between session-mode and transaction-mode ports under one limit; running both poolers + direct connections stacks load toward the compute tier's max connections (direct + Supavisor + PgBouncer backend connections together count toward `max_connections`, with separate pooler caps).
- App-side pools "are satisfactory on their own" for long-standing containers/VMs (deployed static architecture) — i.e., a persistent FastAPI deployment needs no server-side pooler by default. ([Connecting to Postgres](https://supabase.com/docs/guides/database/connecting-to-postgres#application-side-poolers))

PgBouncer/Supavisor transaction-mode implications:
- Transaction mode: "A server connection is assigned to a client only during a transaction" and returned when it ends ([PgBouncer usage](https://www.pgbouncer.org/usage.html#transaction-pooling)). Consequence: anything session-scoped does not survive — named/prepared statements, session-level advisory locks, `SET SESSION`, LISTEN/NOTIFY. Supabase's documented limitation: "Transaction mode does not support prepared statements... turn off prepared statements for your connection library." ([Connecting to Postgres](https://supabase.com/docs/guides/database/connecting-to-postgres#pooler-transaction-mode))
- SQLAlchemy/asyncpg vs PgBouncer: use `poolclass=NullPool` and dynamic prepared statement names (`prepared_statement_name_func`); PgBouncer must be configured to `DISCARD` on return or prepared statements accumulate ("Without proper setup, prepared statements can accumulate quickly and cause performance issues"). ([SQLAlchemy PostgreSQL dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#prepared-statement-name-with-pgbouncer)) — relevant only for asyncpg, which auto-prepares; psycopg2 has no equivalent auto-prepare threshold.
- Do NOT run long-lived session-scoped work (migrations, replication, advisory-lock workflows) through transaction mode.

Celery worker:
- Persistent process → per Supabase's own matrix it should use **direct connection** (or session pooler if IPv4-only), not transaction mode. Transaction pooler buys little for a bounded set of long-lived prefork processes and adds the prepared-statement/session-state constraints. Direct connections from persistent backends are the documented default posture ([Connecting to Postgres](https://supabase.com/docs/guides/database/connecting-to-postgres#how-to-choose-the-right-connection-method)).
- Multiprocessing (Celery named explicitly): an Engine created in the parent process must NOT be inherited by forked children — either build the engine in each child or call `engine.dispose(close=False)` in the child initializer; `NullPool` is an alternative. ([SQLAlchemy FAQ](https://docs.sqlalchemy.org/en/20/faq/connections.html), [Pooling — multiprocessing](https://docs.sqlalchemy.org/en/20/core/pooling.html#using-connection-pools-with-multiprocessing-or-os-fork))
- Recommended config for Supabase (both FastAPI and Celery): `pool_pre_ping=True`, `pool_size` sized to expected concurrency (Supabase pool-size cap applies to pooler routes; direct route counts against compute `max_connections`), `pool_recycle` optional (Postgres doesn't idle-close).

---

## 3. Alembic migrations against Supabase
**Alembic is authoritative for this repository's schema.** B-02 runs `alembic upgrade head` against Supabase (head `ed27f78207cd` applied); all bootstrap guidance below defers to that.
- Supabase's own migration tooling is CLI-based (`supabase db push`), tracked in `supabase_migrations.schema_migrations`; golden rule: never change remote schema outside migration files or `db push` breaks sync. ([Database Migrations](https://supabase.com/docs/guides/deployment/database-migrations)) — Alembic manages its own `alembic_version`; the two systems must not both drive the same schema.
- Run migrations as the **`postgres` role**: the connection-management doc identifies `postgres` as the role used by external tools (explicitly: "Prisma, SQLAlchemy, PSQL..."). ([Connection management](https://supabase.com/docs/guides/database/connection-management)) The migration guide also restores/dumps as the project's postgres user. ([Migrate from Postgres](https://supabase.com/docs/guides/platform/migrating-to-supabase/postgres))
- Migrations should connect via **direct connection** (documented use: "migrations") or session pooler; do not use transaction mode for DDL. ([Connecting to Postgres](https://supabase.com/docs/guides/database/connecting-to-postgres))
- `ALTER SYSTEM`: not part of Supabase's documented configuration surface. Postgres-level settings are changed three ways only: (a) user-context settings via SQL `ALTER DATABASE/ALTER ROLE`; (b) a fixed allowlist of "superuser" settings (e.g. `statement_timeout`, `log_*`, `pg_stat_statements.*`, `session_replication_role`) via `ALTER ROLE postgres SET ...` using the pre-enabled `supautils` extension; (c) server-level params (e.g. `max_connections`, `shared_buffers`, `work_mem`) via dashboard/CLI `supabase postgres-config update`, which requires Owner/Admin and may restart the DB. ([Customizing Postgres configs](https://supabase.com/docs/guides/database/custom-postgres-config))
- `wal_level`, `max_replication_slots` etc. are NOT user-facing on Supabase (replication config table marks them "User-facing: No"). ([Replication overview](https://supabase.com/docs/guides/database/replication))
- Extensions — enable via Dashboard (Database → Extensions) or SQL `create extension <name> with schema extensions;`; most install under the `extensions` schema. ([Extensions overview](https://supabase.com/docs/guides/database/extensions))
  - `uuid-ossp`: **enabled by default and cannot be disabled**; provides `uuid` type, `uuid_generate_v4()` (gen_random_uuid() also built-in). ([uuid-ossp](https://supabase.com/docs/guides/database/extensions/uuid-ossp))
  - `pgcrypto`: no dedicated Supabase docs page in the current docs catalog (see Open questions); enable via SQL `create extension pgcrypto with schema extensions;`. The migration guide's pre-migration step lists extensions via `SELECT * FROM pg_available_extensions` then `CREATE EXTENSION IF NOT EXISTS ...` ([Migrate from Postgres](https://supabase.com/docs/guides/platform/migrating-to-supabase/postgres#pre-migration-checklist)).
  - pgvector: extension name is **`vector`** (not pgvector); enable via dashboard or `create extension vector with schema extensions;`. ([pgvector](https://supabase.com/docs/guides/database/extensions/pgvector))
- Alembic itself: migrations run against the URL configured in `alembic.ini`/`env.py` as the connecting role; `alembic upgrade head` applies pending revisions ([Alembic docs](https://alembic.sqlalchemy.org/en/latest/)). SQLite-origin migrations may need batch mode if they rely on ALTER TABLE unsupported by SQLite — irrelevant on Postgres target but the migration history must be reset for Postgres ([Alembic batch](https://alembic.sqlalchemy.org/en/latest/batch.html)).

---

## 4. Data migration mechanics

Postgres → Supabase (official guide: [Migrate from Postgres](https://supabase.com/docs/guides/platform/migrating-to-supabase/postgres)):
- Three methods: Google Colab notebook, manual pg_dump/pg_restore (all versions), logical replication (PG 10+).
- Manual dump flags: `pg_dump --no-owner --no-privileges --no-subscriptions --format=directory --jobs=N`; same `--no-owner --no-privileges` at restore. Rationale: "prevent Supabase user management conflicts"; users/roles and privileges are **not migrated** — recreate roles and grants after import.
- **RLS status is not migrated** — re-enable RLS per table after import.
- Restore target: session pooler (5432) or direct connection; parallel `-j` sized to Supabase compute cores; `-j` cannot combine with `--single-transaction`.
- Post-restore: `VACUUM VERBOSE ANALYZE;`; verify row counts via `pg_stat_user_tables`.
- If restore fails with extension errors, install missing extensions first (check `pg_available_extensions` on the Supabase side).
- Logical replication method: requires `wal_level=logical`, `max_wal_senders ≥ 1`, `max_replication_slots ≥ 1` on **source**; sequences are NOT replicated — manual sync via data-only dump of sequences before cutover; replica identity required for tables without PK; DDL changes not replicated (schema freeze). (Same guide; wal_level semantics: [PostgreSQL 15 WAL config](https://www.postgresql.org/docs/15/runtime-config-wal.html) — `logical` adds logical decoding info, set only at server start.)
- Replication into/out of Supabase: Supabase side supports `CREATE PUBLICATION`, logical slots (`pg_create_logical_replication_slot`), and `CREATE SUBSCRIPTION`; requires a **direct connection** (not a pooler); non-postgres roles need `CREATE ROLE <user> WITH REPLICATION;` run as postgres. ([Replicate to external Postgres](https://supabase.com/docs/guides/database/postgres/setup-replication-external))

SQLite dev → Supabase:
- No official Supabase guide for SQLite; the sanctioned path is schema via migration tooling + data via dump/import. SQLAlchemy mechanism: `MetaData.create_all(engine)` emits dialect-specific DDL (one statement set per dialect) — usable to create the Postgres schema from the SQLAlchemy metadata, but it bypasses Alembic history and does not migrate data. ([SQLAlchemy MetaData](https://docs.sqlalchemy.org/en/20/core/metadata.html))
- Practical route (not primary-sourced): keep Alembic as source of truth — write the Postgres baseline by `alembic revision` from existing models (or `create_all` then `alembic stamp`), then copy data row-by-row from SQLite via SQLAlchemy sessions. **Default bootstrap for an empty Supabase database is `alembic upgrade head`** (B-02 executed this); `create_all`/`stamp` are fallbacks only when history is unavailable. Type/constraint translation (SQLite JSON/Boolean/text dates vs Postgres JSONB/BOOLEAN/timestamptz; SQLite `INTEGER PRIMARY KEY` → Postgres identity/serial; autoincrement counters/sequences) must be validated per table. See Open questions.

---

## 5. Realtime prerequisites

- Tables must be added to the **`supabase_realtime` publication**: dashboard Publications settings (toggle tables) or `alter publication supabase_realtime add table <table>;`. Without this, no change events fire. ([Postgres Changes](https://supabase.com/docs/guides/realtime/postgres-changes))
- Realtime connects to your database and **acquires a logical replication slot**; it reads the WAL (logical decoding) and appends subscription IDs per record. Broadcast additionally creates a publication on `realtime.messages` (partitioned daily, 3-day retention). ([Realtime Architecture](https://supabase.com/docs/guides/realtime/architecture))
- Logical replication slots require `wal_level = logical` (PG 15 docs: logical level "adds information necessary to support logical decoding"; only settable at server start — [WAL config](https://www.postgresql.org/docs/15/runtime-config-wal.html)). Supabase supports logical slots out of the box on its managed instances (documented procedure creates one with `pg_create_logical_replication_slot(..., 'pgoutput')` — [Replicate to external Postgres](https://supabase.com/docs/guides/database/postgres/setup-replication-external)); `wal_level` is not user-configurable on Supabase ([Replication overview](https://supabase.com/docs/guides/database/replication), [Custom Postgres configs](https://supabase.com/docs/guides/database/custom-postgres-config)).
- Which role: `supabase_admin` is documented as the role "used by Supabase for monitoring and by Realtime" ([Connection management](https://supabase.com/docs/guides/database/connection-management)); replication-slot creation is done with the `postgres` role per the official example ([setup-replication-external](https://supabase.com/docs/guides/database/postgres/setup-replication-external)).

---

## Open questions (unresolved from primary sources)

1. **pgcrypto availability**: current Supabase extension docs catalog has no pgcrypto page (verified by listing the docs repo's extensions dir — pgcrypto.mdx absent, while uuid-ossp.mdx and pgvector.mdx exist). Whether it is preinstalled/available must be verified per project via `SELECT * FROM pg_available_extensions;` at provisioning time.
2. **ALTER SYSTEM blocking**: no current Supabase doc states "ALTER SYSTEM is disabled" in those words; the docs only present dashboard/CLI/ALTER ROLE as the config surface (custom-postgres-config). Assume it is not supported until verified against a live project.
3. **psycopg2 + transaction pooler**: Supabase's prepared-statement caution ([discussion #28239](https://github.com/orgs/supabase/discussions/28239)) and SQLAlchemy's guidance are written around asyncpg; exact behavior of psycopg2's auto-prepare threshold against Supavisor/PgBouncer transaction mode is not documented in primary sources. psycopg2 has no "disable prepared statements" switch — need empirical check or switch driver if transaction mode is required.
4. **Session-level advisory locks under transaction pooling**: implied by PgBouncer semantics (connection returned at transaction end) but no Supabase or PgBouncer primary source found stating the failure mode explicitly.
5. **SQLite→Supabase data copy**: no official Supabase guidance; type/constraint/sequence translation matrix must be validated per table (SQLite autoincrement → Postgres identity/sequence values; JSON column types; booleans; unsupported ALTERs).
6. **Alembic vs Supabase CLI coexistence**: Supabase tracks migrations in `supabase_migrations.schema_migrations` (CLI) while Alembic tracks `alembic_version`; running both against one project is not addressed by either docs set.
7. **Render IPv6 egress**: direct connections need IPv6 (or the paid IPv4 add-on); whether the Render deployment's network has IPv6 egress to `db.<ref>.supabase.co` is not verifiable from these sources — if not, session pooler (IPv4) is the fallback per Supabase's own decision flow.
8. **Dedicated PgBouncer pooler is paid-tier only**; on free tier the options are direct + shared pooler (Supavisor) — affects the pooling plan if the project stays free.
