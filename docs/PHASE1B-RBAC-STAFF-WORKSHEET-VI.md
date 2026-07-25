---
id: A3S-PHASE1B-RBAC-STAFF-WORKSHEET-001
title: Alpha3S I-B M0 — Existing-Staff RBAC Assignment Worksheet (PO điền)
document_type: rbac_assignment_worksheet
parent: A3S-PHASE1B-IMPLEMENTATION-PLAN-001
owner: Alpha3S
author_role: Dev
version: 1.0.1
status: po_approved
po_signoff: "PO approved matrix + staff assignment (controlled file) + initial admin + PII policy 2026-07-25"
created_at: 2026-07-25
language: vi-VN
---

# Existing-Staff RBAC Assignment Worksheet (CA-REVIEW-M0-DEV-002 §7)

> Production có **2 staff hiện hữu** (từ prod audit). Trước khi bật RBAC (migration 016 + seed), PO phải
> **gán role cụ thể cho từng staff**. **KHÔNG mặc định tất cả thành `viewer`/`admin`/role chung** (CA §7.5).
> **Backfill fail nếu còn staff không có role** (CA §7.4). Dùng **định danh nội bộ** (`staff_users.id` +
> username login — KHÔNG phải PII khách); PO điền username/tên ở bản kiểm soát truy cập, không phát rộng.

## 1. Bảng gán (PO điền cột "Role PO chọn" + "Ghi chú")
Lấy danh sách bằng (chạy read-only khi có quyền):
```sql
SELECT id, username, name, is_active, role_key FROM staff_users ORDER BY id;
```

| staff_id | username (PO điền) | Role PO chọn (admin/sales/warehouse/delivery/support/viewer) | Ghi chú |
|---|---|---|---|
| ___ | ______ | ______ | (vd người quản trị hệ thống → admin) |
| ___ | ______ | ______ | |

**Ràng buộc khi chọn:** phải có **≥1 `admin`** (để không rơi vào tình trạng không ai quản trị được);
role phải nằm trong 6 role canonical đã seed (016).

## 2. Tham chiếu role → quyền (đề xuất least-privilege, `rbac_seed_proposed.sql` — chờ PO duyệt)
| Role | Quyền chính (✅ direct) |
|---|---|
| admin | TẤT CẢ |
| sales | customer.view/edit, address.view, order.create_edit, order.cancel_before_ship, order.status_change |
| warehouse | customer.view, fulfillment.status_change, inventory.receive_transfer |
| delivery | fulfillment.status_change, payment.cod_record |
| support | customer.view, payment.cod_record *(sửa khách = propose-change, không direct)* |
| viewer | customer.view *(PII masked)* |
*(Ô ⚠️ "cần duyệt" / ✎ "propose" xử lý ở approval/masking layer milestone sau — xem Phụ lục A feasibility.)*

## 3. Quy trình áp (khi CA release approval + PO điền xong bảng §1)
1. Áp migration 016 (roles/permissions/role_permissions + `staff_users.role_key`).
2. Seed mapping = **migration `018_rbac_seed.sql`** (nội dung = ma trận PO duyệt) — **KHÔNG** chạy
   `rbac_seed_proposed.sql` trực tiếp bằng psql (CA-REVIEW-M0-DEV-003 §5).
3. Gán role bằng **`scripts/assign_staff_roles.py --mapping <file kiểm soát truy cập>`** (transactional,
   idempotent, cardinality fail-closed) — KHÔNG đưa username/PII vào repo; mapping đọc từ file/secret.
4. Script tự **kiểm backfill fail-closed**: ≥1 active admin + không active staff thiếu role → nếu vi phạm
   ROLLBACK. Còn staff NULL → DỪNG, chưa bật strict.
5. Bật **`RBAC_STRICT=true`** (production) → `require_permission` không degrade; startup readiness sẽ
   **fail nếu provisioned mà catalog/mapping thiếu** (đã implement, verified).
6. (Sau) migration siết `role_key NOT NULL`.

## 4. Verify sau khi bật (CA §7.6-7.7)
- [ ] `RBAC_STRICT=true` → non-admin gọi endpoint `staff.manage` → **403**; admin → OK.
- [ ] Disable admin cuối → **409 (last-admin guard)**.
- [ ] Startup readiness: nếu seed thiếu → api **không start** (fail-closed) — đã test dev.
- [ ] Không staff nào ở trạng thái role_key NULL.

## Ký
```text
RBAC STAFF WORKSHEET
[PO SIGN-OFF 2026-07-25] PO DA DUYET:
  - Ma tran role->permission (migration 018_rbac_seed) — GOM xac nhan payment.cod_record cho
    support/delivery (quyen ghi nhan tai chinh).
  - Gan role cho 2 staff hien huu: LUU o CONTROLLED FILE (staff_roles.txt, ngoai repo — CA §7.2 no-PII),
    dung boi scripts/assign_staff_roles.py luc cutover.
  - Initial active admin: da chi dinh (trong controlled file).
  - PII masking/export policy: xac nhan (export admin-only, mask SDT/dia chi/payment evidence).
Backfill fail-closed neu con active staff thieu role. RBAC_STRICT bat SAU CUNG (khong degrade sau cutover).
Author: Dev (Alpha3S). Ngay: 2026-07-25.
```
