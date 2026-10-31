# Knowledge Ask — Streaming (SSE) Contract

Streaming variant of `POST /api/v1/tasks/{task_id}/knowledge/ask`. The non-stream
endpoint stays untouched (compat, tests, rollback path).

## Motivation

`/ask` runs retrieval → LLM answer → LLM judge → persist serially; the client
waits for everything. Streaming emits answer tokens as the provider produces
them, plus citations up-front (known right after retrieval) and the judge
verdict as a trailing event.

## Endpoint

`POST /api/v1/tasks/{task_id}/knowledge/ask/stream`

- Body: `KnowledgeAskRequest` (`{"query"?: string}`) — same schema as `/ask`
- Auth, ownership-404-before-spend, `RATE_LIMIT_KNOWLEDGE_ASK`, budget
  reservation (`LLM_ASK_RESERVE_TOKENS`): identical to `/ask`
- Rollout flag: `KNOWLEDGE_STREAM_ENABLED` (default on) — same convention as
  `BREAKDOWN_ENABLED`/`VOICE_ENABLED`

## Pre-stream errors (normal HTTP, before any SSE bytes)

Same semantics as `/ask`: `404` TASK_NOT_FOUND, `429` budget/rate limit,
`503` AI_NOT_CONFIGURED.

## SSE events (all `data:` payloads are JSON)

| Order | Event | Payload | Notes |
|---|---|---|---|
| 1 | `citations` | `{"citations": [...]}` | Canonical citations, built from retrieved chunks before generation |
| 2 | `token` | `{"text": "<delta>"}` | 0..N raw model deltas, in order |
| 3 | `verdict` | `{"relevance": "RELEVANT\|PARTLY_RELEVANT\|NON_RELEVANT", "explanation": "..."}` | Judge result; degrades to PARTLY_RELEVANT on judge failure (T-7-12) |
| 4 | `done` | `{answer_id, task_id, model, prompt_tokens, completion_tokens, total_tokens, cost_usd, response_time_ms, usage_reported}` | Terminal success; answer row persisted |
| any | `error` | `{"code": "provider_error", "message": "AI service unavailable"}` | Terminal mid-stream failure; stream then closes |

## Server semantics

- `StreamingResponse`, `media_type="text/event-stream"`; set
  `Cache-Control: no-cache`, `X-Accel-Buffering: no`.
- Same snapshot/rollback discipline as `/ask` (audit #27): snapshot ids before
  any provider call; `db.rollback()` releases the pooled connection before the
  seconds-long stream; reuse the session for citations/persist/reconcile.
- Token usage: request `stream_options={"include_usage": true}`; if the
  provider omits usage, fall back to the reserved amount for reconciliation
  (conservative, never under-bills) and emit `usage_reported: false` in
  `done` so clients can tell unmeasured zeros from measured usage.
- Disconnects: before the provider request is sent the reservation is
  refunded; from then on it is settled at actual usage (or the reserve when
  unreported) — matching `/ask` semantics. `stream_ctx.generation_started` is
  the shared flag for that boundary.
- Mid-stream `openai.APIError` → emit `error` event, refund reservation, close.
- Persist the answer row only after the stream completes (display ≠ stored).
- Judge stays serial after generation (needs full text) — `verdict` is a tail
  event by design.

## Client contract (frontend)

- `fetch` with `credentials: "include"` + `Accept: text/event-stream` —
  cookie auth, same as axios `withCredentials`.
- Parse `event:`/`data:` frames from `response.body.getReader()`.
- Thinking mode: show a thinking indicator from request dispatch until the
  first `token` event arrives.
- `error` event → surface toast, discard partial render state as appropriate.
