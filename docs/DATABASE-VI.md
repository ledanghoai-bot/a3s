# Alpha3S — Tài liệu Database

> Tham chiếu đầy đủ schema PostgreSQL (+ pgvector) của hệ thống 3S Coffee.
> Dùng khi deploy, vận hành, hoặc debug — giống 1 file `/help` cho database.
> Cập nhật lần cuối: 17/7 (sau migration 009). Nếu thêm migration mới, nhớ cập
> nhật file này theo.

## Mục lục nhanh
- [Tổng quan luồng dữ liệu](#tổng-quan-luồng-dữ-liệu)
- [Danh sách bảng](#danh-sách-bảng)
- [Chi tiết từng bảng](#chi-tiết-từng-bảng)
- [Lịch sử migration](#lịch-sử-migration)
- [Câu lệnh tra cứu thường dùng](#câu-lệnh-tra-cứu-thường-dùng)
- [Ghi chú vận hành quan trọng](#ghi-chú-vận-hành-quan-trọng)

---

## Tổng quan luồng dữ liệu

```
customers (1 khách = 1 psid, bất kể kênh nào)
    │
    ├── conversations (1 khách hiện chỉ giữ 1 "phiên" đang hoạt động)
    │       │
    │       └── messages (toàn bộ lịch sử chat: khách/bot/nhân viên)
    │
    ├── orders ──── order_items ──── products (+ price_tiers)
    │
    ├── price_overrides (staff duyệt giá/số lượng đặc biệt qua /approve)
    │
    └── escalations (log lý do mỗi lần chuyển cho nhân viên)

knowledge_chunks — dùng cho RAG, liên kết tùy nguồn: tĩnh (không FK), qua
faq_entries, hoặc qua products — xem chi tiết ở mục "Chi tiết từng bảng".
Không bao giờ liên kết tới khách hàng.
```

**Khoá trung tâm của toàn hệ thống là `customers.psid`** — một chuỗi định danh
khách hàng, định dạng khác nhau tuỳ kênh:
- Khách qua **Messenger thật**: PSID Facebook (chuỗi số dài 15-17 chữ số).
- Khách qua **Telegram** (kênh dự phòng): `tg:<telegram_chat_id>`.
- Đơn tạo **thủ công không qua chat nào** (`/orders/new` không kèm psid): tự
  sinh `manual:<uuid ngắn>`.

Toàn bộ code business logic (`orchestrator.py`, `tools.py`, `handoff.py`,
`dashboard.py`...) coi 3 dạng trên là tương đương — không phân biệt kênh khi
xử lý logic, chỉ khác ở phần nhận/gửi tin nhắn (webhook Messenger vs
`telegram_customer_listener.py`).

---

## Danh sách bảng

| Bảng | Vai trò |
|---|---|
| `customers` | Thông tin khách hàng (tên/SĐT/địa chỉ), khoá bằng `psid` |
| `conversations` | 1 phiên chat của 1 khách; giữ cờ `bot_paused` (human handoff) |
| `messages` | Toàn bộ tin nhắn (khách/bot/nhân viên) — nguồn dữ liệu cho dashboard + context bot |
| `products` | Danh mục sản phẩm (đa SKU, CRUD qua dashboard `/products`) |
| `price_tiers` | Bảng giá theo bậc số lượng, gắn với 1 sản phẩm |
| `orders` | Đơn hàng thật |
| `order_items` | Chi tiết từng dòng sản phẩm trong 1 đơn |
| `knowledge_chunks` | Kiến thức cho RAG (vector embedding) — gồm cả nội dung tĩnh, FAQ, và mô tả sản phẩm |
| `escalations` | Log lý do mỗi lần escalate cho nhân viên |
| `price_overrides` | Staff duyệt giá/số lượng đặc biệt qua lệnh `/approve` Telegram |
| `faq_entries` | FAQ tạo qua dashboard (`/faq`) — tự động đồng bộ vào `knowledge_chunks` |

---

## Chi tiết từng bảng

### `customers`
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | BIGSERIAL PK | Dùng làm **"mã KH ngắn"** trên Telegram (`/note 4 ...` thay vì PSID dài) |
| `psid` | TEXT UNIQUE NOT NULL | Khoá định danh khách — xem giải thích 3 định dạng ở trên |
| `name`, `phone`, `address` | TEXT (nullable) | Chỉ được ghi khi có đơn hàng thật đi qua (`create_order`/`create_order_manual`) — **KHÔNG** tự động điền chỉ từ việc chat thường |
| `created_at` | TIMESTAMPTZ | |

### `conversations`
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `customer_id` | FK → customers | |
| `bot_paused` | BOOLEAN DEFAULT FALSE | **Cờ quan trọng nhất hệ thống** — `TRUE` = nhân viên đang xử lý, bot im lặng hoàn toàn (worker/listener check cờ này trước mỗi lượt trả lời) |
| `staff_action` | TEXT DEFAULT 'moi' | ⚠️ **Cột legacy, KHÔNG còn dùng trong UI** (migration 005) — từng là cột "Xử lý" chung cho cả hội thoại, sau đó thay bằng theo dõi từng note/approve riêng lẻ (xem `messages.handled` / `price_overrides.status`). Vẫn còn trong DB, không xoá, chỉ không gọi tới nữa. |
| `created_at` | TIMESTAMPTZ | |

Đơn giản hoá: 1 khách hiện chỉ giữ **1 conversation "đang hoạt động"** (luôn
lấy bản ghi mới nhất theo `customer_id`) — chưa hỗ trợ tách nhiều phiên chat
riêng biệt theo thời gian.

### `messages`
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `conversation_id` | FK → conversations | |
| `role` | TEXT CHECK IN ('customer','bot','agent') | `customer` = khách gõ; `bot` = AI trả lời; `agent` = **nhân viên/sếp** (note tường minh qua `/note`, hoặc tin nhắn thật gõ tay qua Messenger Inbox lúc `bot_paused=TRUE`, bắt được qua cơ chế "timetrap" — xem `app/workers/tasks.py`) |
| `content` | TEXT NOT NULL | |
| `handled` | BOOLEAN DEFAULT FALSE (migration 006) | Chỉ áp dụng ý nghĩa cho `role='agent'` — staff đánh dấu đã xử lý trên dashboard. **KHÔNG lọc theo cờ này khi bơm context cho bot** (`conversation_log.get_recent_agent_messages`) — bot luôn phải biết toàn bộ thoả thuận dù dashboard đã "gọn" hiển thị hay chưa. |
| `created_at` | TIMESTAMPTZ | |

### `products`
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `sku` | TEXT UNIQUE | **Immutable sau khi tạo** (không cho sửa qua CRUD) — là khóa các tool dùng tra cứu |
| `name`, `description` | TEXT | `description` từ 17/7 **tự động dùng cho RAG** (xem phần `knowledge_chunks` bên dưới) |
| `price_vnd` | INTEGER | Giá lẻ mặc định (fallback nếu không khớp bậc nào trong `price_tiers`) |
| `stock` | INTEGER | Tồn kho — bị trừ trực tiếp mỗi khi `create_order`/`create_order_manual` chạy thành công |

CRUD đầy đủ qua `/products` (dashboard) trừ `sku` (immutable). Xóa sản phẩm bị
**từ chối bởi ràng buộc khóa ngoại** nếu đã có đơn hàng/bậc giá liên quan (thiết kế có
chủ đích).

### `price_tiers`
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `product_id` | FK → products | |
| `min_qty` | INTEGER | Ngưỡng số lượng tối thiểu để áp giá này |
| `unit_price_vnd` | INTEGER | |

Bậc giá hiện tại cho `3S-100G`: **1-4 hũ → 170.000đ** · **5-19 hũ → 160.000đ**
· **20-100 hũ → 140.000đ**. Trên 100 hũ: **không tự áp giá**, bot phải
`escalate_to_human` — trừ khi có `price_overrides` khớp đúng số lượng (xem bên dưới).

### `orders`
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `customer_id` | FK → customers | |
| `status` | TEXT DEFAULT 'new', CHECK IN ('new','confirmed','shipped','done','cancelled') (constraint thêm ở migration 003) | Chỉ chuyển được **theo đúng thứ tự tiến** `new → confirmed → shipped → done` (không lùi được), `cancelled` cho phép từ bất kỳ bước nào **trừ** `done` — xem `app/services/orders.py:validate_transition` |
| `total_vnd` | INTEGER | |
| `shipping_name`, `shipping_phone`, `shipping_address` | TEXT | Snapshot lúc tạo đơn (độc lập với `customers.name/phone/address` — khách có thể đổi thông tin sau, đơn cũ vẫn giữ đúng dữ liệu lúc đặt) |
| `created_at` | TIMESTAMPTZ | |

### `order_items`
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `order_id` | FK → orders | |
| `product_id` | FK → products | |
| `quantity` | INTEGER | |
| `unit_price_vnd` | INTEGER | Đơn giá **tại thời điểm chốt đơn** (không tự đổi nếu `price_tiers` thay đổi sau này) |

### `knowledge_chunks`
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `source` | TEXT | `product_profile.md`/`faq.md` (nội dung tĩnh) • `dashboard:faq` (từ `/faq`) • `dashboard:product` (mô tả sản phẩm, từ `/products`) |
| `content` | TEXT | Đoạn text đã chunk |
| `embedding` | `vector(384)` | Model: `paraphrase-multilingual-MiniLM-L12-v2`. Index HNSW cosine. |
| `faq_entry_id` | BIGINT FK → faq_entries, `ON DELETE CASCADE` (migration 008) | Chỉ có giá trị với chunk từ `source='dashboard:faq'` |
| `product_id` | BIGINT FK → products, `ON DELETE CASCADE` (migration 009) | Chỉ có giá trị với chunk từ `source='dashboard:product'` |
| `created_at` | TIMESTAMPTZ | |

**3 nguồn nội dung cùng tồn tại song song, không ghi đè lẫn nhau:**
1. **Nội dung tĩnh** (`product_profile.md`, `faq.md`) — ghi qua `scripts/ingest.py`,
   chạy tay 1 lần, không tự động khi sửa file `.md`.
2. **FAQ qua dashboard** (`dashboard:faq`) — CRUD qua `/faq`
   (`app/services/knowledge_entries.py`), tự tính embedding và ghi/xóa chunk **ngay
   lập tức** khi tạo/sửa/xóa, không cần chạy `ingest.py`.
3. **Mô tả sản phẩm qua dashboard** (`dashboard:product`) — CRUD qua `/products`
   (`app/services/products.py`), tự tạo/sửa/xóa chunk tương ứng mỗi khi sửa trường
   `description` của sản phẩm — y nguyên pattern FAQ.

Ghi lại qua `scripts/ingest.py` (chỉ áp dụng cho nguồn 1). **Không liên kết với
khách hàng nào** — đây là kiến thức dùng chung cho mọi cuộc chat (RAG).

### `faq_entries` (migration 008)
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `question`, `answer` | TEXT NOT NULL | |
| `created_at`, `updated_at` | TIMESTAMPTZ | |

Nguồn thật cho FAQ tạo qua dashboard — xem chi tiết ở mục `knowledge_chunks`
ở trên. Sửa FAQ sẽ **XOÁ chunk cũ rồi TẠO LẠI** (không UPDATE embedding tại
chỗ), tránh lệch content/embedding.

### `escalations`
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `conversation_id` | FK → conversations | |
| `reason` | TEXT NOT NULL | Lý do escalate — có thể do LLM tự quyết định gọi tool, hoặc do khách gõ đúng cụm "gặp nhân viên" (nhánh deterministic), hoặc do staff tự `pause` từ dashboard |
| `created_at` | TIMESTAMPTZ | |

Log lịch sử **mọi lần** `bot_paused` chuyển sang `TRUE` (cả escalate tự động
lẫn staff tự bấm) — dùng để xem lại/cải thiện prompt sau này.

### `price_overrides`
| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `customer_id` | FK → customers | |
| `quantity` | INTEGER NOT NULL | Số lượng CHÍNH XÁC được duyệt — `create_order` chỉ áp dụng khi số lượng khách xác nhận khớp **tuyệt đối** (không làm tròn/suy diễn) |
| `unit_price_vnd` | INTEGER NOT NULL | Đơn giá đặc biệt đã duyệt, ghi đè `price_tiers` chuẩn |
| `note` | TEXT | Ghi chú thêm lúc `/approve` (vd điều kiện giao hàng) |
| `used` | BOOLEAN DEFAULT FALSE | **Nguồn thật duy nhất** cho logic `create_order` — `TRUE` nghĩa là **không dùng lại được nữa**, dù lý do là đã tạo đơn (`status='used'`) hay bị từ chối (`status='rejected'`) |
| `status` | TEXT DEFAULT 'active', CHECK IN ('active','used','rejected') (migration 007) | Chỉ để **dashboard hiển thị đúng nhãn** — không phải nguồn thật cho business logic (đó là cột `used`) |
| `reject_reason` | TEXT (migration 007) | Chỉ có giá trị khi `status='rejected'` |
| `created_at` | TIMESTAMPTZ | |

**Nguyên tắc an toàn quan trọng nhất bảng này:** bảng này **CHỈ được ghi qua
lệnh staff thật** (Telegram admin bot — giới hạn đúng `TELEGRAM_ADMIN_CHAT_ID`
— hoặc dashboard có token). **LLM không bao giờ tự ghi được** — đây là cách hệ
thống chặn AI tự "cấp phép" vượt giới hạn giá/số lượng cho chính nó
(`app/services/tools.py:create_order` chỉ đọc, không bao giờ ghi bảng này).

---

## Lịch sử migration

| # | File | Nội dung |
|---|---|---|
| 001 | `001_init.sql` | Schema gốc: customers, conversations, messages, products, orders, order_items, knowledge_chunks, price_tiers + seed sản phẩm |
| 002 | `002_add_escalations.sql` | Bảng `escalations` |
| 003 | `003_orders_status_check.sql` | CHECK constraint cho `orders.status` |
| 004 | `004_price_overrides.sql` | Bảng `price_overrides` (chưa có `status`/`reject_reason`) |
| 005 | `005_staff_action.sql` | `conversations.staff_action` — **legacy, không còn dùng trong UI** |
| 006 | `006_messages_handled.sql` | `messages.handled` |
| 007 | `007_override_status.sql` | `price_overrides.status` + `reject_reason` |
| 008 | `008_faq_entries.sql` | Bảng `faq_entries` + `knowledge_chunks.faq_entry_id` |
| 009 | `009_product_knowledge.sql` | `knowledge_chunks.product_id` — đồng bộ RAG theo từng sản phẩm |

**Lưu ý deploy quan trọng:** `docker-entrypoint-initdb.d` (thư mục
`./migrations` mount vào container `db`) **chỉ tự chạy 1 LẦN DUY NHẤT lúc tạo
volume Postgres mới tinh**. Nếu DB đã tồn tại từ trước (như trong suốt quá
trình dev ở đây), mọi migration 002 trở đi đều phải **chạy tay**:
```bash
docker compose exec db psql -U alpha3s -d alpha3s -f /docker-entrypoint-initdb.d/00X_ten_file.sql
```
Khi deploy môi trường **hoàn toàn mới** (volume Postgres trống), cả 9 file sẽ
tự chạy theo đúng thứ tự tên file — không cần chạy tay.

---

## Câu lệnh tra cứu thường dùng

Kết nối trực tiếp vào Postgres:
```bash
docker compose exec db psql -U alpha3s -d alpha3s
```

**Xem 5 hội thoại gần nhất kèm trạng thái:**
```sql
SELECT c.id, c.bot_paused, cu.psid, cu.name, cu.phone
FROM conversations c JOIN customers cu ON cu.id = c.customer_id
ORDER BY c.id DESC LIMIT 5;
```

**Xem toàn bộ lịch sử chat của 1 khách (theo PSID):**
```sql
SELECT m.role, m.content, m.created_at
FROM messages m
JOIN conversations c ON c.id = m.conversation_id
JOIN customers cu ON cu.id = c.customer_id
WHERE cu.psid = '<PSID>'
ORDER BY m.created_at ASC;
```

**Tra PSID từ mã KH ngắn (số ID trong `customers`):**
```sql
SELECT psid, name, phone FROM customers WHERE id = <mã_KH>;
```

**Xem đơn hàng thật gần nhất (khác `price_overrides` — xem ghi chú bên dưới):**
```sql
SELECT id, status, total_vnd, shipping_name, shipping_phone, created_at
FROM orders ORDER BY id DESC LIMIT 10;
```

**Xem các phê duyệt `/approve` còn hiệu lực (chưa dùng/chưa từ chối):**
```sql
SELECT po.id, cu.psid, cu.name, po.quantity, po.unit_price_vnd, po.note, po.created_at
FROM price_overrides po JOIN customers cu ON cu.id = po.customer_id
WHERE po.status = 'active' ORDER BY po.created_at DESC;
```

**Xem note nội bộ (agent) chưa xử lý:**
```sql
SELECT m.id, cu.psid, cu.name, m.content, m.created_at
FROM messages m
JOIN conversations c ON c.id = m.conversation_id
JOIN customers cu ON cu.id = c.customer_id
WHERE m.role = 'agent' AND m.handled = FALSE
ORDER BY m.created_at DESC;
```

**Kiểm tra tồn kho hiện tại:**
```sql
SELECT sku, name, stock FROM products;
```

**Xem toàn bộ FAQ đã tạo qua dashboard:**
```sql
SELECT id, question, answer, updated_at FROM faq_entries ORDER BY id;
```

**Đếm số knowledge_chunk theo từng nguồn (kiểm tra RAG đồng bộ đúng chưa):**
```sql
SELECT source, COUNT(*) FROM knowledge_chunks GROUP BY source;
```

---

## Ghi chú vận hành quan trọng

1. **`price_overrides` KHÔNG PHẢI đơn hàng** — chỉ là "giấy phép" giá/số
   lượng đặc biệt. Đơn hàng thật chỉ tồn tại trong bảng `orders`, được tạo khi
   bấm "🤖 Gọi bot tạo đơn"/"👤 NV tạo đơn" thành công. Đừng nhầm 2 bảng này
   khi kiểm tra "có đơn chưa".

2. **Redis (`chat:{sender_id}`) chỉ giữ lịch sử chat 24h** để làm ngữ cảnh
   cho LLM — **không phải nguồn lưu trữ lâu dài**. Dashboard luôn đọc từ
   Postgres (`messages`), không đọc Redis.

3. **`customers.name/phone/address` chỉ được điền khi có đơn hàng thật đi
   qua** — một khách mới chat mà chưa từng đặt đơn sẽ có các cột này là
   `NULL`, dù đã chat rất nhiều.

4. **`used = TRUE` trên `price_overrides` là vĩnh viễn** (không có cơ chế
   "un-reject" hay "un-use" qua UI) — nếu staff bấm nhầm, cần sửa tay qua SQL:
   ```sql
   UPDATE price_overrides SET used = FALSE, status = 'active', reject_reason = NULL
   WHERE id = <id>;
   ```

5. **Không xoá dữ liệu** — hệ thống được thiết kế theo hướng "không bao giờ
   xoá", chỉ đổi cờ/trạng thái (`handled`, `used`, `status`, `bot_paused`).
   Toàn bộ lịch sử note/approve/tin nhắn luôn còn nguyên trong DB để tra cứu
   lại, kể cả khi dashboard "ẩn" chúng khỏi màn hình chính.
