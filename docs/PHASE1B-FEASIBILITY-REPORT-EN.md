---
id: A3S-PHASE1B-FEASIBILITY-REPORT-001
title: Alpha3S Phase I-B — Feasibility Analysis Report (Dev)
document_type: architecture_feasibility_report
in_response_to: A3S-PHASE1B-CA-FEASIBILITY-001
responds_to_review: A3S-PHASE1B-CA-REVIEW-001
owner: Alpha3S
author_role: Dev
version: 0.1.1
status: revised_for_ca_reapproval
created_at: 2026-07-24
last_updated: 2026-07-24
language: en
note: English translation of PHASE1B-FEASIBILITY-REPORT-VI.md v0.1.1; keep both in sync.
---

# Alpha3S I-B — Feasibility Analysis Report (v0.1.1)

> Responds to brief `A3S-PHASE1B-CA-FEASIBILITY-001`, revised per CA review `A3S-PHASE1B-CA-REVIEW-001`
> (APPROVE WITH REQUIRED AMENDMENTS). Every claim is backed by real file/function/schema references. See
> the per-amendment response in `PHASE1B-FEASIBILITY-DEV-RESPONSE-VI.md`.

## 0. Changelog v0.1.0 → v0.1.1 (mapped to CA amendments)

| CA | Item | Handled in v0.1.1 |
|---|---|---|
| P0 §4.1 | Wrong state-machine assessment (claimed it forbids skipping) | §3.1 corrected: only blocks backward, does NOT block skip-forward; added M2 transition matrix |
| P0 §4.2 | Production DB not proven | §2 states clearly only the local Docker instance `172.18.0.3` was queried; **production NOT independently verified**; production audit = M0 prerequisite |
| P0 §4.3 | Don't equate outbox with the whole solution | §6 replaced with a 4-problem → 4-capability decomposition table |
| P0 §4.4 | `sent` flag insufficient against double-send | §6.1 adds full outbox failure semantics; goal at-least-once + effective-once |
| P0 §4.5 | Address must be in the I-B Core Release | §9/§10 renamed: Core Stabilization Slice (M0-M3) ≠ I-B Core Release (M0-M6) |
| P1 §5.1 | Administrative data source | §7.1 distinguishes repo (packaging) vs legal texts (authoritative) + dataset acceptance gate |
| P1 §5.2 | Dataset must support as_of + snapshot | §7.2 adds `as_of=now/<date>`; old orders don't change with a new dataset |
| P1 §5.4 | Inventory balance + immutable ledger | §6.3 adds `inventory_balances` + `inventory_movements` |
| P1 §5.5 | Reservation policy baseline | §6.4 adds a reservation lifecycle table |
| P1 §5.6 | Migration runner not locked to Alembic | §8.1 compares 3 options + reverses the recommendation to a lightweight runner |
| P1 §5.7 | M0 security baseline | §5.1 adds the security baseline list |
| P1 §5.8 | Permission-based authz | §5.2 moves from `require_role` to `require_permission`; role = bundle |
| §6 | Fix permission matrix | Appendix A fixes delivery/support/viewer/export + separation of duties |
| §10 | Additional release gates | §11 updates gates per milestone |

---

## 1. Executive summary

**Verdict (unchanged, CA ACCEPTED): I-B is feasible on the current architecture (modular monolith
FastAPI + PostgreSQL + Redis/arq), with NO new service and NO Core rewrite.** Most items are *add a table
+ add a tool + add a screen*, incremental migration.

**Three levers:**

1. **Migration window.** The DB **queried (local Docker)** is almost empty of commercial data (1 order,
   1 product, 0 staff). If this also holds on production (not verified — §2), the heavy schema redesign
   carries near-zero backfill risk if done early. **Precondition: a real production audit at M0 before
   concluding.**
2. **Right infrastructure seeds exist**: dedupe + dead-letter (`app/workers/tasks.py`), approval + `used`
   flag (`price_overrides.py`), transaction + `FOR UPDATE` (`tools.py:189-241`), session-auth replacing
   `ADMIN_API_TOKEN` (`auth_service.py`).
3. **Technical debt already recorded by the team** (`docs/SALES-FLOW-CURRENT-STATE-VI.md`,
   `ISSUES-VI.md:1133`).

**Scope (renamed per CA §4.5):**
- **Core Stabilization Slice = M0-M3** — a stabilization slice, pays off the 4 real incidents (ghost
  order, order lookup, wrong stock, follow-up). **This is NOT the whole I-B Core.**
- **I-B Core Release = M0-M6** — the full I-B Core: + customer identity, multi-location, **address
  verification (current + legacy + staff, PO-locked)**, delivery + payment baseline.
- **Commerce Growth = P2** — promotion/membership/affiliate/returns/reconcile.

---

## 2. §12.1 + P0§4.2 As-built & production evidence (clarified)

Read directly: all services/workers/api/migrations/dashboard/NLU (list as in v0.1.0).

**Schema/data evidence — stated precisely to avoid misreading (fixed per CA §4.2):**

| Item | Reality |
|---|---|
| DB queried | **Internal Docker instance `172.18.0.3`** (via postgres MCP) — the **local dev/compose DB**, NOT the VPS production |
| Host/environment | Local Docker Compose on the dev machine |
| Schema version determined by | Comparing `information_schema.columns` with `migrations/001-012` → matches 012 |
| Row counts | Of **local**: 1 order, 1 order_item, 1 product, 24 customers/conversations, 154 messages, 0 staff_users, 0 price_overrides, 364 kb_units |
| Production VPS (`160.30.157.235`) | **NOT queried directly this round** — not independently verified |
| "pre-cutover" contradiction | v0.1.0 calling the VPS "pre-cutover" was an **inference from CLAUDE.md/memory**, contradicting `docs/PHASE1-COMPLETION-REPORT` (which confirms cutover). **This claim is withdrawn** — cutover status/production volume must be verified at M0 |

```text
Production data volume: not independently verified
```

**Consequence (release condition):** **A production schema/data audit is a mandatory M0 prerequisite.**
Do not use local row counts to conclude that production migration risk ≈ 0. The "migration window"
conclusion is only valid AFTER the production audit confirms comparable volume.

**Other as-built points (unchanged):** `db_pool.py` used by only 3/11 services (connection churn —
standardize at M0); `create_order` has no command-level idempotency key; Telegram runs inline, bypassing
arq.

---

## 3. §12.1 As-built: corrections

### 3.1. Corrected state-machine assessment (CA P0 §4.1 — ACCEPTED, v0.1.0 was WRONG)

v0.1.0 wrote that `validate_transition()` "forbids skipping/reversing steps" — **wrong**. The real code
(`orders.py:21-41`) has only one guard, blocking backward moves:

```python
if _STAGES.index(new) < _STAGES.index(current):   # _STAGES = [new, confirmed, shipped, done]
    raise ValueError(...)
```

So **skip-forward transitions still PASS**: `new→shipped` (0<2), `new→done` (0<3), `confirmed→done`
(1<3). The docstring says "no skipping" but the code does **not** enforce it.

**Corrected statement (into v0.1.1):**

> The state machine currently forbids backward moves and controls some cancel branches (`done→cancelled`
> is blocked), but **does not forbid skip-forward**; validation lives only in the dashboard service
> (`orders.update_order_status`), **not protected at a shared database/domain boundary** (the LLM path
> `create_order` inserts `'new'` directly, never going through this function).

**M2 must have a defined transition matrix + minimal tests (per CA):**

| Transition | Result |
|---|---|
| `new → confirmed` | pass |
| `confirmed → shipped` | pass |
| `shipped → done` | pass |
| `new → shipped` | reject |
| `new → done` | reject |
| `confirmed → done` | reject |
| `done → cancelled` | reject |
| Repeat same transition | idempotent |

### 3.2. Other findings (unchanged from v0.1.0)

Ghost-order guard = string heuristic (`orchestrator.py:38-56,304-330`); only 4 tools, no order-read
tool; cancel doesn't restock (`orders.py:76-86`); identity = `psid` + channel prefix; `staff_users` has
no role column, no audit (`auth_router.py:43`, `ISSUES-VI.md:207`). All **correct** vs brief §2.

---

## 4. §12.2 Feasibility by capability

S≈1-3 dev-days, M≈4-10, L≈2-4 weeks (relative).

| # | Capability | Reuse | New schema | Est | Note |
|---|---|---|---|---|---|
| 6.1 | RBAC + audit + security baseline | auth_service, session | `permissions`, `role_permissions`, `staff_users.role`, `audit_log` | **M** | Permission-based (§5.2), not just role |
| 6.2 | Customer + channel identities | customers | `customer_identities` | **M** | ~24-row migration; risk = merge |
| 6.3 | Store/warehouse/location | — | `locations` + FK | **M** | 1 default seed location |
| 6.4 | Order lifecycle | validate_transition | 2-axis MVP → 4-axis; `order_events` | **M-L** | 2-axis in Stabilization; payment/followup later |
| 6.5 | Deterministic receipt | existing guard | uses outbox | **S-M** | Render template from real tool result |
| 6.6 | Inventory balance + ledger | FOR UPDATE tx | `inventory_balances` + `inventory_movements` | **L** | Balance table + immutable ledger (§6.3) |
| 6.7 | Address verification | strip_diacritics | `admin_units` versioned + snapshot | **L** | **In I-B Core Release (M5)**, not optional |
| 6.8 | Delivery/fulfillment | orders | `shipments`, `delivery_attempts` | **M** | MVP manual entry, no carrier API |
| 6.9 | Follow-up/outbound | dedupe+dead-letter | `outbox_messages`, `followup_jobs` | **M** | arq cron + outbox semantics (§6.1) |
| 6.10-6.14 | Promotion/member/affiliate/payment/returns | products, escalations | many | **L×n** | **Growth P2** (payment_status baseline at M6) |

**No new service/container needed** (CA agrees). Only add 2 cron jobs inside the existing arq process
(`outbox_dispatcher`, `followup_scheduler`) via `cron_jobs` in `WorkerSettings` (`tasks.py:105`).

---

## 5. Target architecture (adds security + permission)

Keeps the brief's §5 boundaries. Inside the App: add `inventory_service`, `address_service`,
`outbox_service`, `audit_service`, `pricing_service` (P2), a `permissions` layer. Principle: every
mutation → service → DB in one transaction → write outbox in the SAME transaction → dispatcher sends +
emits event; **receipt rendered from the tool result, LLM does not self-declare**.

### 5.1. Mandatory M0 security baseline (CA §5.7)

M0 is not just role/permission; must analyze and implement:
- Login throttling (anti-brute-force); password change/reset; **revoke-all-sessions**; session cleanup
  (purge expired tokens from `staff_sessions`).
- **Cannot disable the last admin**; **staff cannot self-escalate privileges**.
- **XSS risk**: bearer token in `localStorage` (`dashboard/lib/api.js`) → assess moving to an httpOnly
  cookie or accept a controlled risk + CSP; **security headers + CSP**.
- Audit: login success/failure, logout, activation, role/permission change.
- **Server-side authorization for EVERY sensitive API** (not just hidden UI buttons).

### 5.2. Permission-based authorization (CA §5.8)

Don't lock into `require_role` alone. Use permission as the smallest unit; a role is a **bundle** of
permissions:

```text
require_permission("inventory.adjust")
require_permission("order.cancel_after_fulfillment")
require_permission("customer.export")
```

Server-side permission check is the primary protection; UI show/hide is only UX. A `permissions` +
`role_permissions` table lets PO edit the mapping without code changes.

---

## 6. Reliability: correct decomposition (CA P0 §4.3) + outbox semantics (§4.4)

**Outbox is NOT the solution to all 4 problems.** Correct decomposition by capability:

| Problem | Primary solving capability |
|---|---|
| Ghost order | Transaction + **deterministic action receipt** |
| Can't look up an order | **Order-read tools + authorization** |
| Wrong stock | **Reservation + inventory balance/ledger** |
| Non-durable follow-up | **Scheduler + outbox + delivery attempts** |

The outbox is a *shared reliable transport* for receipts + follow-up, NOT the domain model of
orders/inventory.

### 6.1. Outbox failure semantics (M1) — the `sent` flag is not enough (CA §4.4)

Failure scenario: *provider received → worker crash → DB not marked sent → retry sends a second time*.
The M1 design must have:
- **Stable `idempotency_key`** (per business event, not time-based).
- **Outbox state machine**: `pending → claimed → sent → confirmed | dead_letter`.
- **Delivery attempt records** (one row per attempt: time, result, provider message id if any).
- **Atomic claim** via `SELECT ... FOR UPDATE SKIP LOCKED` + **lease/lock timeout** (dead worker → job
  reclaimed after timeout).
- **Bounded retry** + **dead-letter** (reuse the `dead_letter:messages` base, `tasks.py:40-52`).
- **Reconciliation** for unknown-outcome requests (provider timeout); **manual replay with audit**.
- **Dedupe at the channel adapter** if the provider doesn't support idempotency.

**No exactly-once delivery commitment.** Goal: **at-least-once transport + effective-once business
behavior** (a business event applies once via `idempotency_key` even if transport sends ≥1 time).

### 6.2. Deterministic receipt (M1)

Replace the `_reply_claims_order_created` heuristic (`orchestrator.py:304-330`) with: tool returns a real
order_id → write business event `order_created` → render receipt via a deterministic template → push to
outbox. **Remove the marker-string guard only AFTER the replacement receipt is proven** (CA §7.1 M1).

### 6.3. Inventory: balance table + immutable ledger (CA §5.4)

Don't compute stock by summing the whole ledger every request; don't keep `products.stock` as source of
truth. Model:

```text
inventory_balances(location_id, product_id, on_hand, reserved, version)   -- version = optimistic lock
inventory_movements(location_id, product_id, movement_type, quantity,
                    reference_type, reference_id, idempotency_key,
                    actor, reason, created_at)                             -- append-only, immutable
```

In the SAME transaction: (1) lock the balance row → (2) validate available = on_hand−reserved → (3)
update balance (bump version) → (4) append movement (immutable) → (5) append business event/outbox
record. `products.stock` is kept only as a **legacy compatibility field within the migration window**,
no longer source of truth after cutover.

### 6.4. Reservation policy baseline (CA §5.5 — for PO to lock)

| Event | Inventory action |
|---|---|
| Draft | No reserve |
| Customer confirms order | **Reserve** |
| Awaiting staff/payment | Default TTL **24h** (configurable) |
| Staff confirm/processing | Extend or drop TTL |
| Fulfillment handover | Reserved → **fulfilled/deducted** |
| Cancel/expire | **Release** |
| Delivery failed/return | → **return inspection**, NOT auto-added to sellable |
| Damaged return | NOT back to available |

**PO locks** the TTL + reserve timing after checking real operations.

---

## 7. §12.2.5-7 Address verification (I-B Core Release, M5)

**As-built: does not exist** (details as v0.1.0: `address` free text `001_init.sql:8,44`; NLU only ~33
hardcoded names `entity_extraction.py:39-46`; reusable `strip_diacritics:49-52`). Offline-first feasible
per the locked fallback, brief §6.7.2.

### 7.1. Data source: repo ≠ authoritative source (CA §5.1)

Distinguish clearly:
- **Open repository (e.g. ThangLeQuoc — MIT)**: a *packaging/ingestion accelerator* — convenient, has a
  PostgreSQL dump, derived from GSO codes. **Do NOT call this "the official state source".**
- **Authoritative source**: legal texts (Resolution 202/2025/QH15, Decision 19/2025/QĐ-TTg) + the GSO
  registry `danhmuchanhchinh.nso.gov.vn`.

License approval **only** confirms the right to use the package, **not** data accuracy. Ingestion must:
pin release/tag/commit hash; store provenance; store `dataset_version`, `effective_from/to`; checksum;
**no auto-activation of a new dataset**; validation + approval before publish; **dataset rollback**.

**Dataset acceptance gate (before activation):**
1. Total unit count matches the authoritative source for the version. 2. Administrative code unique
within the effective range. 3. Every commune/ward has a valid parent province. 4. No overlapping
effective ranges for the same code. 5. Aliases don't override the canonical name. 6. Legacy mapping has
source + confidence. 7. One-to-many mapping is **not auto-selected**. 8. Import has checksum + test
report.

### 7.2. Dataset must be time-aware (CA §5.2)

The address service supports `as_of=now` (current catalog) and `as_of=<date>` (historical lookup/mapping).
**The order stores an address snapshot + dataset version at verification time; a new dataset does NOT
change an old order's address.**

### 7.3. Locked fallback (CA §5.3)

`Current (post-01/07/2025) → Legacy → Customer confirmation → Staff review`. Rules: the LLM does not
auto-select among multiple candidates; if the customer can't confirm the new address → allow confirming
the old one; if legacy is still uncertain → hand off to staff; **carrier/serviceability failure does not
become verified**; **no quote from unverified free text** (`quote_shipping` takes a `verified_address_id`,
not a string).

---

## 8. §12.3 Migration & compatibility

`expand → migrate → contract`, each step independently deployable (details psid→identities /
stock→ledger / status map as v0.1.0 §8, plus the balance table §6.3). Old→new status backfill: keep
`orders.status` in sync for one beat, then cut. Rollback = expand-only in Core → revert code, keep schema.

### 8.1. Migration runner: comparison (CA §5.6 — Alembic NOT locked)

| Option | Pros | Cons |
|---|---|---|
| **Lightweight runner + `schema_migrations`** (run ordered `.sql` files in one transaction, advisory-lock against concurrent runs, checksum) | Matches the existing raw-SQL migrations (`001-012`); **no ORM just to migrate**; few dependencies | Must write status/checksum/lock ourselves (~1 small file) |
| **Alembic + raw-SQL revisions** | Community standard, has status/history; `sqlalchemy` already in `requirements.txt` | Pulls Alembic + ties to SQLAlchemy metadata; heavier than needed; project deliberately avoids ORM |
| **Other PG tool (sqitch/…)** | Good forward-only | Adds a dependency outside the Python stack |

Criteria: lock against concurrent runs ✔, checksum ✔, transaction-per-migration ✔, **forward-only in
production** ✔, status command ✔, staging rehearsal ✔, no mandatory ORM ✔.

**Dev recommendation (REVERSED from v0.1.0):** **Lightweight runner + `schema_migrations`** — because
migrations are already raw-SQL forward-only, the project has a lesson about avoiding added
dependencies/image rebuilds, and the need is only lock+checksum+status. Alembic is an acceptable fallback
if autogenerate is later needed. **PO/CA to lock.**

---

## 9. Core Stabilization Slice (M0-M3) — the stabilization slice

Solves the 4 real incidents. **This is NOT the whole I-B Core** (CA §4.5). Contents per CA §7.1:

- **M0 Foundation:** migration runner (§8.1); standardized DB pool; audit_log; **permission framework +
  minimal RBAC**; **security baseline (§5.1)**; **production schema/data audit (§2)**.
- **M1 Reliable command & receipt:** command idempotency; transactional outbox + semantics (§6.1);
  delivery attempts; deterministic receipt; remove the marker-string guard **after** the replacement is
  proven.
- **M2 Order & inventory correctness:** 2-axis stabilization; **transition matrix (§3.1)**; order event
  timeline; inventory balance; reservation; immutable movement ledger; cancel/expire/release.
- **M3 Customer visibility & follow-up:** authorized order-read tools; shipping status read; confirmation
  reminder; shipping update; **staff-visible outbound queue**.

---

## 10. I-B Core Release (M0-M6) & Growth (CA §7.2-7.3)

- **M4 Identity & multi-location:** canonical customer; channel identities; default-location backfill;
  store/warehouse/fulfillment location.
- **M5 Address Verification:** versioned admin dataset (§7); current verification; legacy mapping;
  customer confirmation; staff review queue; address snapshot; dataset provenance + rollback.
- **M6 Delivery & payment baseline:** fulfillment board; carrier/tracking manual entry; delivery
  attempts/status; **payment status/evidence independent of order/fulfillment**; COD collection record;
  customer notification via outbox.
- **Commerce Growth P2:** price list, promotion/voucher, membership, affiliate/referral,
  returns/complaints, reconciliation, analytics.

**The I-B Core Release is complete only when it has** (CA §4.5): canonical identity + channel identities +
multi-location + current-address verification + legacy fallback + customer confirmation + staff review +
delivery/fulfillment baseline + payment status baseline.

**Critical path:** M0→M1→M2→M3 (Stabilization) then M4→M5→M6. M4/M5 in parallel after M0. M5 blocked by
PO's license + dataset-update-owner decision.

### 10.1. Relative estimate
Stabilization Slice (M0-M3) ~**L** (4-7 weeks); M4-M6 ~**L** (3-5 weeks); Growth P2 each area **M-L**,
separate releases.

---

## 11. §13.10 + CA §10 Test strategy & release gates

Sandbox-first (project convention); staging migration rehearsal; accented/unaccented pairs for address.

**Gates per milestone (CA §10):**
- **M0:** production baseline verified; permission enforced server-side; cannot disable the last admin;
  sensitive actions audited; migration status/checksum/lock working.
- **M1:** no receipt if the business transaction doesn't commit; retry creates no duplicate business
  action; **crash-after-provider-call tested**; dead-letter + replay audited.
- **M2:** illegal transition rejected (matrix §3.1); no oversell in concurrent test; cancel/expire
  releases the right reservation; ledger + balance reconcile to the same result; every movement has a
  reference + idempotency key.
- **M3:** a customer can only read their own orders; no order leaked via ID guessing; follow-up obeys
  channel policy; staff see pending/failed/dead-letter.
- **M5:** dataset validation passes; current→legacy→staff fallback passes; ambiguous mapping not
  auto-selected; no quote from unverified address; dataset rollback tested.
- **M6:** delivery/payment status independent of order status; customer notification bound to real state;
  COD evidence and reconciliation authority separated.

---

## 12. §12.4.4 + CA §9 PO decisions to lock

1. **Role–permission matrix** (Appendix A). 2. Reservation TTL + reserve timing (§6.4). 3. Follow-up use
cases + consent + opt-out. 4. Approval thresholds: large order / special price / address override /
inventory adjustment / refund. 5. **Administrative dataset update owner** + license approval (§7.1).
6. Payment/COD scope in I-B Core. 7. Promotion/member/affiliate rules before Growth. 8. **Production
audit** results (§2) — confirm real volume/cutover.

---

## 13. §12.5 + CA Risk register (updated)

| Risk | P | I | Mitigation | Owner | Gate |
|---|---|---|---|---|---|
| Production volume/cutover differs from the local assumption (unverified) | Med | High | **Production audit is an M0 prerequisite**; don't migrate until verified | Dev/PO | M0 |
| Outbox double-send / lost message on crash | Med | High | idempotency_key + state machine + SKIP LOCKED + reconciliation (§6.1); at-least-once + effective-once | Dev | M1 |
| Skip-forward transition slips through (as-built) | High | Med | Transition matrix + DB/domain guard (§3.1) | Dev | M2 |
| Oversell under concurrency | Med | High | balance row lock + version (§6.3); concurrent test | Dev | M2 |
| Old→new mapping incomplete / one-to-many | Med | High | Mandatory staff fallback; no auto-select; acceptance gate (§7.1) | PO/Dev | M5 |
| RBAC permission leak (UI hidden but API open) | Med | High | require_permission server-side (§5.2); separation of duties | Dev | M0 |
| Bearer token in localStorage (XSS) | Med | Med | Assess httpOnly cookie + CSP (§5.1) | Dev | M0 |
| Connection churn (8 services connect-per-call) | Med | Med | Standardize db_pool at M0 | Dev | M0 |
| Scope creep into ERP/CRM/WMS | High | High | Stick to Deferred brief §11 | PO/Dev | every M |

---

## 14. §10.5 VPS
4 vCPU/8 GB is enough for the no-heavy-process approach (CA agrees); the 2 embedding models remain the
main RAM consumers; outbox/cron are light. **Must measure on staging** + add index/pagination (the
dashboard loads whole lists, `limit=200`).

---

## 15. Implementation Planning conditions (CA §8) — v0.1.1 self-check

1. Fix state-machine ✔ (§3.1). 2. Clarify production evidence ✔ (§2). 3. Fix outbox role ✔ (§6). 4.
Outbox failure semantics ✔ (§6.1). 5. Rename milestones ✔ (§9-10). 6. Address into I-B Core Release ✔
(§10 M5). 7. Dataset provenance/validation/versioning ✔ (§7.1-7.2). 8. Inventory balance + ledger ✔
(§6.3). 9. Migration runner comparison ✔ (§8.1). 10. Security baseline ✔ (§5.1). 11. Permission matrix ✔
(Appendix A). 12. Test strategy + gates ✔ (§11).

---

## Appendix A — Role → permission matrix (fixed per CA §6)

**Why it's a PO/CA decision:** each cell is a money/stock/order risk-control policy, not a technical
choice. Permissions today = 0 (`auth_router.py:43`, `ISSUES-VI.md:207`). It is the backbone of: (1)
server-side enforcement (`require_permission`, §5.2 — NOT just hidden UI); (2) the approval framework §7.3
— a ⚠️ cell = "send to the approval queue"; (3) audit.

**Legend:** ✅ direct · ⚠️ requires approval · ✎ propose-change (no direct edit) · 👁️ view (PII masked) ·
❌ no access.

| Permission group | admin | sales | warehouse | delivery | support | viewer |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| View customer (PII masked by permission) | ✅ | ✅ | 👁️ | 👁️ | ✅ | 👁️ mask |
| Edit customer (name/phone) | ✅ | ✅ | ❌ | ❌ | ✎ | ❌ |
| View/edit delivery address | ✅ | ✅ | 👁️ | 👁️ | ✎ | ❌ |
| Override address | ✅ | ⚠️ | ❌ | ❌ | ⚠️ | ❌ |
| Create/edit order (pre-fulfillment) | ✅ | ✅ | ❌ | ❌ | ✎ | ❌ |
| Cancel order before shipped | ✅ | ✅ | ❌ | ❌ | ⚠️ | ❌ |
| Edit/cancel order **after fulfillment** (create case/approval, no direct edit) | ⚠️ | ⚠️ | ❌ | ❌ | ⚠️ | ❌ |
| Change `order_status` | ✅ | ✅ | ❌ | ❌ | ⚠️ | ❌ |
| Change `fulfillment_status` (pick/pack/ship/deliver) | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ |
| **Record COD collection** (evidence/amount/reference) | ✅ | ❌ | ❌ | ✅ | ✅ | ❌ |
| **Confirm payment reconciliation** | ✅ | ❌ | ❌ | ❌ | ⚠️ | ❌ |
| Manual inventory adjustment (reason+audit) | ✅ | ❌ | ⚠️ | ❌ | ❌ | ❌ |
| Receive goods / transfer | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| Manage price/promotion | ✅ | ⚠️ (special price) | ❌ | ❌ | ❌ | 👁️ |
| Adjust member points | ✅ | ⚠️ | ❌ | ❌ | ⚠️ | ❌ |
| Approve affiliate commission | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Approve refund (reason+audit) | ✅ | ❌ | ❌ | ❌ | ⚠️ (propose) | ❌ |
| Approval inbox — the **approver** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Manage staff & sessions | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Export customer data (admin-only in MVP)** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| View audit log | ✅ | ❌ | ❌ | ❌ | 👁️ | ❌ |

**Separation of duties (CA §6.5):** the approval requester **cannot** self-approve; the last admin
**cannot** be disabled; post-shipment actions create a **case/approval**, not a direct order edit; refund
+ inventory adjustment **require** reason + audit.

**Specific fixes per CA §6:** (6.1) delivery **only records COD evidence**, admin/reconciliation confirms
payment; (6.2) support uses **propose-change (✎)** for name/phone/address/order, no direct edit; (6.3)
viewer **PII masked** by default (phone/address/payment evidence); (6.4) **export = admin-only** in MVP,
with reason/scope/audit.

**Rollout:** MVP enables admin/sales/warehouse + locks the sensitive cells; delivery/support/viewer fill
in at M6/P2. Enforce server-side; every ⚠️/✎ cell writes audit.

---

## Sign-off

```text
Feasibility Report v0.1.1 — Dev sign-off
Author role: Dev (Alpha3S)
Fully addressed CA-REVIEW-001: P0 §4.1-4.5 and P1 §5.1-5.8 + matrix critique §6 + gates §10.
Submitting to CA re-review to grant: APPROVED FOR IMPLEMENTATION PLANNING.
No production migration / business-state change until: v0.1.1 approved, PO locks mandatory
business policy, production baseline verified (§2, §12.8).
Date: 2026-07-24
```

> The `-VI` original is the source of truth; keep both in sync.
