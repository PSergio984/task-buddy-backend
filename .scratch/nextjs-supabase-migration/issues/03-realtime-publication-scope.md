# B-03 — Realtime publication scope and payload shape

Type: grilling
Status: resolved
Blocked by: F-02 (frontend: 02-realtime-authorization-facts), F-03 (frontend: 03-realtime-access-control)

## Question

Which tables/entities get Supabase Realtime push (tasks, tags, projects, notifications, …?), what payload shape does the frontend need, and what backend-side work does publishing require (enable publication, RLS implications per F-03, any change-data-capture gaps)?

Grill the user (one question at a time) and resolve with domain-modeling on the entity set. Record the decision under `## Answer`.

## Answer

1. **Published entities:** `tbl_tasks`, `tbl_subtasks`, `tbl_projects`, `tbl_tags`, `tbl_notifications` — the UI-live set, all user-scoped, RLS-gated.
2. **Not published:** audit logs (append-only history page, already excluded from offline persistence; refetch on open), users, push_subscriptions (server-internal).
3. **Payload shape: PK-only + refetch** - default REPLICA IDENTITY: INSERT/UPDATE payloads carry the full new row; UPDATE/DELETE `old_record` carries the PK only (full old values would require REPLICA IDENTITY FULL, which is not used). Subscriber invalidates the affected TanStack Query and refetches. No client-side patching.
4. Backend work implied: add the five tables to the `supabase_realtime` publication (per B-01); per-user `FOR SELECT` RLS policies using `sub` claim vs `user_id` column (Realtime delivery is gated by SELECT policies; INSERT/UPDATE policies remain write-enforcement only).
