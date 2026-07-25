---
id: A3S-PHASE1B-AUTH-SESSION-DECISION-RECORD-001
title: Alpha3S I-B M0 — Auth/Session Decision Record (bearer token storage)
document_type: architecture_decision_record
parent: A3S-PHASE1B-IMPLEMENTATION-PLAN-001
owner: Alpha3S
author_role: Dev
version: 1.0.1
status: po_accepted_csp_condition_met_pending_ca_activation
po_signoff: "PO approved 2026-07-25 (temporary localStorage exception, risk owner = PO)"
created_at: 2026-07-25
last_updated: 2026-07-25 15:07 GMT+7
language: vi-VN
---

# ADR — Auth/Session token storage (CA-REVIEW-M0-DEV-002 §9)

## 1. Bối cảnh & hiện trạng (as-built)
- Session token: `secrets.token_urlsafe(32)`, lưu bảng `staff_sessions`, gửi qua header
  `Authorization: Bearer <token>`. Dashboard lưu token trong **`localStorage`** (`dashboard/lib/api.js`).
- **TTL:** trước 7 ngày; **ĐÃ hạ xuống 48h** (CA-REVIEW-M0-DEV-003 §8) — cấu hình `settings.session_ttl_hours`
  (mặc định **48**), production đặt ≤48h.
- **Revocation:** logout xóa 1 session; đổi mật khẩu / deactivate → **revoke-all-sessions**; `is_active`
  bị kiểm mỗi `validate_session`. **Refresh token: KHÔNG có** (token dùng tới hết TTL).
- **CSP dashboard (v1.0.1 — ĐÃ NÂNG CẤP nonce-based, CA-REVIEW-M0-DEV-004 §5):** API có
  `frame-ancestors 'none'` (M0.5). Dashboard Next.js chuyển từ CSP tĩnh (còn `unsafe-inline`) sang
  **nonce-based CSP qua `dashboard/middleware.js`** (Next 14 App Router): `script-src 'self' 'nonce-<random>'
  'strict-dynamic'` — **ĐÃ BỎ `'unsafe-inline'` cho `script-src`**. `next.config.mjs` bỏ header tĩnh
  (middleware sở hữu CSP). ⇒ **inline-script do XSS chèn KHÔNG có nonce → không chạy → không đọc/exfil được
  token trong `localStorage`** (đúng threat model §2). **Verified (evidence v1.0.2):** header CSP có nonce +
  strict-dynamic, **không** unsafe-inline trong `script-src`; nonce **đổi mỗi request**; browser smoke —
  dashboard render + hydrate đầy đủ, **0 CSP violation**, 0 console error. `style-src` giữ `'unsafe-inline'`
  (inline style không execute → không exfil; style-nonce là follow-up UX, không phải điều kiện gate).
  ⇒ **Điều kiện kích hoạt exception (nonce CSP) ĐÃ ĐẠT.**
- **Topology:** API `a3s.robanme.com` vs dashboard `a3s-dash.robanme.com` → **khác subdomain**, XHR
  dashboard→API là **cross-origin**.

## 2. Threat model (XSS / token theft)
- **Mối đe dọa chính:** XSS trong dashboard → JS đọc `localStorage` → **exfiltrate token** → attacker
  đóng vai staff tới hết TTL (7 ngày) trên **mọi máy** (token bearer không gắn thiết bị).
- **Bề mặt tấn công:** dashboard Next (hand-rolled, không component lib) render dữ liệu do staff/khách
  nhập (tên/địa chỉ/nội dung chat) → nếu render không escape → stored XSS.
- **Giảm nhẹ hiện có:** API security headers; token không phải cookie nên **không tự gửi kèm** (giảm CSRF
  cho luồng hiện tại). **Chưa đủ**: localStorage vẫn đọc được nếu có XSS.

## 3. Hai phương án

### 3.1. HttpOnly cookie (preferred, an toàn hơn)
- Token trong cookie **HttpOnly + Secure + SameSite** → JS **không đọc được** → XSS không exfiltrate token.
- **Chi phí cross-subdomain (thật):** dashboard↔API khác subdomain → cookie phải `Domain=.robanme.com` +
  `SameSite=None; Secure` để gửi cross-origin XHR → **bắt buộc CSRF protection** (double-submit token /
  origin check) vì cookie tự gửi. Kèm: đổi login set-cookie, `apiFetch` `credentials:'include'`,
  `require_staff_session` đọc cookie, **session rotation** sau login/đổi mật khẩu.
- **Khối lượng:** trung bình (CSRF machinery + đổi luồng auth 2 phía).

### 3.2. Temporary exception — giữ localStorage (ít việc M0)
- Giữ nguyên, KÈM: (a) **CSP chặt cho dashboard** (`script-src 'self'`, không inline script); (b) rút
  **TTL** (đề xuất 7 ngày → **24–48h**) + revoke-all đã có; (c) API headers (đã có).
- **Rủi ro tồn dư:** nếu có XSS vẫn mất token trong cửa sổ TTL.

## 4. QUYẾT ĐỊNH (Dev đề xuất — chờ PO/CA ký)
> **Chọn 3.2 (Temporary exception) cho M0**, với **deadline bắt buộc** migrate sang **3.1 (HttpOnly
> cookie + CSRF) trước Milestone M6** (khi dashboard chạm payment/COD — mục tiêu giá trị cao).

**Lý do:** M0 foundation dashboard chưa xử lý tiền; cookie+CSRF cross-subdomain là công lớn, không cân
xứng ở M0. localStorage + CSP chặt + TTL ngắn + revoke-all là mức chấp nhận được **có thời hạn**.

## 5. Acceptance criteria của migration (3.2 → 3.1, trước khi đóng gate)
- [ ] Cookie HttpOnly+Secure+SameSite phù hợp; token không còn trong `localStorage`.
- [ ] CSRF protection cho state-changing request (cookie cross-site).
- [ ] Session rotation sau login + đổi mật khẩu; revoke-all vẫn hoạt động.
- [ ] Dashboard CSP resource-level được test trên `a3s-dash.robanme.com`.
- [ ] TTL production ≤ 48h (hoặc refresh-token có revoke).

## 6. Owner, deadline, ràng buộc (CA §9)
- **Risk owner (nghiệp vụ):** PO. **Phê duyệt kiến trúc:** CA (sau khi ADR đủ evidence — bản này).
- **Deadline:** trước M6.
- **Trong thời gian chưa quyết:** **KHÔNG** mở rộng exception sang payment/chức năng rủi ro tài chính;
  **KHÔNG** coi security gate đã đóng (CA §9).
- **Việc kèm ngay ở M0 nếu chọn 3.2:** set CSP dashboard + rút TTL (2 việc nhỏ, Dev làm khi PO chốt).

## 7. Cập nhật v1.0.1 — điều kiện nonce CSP đã đạt (CA-REVIEW-M0-DEV-004 §5)
CA §5 nêu: exception chưa activatable khi CSP còn `unsafe-inline`. Dev đã hoàn thành **lựa chọn (1)** —
nonce/hash-based CSP loại bỏ `unsafe-inline` cho `script-src`, có **browser smoke** + **kiểm header
production-ready** (evidence Package v1.0.2: E-CSP header assertion + per-request nonce + browser 0-violation).
⇒ Rào chắn kỹ thuật của exception được gỡ; **còn chờ CA verify + activation approval** (không tự coi đã mở).
TTL 48h vẫn giữ (không thay CSP). Deadline HttpOnly cookie+CSRF trước M6 **không đổi**.

## Ký
```text
AUTH/SESSION ADR v1.0.1
[PO SIGN-OFF] PO CHAP NHAN temporary exception localStorage cho M0 (risk owner = PO), 2026-07-25.
  Kem dieu kien: nonce CSP truoc kich hoat -> DA IMPLEMENT + VERIFY (v1.0.1); TTL da ha 48h;
  KHONG mo rong sang payment/refund; deadline HttpOnly cookie+CSRF truoc M6.
[CONDITION MET] nonce-based CSP (dashboard/middleware.js) bo unsafe-inline script-src; browser+header smoke PASS
  (Evidence v1.0.2, SHA 8a702d6). Rao chan ky thuat da go.
[CHO CA] activation approval tren production (sau khi verify evidence CSP).
Author role: Dev (Alpha3S). Ngay: 2026-07-25 15:07 GMT+7.
```
