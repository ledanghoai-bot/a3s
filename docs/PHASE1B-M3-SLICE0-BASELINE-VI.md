# Phase I-B M3 — Slice 0: Baseline evidence + Governance artifacts

> Theo `A3S-PHASE1B-M3-DEV-DIRECTIVE-001` v1.0.0 (issued 2026-07-28 00:04+07:00) §3, §5 Slice 0.
> Spec chi phối: `A3S-PHASE1B-M3-SPEC-001` v1.0.0.

## 1. Baseline verification (Directive §3)

Môi trường: Windows 10, Git Bash, repo `D:\alpha3s`.

| Bước | Lệnh | Kết quả | Thời điểm |
|---|---|---|---|
| Xác minh object base | `git cat-file -e 9b49628a83ba1fe02b97913f20f33e4883560b5b^{commit}` | EXIT=0 | 2026-07-28 00:08+07:00 |
| Checkout detached | `git checkout --detach 9b49628a83ba1fe02b97913f20f33e4883560b5b` | HEAD tại 9b49628 | 2026-07-28 00:08+07:00 |
| Tạo branch | `git switch -c feat/phase1b-m3-compliance-sensor-foundations` | OK | 2026-07-28 00:08+07:00 |
| `git rev-parse HEAD` | — | `9b49628a83ba1fe02b97913f20f33e4883560b5b` | 2026-07-28 00:08+07:00 |
| `git status --short` | — | (rỗng — working tree sạch) | 2026-07-28 00:08+07:00 |
| Branch point | exact accepted RC M2 (không phải head di động `a15d65c`, không phải `main c210a84`) | đúng Directive §2.1 | — |
| Upstream | chưa push (sẽ push khi tạo draft PR) | — | — |

## 2. Migration manifest 001–028 (Directive §3.4–3.5)

- Đếm: `ls migrations/*.sql | wc -l` → **28** (EXIT=0).
- Checksum toàn bộ: `sha256sum migrations/*.sql` → manifest đầy đủ lưu tại §5 dưới.
- Xác minh migrations M2 không bị sửa: `git diff --stat 9b49628…  -- migrations/` → **rỗng** (EXIT=0)
  — working tree đúng bằng RC, do đó 021–028 giữ nguyên checksum RC.
- Checksum 021–028 (SHA-256, trích từ manifest):

```text
7caabf5a3f2bf9d58d5d0e2a8322756b32d77a05d68731ff5ee96f8ffff95707  021_inventory_core.sql
c6149ee3847478276baf469db41539b74d4e24834d9f7add8d2a822404f53fd1  022_order_events.sql
7572000cae49ebe11a53da939f27a743829ec0a694e8a1c471f20d4dd9367db0  023_inventory_adjustment_rbac.sql
67319a592ec13e8baf6c152eb8b59ba32cb3b6c58b2eafd5519294af1422931b  024_runtime_db_role.sql
fe34594dbc0ebef9a5ce2629f095fbeb8784f416cf50e1b594014e7a78b2737e  025_order_status_expand.sql
b692619e383bce9e7acceb22e9db6d213491b7efa9c1abd79215b58eded9494e  026_order_mutation_rbac.sql
f3498ec2a4a204567b7843faff64259555b4d1702929694f760a4e2aaa0bfb38  027_order_origin_channel.sql
81accd52ccb6b7b993dea9c063800bb3a9fb051e6aba64dbd4d83e8e1f1e0526  028_products_stock_nonneg.sql
```

- Migration đầu M3 = **029** (Directive §6, khóa). Kiểm tra `029` chưa bị chiếm: không tồn tại
  `migrations/029_*.sql` tại base (danh sách 28 file kết thúc ở 028).

## 3. Fact baseline liên quan M3 (xác minh trên RC, 2026-07-28 00:0x+07:00)

- `orders.status` CHECK hiện hành (migration 025): `new, confirmed, processing, ready_for_fulfillment,
  fulfilled, delivery_failed, return_requested, return_inspection, completed, cancelled,
  cancelled_by_exception, shipped, done` → **đã có `delivery_failed`, CHƯA có `delivered`**;
  chưa có cột `delivered_at`. Migration 029 (S1) chỉ cần expand thêm `delivered` + `delivered_at`.
- Outbox M1 (`outbox_events` + `delivery_attempts` + worker) có 3 destination:
  `telegram_admin`, `messenger`, `telegram_customer` (`app/services/command/outbox_worker.py:161`)
  — nền tái dùng cho Dispatcher S5.
- Self-service deletion qua chat đã có trên RC (`app/services/data_deletion.py`): XOA DU LIEU →
  xác nhận → xóa messages/escalations/conversations + ẩn danh orders/customers + xóa Redis
  `chat:{psid}`/`profile:{psid}` + confirmation code + status URL. Đầu vào cho DSR Runbook.
- LLM vendor call (`app/services/orchestrator.py`): system prompt + toàn bộ history (Redis, TTL ~24h)
  + message hiện tại gửi thẳng `https://api.deepseek.com` model `deepseek-v4-flash` (config.py:35-36).
  Đầu vào cho Vendor Review / AI Use Case Register (hiện trạng TRƯỚC M4).

## 4. Danh mục artifacts Slice 0 (spec §7.1 — đủ, không template trống)

| Artifact | File | Trạng thái |
|---|---|---|
| Sensor Inventory | `docs/SENSOR-INVENTORY.md` | tạo trong slice này |
| Data Classification Catalog | `docs/DATA-CLASSIFICATION-CATALOG.md` | tạo trong slice này |
| Processing Purpose Registry | `docs/PROCESSING-PURPOSE-REGISTRY.md` | tạo trong slice này |
| Vendor/Subprocessor Register (DeepSeek/Meta review) | `docs/VENDOR-SUBPROCESSOR-REGISTER.md` | tạo trong slice này |
| AI Use Case Register | `docs/AI-USE-CASE-REGISTER.md` | tạo trong slice này |
| Retention Schedule | `docs/RETENTION-SCHEDULE.md` | tạo trong slice này |
| DSR Runbook + Deletion Propagation Map | `docs/DSR-RUNBOOK-VI.md` | tạo trong slice này |
| Moment Memory seed (3 moment) | repo A3s-orbit: `E:\A3s-orbit\Dev\moment-memory\` | tạo trong slice này (ngoài core, đúng Directive §5-S0) |

## 5. Manifest checksum đầy đủ 001–028

(sha256sum, sinh 2026-07-28 00:09+07:00, EXIT=0 — bản gốc kèm evidence package)
