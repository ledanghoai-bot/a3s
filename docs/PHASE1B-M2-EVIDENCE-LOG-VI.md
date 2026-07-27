---
id: A3S-PHASE1B-M2-EVIDENCE-LOG
milestone: M2
title: M2 Evidence Log (Submission 3) — exact-SHA run capture
rc_sha: 9b49628a83ba1fe02b97913f20f33e4883560b5b
language: vi-VN
---

# M2 Evidence Log — chạy tại RC `9b49628a83ba1fe02b97913f20f33e4883560b5b`

> Capture command + exit code cho MỌI test tại exact RC SHA (CA M2-S2-F03). Env: Docker Compose,
> container `alpha3s-api-1`, Postgres 16 + pgvector; DB throwaway migrate 001..028 fresh (hoặc DATABASE_URL
> chỉ định). Tất cả **EXIT=0**. Không PII/secret trong log.

```text
m1_itest fresh 001..028

== PART A (self-contained + pytest) @ RC 9b49628 ==
### pytest (M0/M1 units)
$ docker exec alpha3s-api-1 python -m pytest -q
81 passed in 29.54s
EXIT=0

### m2_db_role_test (AC-M2-14 + migrations 001..028 fresh)
$ docker exec alpha3s-api-1 python scripts/m2_db_role_test.py
RESULT: PASS — migration chain 001..024 + AC-M2-14 least-privilege proven
EXIT=0

### m2_backfill_test (AC-M2-12)
$ docker exec alpha3s-api-1 python scripts/m2_backfill_test.py
RESULT: PASS — backfill reconstruct + reconcile + idempotent + abort-on-anomaly proven
EXIT=0

### m2_inventory_domain_test (AC-M2-04/05/06/07/10)
$ docker exec alpha3s-api-1 python scripts/m2_inventory_domain_test.py
RESULT: PASS — inventory domain invariants/idempotency/lock-ordering/reconcile proven
EXIT=0

### m2_existing_apply_rehearsal (AC-M2-16 + S2-F05)
$ docker exec alpha3s-api-1 python scripts/m2_existing_apply_rehearsal.py
RESULT: PASS — existing-apply 020->RC an toan; du lieu hien huu bao toan; no PII in output
EXIT=0

== PART B1 (pool-based) @ RC 9b49628 ==
### m2_transitions_test (AC-M2-01/02/03)
$ docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m2s4_itest -e PYTHONPATH=/srv -w /srv alpha3s-api-1 python scripts/m2_transitions_test.py
RESULT: PASS — transition matrix/guard/events + order.create reservation + lifecycle + compat proven
EXIT=0

### m2_lifecycle_test (AC-M2-01/02/06/07/11 + effective-once)
$ docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m2s5_itest -e PYTHONPATH=/srv -w /srv alpha3s-api-1 python scripts/m2_lifecycle_test.py
RESULT: PASS — lifecycle commands effective-once + SoD/unit-head/stale/expire proven
EXIT=0

### m2_worker_api_test (AC-M2-06 + API RBAC/flag)
$ docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m2s6_itest -e PYTHONPATH=/srv -w /srv alpha3s-api-1 python scripts/m2_worker_api_test.py
RESULT: PASS — expiry worker + HTTP API (RBAC/flag/idempotency/domain-reject) proven
EXIT=0

### m2_rbac_test (S1-F03 + S2-F02 direct-call)
$ docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m2rbac_itest -e PYTHONPATH=/srv -w /srv alpha3s-api-1 python scripts/m2_rbac_test.py
RESULT: PASS — read-only KHONG mutate duoc (F03); mutation perms tach khoi .view
EXIT=0

== PART B2 (pool-based + M1) @ RC 9b49628 ==
### m2_adjustment_compat_test (S1-F02)
$ docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m2adj_itest -e PYTHONPATH=/srv -w /srv alpha3s-api-1 python scripts/m2_adjustment_compat_test.py
RESULT: PASS — adjustment dual-write compat: products.stock==available giu qua small/large/decrease/reject/retry
EXIT=0

### m2_balance_authority_test (S1-F05 + S2-F01 mirror)
$ docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m2ba_itest -e PYTHONPATH=/srv -w /srv alpha3s-api-1 python scripts/m2_balance_authority_test.py
RESULT: PASS — balance-authority (F05) + Phase C mirror contract (F01): stock==available, no negative, reconcile OK
EXIT=0

### m2_customer_notify_test (S1-F06)
$ docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m2cn_itest -e PYTHONPATH=/srv -w /srv alpha3s-api-1 python scripts/m2_customer_notify_test.py
RESULT: PASS — customer transition notification deterministic + durable + dedupe + kenh-aware
EXIT=0

### m2_backfill_prod_dryrun (AC-M2-12 prod snapshot)
$ docker exec alpha3s-api-1 python scripts/m2_backfill_prod_dryrun.py | grep checksum
  "checksum": "deece47fbfbdeab6e071931333c68275382be5d53ba9137827a0004f3f27303e",
EXIT=0

== PART C (M1 regression, fresh m1_itest 001..028) @ RC 9b49628 ==
### command_order_service_test (M1 T1-T10)
$ docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m1_itest -e PYTHONPATH=/srv -w /srv alpha3s-api-1 python scripts/command_order_service_test.py
COMMAND-ORDER-SERVICE PASS: T1 atomicity+redaction; T2 dup same-payload; T3 409 conflict; T4 insufficient_stock; T5 product_not_found; T6 qty-limit; T7 20-conc=1 order no-oversell; T8 mixed-key 10 success/10 conflict no-oversell; T9 new-customer race=2 orders/1 customer (FINDING 1); T10 override single-use no double-spend (FINDING 2)
EXIT=0

### command_http_test (M1 HTTP)
$ docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m1_itest -e PYTHONPATH=/srv -w /srv alpha3s-api-1 python scripts/command_http_test.py
COMMAND-HTTP PASS: 400 no-key / 201 first / 200 dup / 409 conflict / 422 stock+phone / 202 in_progress+Retry-After / receipt lookup 200+404.
EXIT=0

```
