# M4-9 — RBAC Change Record (post-closure security change)

> Authority: `CA-Docs/PHASE1B-M4-9-POST-CLOSURE-RBAC-RATIFICATION-DIRECTIVE-70-VI.md`.
> Phân loại CA: **post-closure security change**. Bản ghi bất biến nối chuỗi sự việc → khắc phục.

## 1. Sự việc gốc (manual mutation, TRƯỚC CA approval)

Sau khi M4-9 handover CLOSED_SUCCESS (Review 68, merge SHA `f664d3a0`), PO chạy **thủ công**
`provision_m4_signing_operator.py` (bản chưa hardened) trên **DB production** — tạo role
`m4_signing_operator` (5 quyền `m4.signing.run.*`) + staff `signer1`. Đây là RBAC/control-plane
mutation **ngoài** authority của Directive 67 / Closure 68 (CA Review 69 xác nhận).

## 2. Hiện trạng production (đã verify read-only)

`evidence-m4-9/pc-01-prod-rbac-verify-*.txt`: role tồn tại + 5 quyền; staff `signer1`; admin **chỉ
view**; `m4_signing_run` runs=**0**; **0 signer**. Production **dormant** — capability chưa dùng.

## 3. Quyết định PO

PO chọn **PA1** (giữ operator + chính thức hóa) — Directive 70. Không revoke; formalize.

## 4. Khắc phục (RBAC Ratification & Hardening — commit `cc8b00d`, branch `feat/m4-9-dashboard-trigger`)

| Yêu cầu Directive 70 / 70A | Đã làm |
|---|---|
| Version-control role/grants | `migrations/048_m4_9_rbac_provisioning.sql` — role + 5 grants idempotent + **DB trigger allowlist** (chặn cấp quyền ngoài 5 → chống escalation) |
| Immutable audit | `audit_service.record` → `audit_log` (đã redact, immutable qua migration 024); action `rbac.provision_operator/revoke_operator/reset_admin`; ghi actor/delegated_by/target/role/grants/ticket/reason/result — **không** password/PIN/token |
| Authorization + fail-closed | bắt buộc `--actor/--ticket/--reason`; thiếu → `ProvisioningError` |
| Rollback/revoke | `--revoke` → role_key NULL + audit → dormant baseline; migration có rollback SQL |
| Idempotency + dry-run + confirmation + no-unlimited-retry | `--dry-run` (plan), `--yes` (apply); idempotent (reassigned, không nhân đôi); không retry vô hạn |
| Allowlist (không role/grant tùy ý) | role cố định hằng số; script chỉ **gán** role, không tạo/grant quyền |
| Tests | `scripts/m4_9_rbac_provisioning_test.py` (13 check, **M4_9_RBAC_ALL_PASS**) + `tests/test_m4_9_rbac_provisioning.py` (9 unit) — least-priv/SoD/authz/idempotent/rollback/redaction/fail-closed |
| Runbook/RACI/break-glass | `docs/M4-9-OPERATOR-RUNBOOK-VI.md` §3+§5 (signer1=Tier A operator, PO=Service Owner/Incident Owner) |

## 5. Ràng buộc còn giữ

- **Chưa merge/deploy/apply** — cần Apply/Merge-Dormant directive riêng của CA.
- Interim: không Execute/Canary/signer/STS/KMS/signing/customer-data/activation; role grants giữ để
  chuẩn bị nhưng **chưa dùng**. Emergency revoke thuộc PO (có evidence).
- **Assignment ≠ activation** — production signing thật vẫn cần Activation Gate riêng (Design 71/72).

## 6. Liên kết
- Commit: `cc8b00d` (branch `feat/m4-9-dashboard-trigger`).
- Report gốc: `Dev/PHASE1B-M4-9-POST-CLOSURE-CHANGES-REPORT-VI.md` (sha256 `5ccff697…`).
- CA: Review 69, Directive 70, Addendum 70-A.
