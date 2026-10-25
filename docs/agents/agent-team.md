# Agent team — how AI agents work on this repo

This repo is developed with multiple cooperating AI agents under the
"agent-team" workflow from the AI Dev Tools Zoomcamp. Each agent has a bounded
role; all agent output goes through the same review loop as human code.

## Roles

| Agent | Entry point | Scope |
|---|---|---|
| Implementer | This session / task prompts | Write code to spec; smallest complete change; run local gates |
| Spec/standards reviewer | `code-review` skill | Does the diff follow repo conventions and the issue spec? |
| Correctness reviewer | `ponytail` (lazy-senior-dev) | Edge cases, scope creep, dead code, "is this the smallest diff that works?" |
| Domain reviewer | lens skill per area (e.g. `vercel-react-native-skills`, `postgresql-optimization`) | Framework-idiom correctness the generalists miss |
| CodeRabbit | `.agents/skills/rabbit-code-review` | External AI review on the fix delta |
| On-call responder | `incident-response/` + `on-call-responder` skill | Alert → evidence packet → bounded diagnosis → one allowlisted action or escalate |
| Build cop | rotating | When CI is red, fix or revert — don't wait for the author |

## The loop (applied to every non-trivial change)

1. Implement → 2. run local gates (ruff/pytest here; lint+format+tsc+test+build
on the frontend; tsc+lint+prettier+jest+export on mobile) → 3. independent
review (≥ spec + correctness + domain lens + CodeRabbit) → 4. verify each
finding concretely before fixing → 5. fix → 6. re-review the delta only →
7. push → 8. remote CI green → 9. standing gates (SonarCloud, CodeRabbit, CI)
before "done".

Findings are kept attributed per reviewer; rejected findings are recorded with
the reason. Cap: 3 fix rounds.

## Standing gates (from AGENTS.md)

SonarCloud scan + CodeRabbit + GitHub Actions (`python-app.yml`,
`sonar-secrets.yml`, `sonarcloud.yml`) must all pass or be recorded as blockers
before any commit/PR/finished-branch is declared done.

## On-call responder boundary

`incident-response/alert-bridge.mjs` receives Grafana webhook alerts, builds an
evidence packet (`collect-evidence.sh` → container logs, `docker ps`, Prometheus
queries, `/health`), and invokes a headless agent (`ONCALL_AGENT_CMD`). The
policy gate in `autonomy-policy.yaml` enforces the hard rule: **the model
proposes, code enforces** — at most one allowlisted action is executed, then
post-action verification; anything else writes `escalation.md`. Every run leaves
a full audit record under `incident-response/incidents/<id>/`. `ONCALL_DRY_RUN=1`
disables execution entirely (default in compose).

## Issue tracker

All work is filed as GitHub Issues (`gh` CLI) — see
`docs/agents/issue-tracker.md`; triage uses the five canonical labels in
`docs/agents/triage-labels.md`.
