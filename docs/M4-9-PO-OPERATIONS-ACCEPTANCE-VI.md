# M4-9 — PO / Operations Acceptance Record (mẫu để ký)

> Tracked action #1 của CA Review 62. Đây là **bản ký nghiệm thu** để đóng handover M4-9.
> PO/Operations đọc runbook + tự chạy được (hoặc chấp nhận điều kiện), rồi điền + ký §4.

## 1. Phạm vi nghiệm thu

Dashboard-triggered Signing Run (control/approval surface) theo:
- `docs/M4-9-DASHBOARD-TRIGGER-DESIGN-VI.md` (thiết kế)
- `docs/M4-9-OPERATOR-RUNBOOK-VI.md` (vận hành + RACI)
- `docs/M4-9-THREAT-MODEL-VI.md` (bảo mật)
- Integrated Handover Package `PHASE1B-M4-9-INTEGRATED-HANDOVER-PACKAGE-VI` (bằng chứng test).

## 2. Xác nhận Operations tự vận hành được

| Mục | Xác nhận |
|---|---|
| Đã đọc runbook + hiểu trình tự start→confirm→preflight→ceremony→canary→execute→close | ☐ |
| Hiểu SoD: người approve canary **phải khác** operator | ☐ |
| Hiểu abort/break-glass luôn khả dụng, yêu cầu reason | ☐ |
| Hiểu `CLEANUP_FAILED` là trạng thái nguy hiểm → Incident Owner vào cuộc | ☐ |
| Biết pin_secret nạp server-side (ngoài dashboard), không nhập qua UI | ☐ |

## 3. Phân vai (RACI — điền tên)

| Vai | Người |
|---|---|
| Service Owner / PO | ______________________ |
| Operator / SRE | ______________________ |
| Approver (khác Operator) | ______________________ |
| Security Custodian (USB/secret) | ______________________ |
| Incident Owner + escalation path | ______________________ |

## 4. Xác nhận & tracked-action disposition

- **Full signer-stack rehearsal (#2):** ☐ đã xem bằng chứng `M4_9_FULLSTACK_PASS` (worker→runner→signer,
  synthetic, dormant) / ☐ chấp nhận như điều kiện riêng trước production signing.
- **Frontend permission UX (#3):** ☐ chấp nhận (UI ẩn nút theo quyền, backend enforce 403).
- **pin_secret↔JWT (#4, T9-03):** owner = **PO (anh Hoài)**; gate riêng, lên lịch sau; **không**
  tuyên bố production-signing readiness dựa trên rehearsal hiện tại. ☐ đồng ý.

```
Tôi, PO/Service Owner dự án alpha3s (danh tính: HOAI), xác nhận Operations tự vận hành được M4-9
trong policy đã duyệt, chấp nhận các tracked-action disposition trên.
Ký — ngày __/__/2026: ______________________
```
