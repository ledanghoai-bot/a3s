# M4 — Signer Access Request (Directive 91): thiết kế + RBAC matrix + rollback

Luồng hợp nhất: **signer-role tạm thời + activation window** qua dashboard. Backend tách 2 event khi
approve. SoD tối thiểu (Addendum 90): **Signer (request+execute) ≠ PO/Approver**.

## State machine (`m4_signer_access_request`)
```
SUBMITTED --preflight_pass--> PREFLIGHT_PASSED --approve--> ACTIVE --close--> CLOSED
   (preflight_fail/revoke -> REVOKED)      (revoke -> REVOKED)   (expire -> EXPIRED | revoke -> REVOKED)
CLOSED / EXPIRED / REVOKED = terminal
```

**approve tách 2 event (audit riêng):**
1. `provision_role` — INSERT `m4_temp_signer_role_grant` (staff=requester, role=`m4_signing_operator`,
   valid_until=window_end, is_rehearsal). BỎ QUA nếu requester đã có static role (chỉ issue window).
2. `approve` — INSERT `m4_signing_activation` (window APPROVED, TTL) + link `activation_id`.

**Auto-revoke** (worker cron 60s `signer_access_expiry_job` + close/revoke): request ACTIVE quá
window_end → EXPIRED; revoke temp grant (revoked_at); terminal activation. Defensive sweep revoke mọi
grant quá valid_until.

## Permission resolution (temp grant)
`permission_service.load_staff_authz` UNION quyền từ temp grant **đang hiệu lực**
(`valid_from<=now<valid_until`, `revoked_at IS NULL`, `is_rehearsal=false`) → role `m4_signing_operator`
(5 quyền `m4.signing.run.*`). Query mỗi request (không cache). **Rehearsal grant KHÔNG cấp quyền thật.**
Feature-detect (bảng chưa tồn tại pre-051 → bỏ qua).

## RBAC matrix (API `/dashboard/signer-access`)

| Action | Endpoint | Permission | Ai |
|---|---|---|---|
| view | GET /requests, /{id} | `m4.signer_access.view` | signer/PO/auditor |
| submit | POST /requests | `m4.signer_access.request` | signer (requester=session) |
| preflight | POST /{id}/preflight | `m4.signer_access.request` | signer |
| approve | POST /{id}/approve | `m4.signer_access.approve` | PO/approver (≠requester) |
| close | POST /{id}/close | `m4.signer_access.approve` | PO |
| revoke | POST /{id}/revoke | `m4.signer_access.approve` | PO |

- requester/approver **lấy từ session** (`staff["id"]`), không tin body → chống mạo danh.
- SoD `approver≠requester` enforce ở service (`activation.py`/`signer_access.py`), UI không phải lớp duy nhất.
- Backend luôn 403 nếu thiếu quyền (defense-in-depth); UI ẩn nút chỉ là UX (`can()` fail-safe khi perms=null).

## Bất biến an ninh
- Capability `m4.signing.activate.production` **dormant** (không grant bởi luồng này).
- Role temp allowlist `m4_signing_operator` (CHECK ở DB); Addendum 70A CLI provisioning vẫn chuẩn enforce.
- digest lock (trigger), idempotency (request_id), stale-preflight (15 phút), fail-closed, audit bất biến no-secret.
- KHÔNG secret/token/private key trong UI/API/audit. KHÔNG default signer role khi tạo account.
- Rehearsal (`is_rehearsal`) tách production: grant không cấp quyền thật, không chạm KMS/customer data.

## Rollback (migration 051)
```sql
DROP TRIGGER IF EXISTS m4_tsrg_no_delete ON m4_temp_signer_role_grant;
DROP TABLE IF EXISTS m4_temp_signer_role_grant; DROP FUNCTION IF EXISTS m4_tsrg_forbid_delete();
DROP TRIGGER IF EXISTS m4_sar_no_delete ON m4_signer_access_request;
DROP TRIGGER IF EXISTS m4_sar_digest_lock ON m4_signer_access_request;
DROP TABLE IF EXISTS m4_signer_access_request;
DROP FUNCTION IF EXISTS m4_sar_forbid_delete(); DROP FUNCTION IF EXISTS m4_sar_guard_digest();
DELETE FROM permissions WHERE key IN ('m4.signer_access.view','m4.signer_access.request','m4.signer_access.approve');
```
An toàn khi chưa có request/grant nào (dormant). Code rollback: revert commit; router/worker feature-detect
(bảng thiếu → no-op), permission UNION feature-detect → không vỡ.
