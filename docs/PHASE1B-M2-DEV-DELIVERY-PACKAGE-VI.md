---
id: A3S-PHASE1B-M2-DEV-DELIVERY-PACKAGE
milestone: M2
title: M2 Delivery Package — Order and Inventory Correctness (Submission 3, Final Closure)
governing_directive: A3S-PHASE1B-M2-DEV-DIRECTIVE-001 v1.0.0
responds_to: A3S-PHASE1B-M2-CA-CONSOLIDATED-REVIEW-SUBMISSION-2 (CHANGES_REQUIRED)
release_candidate_sha: 9b49628a83ba1fe02b97913f20f33e4883560b5b
branch: feat/phase1b-m2-order-inventory-correctness
language: vi-VN
---

# M2 Delivery Package — Submission 3 (Final Closure)

> Trả lời CA Consolidated Review Submission 2. **RC SHA (full 40-char):**
> `9b49628a83ba1fe02b97913f20f33e4883560b5b`. Code + evidence tại RC này; package + evidence-log commit
> trên đầu là **docs-only** (chứng minh delta §2). Flags M2 mặc định **TẮT**. Backorder đã tách khỏi M2.

## 1. Disposition — CA Submission 2 (S2-F01…F05)

| Finding | Sev | Xử lý | Commit / file |
|---|---|---|---|
| **S2-F01** balance-authority ghi legacy stock stale | P0 | **Phase C mirror contract**: thay MỌI delta `products.stock` (create/cancel/expire/fulfill/adjustment) bằng **materialize** `stock := balance.available` (`inv_repo.materialize_stock_mirror`, default loc) — không delta stale, heal split-brain, không âm. Migration `028` CHECK `stock>=0`. Áp dụng nhất quán mọi write path. | `1591c91` · `repository.py`, `order_service.py`, `transition_service.py`, `lifecycle.py`, `028_*.sql` |
| **S2-F02** command service bypass RBAC | P0🔒 | `_enforce()` authorization **fail-closed tại `execute_lifecycle` (shared command boundary)** — permission từ transition matrix/registry + adjustment perms; `system` actor bypass; HTTP `_check_perm` giữ defense-in-depth. | `1591c91` · `lifecycle.py` |
| **S2-F03** exact-RC evidence chưa khóa/verifiable | P1 | Full 40-char RC SHA; git-diff proof RC→head chỉ docs (§2); **evidence log** command + exit code + kết quả tại exact SHA (`docs/PHASE1B-M2-EVIDENCE-LOG-VI.md`, 16/16 EXIT=0); command đầy đủ (không `…`). | package + evidence log (docs) |
| **S2-F04** runbook lệch migration/evidence | P1 | Runbook §2 migrations **021–028**, §5 alert negative-stock/drift, §9 rewrite (mirror contract, command-boundary RBAC, authority/mutation-perm/customer-notify), §9 evidence remediation. | `9b49628` · `PHASE1B-M2-RUNBOOK-VI.md` |
| **S2-F05** existing-apply rehearsal chưa đủ đại diện | P1 | Rehearsal thêm: roles/grants (least-priv), indexes/constraints/triggers, migration checksums, **backfill + reconcile trên existing data**, invariants; caveat production=M0 (M1 chưa deploy → không tồn tại M1-prod DB; production access full-dump vẫn gated). | `9b49628` · `m2_existing_apply_rehearsal.py` |

### Carry-forward — CA Submission 1 (đã đóng ở S2 + S3)
| S1 finding | Trạng thái |
|---|---|
| F01 backorder scope | **Closed** — tách khỏi M2 |
| F02 adjustment dual-write | **Closed** — nay là mirror contract nhất quán (S2-F01) |
| F03 mutation dùng read perm | **Closed** — API (S1) + command boundary (S2-F02) |
| F04 immutable RC | **Closed** — S2-F03 (full SHA + diff proof + evidence log) |
| F05 balance authority | **Closed** — read path (S1) + mirror/no-split-brain (S2-F01) |
| F06 customer notify | **Closed** |
| F07 existing-apply | **Closed** — S2-F05 (deep rehearsal) |
| F08 FIFO | Moot (backorder tách) |

## 2. Release-candidate + docs-only proof
```
RC SHA (full) : 9b49628a83ba1fe02b97913f20f33e4883560b5b
branch : feat/phase1b-m2-order-inventory-correctness (off d7ccc4f; M1 46e1169 ancestor)
migrations : 021 inventory_core · 022 order_events · 023 adjustment_rbac · 024 runtime_db_role
             · 025 order_status_expand · 026 order_mutation_rbac · 027 order_origin_channel
             · 028 products_stock_nonneg
Proof code/evidence không drift sau RC (CA S2-F03):
   git diff --stat 9b49628a83ba1fe02b97913f20f33e4883560b5b..HEAD
   -> CHỈ docs/ (PHASE1B-M2-DEV-DELIVERY-PACKAGE-VI.md, PHASE1B-M2-EVIDENCE-LOG-VI.md).
```

## 3. Evidence — exact-SHA, command + exit code
Chi tiết capture: **`docs/PHASE1B-M2-EVIDENCE-LOG-VI.md`** (mọi command + `EXIT=0`, chạy tại RC `9b49628`).
Tổng hợp: **16/16 EXIT=0**.

| Nhóm | Test | AC / Finding |
|---|---|---|
| Units | `pytest -q` → **81 passed** | M0/M1 regression |
| M1 | `command_order_service_test` (T1–T10) + `command_http_test` (fresh m1_itest 001..028) | M1 không regress |
| Schema/role | `m2_db_role_test` (migrations 001..028 fresh) | AC-M2-14 |
| Backfill | `m2_backfill_test` + `m2_backfill_prod_dryrun` (checksum `deece47…`) | AC-M2-12 |
| Domain | `m2_inventory_domain_test` | AC-M2-04/05/06/07/10 |
| Transitions | `m2_transitions_test` | AC-M2-01/02/03 |
| Lifecycle | `m2_lifecycle_test` | AC-M2-01/02/06/07/11 |
| Worker/API | `m2_worker_api_test` | AC-M2-06 + API |
| **RBAC** | `m2_rbac_test` (viewer→403 mọi mutation; **direct execute_lifecycle→forbidden no-mutation**) | S1-F03 + **S2-F02** |
| **Adjustment** | `m2_adjustment_compat_test` | S1-F02 |
| **Authority+Mirror** | `m2_balance_authority_test` (stock==available, **no negative**, reconcile — 2 hướng split-brain) | S1-F05 + **S2-F01** |
| **Customer notify** | `m2_customer_notify_test` | S1-F06 |
| **Existing-apply** | `m2_existing_apply_rehearsal` (grants/indexes/constraints/checksums + backfill+reconcile) | AC-M2-16 + **S2-F05** |

## 4. Contract Phase C (mirror) — tóm tắt (chi tiết runbook §9.1)
`products.stock` là **mirror** của `balance.available` (default loc): mọi inventory write materialize
`stock := on_hand - reserved`. → `stock == available` luôn đúng, `stock ≥ 0` (invariant + CHECK 028),
split-brain tự heal. Reconciliation sau mỗi op = `ok`. Legacy direct writers (dashboard product edit) là
đường ngoài command — Phase C sẽ chặn bằng permission/trigger tại cutover (ghi rõ, ngoài scope M2 core).

## 5. Security / rollback / monitoring
- RBAC 2 tầng (HTTP + command boundary), mutation perms tách read, SoD + Unit Head, DB-role least-priv,
  audit fail-closed, Idempotency-Key, không PII.
- Mirror + CHECK 028 → không stock âm; reconcile endpoint `ok:false` hoặc `stock!=available` → P1.
- Rollback: flags OFF → hành vi trước; ledger/events append-only; mirror idempotent.

## 6. Open decisions (PO/CA)
1. Backorder: tách khỏi M2 (PO 27/7) — change/milestone riêng, spec+AC đầy đủ.
2. Production snapshot artifact: read-only, PO-approved, PII-free, checksum `deece47…`; vị trí verify-able
   cung cấp theo yêu cầu CA. Full production dump / DB-role cutover vẫn cần production-access gate riêng.

## 7. Submission Index
| File | Trong RC |
|---|---|
| `docs/PHASE1B-M2-DEV-DELIVERY-PACKAGE-VI.md` (file này) + `PHASE1B-M2-EVIDENCE-LOG-VI.md` | docs-only trên 9b49628 |
| `docs/PHASE1B-M2-RUNBOOK-VI.md`, `PHASE1B-M2-SLICE0-BASELINE-AUDIT-VI.md` | 9b49628 |
| `migrations/021…028*.sql` | 9b49628 |
| `app/services/inventory/*`, `app/services/order/*`, `app/services/command/{lifecycle,order_service,registry}.py` | 9b49628 |
| `app/api/inventory.py`, `app/config.py`, `app/main.py`, `app/workers/tasks.py` | 9b49628 |
| `scripts/m2_*` (13 evidence scripts) | 9b49628 |

## Self-check checklist (Protocol §4)
- [x] S2-F01…F05 disposition đầy đủ (commit/file); S1 findings closed.
- [x] **Full 40-char RC SHA** `9b49628a83ba1fe02b97913f20f33e4883560b5b`; git-diff proof docs-only.
- [x] Evidence log exact-SHA: command + **EXIT=0** (16/16), không `…`.
- [x] Runbook đồng bộ migrations 021–028 + Phase C mirror contract + alerts.
- [x] Mirror contract nhất quán mọi write path; stock≥0 (CHECK 028); reconcile OK.
- [x] RBAC enforce tại shared command boundary + negative direct-call test.
- [x] Không secret/PII trong tài liệu; quyết định PO/CA tách rõ.
