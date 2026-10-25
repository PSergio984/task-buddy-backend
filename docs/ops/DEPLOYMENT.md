# Deployment & rollback

## Topology

| Surface | Platform | Source of truth | Deploy trigger |
|---|---|---|---|
| Backend API | Render (`task-buddy-backend-wy3w`) | `render.yaml` in this repo | git push to `main` (auto) or deploy hook |
| Frontend | Vercel (`task-buddy-frontend.vercel.app`) | `task-buddy-frontend` repo | git push to `main` (auto) |
| DB | Supabase Postgres + pgvector | Alembic migrations | `alembic upgrade head` (runs in `start.sh`) |

## Production gate

`.github/workflows/deploy-production.yml` — `workflow_dispatch` only, bound to
the GitHub `production` **environment**. Configure the environment with
*Required reviewers* (Repo → Settings → Environments → production) so every
deploy pauses for human approval.

The workflow: records intent → pre-deploy health check → fires
`secrets.RENDER_DEPLOY_HOOK` → post-deploy health check with retries. If the
secret is unset it records intent only (safe no-op).

Required secret: `RENDER_DEPLOY_HOOK` — Render dashboard → service → Settings →
Deploy Hook.

Auto-deploy on push to `main` stays enabled on Render for the common case; the
gate exists for deliberate/sensitive releases and documents the deploy path.

## Rollback

**Backend (Render):**
1. Render dashboard → `task-buddy-backend` → Events/Deploys → pick the last
   known-good deploy → **Rollback deploy** (re-deploys that image — fastest path).
2. Or revert on git: `git revert <sha> && git push` — CI runs, Render
   auto-deploys the revert.
3. Verify: `curl https://task-buddy-backend-wy3w.onrender.com/health` →
   `{"status":"ok"}`; watch Grafana 5xx panel for 10 min.

**Database migrations:** all migrations must be backward-compatible (expand-only;
see `docs/adr/`). If a bad migration shipped, roll the app back FIRST (old code
still works on the new schema), then repair the schema in a follow-up migration —
never downgrade in place.

**Frontend (Vercel):** dashboard → Deployments → `⋯` on last good → *Promote to
Production* (instant, no rebuild). Or `git revert` + push.

**Alerting during rollback:** the on-call alert-bridge stays up if you run the
local stack; Render-side alerts route through Grafana Cloud if configured, else
watch the Render logs + `/health` until stable.

## Smoke checklist after any deploy/rollback

- [ ] `GET /health` → 200 `{"status":"ok"}`
- [ ] `GET /docs` renders
- [ ] Register/login round-trip (`POST /api/v1/users/register`)
- [ ] Task create → appears in `GET /api/v1/tasks`
- [ ] Frontend loads, proxies `/api/*` (no console CORS errors)
