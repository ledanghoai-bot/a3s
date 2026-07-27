---
id: A3S-PHASE1B-M2-DEV-DELIVERY-PACKAGE
milestone: M2
title: M2 Delivery Package — Order and Inventory Correctness (Submission 1)
governing_directive: A3S-PHASE1B-M2-DEV-DIRECTIVE-001 v1.0.0
release_candidate_sha: 46f4459a3a3fc13a4ffc04f085b0b2f29a8a5601
branch: feat/phase1b-m2-order-inventory-correctness
language: vi-VN
---

# M2 Delivery Package — Submission 1

> Một Delivery Package hợp nhất (CA-GOVERNANCE-001). Flags M2 mặc định **TẮT** — không đổi hành vi
> production khi chưa cutover. RC SHA `46f4459`, branch `feat/phase1b-m2-order-inventory-correctness`
> (off `d7ccc4f`, M1 accepted `46e1169` là ancestor), Git clean.

## 1. Delivery Report — phạm vi

### Đã làm (Slice 0–7, đúng thứ tự Directive §4)
- **S0** baseline audit + legacy status mapping + finding cancel-no-restore (`docs/PHASE1B-M2-SLICE0-BASELINE-AUDIT-VI.md`).
- **S1** schema expand: migrations **021** inventory core (locations/balances/reservations/movements, invariants
  CHECK + ledger append-only trigger), **022** order_events + order inventory columns, **023** adjustment
  requests + SoD + RBAC (role `unit_head`, 13 perms), **024** runtime DB-role least-privilege (`alpha3s_app`),
  **025** expand `orders.status` CHECK.
- **S2** backfill + reconciliation tooling (`scripts/m2_backfill.py`): reconstruct opening (không copy mù),
  resumable/idempotent, abort-on-anomaly, §17.1 reconcile.
- **S3** inventory domain (`app/services/inventory/`): `apply_movement` (ledger+balance+invariant+idempotent),
  lock ordering §10.4, reserve/release/fulfill/adjust, reconcile service.
- **S4** order state machine (`app/services/order/`): matrix guard §7.2, order_events, `apply_transition`
  engine, `reserve_on_create` gắn vào `order.create.v1` (flag).
- **S5** lifecycle command service (`app/services/command/lifecycle.py`): 14 command type §8.1, effective-once,
  reservation extend/expire, adjustment request/approve/reject (SoD + Unit Head + stale revalidate).
- **S6** expiry worker (cron 60s) + HTTP API (`app/api/inventory.py`) + dashboard **Kho** page + runbook.
- **S7** full regression + delivery package (tài liệu này).

### Chưa làm / khác plan (khai báo trung thực — xem §7 Open decisions)
- **Phase C balance-authority read-path** (AC-M2-13 phần sau): flag `M2_BALANCE_AUTHORITY` đã có + gate,
  runbook mô tả; nhưng đường "đọc availability TỪ balance thay legacy stock" **chưa wire vào order.create**
  (hiện legacy stock vẫn authority + ledger dual-write/shadow). Đúng thiết kế phased §15.6 (Phase A/B trong
  scope; Phase C cutover là bước rollout sau, cần CA gate). → Không phải regression; là ranh giới rollout.
- **Customer outbox notification cho transition** (AC-M2-15): receipt lifecycle **deterministic từ committed
  state** (evidence có); nhưng outbox thông báo KHÁCH khi đổi status (vd cancelled) **chưa wire** cho M2
  transition (M1 đã có customer receipt cho order.create). Transition là staff-driven; đề xuất P2/backlog.
- **Migration "existing-apply"** (AC-M2-16 phần existing): rehearsal chạy **fresh 001..025**; migrations
  expand-only (`IF NOT EXISTS`/drop-add constraint) nên apply trên DB đã ở 020 là forward an toàn, nhưng
  evidence hiện chỉ có fresh. Đề xuất chạy existing-apply rehearsal tại cutover.

## 2. Release-candidate SHA
```
SHA    : 46f4459a3a3fc13a4ffc04f085b0b2f29a8a5601
branch : feat/phase1b-m2-order-inventory-correctness (off d7ccc4f)
git    : clean (không untracked/uncommitted tại thời điểm nộp)
commits: 788fa61 S0 · 3db122f S1 · f6ed27a S2 · c09b160 S3 · a0a846a S4 · e84c250 S5 · 46f4459 S6
```

## 3. Evidence — commands, exit code, assertion mapping

Test chạm DB = script standalone chạy trên throwaway DB (migrate 001..025 fresh). Exit 0 = PASS.

| Script | Lệnh | Bao phủ |
|---|---|---|
| `scripts/m2_db_role_test.py` | `docker exec alpha3s-api-1 python scripts/m2_db_role_test.py` | AC-M2-14, migration rehearsal 001..025 |
| `scripts/m2_backfill_test.py` | `docker exec alpha3s-api-1 python scripts/m2_backfill_test.py` | AC-M2-12 |
| `scripts/m2_backfill_prod_dryrun.py` | `docker exec alpha3s-api-1 python scripts/m2_backfill_prod_dryrun.py` | AC-M2-12 trên production snapshot (checksum `deece47`) |
| `scripts/m2_inventory_domain_test.py` | `docker exec alpha3s-api-1 python scripts/m2_inventory_domain_test.py` | AC-M2-04/05/06/07/10 |
| `scripts/m2_transitions_test.py` | `docker exec -e DATABASE_URL=…m2s4_itest -e PYTHONPATH=/srv -w /srv alpha3s-api-1 python scripts/m2_transitions_test.py` | AC-M2-01/02/03 |
| `scripts/m2_lifecycle_test.py` | `… DATABASE_URL=…m2s5_itest … python scripts/m2_lifecycle_test.py` | AC-M2-01/02/06/07/11 + effective-once |
| `scripts/m2_worker_api_test.py` | `… DATABASE_URL=…m2s6_itest … python scripts/m2_worker_api_test.py` | AC-M2-06 (expiry) + API RBAC/flag/idempotency |
| pytest | `docker exec alpha3s-api-1 python -m pytest -q` | 81 unit M0/M1 (regression) |
| M1 regress | `… DATABASE_URL=…m1_itest … python scripts/command_order_service_test.py` + `command_http_test.py` | M1 không regress bởi M2 |

**Kết quả (chạy tại SHA 46f4459):** tất cả **PASS**. pytest **81 passed**. M1 order_service (T1–T10) + http PASS.
M2 S1–S6 PASS. (Ghi chú hygiene: `reset()` M1 không clear `staff_users`/`audit_log` → rerun cần DB fresh;
đã chạy trên m1_itest fresh cho record.)

### AC → evidence mapping
| AC | Evidence |
|---|---|
| AC-M2-01 transition matrix, no skip/back | m2_transitions [1] guard; m2_lifecycle [2] illegal→rejected; m2_worker_api illegal→409 |
| AC-M2-02 one event/transition idempotent | m2_lifecycle confirm event=1 + event idempotent; migration 022 append-only trigger |
| AC-M2-03 create reserve atomic, thiếu→no order | m2_transitions [2] reserve; [6] fail-closed rollback (no order/command) |
| AC-M2-04 concurrent no oversell | m2_inventory_domain [7] FOR UPDATE serialize → đúng 1 winner |
| AC-M2-05 balance invariants + available | m2_inventory_domain [3][4] invariant reject; available=on_hand-reserved |
| AC-M2-06 cancel/expire release đúng qty, no double | m2_lifecycle [4][5]; m2_worker_api sweep + idempotent noop |
| AC-M2-07 fulfill consume once | m2_transitions [3]; m2_lifecycle [3] |
| AC-M2-08 delivery_failed/return no auto-available | transitions.py: các transition này inventory_effect=NONE/return_inspect (không tăng available) |
| AC-M2-09 ledger/events append-only + ref/idem/actor | migration 021/022 trigger; m2_db_role runtime KHÔNG UPDATE/DELETE; apply_movement luôn set ref/idem/actor |
| AC-M2-10 reconcile | m2_inventory_domain [6]; m2_worker_api reconciliation ok |
| AC-M2-11 adjustment perm/reason/audit + Unit Head | m2_lifecycle [6] SoD/unit-head/stale; m2_worker_api adjustment API + audit fail-closed |
| AC-M2-12 backfill no blind copy | m2_backfill_test + prod dry-run (on_hand=stock+reserved, available==stock) |
| AC-M2-13 compat mismatch + balance authority gate | reconcile stock==available; flag M2_BALANCE_AUTHORITY gate (Phase C read-path chưa wire — §7) |
| AC-M2-14 DB role least-privilege | m2_db_role 14/14 (no DDL/ledger-mutate/audit/schema_migrations; not super) |
| AC-M2-15 deterministic receipt committed, no LLM | receipt lifecycle build từ committed result_payload; customer-outbox-cho-transition: §7 backlog |
| AC-M2-16 migration fresh/existing + rollback + observability | rehearsal fresh 001..025 (mọi test); runbook §6 rollback; log_event metrics; existing-apply: §7 |

## 4. Migration / data artifacts
- Migrations **021–025** (expand-only, forward, transactional, postcondition fail-closed). Manifest tại
  cutover cập nhật `expected_*` cho bảng M2 (đề xuất — hiện postcondition mỗi migration đã tự-validate).
- Backfill tooling `scripts/m2_backfill.py` (audit/plan/apply/reconcile). Report production dry-run:
  `E:/Alpha3s/prod-snapshot/m2_backfill_prod_plan_report.json` (read-only snapshot, PII-free, PO-approved).
- Production snapshot audit: 2 đơn `new`, 1 SKU stock=998, 0 cancel/anomaly → reconstruct 1000/2/998 (clean).

## 5. Deployment / runbook
`docs/PHASE1B-M2-RUNBOOK-VI.md` — flags & phased rollout (§15.6), cutover checklist, expiry worker,
adjustment approval, metrics/alerts, rollback, sự cố thường gặp, lệnh nhanh. DB-role cutover (AC-M2-14):
ops set `alpha3s_app` LOGIN+password + đổi `DATABASE_URL` tại release (không commit secret).

## 6. Security / rollback / monitoring
- **Security**: RBAC per-action (13 M2 perms), SoD DB CHECK + code, Unit Head scope, runtime DB-role
  least-privilege (defense-in-depth ngoài trigger), audit fail-closed mọi command, Idempotency-Key bắt buộc,
  không PII trong payload M2/receipt/log.
- **Rollback boundary** (§16): trước balance-authority tắt flags giữ schema; sau dual-write forward-fix
  (không sửa balance mù); ledger/events append-only (correction = row mới).
- **Monitoring**: structured `log_event` (reservation.expiry.sweep, *.rejected, expire.error); reconciliation
  endpoint (`ok:false` → P1); assert `products.stock==available` (Phase B).
- **Go/No-Go**: backfill reconcile `ok:true` + regression xanh + canary confirm/fulfill/cancel + expiry sweep
  quan sát được → Go bật `M2_INVENTORY_LEDGER`; balance-authority (Phase C) là gate riêng cần CA.

## 7. Open decisions (PO/CA)
1. **Phase C balance-authority read-path**: wire order.create đọc availability từ balance (thay legacy stock)
   — trong M2 scope hay tách sang cutover-phase riêng có CA gate? (Đề xuất: gate riêng, giữ như hiện tại.)
2. **Customer outbox notification cho transition** (cancel/fulfill…): thêm trong M2 hay P2 backlog?
   (Đề xuất P2 — transition là staff-driven; M1 đã có customer receipt cho create.)
3. **Existing-apply migration rehearsal** (020→025 trên bản sao production): chạy tại cutover window —
   PO xác nhận lịch maintenance.
4. **DB-role cutover** đổi `DATABASE_URL` sang `alpha3s_app` — thời điểm ops thực hiện (cần downtime ngắn?).
5. Production snapshot đã chạy **read-only, PO-approved** (Directive §10 production-access) — ghi nhận là
   ngoại lệ có phê duyệt.
6. **PO CHANGE — Backorder / never-drop-order** (mới, PO chỉ đạo sau Submission 1): thiếu hàng KHÔNG bỏ
   đơn → giữ backorder + escalate inventory topup + auto-reserve FIFO. **Lệch CA spec §10.1 có chủ đích**,
   gated flag `M2_BACKORDER_ESCALATION` (default OFF → hành vi M2 đã duyệt giữ nguyên). Chi tiết + evidence:
   `docs/PHASE1B-M2-PO-CHANGE-BACKORDER-VI.md`. **Cần CA chấp nhận** như PO change trong M2 hay tách riêng.
   Migrations giờ 001..**026**; thêm `scripts/m2_backorder_test.py` (PASS).

## 8. Submission Index
| File | Loại | Trong SHA |
|---|---|---|
| `docs/PHASE1B-M2-DEV-DELIVERY-PACKAGE-VI.md` | package (file này) | 46f4459+ |
| `docs/PHASE1B-M2-SLICE0-BASELINE-AUDIT-VI.md` | baseline audit | 788fa61 |
| `docs/PHASE1B-M2-RUNBOOK-VI.md` | runbook | 46f4459 |
| `migrations/021_inventory_core.sql` … `025_order_status_expand.sql` | migrations | 3db122f/a0a846a |
| `app/services/inventory/*` , `app/services/order/*` | domain | c09b160/a0a846a |
| `app/services/command/lifecycle.py`, `expiry_worker.py`, `registry.py` | command layer | e84c250/46f4459 |
| `app/api/inventory.py`, `app/workers/tasks.py`, `app/main.py`, `app/config.py` | API/worker/wiring | 46f4459/a0a846a |
| `dashboard/app/inventory/page.js`, `dashboard/app/layout.js` | UI | 46f4459 |
| `scripts/m2_*_test.py`, `scripts/m2_backfill*.py` | evidence | S1–S6 |

## Self-check checklist (Protocol §4)
- [x] Scope khớp Directive §3–4 + AC-M2-01…16 (partials khai báo rõ §1/§7).
- [x] Code đã commit, Git clean, RC SHA ghim `46f4459`.
- [x] Mọi test chạy tại đúng SHA; PASS có command + exit code (§3).
- [x] Version/metadata nhất quán giữa các tài liệu.
- [x] Không còn "sẽ gửi SHA/log sau".
- [x] Không tuyên bố PASS thiếu command/exit code.
- [x] Runbook khớp code thực tế (flags, worker, API, rollback).
- [x] Không secret/PII trong tài liệu (payload M2 non-PII; snapshot PII-free).
- [x] Quyết định cần PO/CA tách rõ (§7), không ghi nhầm thành blocker kỹ thuật.
