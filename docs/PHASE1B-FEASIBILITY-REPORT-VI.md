---
id: A3S-PHASE1B-FEASIBILITY-REPORT-001
title: Alpha3S Giai đoạn I-B — Báo cáo phân tích tính khả thi (Dev)
document_type: architecture_feasibility_report
in_response_to: A3S-PHASE1B-CA-FEASIBILITY-001
responds_to_review: A3S-PHASE1B-CA-REVIEW-001
owner: Alpha3S
author_role: Dev
version: 0.1.1
status: revised_for_ca_reapproval
created_at: 2026-07-24
last_updated: 2026-07-24
language: vi-VN
---

# Alpha3S I-B — Báo cáo phân tích tính khả thi (v0.1.1)

> Trả lời đề bài `A3S-PHASE1B-CA-FEASIBILITY-001`, đã sửa theo phản biện CA `A3S-PHASE1B-CA-REVIEW-001`
> (APPROVE WITH REQUIRED AMENDMENTS). Mọi nhận định dẫn chứng bằng file/function/schema thật. Xem phần
> phản hồi từng amendment ở `PHASE1B-FEASIBILITY-DEV-RESPONSE-VI.md`.

## 0. Changelog v0.1.0 → v0.1.1 (map theo amendment CA)

| CA | Nội dung | Xử lý ở v0.1.1 |
|---|---|---|
| P0 §4.1 | Đánh giá sai state machine (nói đã cấm nhảy bước) | §3.1 sửa lại đúng: chỉ chặn lùi, KHÔNG chặn skip-forward; thêm transition matrix M2 |
| P0 §4.2 | Chưa chứng minh production DB | §2 nói rõ chỉ query Docker local `172.18.0.3`; **production KHÔNG được xác minh độc lập**; production audit = prerequisite M0 |
| P0 §4.3 | Không đồng nhất outbox = lời giải toàn bộ | §6 thay bằng bảng phân rã 4 vấn đề → 4 năng lực |
| P0 §4.4 | `sent` flag chưa đủ chống gửi trùng | §6.1 thêm outbox failure semantics đầy đủ; mục tiêu at-least-once + effective-once |
| P0 §4.5 | Address phải nằm trong I-B Core Release | §9/§10 đổi tên: Core Stabilization Slice (M0-M3) ≠ I-B Core Release (M0-M6) |
| P1 §5.1 | Nguồn dữ liệu hành chính | §7.1 phân biệt repo (đóng gói) vs văn bản pháp luật (authoritative) + dataset acceptance gate |
| P1 §5.2 | Dataset hỗ trợ as_of + snapshot | §7.2 thêm `as_of=now/<date>`; đơn cũ không đổi theo dataset mới |
| P1 §5.4 | Inventory balance + immutable ledger | §6.3 thêm `inventory_balances` + `inventory_movements` |
| P1 §5.5 | Reservation policy baseline | §6.4 thêm bảng vòng đời reservation |
| P1 §5.6 | Migration runner chưa khóa Alembic | §8.1 so sánh 3 phương án + đảo khuyến nghị sang lightweight runner |
| P1 §5.7 | M0 security baseline | §5.1 thêm danh sách security baseline |
| P1 §5.8 | Permission-based authz | §5.2 chuyển từ `require_role` sang `require_permission`; role = bundle |
| §6 | Sửa permission matrix | Phụ lục A sửa delivery/support/viewer/export + separation of duties |
| §10 | Release gates bổ sung | §11 cập nhật gate theo từng milestone |

---

## 1. Tóm tắt điều hành

**Kết luận (không đổi, CA đã ACCEPT): I-B khả thi trên chính kiến trúc hiện tại (modular monolith
FastAPI + PostgreSQL + Redis/arq), KHÔNG service mới, KHÔNG viết lại Core.** Phần lớn hạng mục là *thêm
bảng + thêm tool + thêm màn hình*, migration tăng dần.

**Ba đòn bẩy:**

1. **Cửa sổ migration.** DB **đã query (local Docker)** gần như trống dữ liệu thương mại (1 đơn, 1 sản
   phẩm, 0 staff). Nếu điều này cũng đúng trên production (chưa xác minh — §2), redesign schema nặng
   gần như không rủi ro backfill nếu làm sớm. **Điều kiện tiên quyết: audit production thật ở M0 trước
   khi kết luận.**
2. **Đã có mầm hạ tầng đúng hướng**: dedupe + dead-letter (`app/workers/tasks.py`), approval + cờ `used`
   (`price_overrides.py`), transaction + `FOR UPDATE` (`tools.py:189-241`), session-auth thay
   `ADMIN_API_TOKEN` (`auth_service.py`).
3. **Nợ kỹ thuật đã được team ghi nhận** (`docs/SALES-FLOW-CURRENT-STATE-VI.md`, `ISSUES-VI.md:1133`).

**Phạm vi (đã đổi tên theo CA §4.5):**
- **Core Stabilization Slice = M0-M3** — lát cắt ổn định hóa, trả 4 sự cố thật (ghost order, tra đơn,
  tồn kho sai, follow-up). **Đây KHÔNG phải toàn bộ I-B Core.**
- **I-B Core Release = M0-M6** — mới là I-B Core đầy đủ: + customer identity, multi-location, **address
  verification (current + legacy + staff, đã khóa bởi PO)**, delivery + payment baseline.
- **Commerce Growth = P2** — promotion/membership/affiliate/returns/reconcile.

---

## 2. §12.1 + P0§4.2 As-built & bằng chứng production (đã làm rõ)

Đã đọc trực tiếp toàn bộ service/worker/api/migration/dashboard/NLU (danh sách như v0.1.0).

**Bằng chứng schema/số liệu — nói rõ để tránh hiểu nhầm (sửa theo CA §4.2):**

| Hạng mục | Thực tế |
|---|---|
| DB đã query | **Instance Docker nội bộ `172.18.0.3`** (qua postgres MCP) — là DB **dev/compose local**, KHÔNG phải VPS production |
| Host/môi trường | Local Docker Compose trên máy dev |
| Schema version xác định qua | Đối chiếu `information_schema.columns` với `migrations/001-012` → khớp 012 |
| Row counts | Của **local**: 1 order, 1 order_item, 1 product, 24 customers/conversations, 154 messages, 0 staff_users, 0 price_overrides, 364 kb_units |
| Production VPS (`160.30.157.235`) | **KHÔNG query trực tiếp trong đợt này** — chưa xác minh độc lập |
| Mâu thuẫn "pre-cutover" | v0.1.0 gọi VPS "pre-cutover" là **suy luận từ CLAUDE.md/memory**, mâu thuẫn với `docs/PHASE1-COMPLETION-REPORT` (xác nhận đã cutover). **Rút lại khẳng định này** — trạng thái cutover/volume production phải xác minh ở M0 |

```text
Production data volume: not independently verified
```

**Hệ quả (điều kiện release):** **Production schema/data audit là prerequisite bắt buộc của M0.**
Không dùng row count local để kết luận rủi ro migration production ≈ 0. Kết luận "cửa sổ migration" chỉ
có hiệu lực SAU khi audit production xác nhận volume tương đương.

**Điểm as-built khác (không đổi):** `db_pool.py` chỉ 3/11 service dùng (churn kết nối — chuẩn hóa ở
M0); `create_order` không có idempotency key ở tầng command; Telegram xử lý inline không qua arq.

---

## 3. §12.1 As-built: đính chính nhận định

### 3.1. Sửa đánh giá state machine (CA P0 §4.1 — CHẤP NHẬN, v0.1.0 SAI)

v0.1.0 viết `validate_transition()` "đã cấm nhảy/lùi bậc" — **sai**. Code thật (`orders.py:21-41`) chỉ
có một guard chặn lùi:

```python
if _STAGES.index(new) < _STAGES.index(current):   # _STAGES = [new, confirmed, shipped, done]
    raise ValueError(...)
```

Nên các transition **skip-forward vẫn PASS**: `new→shipped` (0<2), `new→done` (0<3), `confirmed→done`
(1<3). Docstring nói "không nhảy cóc" nhưng code **không** enforce điều đó.

**Nhận định đúng (thay vào v0.1.1):**

> State machine hiện cấm đi lùi và kiểm soát một số nhánh hủy (`done→cancelled` bị chặn), nhưng **chưa
> cấm skip-forward**; validation chỉ nằm ở service dashboard (`orders.update_order_status`), **chưa được
> bảo vệ tại database/domain boundary dùng chung** (luồng LLM `create_order` insert thẳng `'new'`, không
> đi qua hàm này).

**M2 phải có transition matrix xác định + test tối thiểu (theo CA):**

| Transition | Kết quả |
|---|---|
| `new → confirmed` | pass |
| `confirmed → shipped` | pass |
| `shipped → done` | pass |
| `new → shipped` | reject |
| `new → done` | reject |
| `confirmed → done` | reject |
| `done → cancelled` | reject |
| Lặp lại cùng transition | idempotent |

### 3.2. Các nhận định khác (không đổi so với v0.1.0)

Ghost order guard = heuristic chuỗi (`orchestrator.py:38-56,304-330`); chỉ 4 tool, không có tool đọc
đơn; hủy đơn không hoàn tồn (`orders.py:76-86`); identity = `psid` + prefix kênh; `staff_users` không
có cột role, không audit (`auth_router.py:43`, `ISSUES-VI.md:207`). Tất cả **đúng** với brief §2.

---

## 4. §12.2 Feasibility từng capability

S≈1-3 dev-day, M≈4-10, L≈2-4 tuần (tương đối).

| # | Capability | Reuse | Schema mới | Est | Ghi chú |
|---|---|---|---|---|---|
| 6.1 | RBAC + audit + security baseline | auth_service, session | `permissions`, `role_permissions`, `staff_users.role`, `audit_log` | **M** | Permission-based (§5.2), không chỉ role |
| 6.2 | Customer + channel identities | customers | `customer_identities` | **M** | Migration ~24 dòng; rủi ro = merge |
| 6.3 | Store/warehouse/location | — | `locations` + FK | **M** | 1 location seed mặc định |
| 6.4 | Order lifecycle | validate_transition | 2 trục MVP → 4 trục; `order_events` | **M-L** | 2 trục ở Stabilization; payment/followup sau |
| 6.5 | Deterministic receipt | guard hiện có | dùng outbox | **S-M** | Render template từ tool result thật |
| 6.6 | Inventory balance + ledger | FOR UPDATE tx | `inventory_balances` + `inventory_movements` | **L** | Balance table + immutable ledger (§6.3) |
| 6.7 | Address verification | strip_diacritics | `admin_units` versioned + snapshot | **L** | **Trong I-B Core Release (M5)**, không optional |
| 6.8 | Delivery/fulfillment | orders | `shipments`, `delivery_attempts` | **M** | MVP nhập tay, không carrier API |
| 6.9 | Follow-up/outbound | dedupe+dead-letter | `outbox_messages`, `followup_jobs` | **M** | arq cron + outbox semantics (§6.1) |
| 6.10-6.14 | Promotion/member/affiliate/payment/returns | products, escalations | nhiều | **L×n** | **Growth P2** (payment_status baseline ở M6) |

**Không cần service/container mới** (CA đồng ý). Chỉ thêm 2 cron trong tiến trình arq đã có
(`outbox_dispatcher`, `followup_scheduler`) qua `cron_jobs` trong `WorkerSettings` (`tasks.py:105`).

---

## 5. Kiến trúc mục tiêu (bổ sung security + permission)

Giữ ranh giới brief §5. Thay đổi bên trong App: thêm `inventory_service`, `address_service`,
`outbox_service`, `audit_service`, `pricing_service` (P2), lớp `permissions`. Nguyên tắc: mọi mutation
→ service → DB trong 1 transaction → ghi outbox trong CÙNG transaction → dispatcher gửi + phát event;
**receipt render từ tool result, LLM không tự tuyên bố**.

### 5.1. Security baseline bắt buộc ở M0 (CA §5.7)

M0 không chỉ role/permission, phải phân tích và làm:
- Login throttling (chống brute-force); password change/reset; **revoke-all-sessions**; session cleanup
  (xóa token hết hạn khỏi `staff_sessions`).
- **Không cho disable admin cuối cùng**; **không cho staff tự nâng quyền**.
- **XSS risk**: bearer token đang nằm `localStorage` (`dashboard/lib/api.js`) → đánh giá chuyển
  httpOnly cookie hoặc chấp nhận rủi ro có kiểm soát + CSP; **security headers + CSP**.
- Audit: login success/failure, logout, activation, role/permission change.
- **Server-side authorization cho MỌI sensitive API** (không chỉ ẩn nút UI).

### 5.2. Permission-based authorization (CA §5.8)

Không khóa vào `require_role` thuần. Dùng permission là đơn vị nhỏ nhất; role là **bundle** permission:

```text
require_permission("inventory.adjust")
require_permission("order.cancel_after_fulfillment")
require_permission("customer.export")
```

Server-side permission check là bảo vệ chính; ẩn/hiện UI chỉ là UX. Bảng `permissions` +
`role_permissions` cho phép PO sửa mapping mà không đổi code.

---

## 6. Reliability: phân rã đúng (CA P0 §4.3) + outbox semantics (§4.4)

**Outbox KHÔNG phải lời giải cho cả 4 vấn đề.** Phân rã đúng theo năng lực:

| Vấn đề | Năng lực giải quyết chính |
|---|---|
| Ghost order | Transaction + **deterministic action receipt** |
| Không tra được đơn | **Order-read tools + authorization** |
| Sai tồn kho | **Reservation + inventory balance/ledger** |
| Follow-up không bền vững | **Scheduler + outbox + delivery attempts** |

Outbox là *nền vận chuyển tin cậy* chung cho receipt + follow-up, KHÔNG phải domain model của đơn/tồn.

### 6.1. Outbox failure semantics (M1) — `sent` flag không đủ (CA §4.4)

Kịch bản hỏng: *provider đã nhận → worker crash → DB chưa đánh dấu sent → retry gửi lần hai*. Thiết kế
M1 phải có:
- **`idempotency_key` ổn định** (theo business event, không theo thời gian).
- **Outbox state machine**: `pending → claimed → sent → confirmed | dead_letter`.
- **Delivery attempt records** (mỗi lần thử 1 dòng: thời điểm, kết quả, provider message id nếu có).
- **Atomic claim** bằng `SELECT ... FOR UPDATE SKIP LOCKED` + **lease/lock timeout** (worker chết →
  job được claim lại sau timeout).
- **Bounded retry** + **dead-letter** (tái dùng nền `dead_letter:messages`, `tasks.py:40-52`).
- **Reconciliation** cho request không rõ kết quả (provider timeout); **manual replay có audit**.
- **Dedupe tại channel adapter** nếu provider không hỗ trợ idempotency.

**Không cam kết exactly-once delivery.** Mục tiêu: **at-least-once transport + effective-once business
behavior** (business event chỉ áp dụng một lần nhờ `idempotency_key`, dù transport gửi ≥1 lần).

### 6.2. Deterministic receipt (M1)

Thay heuristic `_reply_claims_order_created` (`orchestrator.py:304-330`) bằng: tool trả order_id thật →
ghi business event `order_created` → render receipt bằng template xác định → đẩy outbox. **Chỉ gỡ guard
marker-string SAU khi receipt thay thế đã được chứng minh** (CA §7.1 M1).

### 6.3. Inventory: balance table + immutable ledger (CA §5.4)

Không tính tồn bằng cách cộng toàn bộ ledger mỗi request; cũng không giữ `products.stock` làm source of
truth. Mô hình:

```text
inventory_balances(location_id, product_id, on_hand, reserved, version)   -- version = optimistic lock
inventory_movements(location_id, product_id, movement_type, quantity,
                    reference_type, reference_id, idempotency_key,
                    actor, reason, created_at)                             -- append-only, immutable
```

Trong CÙNG transaction: (1) lock balance row → (2) validate available = on_hand−reserved → (3) update
balance (bump version) → (4) append movement (immutable) → (5) append business event/outbox record.
`products.stock` chỉ giữ làm **legacy compatibility field trong migration window**, hết là source of
truth sau cutover.

### 6.4. Reservation policy baseline (CA §5.5 — để PO chốt)

| Sự kiện | Hành động tồn kho |
|---|---|
| Draft | Chưa reserve |
| Khách xác nhận đơn | **Reserve** |
| Chờ staff/thanh toán | TTL mặc định **24h** (cấu hình được) |
| Staff confirm/processing | Gia hạn hoặc bỏ TTL |
| Fulfillment handover | Chuyển reserved → **fulfilled/deducted** |
| Cancel/expire | **Release** |
| Delivery failed/return | → **return inspection**, KHÔNG tự cộng vào sellable |
| Damaged return | KHÔNG về available |

**PO chốt** TTL + thời điểm reserve sau khi đối chiếu quy trình thực tế.

---

## 7. §12.2.5-7 Address verification (I-B Core Release, M5)

**As-built: không tồn tại** (chi tiết như v0.1.0: `address` free text `001_init.sql:8,44`; NLU chỉ ~33
tên hardcode `entity_extraction.py:39-46`; reuse được `strip_diacritics:49-52`). Offline-first khả thi
theo fallback đã khóa brief §6.7.2.

### 7.1. Nguồn dữ liệu: repo ≠ nguồn authoritative (CA §5.1)

Phân biệt rạch ròi:
- **Repository mở (vd ThangLeQuoc — MIT)**: *nguồn đóng gói/accelerator ingestion* — thuận tiện, có
  PostgreSQL dump, dẫn từ mã GSO. **KHÔNG gọi đây là "nguồn chính thức của Nhà nước".**
- **Nguồn authoritative**: văn bản pháp luật (Nghị quyết 202/2025/QH15, QĐ 19/2025/QĐ-TTg) + danh mục
  GSO `danhmuchanhchinh.nso.gov.vn`.

License approval **chỉ** xác nhận quyền dùng package, **không** xác nhận độ chính xác dữ liệu. Ingestion
phải: pin release/tag/commit hash; lưu provenance; lưu `dataset_version`, `effective_from/to`; checksum;
**không auto-activate dataset mới**; validation + approval trước publish; **rollback dataset**.

**Dataset acceptance gate (trước khi activate):**
1. Tổng số đơn vị khớp nguồn authoritative của version. 2. Administrative code duy nhất trong effective
range. 3. Mọi xã/phường có parent tỉnh hợp lệ. 4. Không có effective range chồng lấn cho cùng code.
5. Alias không override canonical name. 6. Legacy mapping có source + confidence. 7. Mapping one-to-many
**không auto-select**. 8. Import có checksum + test report.

### 7.2. Dataset hỗ trợ thời điểm (CA §5.2)

Address service hỗ trợ `as_of=now` (danh mục hiện hành) và `as_of=<date>` (tra/mapping lịch sử). **Order
lưu address snapshot + dataset version tại thời điểm xác minh; dataset mới KHÔNG tự đổi địa chỉ đơn cũ.**

### 7.3. Fallback đã khóa (CA §5.3)

`Current (sau 01/07/2025) → Legacy → Customer confirmation → Staff review`. Rule: LLM không tự chọn khi
nhiều candidate; khách không xác nhận được địa chỉ mới → cho xác nhận địa chỉ cũ; legacy vẫn không chắc
→ chuyển staff; **carrier/serviceability failure không biến thành verified**; **không tính cước từ free
text chưa xác minh** (`quote_shipping` nhận `verified_address_id`, không nhận string).

---

## 8. §12.3 Migration & compatibility

`expand → migrate → contract`, mỗi bước deploy độc lập (chi tiết psid→identities / stock→ledger / status
map như v0.1.0 §8, cộng thêm balance table §6.3). Backfill status cũ→mới: giữ `orders.status` đồng bộ 1
nhịp rồi cắt. Rollback = expand-only trong Core → revert code, giữ schema.

### 8.1. Migration runner: so sánh (CA §5.6 — Alembic CHƯA khóa)

| Phương án | Ưu | Nhược |
|---|---|---|
| **Lightweight runner + `schema_migrations`** (chạy các file `.sql` có thứ tự trong 1 transaction, advisory-lock chống chạy song song, checksum) | Khớp đúng migration raw-SQL đang có (`001-012`); **không kéo ORM chỉ để migrate**; ít phụ thuộc | Phải tự viết status/checksum/lock (~1 file nhỏ) |
| **Alembic + raw-SQL revisions** | Chuẩn cộng đồng, có status/history; `sqlalchemy` đã có sẵn trong `requirements.txt` | Kéo Alembic + gắn với SQLAlchemy metadata; nặng hơn nhu cầu; dự án cố ý tránh ORM |
| **Công cụ PG khác (sqitch/…)** | Forward-only tốt | Thêm dependency ngoài hệ Python |

Tiêu chí: lock chống chạy đồng thời ✔, checksum ✔, transaction-per-migration ✔, **forward-only ở
production** ✔, status command ✔, staging rehearsal ✔, không bắt buộc ORM ✔.

**Khuyến nghị Dev (ĐẢO so với v0.1.0):** **Lightweight runner + `schema_migrations`** — vì migration
hiện đã là raw SQL forward-only, dự án có bài học tránh thêm dependency/rebuild image, và nhu cầu chỉ
cần lock+checksum+status. Alembic là fallback chấp nhận được nếu sau này cần autogenerate. **PO/CA
chốt.**

---

## 9. Core Stabilization Slice (M0-M3) — lát cắt ổn định hóa

Giải đúng 4 sự cố thật. **Đây KHÔNG phải toàn bộ I-B Core** (CA §4.5). Nội dung theo cấu trúc CA §7.1:

- **M0 Foundation:** migration runner (§8.1); chuẩn hóa DB pool; audit_log; **permission framework +
  minimal RBAC**; **security baseline (§5.1)**; **production schema/data audit (§2)**.
- **M1 Reliable command & receipt:** command idempotency; transactional outbox + semantics (§6.1);
  delivery attempts; deterministic receipt; gỡ marker-string guard **sau khi** replacement được chứng
  minh.
- **M2 Order & inventory correctness:** 2-trục stabilization; **transition matrix (§3.1)**; order event
  timeline; inventory balance; reservation; immutable movement ledger; cancel/expire/release.
- **M3 Customer visibility & follow-up:** authorized order-read tools; shipping status read; confirmation
  reminder; shipping update; **staff-visible outbound queue**.

---

## 10. I-B Core Release (M0-M6) & Growth (CA §7.2-7.3)

- **M4 Identity & multi-location:** canonical customer; channel identities; default-location backfill;
  store/warehouse/fulfillment location.
- **M5 Address Verification:** versioned admin dataset (§7); current verification; legacy mapping;
  customer confirmation; staff review queue; address snapshot; dataset provenance + rollback.
- **M6 Delivery & payment baseline:** fulfillment board; carrier/tracking nhập tay; delivery
  attempts/status; **payment status/evidence độc lập với order/fulfillment**; COD collection record;
  customer notification qua outbox.
- **Commerce Growth P2:** price list, promotion/voucher, membership, affiliate/referral,
  returns/complaints, reconciliation, analytics.

**I-B Core Release chỉ hoàn thành khi có đủ** (CA §4.5): canonical identity + channel identities +
multi-location + current-address verification + legacy fallback + customer confirmation + staff review +
delivery/fulfillment baseline + payment status baseline.

**Đường găng:** M0→M1→M2→M3 (Stabilization) rồi M4→M5→M6. M4/M5 song song sau M0. M5 chặn bởi quyết định
license + owner cập nhật dataset của PO.

### 10.1. Ước lượng tương đối
Stabilization Slice (M0-M3) ~**L** (4-7 tuần); M4-M6 ~**L** (3-5 tuần); Growth P2 mỗi mảng **M-L**, chia
release riêng.

---

## 11. §13.10 + CA §10 Test strategy & release gates

Sandbox-first (quy ước dự án); migration rehearsal trên staging; cặp có-dấu/không-dấu cho address.

**Gate theo milestone (CA §10):**
- **M0:** production baseline được xác minh; permission enforced server-side; không disable admin cuối;
  sensitive action có audit; migration status/checksum/lock hoạt động.
- **M1:** không sinh receipt nếu business transaction không commit; retry không tạo business action
  trùng; **crash-after-provider-call được test**; dead-letter + replay có audit.
- **M2:** illegal transition bị reject (matrix §3.1); không oversell trong concurrent test;
  cancel/expire release đúng reservation; ledger + balance reconcile cùng kết quả; mọi movement có
  reference + idempotency key.
- **M3:** customer chỉ đọc order của chính mình; không lộ order qua đoán ID; follow-up tuân channel
  policy; staff thấy pending/failed/dead-letter.
- **M5:** dataset validation pass; current→legacy→staff fallback pass; ambiguous mapping không
  auto-select; không tính cước từ address chưa verified; dataset rollback được thử.
- **M6:** delivery/payment status độc lập order status; customer notification bind trạng thái thật; COD
  evidence và reconciliation authority được tách.

---

## 12. §12.4.4 + CA §9 Quyết định PO cần khóa

1. **Role–permission matrix** (Phụ lục A). 2. Reservation TTL + thời điểm reserve (§6.4). 3. Follow-up
use cases + consent + opt-out. 4. Ngưỡng approval: đơn lớn / giá đặc biệt / address override / inventory
adjustment / refund. 5. **Owner cập nhật dataset hành chính** + duyệt license (§7.1). 6. Phạm vi
payment/COD ở I-B Core. 7. Rule promotion/member/affiliate trước Growth. 8. Kết quả **production audit**
(§2) — xác nhận volume/cutover thật.

---

## 13. §12.5 + CA Risk register (cập nhật)

| Risk | P | I | Mitigation | Owner | Gate |
|---|---|---|---|---|---|
| Production volume/cutover khác giả định local (chưa xác minh) | TB | Cao | **Production audit là prerequisite M0**; không migrate khi chưa xác minh | Dev/PO | M0 |
| Outbox double-send / mất message khi crash | TB | Cao | idempotency_key + state machine + SKIP LOCKED + reconciliation (§6.1); at-least-once + effective-once | Dev | M1 |
| Skip-forward transition lọt (as-built) | Cao | TB | Transition matrix + DB/domain guard (§3.1) | Dev | M2 |
| Oversell khi đồng thời | TB | Cao | balance row lock + version (§6.3); concurrent test | Dev | M2 |
| Mapping cũ→mới không đủ / one-to-many | TB | Cao | Staff fallback bắt buộc; không auto-select; acceptance gate (§7.1) | PO/Dev | M5 |
| RBAC rò quyền (UI ẩn nhưng API hở) | TB | Cao | require_permission server-side (§5.2); separation of duties | Dev | M0 |
| Bearer token trong localStorage (XSS) | TB | TB | Đánh giá httpOnly cookie + CSP (§5.1) | Dev | M0 |
| Connection churn (8 service connect-per-call) | TB | TB | Chuẩn hóa db_pool ở M0 | Dev | M0 |
| Scope creep sang ERP/CRM/WMS | Cao | Cao | Bám Deferred brief §11 | PO/Dev | mọi M |

---

## 14. §10.5 VPS
4 vCPU/8 GB đủ cho phương án không thêm process nặng (CA đồng ý); 2 model embedding vẫn là hộ RAM chính;
outbox/cron nhẹ. **Bắt buộc đo trên staging** + thêm index/pagination (dashboard đang tải cả list,
`limit=200`).

---

## 15. Điều kiện Implementation Planning (CA §8) — self-check v0.1.1

1. Sửa state-machine ✔ (§3.1). 2. Làm rõ production evidence ✔ (§2). 3. Sửa vai trò outbox ✔ (§6).
4. Outbox failure semantics ✔ (§6.1). 5. Đổi tên milestone ✔ (§9-10). 6. Address vào I-B Core Release ✔
(§10 M5). 7. Dataset provenance/validation/versioning ✔ (§7.1-7.2). 8. Inventory balance + ledger ✔
(§6.3). 9. So sánh migration runner ✔ (§8.1). 10. Security baseline ✔ (§5.1). 11. Permission matrix ✔
(Phụ lục A). 12. Test strategy + gates ✔ (§11).

---

## Phụ lục A — Ma trận role → permission (đã sửa theo CA §6)

**Vì sao là quyết định PO/CA:** mỗi ô là chính sách kiểm soát rủi ro bằng tiền/tồn/đơn, không phải lựa
chọn kỹ thuật. Hiện phân quyền = 0 (`auth_router.py:43`, `ISSUES-VI.md:207`). Là xương sống của: (1)
enforce server-side (`require_permission`, §5.2 — KHÔNG chỉ ẩn UI); (2) approval framework §7.3 — ô ⚠️ =
"đẩy vào hàng chờ duyệt"; (3) audit.

**Chú thích:** ✅ trực tiếp · ⚠️ cần duyệt (approval) · ✎ propose-change (không tự sửa) · 👁️ xem (PII
masked) · ❌ không.

| Nhóm quyền | admin | sales | warehouse | delivery | support | viewer |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| Xem khách (PII masked theo quyền) | ✅ | ✅ | 👁️ | 👁️ | ✅ | 👁️ mask |
| Sửa khách (tên/SĐT) | ✅ | ✅ | ❌ | ❌ | ✎ | ❌ |
| Xem/sửa địa chỉ giao | ✅ | ✅ | 👁️ | 👁️ | ✎ | ❌ |
| Override địa chỉ | ✅ | ⚠️ | ❌ | ❌ | ⚠️ | ❌ |
| Tạo/sửa đơn (trước fulfillment) | ✅ | ✅ | ❌ | ❌ | ✎ | ❌ |
| Hủy đơn trước shipped | ✅ | ✅ | ❌ | ❌ | ⚠️ | ❌ |
| Sửa/hủy đơn **sau fulfillment** (tạo case/approval, không sửa trực tiếp) | ⚠️ | ⚠️ | ❌ | ❌ | ⚠️ | ❌ |
| Đổi `order_status` | ✅ | ✅ | ❌ | ❌ | ⚠️ | ❌ |
| Đổi `fulfillment_status` (pick/pack/ship/deliver) | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ |
| **Ghi nhận COD thu hộ** (evidence/số tiền/reference) | ✅ | ❌ | ❌ | ✅ | ✅ | ❌ |
| **Xác nhận payment reconciliation** | ✅ | ❌ | ❌ | ❌ | ⚠️ | ❌ |
| Điều chỉnh tồn kho thủ công (reason+audit) | ✅ | ❌ | ⚠️ | ❌ | ❌ | ❌ |
| Nhận hàng / chuyển kho | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| Quản lý giá/khuyến mãi | ✅ | ⚠️ (giá đặc biệt) | ❌ | ❌ | ❌ | 👁️ |
| Điều chỉnh điểm thành viên | ✅ | ⚠️ | ❌ | ❌ | ⚠️ | ❌ |
| Duyệt hoa hồng affiliate | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Duyệt refund (reason+audit) | ✅ | ❌ | ❌ | ❌ | ⚠️ (đề xuất) | ❌ |
| Approval inbox — người **duyệt** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Quản lý staff & session | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Export dữ liệu khách (admin-only ở MVP)** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Xem audit log | ✅ | ❌ | ❌ | ❌ | 👁️ | ❌ |

**Separation of duties (CA §6.5):** người tạo approval request **không** được tự approve; **không** disable
admin cuối cùng; action sau shipment tạo **case/approval**, không sửa trực tiếp order; refund + inventory
adjustment **bắt buộc** reason + audit.

**Sửa cụ thể theo CA §6:** (6.1) delivery **chỉ ghi COD evidence**, admin/đối soát mới xác nhận payment;
(6.2) support **propose-change** (✎) cho tên/SĐT/địa chỉ/đơn, không tự sửa; (6.3) viewer **PII masked**
mặc định (SĐT/địa chỉ/payment evidence); (6.4) **export = admin-only** ở MVP, kèm reason/scope/audit.

**Triển khai:** MVP bật admin/sales/warehouse + khóa các ô nhạy cảm; delivery/support/viewer bồi ở
M6/P2. Enforce server-side; mọi ô ⚠️/✎ ghi audit.

---

## Ký

```text
Feasibility Report v0.1.1 — Dev sign-off
Author role: Dev (Alpha3S)
Đã xử lý đầy đủ P0 §4.1-4.5 và P1 §5.1-5.8 + phản biện matrix §6 + gates §10 của CA-REVIEW-001.
Trình CA re-review để cấp: APPROVED FOR IMPLEMENTATION PLANNING.
Chưa chạy migration production / thay đổi business state cho tới khi: v0.1.1 được duyệt,
business policy PO khóa, production baseline được xác minh (§2, §12.8).
Ngày: 2026-07-24
```

> Bản `-EN` (CA đã review theo bản EN) cần đồng bộ lên v0.1.1 — xem `PHASE1B-FEASIBILITY-REPORT-EN.md`.
