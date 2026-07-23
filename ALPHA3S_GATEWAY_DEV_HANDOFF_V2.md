---
id: AGW-IMPL-001
title: Alpha3S Customer Terminal Implementation Plan
document_type: implementation_plan
domain: gateway
owner: Alpha3S
author: CA
version: 2.0.0
status: approved
approved_by: PO
approved_at: 2026-07-22
proposes_to_supersede: AGW-IMPL-001 v1.0.0
depends_on:
  - AGW-ARCH-001 v2.0.0
last_updated: 2026-07-22
---

# Alpha3S Customer Terminal Implementation Plan

## Objective

Rút đường tới giá trị từ platform roadmap thành sáu chặng nhỏ; mỗi chặng phải tạo kết quả vận hành hoặc business nhìn thấy.

## Work Order

```text
A. Core completion
  + B. VPS foundation in parallel
→ C. Thin-terminal reliability
→ D. Messenger parity + Web Customer Terminal
→ E. Zalo OA
→ F. Evidence-driven hardening
```

## Chặng A — Finish Current Core

### A1 — Complete KB V2 integration

- Nối KB V2 vào bot production path.
- Smoke/regression pass.

### A2 — Complete NLU router

- Hoàn tất `ENABLE_NLU_ROUTER` path.
- Vá `_extract_location` và defect normalization còn mở.

### A3 — Measure embedding memory before KB V2 freeze

- Đo RSS thực của embedding process trên môi trường hiện tại với corpus/load đại diện.
- Chọn local small/quantized hoặc hosted embedding API trước khi chốt KB V2.
- Ghi evidence và memory budget; HOST-003 chỉ xác nhận lại quyết định trên VPS đích.

**Exit:** Core baseline ổn định; Gateway không phải debug đồng thời lỗi KB/NLU chưa đóng.

## Chặng B — VPS Foundation

### HOST-001 — Provision approved VPS

**P0 — PO budget approved**

- Linux VPS `2 vCPU / 4 GB RAM / 60 GB SSD`.
- SSH key, firewall, non-root operations account.
- Docker Engine + Compose.
- swap 2–4 GB.

### HOST-002 — Production Compose profile

- Reverse proxy + HTTPS.
- API, worker, Telegram poller, PostgreSQL, Redis, dashboard.
- `restart: always` and healthchecks.
- Resource limits/reservations where useful.
- Production Next.js build.

### HOST-003 — Tune constrained resources

- PostgreSQL pool/connection and memory settings.
- Redis maxmemory/TTL policy.
- One embedding process; revalidate Chặng A RSS/budget on target VPS.
- Decide small/quantized/API embedding if memory gate fails.

### HOST-004 — Backup and restore

- Daily PostgreSQL backup.
- Provision a low-cost VPS/hosting target used only for encrypted off-host backup; deploy no Alpha3S runtime or public service there.
- Keep a fast local rolling copy plus off-host copy via least-privilege SFTP/SSH or compatible object storage.
- Back up database and recovery configuration; encrypt/separate secrets and never store them plaintext.
- Store the backup decryption key and minimum restore secrets independently from the production host in an external password manager/secret store or secure offline copy.
- Verify upload checksum/freshness and alert on missed/stale backup.
- Retention policy.
- Restore drill from the off-host copy while assuming total loss of the production host; recover using only independently held keys/secrets and record RPO/RTO.
- Record single-VPS recovery downtime; obtain PO acknowledgement of measured RPO/RTO before production.

### HOST-005 — Staging smoke and promotion

- Deploy current Alpha3S unchanged first.
- Measure idle/load RAM, CPU, disk and restart behavior.
- Test rollback.

**Exit gate B:** HTTPS, health, encrypted off-host backup, restore from backup-only host, resource baseline and rollback all pass. Backup host runs no Alpha3S workload and is not represented as failover. Chatwoot self-host is not deployed on the production VPS.

## Chặng C — Thin-Terminal Reliability

### TERM-001 — Fix inbound dedupe/retry

- Minimal durable inbound event status.
- Failed processing remains retryable.
- Completed duplicate is no-op.

### TERM-002 — Typed errors

- Distinguish transient, permanent and business error.
- Orchestrator fallback is explicit result, not swallowed infrastructure failure.

### TERM-003 — Idempotent order

- Unique business command key.
- Stock deducted once.
- Retry returns original order.

### TERM-004 — Serial inbound ordering

- Route customer inbound through one durable queue.
- Run one consumer (`max_jobs=1`).
- Measure queue wait/backlog.

### TERM-005 — Delivery errors

- Stop swallowing Telegram/provider send errors.
- Map error to transient/permanent.
- Telegram customer fallback must enter `terminal_inbound_events`; Admin/Operations path may remain separate but must emit structured errors.

### TERM-006 — Database pooling

- Shared pool for hot path.
- Process-specific pool limits suitable for 4 GB VPS.

### TERM-007 — Migration runner

- Track applied migration/checksum.
- Fresh/existing DB parity.

### TERM-008 — Minimal durable outbound

- `terminal_outbound_deliveries`.
- Retry schedule and dead-letter.
- Safe manual replay.

### TERM-009 — Minimal trace and metrics

- `trace_id` end-to-end.
- received/duplicate/processed/failed/retry/dead-letter/queue-wait metrics.

**Exit gate C:** duplicate/retry/order/order-sequence/delivery tests pass on VPS; no lost message in controlled crash tests.

## Chặng D — Messenger + Web Customer Terminal

### CH-001 — Minimal terminal contract

- One normalized text message.
- One minimal outbound response.
- Provider fixture validation.
- Web contract requires stable `client_message_id` UUID v4 per user message; resend/reconnect reuses it and Terminal maps it to `external_event_id`.

### CH-002 — Thin adapter interface

- verify;
- normalize;
- evaluate send policy;
- deliver.

### CH-003 — Messenger parity

- Move existing Messenger path behind terminal.
- Preserve current behavior and dashboard history.
- Echo/duplicate tests.
- Enforce Meta standard 24-hour send window; only explicitly allowed and PO-approved exception use cases may send outside it.

### WEB-001 — Lightweight widget on existing website

- Alpha3S-owned widget source and deployment.
- Anonymous/session identity.
- Text send/receive and reconnect.
- Reuse terminal pipeline.
- Rate limit and abuse protection.
- Persist one `client_message_id` per composed message locally until accepted; reconnect/retry never creates a new ID for the same message.

### WEB-002 — Existing dashboard as staff inbox

- Conversation list/history.
- Staff reply/takeover/resume.
- Preserve `bot_paused` ownership in App.
- Add near-realtime refresh/SSE only when needed.
- Structured log every pause/resume/takeover with actor, conversation, action, timestamp and `trace_id`.

### WEB-003 — Web security and continuity

- Signed/opaque session identifier.
- Origin/CORS/CSRF policy as applicable.
- Message size/rate limits.
- Reconnect and duplicate-send tests.
- Define Web `DELIVERED` as outbound persisted in App message history. SSE/WebSocket push is best-effort; closed/offline tab does not trigger delivery retry/dead-letter and reload/poll recovers history.

**Exit gate D:** Messenger regression and 24-hour policy green; one visitor on the existing website completes an end-to-end Alpha3S conversation; same-ID reconnect cannot duplicate; response remains visible after tab close/reload; staff handoff works; no business source of truth is moved out of App. Review queue wait p95/backlog immediately during Web pilot and open the ordering ADR if trigger is crossed.

## Chặng E — Zalo OA

### CH-004 — Zalo OA discovery/configuration

- OA/OpenAPI credentials and webhook verification.
- Confirm current official send/quota policy during implementation.
- Record source/date and configure numeric limits outside Core; do not assume the 2026-07-22 values are permanent.
- Store last interaction and send eligibility metadata.

### CH-005 — Zalo reactive text flow

- inbound customer text;
- Core response;
- outbound reply;
- error mapping and dead-letter.

### CH-006 — Zalo cost/window policy

- distinguish 48-hour free allowance from 7-day eligibility;
- `window_expired` permanent after eligibility;
- allow billable send only within PO-configured billing period and budget;
- atomically reserve estimated cost idempotently by `terminal_outbound_deliveries.idempotency_key`, so retry of the same delivery never reserves or charges twice;
- record billable count, unit price, estimated cost and `trace_id`;
- configurable alerts, baseline `50% / 80% / 100%`;
- hard stop billable send at cap while eligible free sends continue;
- audit every budget/override change.

**Exit gate E:** Zalo customer can complete reactive consultation; retry never sends outside approved window or exceed the atomically enforced budget; cap test proves billable hard stop while eligible free sends continue; budget alerts/audit/reconciliation work; Messenger and Web regression remain green.

## Chặng F — Evidence-Driven Hardening

Open only when trigger occurs:

- multi-worker lease when queue SLO fails;
- richer identity when cross-channel merge is required;
- tenant when second brand is approved;
- richer handoff states when staff workflow demands them;
- separate Gateway service when SLA/security/resource ownership differs;
- larger VPS when measured resource threshold is exceeded.

## QA Matrix

| Scenario | C | D Messenger | D Web | E Zalo |
|---|---:|---:|---:|---:|
| Duplicate inbound | Required | Required | Required | Required |
| Failure then retry | Required | Required | Required | Required |
| Order idempotency | Required | Required | Required | Required |
| Message ordering | Required | Required | Required | Required |
| Outbound retry/dead-letter | Required | Required | Required | Required |
| Send-window/cost policy | — | Required | N/A | Required |
| Billable budget reservation/cap | — | N/A | N/A | Required |
| Billable retry does not double-reserve | — | N/A | N/A | Required |
| Stable client message ID on reconnect | — | — | Required | — |
| Persisted history after tab close | — | — | Required | — |
| Handoff AI silence | Required | Required | Required | Required |
| Restart recovery | Required | Required | Required | Required |

## Stop/Go Rules

STOP when:

- VPS backup/restore is not proven;
- memory baseline exceeds safe budget;
- message/order can duplicate;
- Zalo cost/window rule, billing period or budget cap is not configured;
- Chatwoot self-host is proposed on approved 4 GB VPS;
- terminal begins owning business/customer/conversation state.
- PO has not acknowledged the single-VPS SPOF and measured recovery RPO/RTO before production promotion.

GO when the current chặng exit gate passes; later platform work does not block earlier value.

## Approval Record

| Item | Status | Actor | Date |
|---|---|---|---|
| Hosting budget | approved | PO | 2026-07-22 |
| Backup-only host strategy | approved | PO | 2026-07-22 |
| Zalo monitored billable budget | approved | PO | 2026-07-22 |
| AGW-REVIEW-002 findings | incorporated | CA | 2026-07-22 |
| Dev re-review/sign-off | approved | Dev | 2026-07-22 |
| Revised implementation v2.0.0 | approved | PO | 2026-07-22 |

## Dev Review Disposition

| Finding | Disposition | Implementation evidence |
|---|---|---|
| REV2-01 Web inbound idempotency | Accepted / REQUIRED | CH-001, WEB-001, WEB-003 and QA reconnect test |
| REV2-02 Web delivery semantics | Accepted / REQUIRED | WEB-003 and Exit gate D |
| REV2-03 embedding RSS timing | Accepted / REQUIRED | A3 before KB V2 freeze; HOST-003 revalidation |
| REV2-04 Messenger 24-hour window | Accepted / REQUIRED | CH-003 and provider-window QA |
| REV2-05 single-VPS SPOF | Accepted / REQUIRED | HOST-004, Stop/Go and PO acknowledgement |
| REV2-06 Zalo numeric rules | Closed | 48h/7-day policy remains configurable; “8 free messages” is unconfirmed and must not be assumed before CH-004 |
| REV2-07 serial-worker latency | Accepted / advisory | Immediate Web-pilot metrics and ADR trigger |
| REV2-08 Telegram durability | Accepted / advisory | TERM-005 |
| REV2-09 handoff auditability | Accepted / advisory | WEB-002 structured logs |
| REV2-10 diagram queue flow | Accepted / advisory | Architecture §2.1 now shows API persist and worker DB claim |
| REV2-11 independent backup key | Accepted / advisory | HOST-004 requires keys/secrets outside production and total-loss restore drill |
| REV2-12 idempotent Zalo budget | Accepted / advisory | CH-006 and QA bind reservation to outbound delivery idempotency key |
