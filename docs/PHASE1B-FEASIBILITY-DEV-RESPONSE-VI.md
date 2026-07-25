---
id: A3S-PHASE1B-DEV-RESPONSE-001
title: Alpha3S I-B — Phản hồi của Dev đối với Phản biện CA (CA-REVIEW-001)
document_type: dev_response_to_review
responds_to: A3S-PHASE1B-CA-REVIEW-001
updates_document: A3S-PHASE1B-FEASIBILITY-REPORT-001
report_version_before: 0.1.0
report_version_after: 0.1.1
owner: Alpha3S
author_role: Dev
version: 1.0.0
status: submitted_for_ca_reapproval
created_at: 2026-07-24
language: vi-VN
---

# Phản hồi của Dev đối với CA-REVIEW-001

Gửi CA. Dev đã tiếp nhận phản biện `A3S-PHASE1B-CA-REVIEW-001` (APPROVE WITH REQUIRED AMENDMENTS) và
phát hành **feasibility report v0.1.1**. Văn bản này ghi rõ cách xử lý từng amendment để CA re-review.

**Tổng quan:** Dev **chấp nhận toàn bộ** P0 và P1. Không có amendment nào bị từ chối. Hai điểm Dev tự
nhận sai của v0.1.0: **(P0§4.1)** đánh giá state machine, **(P0§4.2)** đã query nhầm DB local Docker và
suy luận sai trạng thái production. Một điểm Dev **đảo lại khuyến nghị của chính mình**: **(P1§5.6)**
migration runner.

## P0 — Bắt buộc sửa

| # | Amendment | Trạng thái | Xử lý ở v0.1.1 |
|---|---|---|---|
| §4.1 | Đánh giá sai state machine | ✅ Chấp nhận (v0.1.0 SAI) | §3.1: sửa đúng — code chỉ chặn lùi (`index(new)<index(current)`), skip-forward `new→shipped/new→done/confirmed→done` vẫn PASS; docstring "không nhảy cóc" không được enforce. Thêm transition matrix + test M2 đúng bảng CA yêu cầu. |
| §4.2 | Chưa chứng minh production DB | ✅ Chấp nhận (v0.1.0 SAI) | §2: nói rõ chỉ query **Docker local `172.18.0.3`**, KHÔNG query VPS; **rút lại** khẳng định "pre-cutover" (là suy luận, mâu thuẫn Phase I report); ghi `Production data volume: not independently verified`; **production audit = prerequisite M0**; không dùng row count local để kết luận rủi ro production. |
| §4.3 | Không đồng nhất outbox = lời giải toàn bộ | ✅ Chấp nhận | §6: thay bằng bảng phân rã 4 vấn đề → 4 năng lực (receipt / read-tools+authz / reservation+ledger / scheduler+outbox). Outbox = nền vận chuyển, không phải domain model. |
| §4.4 | `sent` flag chưa đủ | ✅ Chấp nhận | §6.1: outbox failure semantics đầy đủ — idempotency_key, state machine, delivery attempts, `SKIP LOCKED` + lease timeout, bounded retry, reconciliation, dead-letter, manual replay có audit, adapter dedupe. **Không cam kết exactly-once**; mục tiêu at-least-once transport + effective-once business. |
| §4.5 | Address phải trong I-B Core Release | ✅ Chấp nhận | §9-10: đổi tên — **Core Stabilization Slice = M0-M3** (không phải toàn bộ Core), **I-B Core Release = M0-M6** (gồm address M5, identity, multi-location, delivery, payment baseline), **Growth = P2**. |

## P1 — Amendment kiến trúc

| # | Amendment | Trạng thái | Xử lý ở v0.1.1 |
|---|---|---|---|
| §5.1 | Nguồn dữ liệu hành chính | ✅ Chấp nhận | §7.1: phân biệt repo mở (accelerator, KHÔNG gọi là nguồn Nhà nước) vs văn bản pháp luật + GSO (authoritative). Thêm pin commit/provenance/version/effective/checksum/no-auto-activate/rollback + **dataset acceptance gate 8 mục**. |
| §5.2 | Dataset hỗ trợ as_of | ✅ Chấp nhận | §7.2: `as_of=now/<date>`; order lưu snapshot + dataset version; dataset mới không đổi đơn cũ. |
| §5.3 | Fallback đã khóa | ✅ Chấp nhận | §7.3: current→legacy→confirm→staff; carrier failure ≠ verified; không tính cước từ free text. |
| §5.4 | Inventory balance + immutable ledger | ✅ Chấp nhận | §6.3: `inventory_balances`(on_hand/reserved/version) + `inventory_movements`(immutable, idempotency_key); 5 bước trong 1 transaction; `products.stock` chỉ legacy trong migration window. |
| §5.5 | Reservation policy baseline | ✅ Chấp nhận | §6.4: bảng vòng đời (draft→confirm reserve→TTL 24h→handover deduct→cancel/expire release→return inspection). PO chốt TTL. |
| §5.6 | Alembic chưa khóa | ✅ Chấp nhận + **đảo khuyến nghị** | §8.1: so sánh 3 phương án theo tiêu chí CA. Dev **đổi khuyến nghị từ Alembic (v0.1.0) sang lightweight runner + `schema_migrations`** — vì migration đã là raw SQL forward-only, dự án có bài học tránh thêm dependency/ORM. Alembic = fallback. PO/CA chốt. |
| §5.7 | M0 security baseline | ✅ Chấp nhận | §5.1: throttling, password reset, revoke-all-sessions, session cleanup, không disable admin cuối, không tự nâng quyền, XSS localStorage+CSP, audit login/logout/role change, server-side authz mọi sensitive API. |
| §5.8 | Permission-based authz | ✅ Chấp nhận | §5.2: `require_permission("inventory.adjust")…`; role = bundle permission; server-side là bảo vệ chính. |

## §6 — Phản biện Role–Permission Matrix

| # | Amendment | Xử lý (Phụ lục A v0.1.1) |
|---|---|---|
| §6.1 | Delivery không xác nhận mọi payment | Delivery **chỉ ghi COD evidence/số tiền/reference**; admin/đối soát xác nhận reconciliation (tách 2 hàng riêng). |
| §6.2 | Support không tự sửa customer/order | Support chuyển sang **propose-change (✎)** cho tên/SĐT/địa chỉ/đơn. |
| §6.3 | Viewer không mặc định thấy PII | Viewer **PII masked** (SĐT/địa chỉ/payment evidence) ở UI + API. |
| §6.4 | Export = admin-only ở MVP | Đổi export thành **admin-only** + reason/scope/audit. |
| §6.5 | Separation of duties | Ghi rõ: không tự-approve; không disable admin cuối; action sau shipment tạo case/approval; refund + inventory adjustment bắt buộc reason+audit. |

## §7, §9, §10 — Cấu trúc milestone, quyết định PO, release gates

- **Milestone** đổi đúng cấu trúc CA §7 (M0-M6 với nội dung tương ứng) — §9-10 v0.1.1.
- **Quyết định PO** cần khóa: gom đủ 8 mục (thêm "kết quả production audit") — §12 v0.1.1.
- **Release gates** theo CA §10 cho M0/M1/M2/M3/M5/M6 — §11 v0.1.1.

## Cam kết & điều kiện

Dev **chưa** chạy migration production hoặc thay đổi business state hiện hành. Chỉ chuẩn bị thiết kế chi
tiết M0 trong thời gian chờ, và sẽ khởi động implementation **sau khi**: (1) v0.1.1 được PO/CA chấp
thuận; (2) PO khóa business policy bắt buộc (§12 v0.1.1); (3) production baseline được xác minh (audit
M0).

## Ký

```text
DEV SIGN-OFF — A3S-PHASE1B-DEV-RESPONSE-001
Đã xử lý đầy đủ: P0 §4.1–4.5, P1 §5.1–5.8, phản biện matrix §6, milestone §7, gates §10.
Feasibility report: v0.1.0 → v0.1.1 (revised_for_ca_reapproval).
Trạng thái mong muốn: trình CA để cấp "APPROVED FOR IMPLEMENTATION PLANNING".
Author role: Dev (Alpha3S)  ·  Chuẩn bị qua Claude Code
Ngày: 2026-07-24
```

> Lưu ý: quyết định cuối "APPROVED FOR IMPLEMENTATION PLANNING" thuộc thẩm quyền CA — Dev không tự cấp.
> Văn bản này là chữ ký xác nhận Dev đã xử lý amendment và trình lại, chờ CA re-review.
