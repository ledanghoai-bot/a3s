# M4-9 — PO / Operations Acceptance Record (Tiered model — mẫu để ký)

> Đóng handover M4-9 (CA Review 62/65). Ký cho **mô hình tiered** đã được CA chấp nhận (Review 64/65).
> PO/Operations đọc runbook 2 tầng + tự chạy được Tier A, rồi điền RACI + ký §4.

## 1. Phạm vi nghiệm thu

Dashboard-triggered Signing Run (tiered) theo:
- `docs/M4-9-DASHBOARD-TRIGGER-DESIGN-VI.md` §10 (tiered)
- `docs/M4-9-OPERATOR-RUNBOOK-VI.md` (2 tầng)
- `docs/M4-9-THREAT-MODEL-VI.md` (SoD conditional)
- Correction Package `PHASE1B-M4-9-TIERED-CORRECTION-PACKAGE-VI` (CA ACCEPT — Review 65).

## 2. Xác nhận Operations tự vận hành được (Tier A)

| Mục | Xác nhận |
|---|---|
| Đã đọc runbook §1 (Tier A "1 người, 1 màn hình") | ☑ |
| Tự chạy được Tier A trên dashboard: Start→Preflight(checklist)→Ceremony→Canary→Execute→CLOSED | ☑ |
| Hiểu **đọc checklist xanh/đỏ** thay vì nhớ tiền điều kiện | ☑ |
| Hiểu hệ thống **tự nâng Tier B** (fail-closed) nếu non-repudiation/PII/batch>260/quota>5 | ☑ |
| Hiểu abort luôn có; `CLEANUP_FAILED` → Incident Owner | ☑ |
| Hiểu Tier B (hiếm) cần 2 người + USB + SoD — theo runbook §2 | ☑ |

## 3. Phân vai (RACI — điền tên)

| Vai | Tier A | Tier B |
|---|---|---|
| Service Owner / PO | HOAI | (như Tier A) |
| Operator | Staff 1 (kiêm approve) | Staff 1 |
| Approver (khác Operator) | (kiêm) | PO - HOAI |
| Security Custodian (USB CA02) | — | Staff 1 |
| Incident Owner + escalation | PO - HOAI | (như Tier A) |

> **Ghi chú SoD (Tier B):** Operator = Staff 1, Approver = HOAI → **SoD approve≠operate ĐẠT**
> (backend + DB enforce). Lưu ý cân nhắc: Security Custodian (USB) cũng = Staff 1 (trùng Operator) —
> hợp lệ theo luật SoD hiện hành (chỉ ép approve≠operate), nhưng nếu PO muốn tách custody USB khỏi
> người vận hành để dual-control chặt hơn thì gán Custodian ≠ Staff 1. PO quyết; không chặn nghiệm thu.

## 4. Xác nhận

- **Mô hình tiered:** ☑ chấp nhận (Tier A single-operator; Tier B giữ SoD+ceremony+Ed25519-KMS).
- **Auto-escalate fail-closed:** ☑ chấp nhận (cap batch 260, quota routine 5).
- **pin_secret↔JWT (T9-03):** owner = **PO (anh Hoài)**, gate riêng sau. ☑ đồng ý.

```
Tôi, PO/Service Owner dự án alpha3s (danh tính: HOAI), xác nhận Operations tự vận hành được M4-9
tiered (Tier A single-operator; Tier B giữ ceremony/SoD), chấp nhận các disposition trên.
Ký — ngày 28/08/2026: PO - HOAI
```
