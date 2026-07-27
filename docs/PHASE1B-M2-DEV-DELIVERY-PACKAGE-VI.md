---
id: A3S-PHASE1B-M2-DEV-DELIVERY-PACKAGE
milestone: M2
title: M2 Delivery Package — Order and Inventory Correctness (Submission 2)
governing_directive: A3S-PHASE1B-M2-DEV-DIRECTIVE-001 v1.0.0
responds_to: A3S-PHASE1B-M2-CA-CONSOLIDATED-REVIEW-SUBMISSION-1 (CHANGES_REQUIRED)
implementation_evidence_sha: 797682b9  # code + evidence; package/runbook trên đầu là docs-only
branch: feat/phase1b-m2-order-inventory-correctness
language: vi-VN
---

# M2 Delivery Package — Submission 2 (Remediation)

> Trả lời CA Consolidated Review Submission 1. **Code + evidence** ghim tại SHA `797682b` (commit cuối
> chứa toàn bộ code/test). Package + runbook trên đầu là **docs-only** (implementation không đổi) → PR
> head sau commit này = docs delta. Flags M2 mặc định **TẮT**.

## 1. Disposition — CA findings F01…F08

| Finding | Sev | Xử lý | Commit / file |
|---|---|---|---|
| **F01** backorder scope-change | P0 | **Đã loại toàn bộ** backorder khỏi M2 RC (migration 026-backorder, code, test, PO-doc, weavings). Backorder sẽ làm milestone/change-gate riêng với spec+AC đầy đủ. | `f9d86d2` (revert) |
| **F02** adjustment phá dual-write | P0 | Adjustment (small + large-approve) **dual-write `products.stock`** ở default location khi legacy stock còn authority → giữ `products.stock == available`. Reject không đổi; retry idempotent; non-default loc không dual-write. | `587b34e` · `lifecycle.py _compat_stock_dualwrite` |
| **F03** mutation dùng quyền read | P0🔒 | Quyền WRITE riêng `order.complete` / `order.delivery.manage` / `order.return.manage` (migration `026`, **KHÔNG cấp viewer**); complete/mark_delivery_failed/request_return/return_inspect bỏ `order.transition.view`. | `386b884` · `026_order_mutation_rbac.sql`, `transitions.py`, `api/inventory.py` |
| **F04** RC SHA không khóa | P1 | Package này ghim **một** implementation/evidence SHA `797682b`, migration manifest 021–027, evidence chạy lại đúng SHA (§3). | package này |
| **F05** AC-M2-13 balance-authority | P1 | Wire `order.create` đọc availability **từ balance** khi `m2_balance_authority` ON (Phase C), legacy khi OFF; chống split-brain (một nguồn); reserve FOR UPDATE là guard cuối. | `e7c6484` · `order_service.py` |
| **F06** AC-M2-15 customer notify | P1 | `apply_transition` emit customer outbox **deterministic** (confirmed/fulfilled/cancelled/completed) qua kênh gốc (migration `027` `orders.origin_channel`), dedupe + retry/dead-letter M1, không LLM. | `a4f0501` · `027_order_origin_channel.sql`, `transition_service.py` |
| **F07** AC-M2-16 existing-apply | P1 | Rehearsal apply 021→027 trên DB **đã tồn tại ở mốc 020** + dữ liệu đại diện; checksum PRE/POST identical, no PII. | `797682b` · `m2_existing_apply_rehearsal.py` |
| **F08** "FIFO" không FIFO | P1 | **Moot** — thuộc backorder đã loại (F01). Khi làm backorder riêng sẽ chốt policy FIFO + fairness test. | (removed) |

## 2. Release-candidate
```
implementation/evidence SHA : 797682b9  (code + toàn bộ test)
branch : feat/phase1b-m2-order-inventory-correctness (off d7ccc4f; M1 46e1169 là ancestor)
migrations : 021 inventory_core · 022 order_events · 023 adjustment_rbac · 024 runtime_db_role
             · 025 order_status_expand · 026 order_mutation_rbac · 027 order_origin_channel
git : clean. Backorder (026-backorder cũ) đã revert khỏi RC.
```

## 3. Evidence — chạy lại tại SHA 797682b (exit 0 = PASS)

| Script | Lệnh | Bao phủ |
|---|---|---|
| pytest | `docker exec alpha3s-api-1 python -m pytest -q` | **81 passed** (M0/M1 units, regression) |
| M1 order_service | `… DATABASE_URL=…m1_itest … command_order_service_test.py` | **PASS** T1–T10 (fresh 001..027) |
| M1 http | `… m1_itest … command_http_test.py` | **PASS** |
| `m2_db_role_test.py` | `docker exec alpha3s-api-1 python scripts/m2_db_role_test.py` | AC-M2-14 + migration fresh 001..027 |
| `m2_backfill_test.py` + `m2_backfill_prod_dryrun.py` | `docker exec … scripts/…` | AC-M2-12 (prod dry-run checksum `deece47…`) |
| `m2_inventory_domain_test.py` | idem | AC-M2-04/05/06/07/10 (incl concurrency) |
| `m2_transitions_test.py` | `…m2s4_itest…` | AC-M2-01/02/03 |
| `m2_lifecycle_test.py` | `…m2s5_itest…` | AC-M2-01/02/06/07/11 |
| `m2_worker_api_test.py` | `…m2s6_itest…` | AC-M2-06 + API RBAC/flag/idempotency |
| **`m2_rbac_test.py`** (F03) | `…m2rbac_itest…` | viewer→403 cho 8 mutation + 2 adjustment; admin pass |
| **`m2_adjustment_compat_test.py`** (F02) | `…m2adj_itest…` | reconcile `stock==available` sau small/large/decrease/reject/retry; non-default loc |
| **`m2_balance_authority_test.py`** (F05) | `…m2ba_itest…` | AC-M2-13 authority switch, chống split-brain |
| **`m2_customer_notify_test.py`** (F06) | `…m2cn_itest…` | AC-M2-15 deterministic + durable + dedupe + kênh-aware |
| **`m2_existing_apply_rehearsal.py`** (F07) | `docker exec … scripts/…` | AC-M2-16 existing-apply 020→027, data bảo toàn |

**Kết quả:** tất cả **PASS** tại `797682b`. (Ghi chú hygiene: M1 `reset()` không clear `staff_users`/
`audit_log` → M1 test chạy trên DB fresh; đã ghi rõ.)

### AC → evidence (cập nhật)
| AC | Evidence |
|---|---|
| AC-M2-01/02 transition matrix + event idempotent | m2_transitions/lifecycle; migration 022 trigger |
| AC-M2-03 create reserve atomic, thiếu→no order | m2_transitions [2][6]; **backorder đã loại → hành vi đúng spec §10.1** |
| AC-M2-04/05 concurrency + invariants | m2_inventory_domain [3][4][7] |
| AC-M2-06/07 cancel/expire/fulfill | m2_lifecycle [3][4][5]; m2_worker_api sweep |
| AC-M2-08 no auto-available trước inspection | transitions.py effect NONE/return_inspect |
| AC-M2-09 append-only + ref/idem/actor | migration 021/022 trigger; m2_db_role revoke |
| AC-M2-10 reconcile | m2_inventory_domain [6]; **m2_adjustment_compat (stock==available sau adjustment — F02)** |
| AC-M2-11 adjustment perm/SoD/Unit Head | m2_lifecycle [6]; m2_rbac (adjustment→403 viewer) |
| AC-M2-12 backfill no blind copy | m2_backfill + prod dry-run |
| **AC-M2-13** compat + balance authority gate | **m2_balance_authority (F05) — read path wired + gate + split-brain**; m2_adjustment_compat reconcile |
| AC-M2-14 DB role least-privilege | m2_db_role 14/14 |
| **AC-M2-15** deterministic customer notify | **m2_customer_notify (F06) — durable/dedupe/kênh-aware, no LLM** |
| **AC-M2-16** migration fresh/existing + rollback | fresh (mọi test) + **m2_existing_apply_rehearsal (F07)**; runbook §6 rollback |
| **F03 security** mutation ≠ read perm | **m2_rbac — viewer→403 mọi mutation** |

## 4. Migration / data artifacts
- Migrations 021–027 (expand-only, forward, transactional, postcondition fail-closed). Fresh rehearsal
  (mọi throwaway test migrate 001..027) + **existing-apply** rehearsal (020→027) — data bảo toàn (checksum).
- Backfill tooling `scripts/m2_backfill.py`. Production dry-run artifact: `E:/Alpha3s/prod-snapshot/
  m2_backfill_prod_plan_report.json` — **read-only snapshot, PO-approved 27/7** (Directive §10 production-access
  exception, log tại Slice0 §8), PII-free, checksum `deece47fbfbdeab6e071931333c68275382be5d53ba9137827a0004f3f27303e`.
  (Lưu ý: artifact hiện ở đường dẫn máy dev; sẵn sàng chuyển vị trí verify-able theo yêu cầu CA.)

## 5. Deployment / runbook
`docs/PHASE1B-M2-RUNBOOK-VI.md` (đã cập nhật: mutation perms F03, balance-authority read path F05,
adjustment dual-write F02, customer notify F06). Flags TẮT mặc định; rollout phased §15.6; DB-role cutover.

## 6. Security / rollback / monitoring
- RBAC per-action + **mutation perms tách read** (F03); SoD + Unit Head; DB-role least-privilege; audit
  fail-closed; Idempotency-Key; không PII payload/receipt/log.
- Rollback: flags OFF → hành vi trước; ledger/events append-only (correction = row mới); adjustment
  dual-write giữ `stock==available` (reconcile endpoint `ok:false` → P1).

## 7. Open decisions (PO/CA)
1. **Backorder** đã tách khỏi M2 (theo PO 27/7 + F01). Sẽ trình như change/milestone riêng với spec+AC.
2. Production snapshot artifact — CA muốn vị trí verify-able + approval reference: sẵn sàng cung cấp lại.

## 8. Submission Index
| File | Trong SHA |
|---|---|
| `docs/PHASE1B-M2-DEV-DELIVERY-PACKAGE-VI.md` (file này) | package (docs-only trên 797682b) |
| `docs/PHASE1B-M2-RUNBOOK-VI.md`, `PHASE1B-M2-SLICE0-BASELINE-AUDIT-VI.md` | docs |
| `migrations/021…027*.sql` | 797682b |
| `app/services/inventory/*`, `app/services/order/*`, `app/services/command/{lifecycle,order_service,registry}.py` | 797682b |
| `app/api/inventory.py`, `app/config.py`, `app/main.py`, `app/workers/tasks.py` | 797682b |
| `scripts/m2_*` (12 evidence scripts) | 797682b |

## Self-check checklist (Protocol §4)
- [x] Scope khớp Directive + AC-M2-01..16; backorder scope-change đã loại (F01).
- [x] Code committed, Git clean, **một** implementation/evidence SHA `797682b`.
- [x] Mọi test chạy tại đúng SHA; PASS có command + exit code (§3).
- [x] Disposition F01–F08 đầy đủ với commit/file.
- [x] Version/metadata nhất quán; migration manifest 021–027.
- [x] Không "sẽ gửi sau"; không PASS thiếu command/exit code.
- [x] Runbook khớp code (mutation perms, balance-authority, dual-write, customer notify).
- [x] Không secret/PII trong tài liệu.
- [x] Quyết định PO/CA tách rõ (§7).
