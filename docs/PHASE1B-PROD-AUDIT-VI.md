---
id: A3S-PHASE1B-PROD-AUDIT-001
title: Alpha3S I-B M0.0 — Production Audit Report (read-only)
document_type: production_audit_report
parent: A3S-PHASE1B-IMPLEMENTATION-PLAN-001
owner: Alpha3S
author_role: Dev
version: 1.0.0
status: submitted_to_ca
created_at: 2026-07-25
language: vi-VN
---

# M0.0 — Production Audit Report (read-only)

> Thực hiện theo CA-REVIEW-IMPL-M0 §2 + CA-REVIEW-M0-DEV §11 (Dev chạy M0.0 sau khi PO cấp quyền
> read-only). PO (anh Hoài) đã approve truy cập VPS trong phiên này. **Chỉ đọc — không baseline, không
> migration, không đổi config trong phiên audit.** Raw output lưu ở scratchpad (access-controlled), report
> này chỉ chứa aggregate/anomaly, KHÔNG PII.

## 0. Identity block (CA §7.3)

| Trường | Giá trị |
|---|---|
| Host | `azvps-1784814855` (VPS 160.30.157.235) · user `root` |
| Environment | Production · `/srv/alpha3s` · `docker-compose.prod.yml` |
| DB | `alpha3s` · PostgreSQL 16.14 (pgvector image) · volume `alpha3s_pgdata` |
| Audit time | **2026-07-25 04:42:30 UTC** (11:42 +07) |
| Git commit đang chạy | `c210a84c256c970a345a4eec2061a31666fe8ca7` (branch `main`; **1 tracked file dirty** — xem §3) |
| Image (api) | `alpha3s-api` (local build) |
| Schema fingerprint | `552ad05c8471d435a33ce5b7feaf611b` (120 columns) |
| Read-only statement | Toàn bộ query bọc `BEGIN; SET TRANSACTION READ ONLY; … ROLLBACK` — `transaction_read_only=on` xác nhận; mọi lệnh ghi bị Postgres từ chối |
| Operator | Dev (Claude Code) qua SSH key-based `alpha3s-vps`, PO approve phiên này |
| Access | SSH đã cấu hình sẵn (không nhập credential); truy cập read-only |

## 1. Phương pháp
`scripts/prod_audit.sql` (đã validate trên throwaway) pipe qua SSH stdin vào
`docker compose -f docker-compose.prod.yml exec -T db psql -U alpha3s -d alpha3s -f -`. Tách **DB audit**
(SQL) và **cutover/deployment audit** (lệnh read-only ngoài SQL) — CA §7.1.

## 2. Database audit

### 2.1. Schema state → baseline threshold = **13**
| Check | Production |
|---|---|
| `schema_migrations` (đã dùng runner?) | **false** → chưa có migration tracking |
| `products.net_weight_g` / `serving_size_g` (≥012?) | true / true |
| `data_deletion_requests` (013 áp tay?) | **true** |
| `staff_users.role_key` (016 RBAC?) | false |
| `audit_log` (015?) | false |

→ Production đang ở **012 + 013 (data_deletion áp ngoài luồng), M0 chưa áp**. Khi migrate: dùng
**`baseline_manifest_13.json`** (baseline 001-013, verify `data_deletion_requests`), rồi runner áp
`014_correct_product_seed` + 015/016/017. **Khớp giả định dev**, và giải thích vì sao cần manifest-13.

### 2.2. Data volume (aggregate, KHÔNG PII)
`orders=2` (đều status `new`), `order_items=2`, `products=1`, `customers=2` (prefix: 1 telegram · 1
messenger/khác · 0 manual), `conversations=2`, `messages=48`, `escalations=1`, `price_overrides=0`,
`staff_users=2`, `kb_units=364`, `knowledge_chunks=0` (RAG cũ rỗng — KB V2 là nguồn thật).

→ **Volume thương mại rất nhỏ (2 đơn, 1 SP)** → giả định "cửa sổ migration low-risk" **được xác nhận trên
production**. **KHÔNG cần backfill rehearsal nặng cho M2** (điều kiện CA §4.2 gỡ). *Lưu ý:* **có 2 staff
thật** → khi áp RBAC (016) phải theo quy trình existing-staff (audit → PO gán role → backfill), **không**
mặc định `viewer`.

### 2.3. Data anomalies (khớp CA-CHECK §3 — CONFIRMED trên production)
- **`3S-100G` còn claim "100% Robusta"** = **true** → trái Brand Truth, đang live.
- **`3S-100G` `serving_size_g = 2.00`** (net_weight 100) → unsupported serving, bot suy "~50 ly".

→ **Migration `014` (corrective) cần chạy trên production.** *Điều kiện trước khi ký/chạy 014 prod:* xác
minh mô tả production khớp IN-list known-bad của 014 (nếu là biến thể khác → postcondition fail-closed sẽ
chặn, buộc bổ sung variant). Đây là dữ liệu mô tả (không PII) — kiểm ở bước chuẩn bị migration prod, ngoài
phiên audit này.

## 3. Cutover / deployment audit (ngoài SQL — CA §7.1)
- **8/8 container running**: api, worker, telegram_bot, telegram_customer_bot, dashboard, db, redis, caddy.
- **Git**: branch `main` @ `c210a84`; **1 tracked file dirty** trên production working tree → *cần verify
  drift* (có thể sót từ thao tác trước; không phải `.env` vì `.env` gitignored). Branch M0 (`phase1b-m0`)
  **chưa deploy** — đúng (M0 chưa được release).
- **LLM model**: container api `LLM_MODEL=deepseek-v4-flash` → **sự cố `deepseek-chat` đã fix trên
  production** (phiên "Production LLM model configuration", 25/7); backup `.env.bak.pre-llmfix` tồn tại.
- **Telegram**: admin bot `@Ben3s_bot` active (getMe OK).
- **Meta webhook / carrier**: chưa kiểm trong phiên này (cần Graph API/Meta dashboard) — để checklist.
- **Backup/restore readiness**: thấy `.env.bak.pre-llmfix`; **chưa xác minh cron pg_dump ngày** (memory
  `vps-production` nhắc backup VPS chỉ theo tuần → cần cron pg_dump) — **khuyến nghị verify trước mọi
  migration production**.

## 4. Kết luận & tác động tới plan
1. **Baseline threshold production = 13** → dùng `baseline_manifest_13.json` (không phải manifest-12 như
   env 012 thuần).
2. **Cửa sổ migration low-risk XÁC NHẬN** (2 đơn, 1 SP) → không cần backfill rehearsal nặng (gỡ điều kiện
   CA §4.2 về "không dùng row count local để kết luận").
3. **Anomaly 014 confirmed live** → 014 cần chạy production (khi CA release approval). Kiểm IN-list mô tả
   trước.
4. **2 staff thật** → RBAC (016) theo quy trình existing-staff, PO gán role, KHÔNG default viewer.
5. **1 file dirty trên main production** + **backup ngày chưa xác minh** → 2 việc cần làm sạch trước
   production migration.
6. Mâu thuẫn "pre-cutover" (đã rút lại ở feasibility v0.1.1) → **thực tế production đang live** (2 đơn, 48
   msg, bot chạy) — không còn "pre-cutover".

## 5. Ràng buộc CA §11 — đã tuân thủ
- [x] Read-only (transaction READ ONLY + ROLLBACK; write bị từ chối).
- [x] Không PII/secret trong report (chỉ aggregate/anomaly/prefix; không raw psid/phone/address/mô tả/token).
- [x] Raw output lưu access-controlled (scratchpad phiên, không commit).
- [x] Identity block đầy đủ (§0).
- [x] Tách DB audit / cutover audit.
- [x] **Không** chạy baseline/migration trong phiên audit.
- Nhắc: production audit ≠ production migration approval (vẫn cần CA release approval + PO gates).

## Ký
```text
PROD AUDIT — A3S-PHASE1B-PROD-AUDIT-001 v1.0.0
Read-only production audit tren VPS 160.30.157.235 (PO approve phien nay). Production = schema 012+013
(data_deletion ap tay), M0 chua ap, baseline_through=13; volume nho (2 don/1 SP) -> migration window
low-risk XAC NHAN; anomaly "100% Robusta" + serving=2 CONFIRMED live -> 014 can chay prod; 2 staff that
-> RBAC theo quy trinh existing-staff. Khong PII, khong ghi, khong migration trong phien.
Author role: Dev (Alpha3S). Ngay: 2026-07-25
```
