---
id: A3S-PHASE1B-M0-DEV-REPORT-001
title: Alpha3S I-B — Dev Report gửi CA: M0 development + rehearsal
document_type: dev_report_to_ca
responds_to: A3S-PHASE1B-CA-REVIEW-M0-DEV-002
reports_on: A3S-PHASE1B-IMPLEMENTATION-PLAN-001
plan_version: 0.1.3
owner: Alpha3S
author_role: Dev
version: 1.0.5
status: submitted_to_ca
created_at: 2026-07-25
last_updated: 2026-07-25
branch: phase1b-m0
commit_sha: 29ce7a4319117d40751e57a3c0e8079d0f42c204
evidence: A3S-PHASE1B-M0-EVIDENCE-PACKAGE-001
language: vi-VN
---

# Dev Report gửi CA — M0 development + rehearsal (v1.0.5)

> Bản phát hành **thống nhất một phiên bản** (chuẩn hóa theo CA-REVIEW-M0-DEV-002 §5, thay các bản
> 1.0.1-1.0.4 rời). Mọi kết quả dẫn tới **Evidence Package** (`A3S-PHASE1B-M0-EVIDENCE-PACKAGE-001`,
> commit `29ce7a4319117d40751e57a3c0e8079d0f42c204`) — không dùng chữ "chạy thật" thay cho đường dẫn
> evidence. Host production ghi bằng **alias** (`alpha3s-vps`), không IP.

## 0. Changelog (một dòng đời)
| Ver | Nội dung |
|---|---|
| 1.0.1 | 4 P0 runner fixed + negative rehearsal |
| 1.0.2 | M0.3 audit + M0.4 RBAC + M0.5 security |
| 1.0.3 | M0.2 DB pool 8/8 + KB layer-3 + phát hiện sự cố model DeepSeek |
| 1.0.4 | Auth session decision record + layer-3 post-014 |
| **1.0.5** | **Chuẩn hóa version + narrative; gắn Evidence Package (SHA); tách rõ production-change vs M0-migration** |

## 1. Ranh giới quan trọng — production (CA §5, §10)
**M0 migration KHÔNG chạm production.** Toàn bộ M0 dev/rehearsal chạy trên container tạm (đã xóa) + dev
stack; production baseline/migration/RBAC **chưa chạy, chưa được duyệt**.

**Đã có 2 phiên truy cập production RIÊNG BIỆT, mỗi phiên PO approve riêng — KHÔNG phải M0 migration:**
1. **Incident/config fix (LLM model)** — phiên change riêng, PO approve. Chi tiết §7.
2. **M0.0 production audit** — phiên read-only riêng, PO approve, không thực hiện thay đổi. Xem
   `A3S-PHASE1B-PROD-AUDIT-001`.

→ Không có mâu thuẫn "production vừa không đổi vừa đã sửa": **M0 migration không đổi production**; **LLM
config đã đổi trong một phiên incident riêng**; **audit là phiên read-only riêng**.

## 2. M0 development (đã implement, evidence §6)

**Migration runner** (`scripts/migrate.py`) — 4 P0 CA-REVIEW-M0-DEV-001 đã fix:
- Baseline chỉ tới `manifest.baseline_through`; `never_baseline:["014"]`; drift-check + atomic.
- Manifest verify đủ tables/columns/**constraints/indexes/prebaseline_data_assertions**, fail-closed.
- `up` chạy post-migration validation, fail → exit≠0.
- Corrective `014` DO-block executable pre/postcondition, RAISE→rollback→không ghi.
- Advisory lock fail-fast; non-transactional recovery note (plan §5.3-5.4).

**M0.2 DB pool** — 8 service (`handoff, orders, price_overrides, knowledge_entries, metrics, auth_service,
tools, rag`) → `acquire/release`; sizing `min1/max5` + command_timeout; pool lazy (sau fork); lifecycle
`close_pool` (FastAPI lifespan + arq on_shutdown).

**M0.3 Audit** (`audit_service.py`, `015_audit_log.sql`) — nhóm A fail-closed cùng transaction + redaction;
actor `actor_type/actor_ref/actor_staff_id`; append-only **convention** (DB-role enforcement = §5 release-gate).

**M0.4 RBAC** (`016_rbac.sql`, `permission_service.py`) — roles/permissions/role_permissions +
`staff_users.role_key`; mapping **KHÔNG** seed migration (đề xuất `rbac_seed_proposed.sql` chờ PO); no-cache;
`require_permission` (403); staff CRUD hardened (last-admin guard, no-escalation, audit fail-closed).
Backward-compat degrade **chỉ dùng trong dev rollout** — sau production cutover phải strict (CA §7, xem §4).

**M0.5 Security** (`app/security/`, `017_auth_hardening.sql`) — login throttling đa chiều (fail-open),
password change + revoke-all-sessions, `must_change_password` restricted session, security headers.

## 3. 3 lớp validation (CA §8 — tách, không gom 1 PASS)
- **Lớp 1 SQL** (`fresh_db_seed_validation.sql`): exact approved description + exact tiers + serving NULL +
  net_weight 100 → PASS (Evidence E1/E4/E6).
- **Lớp 2 application** (`app_integration_validation.py`, `m0_foundation_validation.py`): search_products
  không serving_info; audit fail-closed + redaction; RBAC least-privilege → PASS (Evidence E2/E3).
- **Lớp 3 KB/UAT smoke** (LLM): brand-truth PASS (Robusta+Arabica, không "100% Robusta"); serving post-014
  → bot không còn "50 ly". *(Chạy trên dev stack + throwaway; sender test đã dọn net-zero.)*

## 4. Đáp ứng release-gate CA (điều kiện trước production)
- **RBAC (CA §7):** đồng ý không seed mapping trong migration. **Còn nợ code:** (a) strict-mode sau
  provisioning (không degrade sau cutover); (b) startup/readiness **fail nếu RBAC provisioned nhưng
  catalog/mapping thiếu**. → làm ở batch tiếp + existing-staff worksheet (`PHASE1B-RBAC-STAFF-WORKSHEET`).
- **Audit (CA §8):** liệt kê chính xác nhóm A; integration test audit-rollback nhiều case; **hạn chế
  UPDATE/DELETE `audit_log` cho app runtime role HOẶC time-boxed exception có owner/deadline**; mở rộng
  redaction (phone/email/address/nested). → batch tiếp (audit release-gate).
- **Auth/session (CA §9):** decision record đầy đủ (threat model, TTL, refresh/revocation, CSP, CSRF,
  deadline/owner/acceptance) → `PHASE1B-AUTH-SESSION-DECISION-RECORD` (batch tiếp). Trong khi chờ: **không**
  mở rộng exception sang payment; **không** coi security gate đã đóng.

## 5. M0.0 Production audit (tóm tắt — xem `PHASE1B-PROD-AUDIT-VI.md`)
Read-only, PO approve. Production ở **012+013** (data_deletion áp tay, M0 chưa áp) → **baseline_through=13**;
volume nhỏ (2 đơn/1 SP/2 staff) → migration window low-risk (nhưng **low-risk ≠ no-risk**, CA §4.2: vẫn
backup + window + runbook + verify IN-list + verify staff/role). Anomaly "100% Robusta" + `serving_size_g=2`
**confirmed live** → 014 cần chạy production. **2 blocker vận hành (CA §4.3):** 1 tracked-file drift +
backup/restore chưa xác minh (`.env.bak` KHÔNG phải backup DB).

## 6. Immutable evidence (CA §6)
`A3S-PHASE1B-M0-EVIDENCE-PACKAGE-001` — full SHA `29ce7a4319117d40751e57a3c0e8079d0f42c204`, git status
clean tại revision test, artifact list + checksum, 6 kịch bản (E1-E6) với exact command + exit code +
sanitized log + mapping assertion→test. *(Đây thay cho "commit SHA gửi sau" ở bản cũ.)*

## 7. Incident/config change — LLM model DeepSeek (§10 CA, phiên riêng)
- **Bản chất:** vendor deprecate model name `deepseek-chat` (API 400 → bot trả fallback mọi tin nhắn).
  **Không phải migration M0.**
- **Thời điểm + quyền:** 2026-07-25, **PO approve** phiên change (dev) và phiên SSH production riêng.
- **Giá trị cũ → mới (không secret):** `LLM_MODEL: deepseek-chat → deepseek-v4-flash`.
- **Dev:** sửa `.env` dev + `config.py` default; `docker compose up -d --force-recreate` (env_file nạp lúc
  create — `restart` không đủ).
- **Production (`alpha3s-vps`, `/srv/alpha3s`, `docker-compose.prod.yml`):** backup `.env`→`.env.bak.pre-llmfix`;
  đổi `LLM_MODEL`; `up -d --force-recreate api worker telegram_bot telegram_customer_bot`.
- **Container recreate:** 4 service; **health/smoke:** api healthy, 8/8 Up, gọi LLM cô lập `MODEL_OK`, bot
  trả lời thật (hết fallback).
- **Rollback:** khôi phục `.env.bak.pre-llmfix` + `up -d --force-recreate`.

## 8. Đề nghị CA & việc còn lại
**Đề nghị:** ghi nhận Evidence Package (§6) để chuyển 4 P0 từ `reported closed` → `CA verified closed`;
chấp nhận prod audit (đã có pre-release actions).
**Batch tiếp (Dev, development):** strict RBAC + startup readiness check; audit release-gate (group-A list +
rollback integration tests + redaction mở rộng + DB-role/time-boxed exception); auth session decision
record; existing-staff worksheet.
**Cần PO:** duyệt ma trận role→permission; gán role 2 staff; localStorage risk-acceptance.
**Cần user/ops (production):** verify tracked-file drift; backup DB mới + restore evidence.
**KHÔNG chạy** production baseline/migration/RBAC tới khi CA release approval + PO gates + cleanup.

## Ký
```text
DEV REPORT — A3S-PHASE1B-M0-DEV-REPORT-001 v1.0.5 (thong nhat version)
M0 development + rehearsal + M0.0 prod audit hoan tat; evidence tai commit
29ce7a4319117d40751e57a3c0e8079d0f42c204 (Evidence Package rieng).
Production M0 migration: KHONG chay (chua duoc duyet). 2 phien production rieng (LLM incident fix + audit
read-only) deu PO approve — tach bach voi M0 migration. Release gate OPEN; cho CA verified-closed + PO
gates. Author role: Dev (Alpha3S). Ngay: 2026-07-25.
```
