---
id: A3S-PHASE1B-M2-FULL-CHAIN-REHEARSAL-EVIDENCE
milestone: M2
type: release-preparation-artifact
title: Full-chain existing-apply rehearsal 018(M0)->028 — evidence (release-prep, NGOAI accepted RC)
branch: release-prep/m2-full-chain-rehearsal
run_head_sha: 5556f504b3bf1abefc25412f3363976dcdd4e627
base: ea4dba8124b5cc73b755656c8789f331bcc2854d (M2 accepted head — branch-off point, CHUA chua harness)
language: vi-VN
---

# Full-chain rehearsal 018→028 — Evidence (release-preparation)

> Artifact chuẩn bị release theo CA Gate 4 feedback + correction. Full-chain rehearsal `019`–`028`
> (M1 019-020 + M2 021-028) từ mốc **018 (M0 = production thật)**. **KHÔNG thuộc M2 accepted RC** — trên
> branch release-prep riêng để PR M2 giữ accepted RC + docs-only tail. Harness =
> `scripts/m2_existing_apply_rehearsal.py` với `EXISTING_THROUGH=18` (chỉ trên branch này).

## Run capture — exact command · timestamp · exit code · exact commit
- **run_head_sha (full 40-char):** `5556f504b3bf1abefc25412f3363976dcdd4e627` — **commit release-prep ĐÃ
  CHỨA harness** mà run thực thi (KHÔNG phải base `ea4dba8`). Lần run này `git rev-parse HEAD` =
  `5556f504…` (harness đã committed).
- **Artifact path:** `docs/PHASE1B-M2-FULL-CHAIN-REHEARSAL-EVIDENCE-VI.md` (file này). Được cập nhật ở
  **docs-only successor** của `5556f504…` (chỉ file này đổi; harness KHÔNG đổi) — compare rõ.
- **Environment:** Docker Compose, container `alpha3s-api-1`, Postgres 16 + pgvector; throwaway DB `m2exist_itest`.

```text
run_head_sha (full 40-char): 5556f504b3bf1abefc25412f3363976dcdd4e627
branch: release-prep/m2-full-chain-rehearsal
timestamp: 2026-07-28 09:05:41 +0700
command: docker exec alpha3s-api-1 python scripts/m2_existing_apply_rehearsal.py
--- OUTPUT ---
[setup] existing=001..018 (18 files); apply=['019', '020', '021', '022', '023', '024', '025', '026', '027', '028']
[1] dựng DB hiện hữu ở mốc 018 (M0 production) + seed dữ liệu đại diện
  PASS schema_migrations tới 018 (M0) (018_rbac_seed)
[pre] orders=5 products=1 statuses=['cancelled', 'confirmed', 'done', 'new', 'shipped'] checksum=e46af18174cd
[2] EXISTING-APPLY: migration 019..028 (M1+M2) trên DB đã có dữ liệu
  PASS apply 019..028 (gồm M1 019-020) thành công (postcondition mỗi migration PASS)
[3] POST integrity
  PASS du lieu hien huu KHONG doi (checksum e46af18174cd == e46af18174cd)
  PASS orders/products count giữ nguyên (5/1 -> 5/1)
  PASS new table command_executions hiện diện sau existing-apply
  PASS new table outbox_events hiện diện sau existing-apply
  PASS new table delivery_attempts hiện diện sau existing-apply
  PASS new table inventory_balances hiện diện sau existing-apply
  PASS new table inventory_movements hiện diện sau existing-apply
  PASS new table order_events hiện diện sau existing-apply
  PASS new table inventory_adjustment_requests hiện diện sau existing-apply
  PASS orders.inventory_status default 'unreserved' cho existing rows (5)
  PASS orders.origin_channel NULL cho existing rows (5)
  PASS orders_status_check bao gom legacy + M2 status (existing data hop le)
  PASS 024 runtime role + 026 mutation perms hiện diện
[4] runtime objects: roles/grants, indexes, constraints, checksums
  PASS grants: app SELECT orders=True, NOT UPDATE ledger=False
  PASS object present: inventory_reservations_one_active_idx
  PASS object present: inventory_movements_no_update
  PASS object present: order_events_no_update
  PASS object present: inventory_balances_reserved_le_onhand
  PASS object present: products_stock_nonneg
  PASS migration checksums recorded, distinct (28 rows, 28 checksums)
[5] backfill + reconcile trên existing data (post-migration)
  PASS audit existing data OK (anomalies=[])
  PASS reconcile post-backfill OK (mismatches=[])
  PASS balance invariants hold (0 vi phạm)
[caveat] Rehearsal khởi từ mốc 018 (= M0 production that) + apply TOAN CHUOI 019..028 (M1+M2)
         -> dung duong upgrade production khi merge M2. Dung representative data (khong PII).
         Full production dump/snapshot that van can production-access gate rieng (CA acceptance §4).
[duration] 3.01s

RESULT: PASS — existing-apply 018(M0)->028 (M1+M2) an toan; du lieu hien huu bao toan; no PII in output
EXIT=0
```

## Ghi chú
- Release thật: chạy harness trên **artifact production 018** (snapshot/dump được phép) — production-access gate riêng (CA acceptance §4).
- Accepted M2 rehearsal (`m2_existing_apply_rehearsal.py` bản 020→028) giữ NGUYÊN trong accepted RC `9b49628`; harness 018 CHỈ trên branch release-prep này.
