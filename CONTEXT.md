# Task Buddy Backend

Task Buddy's backend domain: a personal task-management service with LLM-assisted planning, notifications, and per-user resource budgets.

## Language

### Transactional email

**Email class**:
One of the three kinds of transactional email the service sends: verification, password reset, and password-changed notification. Classes differ in what recovery looks like when delivery fails.
_Avoid_: email type, notification kind

**Delivery chain**:
A single send event's fixed sequence of independent transport attempts: primary API provider first, then direct SMTP fallback.
_Avoid_: retry, failover

**Best-effort delivery**:
The delivery contract for every email class: each send event passes once through the delivery chain; if every channel fails, the email is lost and recovery is user-initiated (re-request or resend).
_Avoid_: fire-and-forget, guaranteed delivery

**Recovery path**:
A user-facing action that re-triggers a lost email: resending verification, re-requesting a password reset.
_Avoid_: retry (reserved for automated re-attempts)

### LLM budget

**Daily token budget**:
The per-user cap on total LLM tokens consumed in one UTC day, shared by every feature that calls an LLM.
_Avoid_: quota (vague), spend limit

**Reservation**:
A pre-call hold of estimated tokens against the daily token budget; a request without a reservation never reaches the provider.
_Avoid_: pre-check, quota check

**Reconciliation**:
The post-call adjustment of a reservation from its estimate to the provider-reported actual.
_Avoid_: settle

**Refund**:
Release of a full reservation back to the budget when the LLM call fails before returning usage.
_Avoid_: rollback
