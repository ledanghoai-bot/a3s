---
id: A3S-PHASE1B-M2-MERGE-READINESS
milestone: M2
title: M2 Merge-Readiness Package (Work Order A) — chuẩn bị, CHƯA merge
responds_to: A3S-PHASE1B-M2-M3-COORDINATION-NOTICE-001 §3 (Work Order A)
accepted_rc_sha: 9b49628a83ba1fe02b97913f20f33e4883560b5b
reviewed_pr_head_sha: ea4dba8124b5cc73b755656c8789f331bcc2854d
production_main_sha: 4ce5f3ab2b95846cbc5a3dd5b21528a891b36314
language: vi-VN
---

# M2 Merge-Readiness (Work Order A)

> **AUTHORIZED = chuẩn bị evidence.** Tài liệu này KHÔNG merge/deploy. `Merge main now: NOT AUTHORIZED`
> (Coordination Notice §6). Trình PO/CA release gate để lấy merge/deploy authority riêng.

## 1. Accepted RC + docs-only tail (Notice §3.1)
- **Accepted code RC:** `9b49628a83ba1fe02b97913f20f33e4883560b5b`.
- **Reviewed PR head:** `ea4dba8124b5cc73b755656c8789f331bcc2854d` (== `origin/feat/phase1b-m2-order-inventory-correctness`, không drift).
- **Compare RC → reviewed PR head** = **docs-only, 2 file** (khớp CA acceptance):
  `docs/PHASE1B-M2-DEV-DELIVERY-PACKAGE-VI.md`, `docs/PHASE1B-M2-EVIDENCE-LOG-VI.md`.
  → `git diff --stat 9b49628..ea4dba8` = 2 docs, **0 code/migration/test**.
- **RC là ancestor** của reviewed head ✅ (`git merge-base --is-ancestor 9b49628 ea4dba8`).
- **PR M2 giữ ĐÚNG accepted RC + docs-only tail** (CA correction, option 1): KHÔNG có code/migration/**test**
  drift sau RC. `scripts/m2_existing_apply_rehearsal.py` đã khôi phục về bản accepted (020→028). Verify:
  `git diff 9b49628..HEAD` = **CHỈ docs**.
- **Full-chain rehearsal 019→028 (từ 018)** — theo Gate 4 feedback — là **release-preparation artifact
  RIÊNG**, KHÔNG nằm trong accepted RC: branch `release-prep/m2-full-chain-rehearsal`, evidence
  `docs/PHASE1B-M2-FULL-CHAIN-REHEARSAL-EVIDENCE-VI.md` (command/timestamp/exit/path đầy đủ).

## 2. Current main + full compare (Notice §3.2)
- **Production main = `origin/main` = `4ce5f3ab2b95846cbc5a3dd5b21528a891b36314`** (M0 rc7, tag ib-m0-rc7).
- ⚠️ `local main` = `c210a84` là **ref cũ, BEHIND `origin/main`** (chưa pull; `origin/main..local main` = rỗng).
  KHÔNG phải rogue merge. Authoritative main = `origin/main`. (Khuyến nghị: `git branch -f main origin/main` để dọn, không bắt buộc.)
- **`origin/main` là ancestor của `ea4dba8`** ✅ → merge **clean / fast-forwardable** (`ea4dba8..origin/main` rỗng).
- **M2 branch ahead of production main: 32 commits.**

### ⚠️ M2 merge = M1 + M2 go-live (điểm PO/CA phải biết)
Production main ở **M0** (migrations ≤018). Merge M2 branch mang **migrations 019–028** vào main → khi deploy sẽ apply:
```
019 command_bus, 020 command_rbac         ← M1 (dev-accepted nhưng CHƯA từng deploy production)
021 inventory_core … 028 products_stock_nonneg  ← M2
```
Nghĩa là merge M2 = **deploy cả M1 và M2**. Đây là schema change lớn trên DB production, KHÔNG chỉ M2.

## 3. CI / checksum / drift (Notice §3.3)
- **CI:** GitHub Actions run #29 tại PR head `ea4dba8` = **success** (CA acceptance §3 ghi nhận).
- **Migration manifest/checksum:** `001`–`028`. Migrations expand-only, forward, postcondition fail-closed.
- **Rehearsal (2 mức):** (a) *accepted RC* — `m2_existing_apply_rehearsal.py` existing-apply 020→028 (dev
  evidence, trong RC); (b) *release-prep* — **full-chain 019→028 từ mốc 018 (M0)** vì production ≤018, M1
  chưa deploy (Gate 4 feedback) → branch `release-prep/m2-full-chain-rehearsal` + evidence khóa
  (command/timestamp/exit/path). Release chạy trên **artifact production 018** thật (production-access gate).
- **Changed-file manifest RC→PR head:** 2 docs (xem §1). **Không code drift sau accepted RC.**
- **Evidence log:** `docs/PHASE1B-M2-EVIDENCE-LOG-VI.md` — 16/16 EXIT=0 tại RC.

## 4. Merge plan — giữ provability RC là ancestor (Notice §3.4)
1. **Nội dung merge = đúng `ea4dba8`** (bản CA đã ghi nhận). Docs bổ sung sau acceptance (release-readiness,
   merge-readiness này) là **docs-only** — RC `9b49628` vẫn là ancestor; liệt kê compare đầy đủ khi merge.
2. **Cách merge:** `git checkout main && git merge --no-ff ea4dba8` (merge commit rõ ràng cho audit;
   RC + toàn bộ lịch sử M1/M2 giữ trong history). KHÔNG squash (mất ancestry RC).
3. **Sau merge:** ghi exact merge SHA trên main; verify `git merge-base --is-ancestor 9b49628 <mergeSHA>`.
4. Merge SHA này là baseline cho **M3 re-baseline** (Work Order B, sau khi merge hợp lệ).

## 5. Auto-deploy impact / production state / rollback (Notice §3.5)
- **`main` push = auto-deploy VPS** (khách thật). Merge = go-live.
- **Production migration state:** hiện ≤018 (M0). Deploy chạy one-shot migrate → apply **019..028** trên DB
  production (bảng/cột/constraint mới: order status CHECK expand 025, `products_stock_nonneg` 028, runtime
  DB-role 024, inventory tables/ledger, order_events…). **Backup + existing-apply rehearsal trên artifact
  production PHẢI xong trước** (CA acceptance §4 gate 3–4; Release-Readiness gate 3–4).
- **Feature flags mặc định OFF** → code path M1/M2 **dormant**, nhưng **SCHEMA vẫn được apply**. Hành vi
  runtime = M0/legacy cho tới khi bật flag (rollout phased, gate 7).
- **Rollback/containment:** flags OFF sẵn; ledger/events append-only; mirror idempotent; trường hợp nặng →
  restore backup (gate 3). Runbook §6.

## 6. Release-gate request (Notice §3.6 — PO/CA action)
DEV trình PO + CA release authority để duyệt **merge/deploy** riêng. Sau khi có approval, DEV thực thi theo
**Release-Readiness plan** (`docs/PHASE1B-M2-RELEASE-READINESS-VI.md`, 8 gate) — KHÔNG merge trước approval.

## 7. STOP conditions (Notice §3 cuối) — trạng thái hiện tại
| Điều kiện STOP | Trạng thái |
|---|---|
| Drift ngoài accepted RC + docs-only tail | ✅ Không (compare = 2 docs; docs bổ sung đều docs-only) |
| Migration checksum thay đổi | ✅ Không (001–028 ổn định) |
| CI không xanh | ✅ CI #29 success |
| Merge = production change chưa duyệt | ⛔ ĐÚNG — nên **KHÔNG merge**; chờ PO/CA release gate |

## 8. Authority self-limit
DEV **KHÔNG** merge main / deploy / production migration / M3 re-baseline (chưa merge). Chỉ chuẩn bị
evidence + trình gate. Mọi bước production cần PO chốt + CA release-approve + production-access gate riêng.
