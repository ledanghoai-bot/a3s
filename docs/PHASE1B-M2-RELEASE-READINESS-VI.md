---
id: A3S-PHASE1B-M2-RELEASE-READINESS
milestone: M2
title: M2 Release-Readiness / Go-Live Plan (chuẩn bị — CHƯA thực thi)
accepted_rc_sha: 9b49628a83ba1fe02b97913f20f33e4883560b5b
ca_acceptance: A3S-PHASE1B-M2-CA-DEVELOPMENT-ACCEPTANCE (DEVELOPMENT_ACCEPTED)
language: vi-VN
---

# M2 Release-Readiness — Go-Live Plan

> **Trạng thái: KẾ HOẠCH, CHƯA THỰC THI.** M2 mới ở mức **DEVELOPMENT_ACCEPTED** (CA). Tài liệu này
> chuẩn bị sẵn cho 8 gate §4 của CA acceptance. **KHÔNG** merge/deploy/backfill/bật-flags cho tới khi
> **PO chốt + CA release-approve** từng gate. Dev (Claude) KHÔNG tự vượt bất kỳ gate nào ở đây. Chi tiết
> vận hành: [runbook](PHASE1B-M2-RUNBOOK-VI.md).

## 0. Điều kiện tiên quyết (đã đạt)
- CA DEVELOPMENT_ACCEPTED tại RC `9b49628a83ba1fe02b97913f20f33e4883560b5b`.
- Evidence log 16/16 EXIT=0 (`PHASE1B-M2-EVIDENCE-LOG-VI.md`).
- Flags OFF; migrations 021–028 khóa; backorder đã tách khỏi RC.
- **Lưu ý deploy:** production hiện `main`@M0. Merge M2 branch → main sẽ mang **cả M1 (019-020) + M2
  (021-028)**. Production DB đang ở ~mốc M0 (≤018) → cutover apply 019..028.

## 1. Gate 1 — PO merge/release decision (governance)
- **Ai:** PO (anh Hoài) + CA release-approve.
- **Việc:** duyệt merge PR #2 → `main`. Vì `main` push = auto-deploy VPS (khách thật) → merge = go-live.
- **Trước khi merge:** tất cả gate 2–8 dưới phải có kế hoạch + approval; hoặc merge nhưng giữ flags OFF
  (M2 code trơ, hành vi M0/M1) rồi rollout sau. **Khuyến nghị:** merge với flags OFF trước, rollout tách.
- **Checkpoint:** ☐ PO approve merge ☐ CA release-approve ☐ chọn chiến lược (merge-flags-off vs full).

## 2. Gate 2 — Production-access gate (mọi snapshot/dump/read/write)
- Mỗi lần chạm production DB (snapshot, dump, backfill, migrate) là **một** production-access cần PO
  approve riêng (như snapshot read-only 27/7). Log minh bạch từng lần vào evidence.
- **Checkpoint:** ☐ PO approve từng thao tác ☐ ghi log actor/time/scope.

## 3. Gate 3 — Backup/restore verification + maintenance window
- **Backup trước cutover:** `pg_dump` full production DB → lưu off-site (VPS backup tuần KHÔNG đủ → cron
  `pg_dump` ngày, xem memory `vps-plan3-candidate`). Verify restore vào DB throwaway (đối chiếu row counts).
- **Maintenance window:** chọn giờ thấp tải; thông báo; chuẩn bị rollback (restore từ backup).
- **Checkpoint:** ☐ backup mới + verify restore OK ☐ window chốt ☐ thông báo.

## 4. Gate 4 — Migration rehearsal trên artifact release-permitted
- **Production ở M0 (≤018); M1 (019-020) CHƯA deploy** → rehearsal phải phủ **TOÀN CHUỖI `019`–`028`
  (gồm M1 019-020 + M2 021-028)** trên **bản sao/snapshot production (mốc 018) được phép** — KHÔNG chỉ
  021–028 (CA merge-readiness feedback). Đối chiếu: migration checksums, row counts/invariants,
  roles/grants, indexes/constraints, backfill plan, post-migration reconciliation.
- Tooling **release-prep** (KHÔNG trong accepted RC): branch `release-prep/m2-full-chain-rehearsal` — harness
  dựng DB ở **018** + apply **019..028**; dev-side PASS (28 checksums, data bảo toàn, M1+M2 tables),
  evidence khóa command/timestamp/exit/path (`docs/PHASE1B-M2-FULL-CHAIN-REHEARSAL-EVIDENCE-VI.md`).
  Release: chạy trên **artifact production 018** thật (production-access gate).
- **Checkpoint:** ☐ rehearsal trên artifact prod PASS ☐ checksum/counts khớp ☐ no PII trong log.

## 5. Gate 5 — Runtime DB-role provisioning + secret
- Ops: `ALTER ROLE alpha3s_app WITH LOGIN PASSWORD '<secret from vault>'`; đổi `DATABASE_URL` runtime →
  `alpha3s_app`. **KHÔNG commit secret.** Readiness: không start runtime bằng migration-owner credential.
- **Checkpoint:** ☐ role provisioned ☐ secret trong vault ☐ DATABASE_URL cutover ☐ smoke health.

## 6. Gate 6 — Backfill production (audit → plan → approve → apply → reconcile)
```bash
python scripts/m2_backfill.py audit                       # exit 0, không anomaly
python scripts/m2_backfill.py plan  --report R.json        # review checksum + số liệu
# --- PO/CA approve report ---
python scripts/m2_backfill.py apply --report R.json        # idempotent
python scripts/m2_backfill.py reconcile                    # ok: true (stock==available)
```
- **Checkpoint:** ☐ audit clean ☐ report approved ☐ apply ☐ reconcile ok ☐ artifact/checksum lưu.

## 7. Gate 7 — Rollout lần lượt theo phase (§15.6, runbook §1/§9)
1. **schema/backfill** xong (gate 4+6).
2. Bật **`M2_INVENTORY_LEDGER`** — canary (owner = Unit Head). Quan sát reserve tại order.create + expiry sweep.
3. Bật **`M2_ORDER_TRANSITIONS`** — smoke confirm→fulfill 1 đơn test; adjustment nhỏ; approve lớn.
4. Bật **`M2_BALANCE_AUTHORITY`** **CUỐI CÙNG** — sau khi assert `products.stock == available` xanh liên tục.
- Mỗi bước: theo dõi reconciliation; **mismatch hoặc negative-stock attempt = P1 → DỪNG rollout.**
- **Checkpoint mỗi flag:** ☐ canary ok ☐ reconcile ok ☐ metrics ok ☐ PO/CA go.

## 8. Gate 8 — Canary, observability, rollback decision
- **Metrics/alert (runbook §5):** `reservation.expiry.sweep`, `<command>.rejected`, reconciliation
  `ok:false`, `products.stock<0` attempt, `stock!=available`.
- **Go/No-Go:** backfill reconcile ok + regression xanh + canary confirm/fulfill/cancel + expiry quan sát
  được → Go bật flag kế. Bất kỳ P1 → No-Go, rollback.
- **Rollback (runbook §6):** trước balance-authority → tắt flags (giữ schema); sau dual-write → forward-fix
  (không sửa balance mù); ledger/events append-only. Trường hợp nặng → restore backup (gate 3).
- **Checkpoint:** ☐ dashboards live ☐ alerts on ☐ rollback drill/hiểu rõ.

## 9. Ngoài scope (không thuộc release M2 này)
- **Backorder "không bỏ đơn"**: change/milestone riêng (spec+AC+FIFO/fairness+gate). PO muốn → mở sau.
- **Phase D** retire `products.stock`: không thuộc M2 cutover nếu còn caller legacy (dashboard product edit).

## 10. Dev (Claude) tự-giới hạn
Dev **KHÔNG** tự: merge PR, push `main`, deploy, chạm production DB, bật flags, provision secret. Mọi
gate cần PO chốt + CA release-approve; production-access cần approve riêng từng lần. Dev chỉ chuẩn bị
kế hoạch/tooling/evidence và thực thi **sau** khi có approval rõ ràng cho từng bước.
