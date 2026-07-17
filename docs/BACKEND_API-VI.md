# Alpha3S — Tài liệu Backend API (FastAPI)

> Mô tả toàn bộ backend FastAPI: webhook Messenger, luồng xử lý AI
> (orchestrator + tool calling), các service, và API nội bộ (`/admin/*`,
> `/dashboard/*`). Dùng khi deploy, debug, hoặc phát triển tiếp.
> Cập nhật lần cuối: 17/7 (sau Bat 3 — thêm Metrics/Analytics).

## Mục lục nhanh
- [Tổng quan kiến trúc](#tổng-quan-kiến-trúc)
- [Luồng xử lý 1 tin nhắn Messenger](#luồng-xử-lý-1-tin-nhắn-messenger)
- [orchestrator.py — bộ não AI](#orchestratorpy--bộ-não-ai)
- [4 Tool (function calling)](#4-tool-function-calling)
- [Human handoff](#human-handoff)
- [Router `/webhook`](#router-webhook)
- [Router `/admin`](#router-admin)
- [Router `/dashboard`](#router-dashboard)
- [Danh sách service (app/services/)](#danh-sách-service-appservices)
- [Danh sách worker (app/workers/)](#danh-sách-worker-appworkers)
- [Biến môi trường đầy đủ](#biến-môi-trường-đầy-đủ)
- [Giới hạn đã biết](#giới-hạn-đã-biết)

---

## Tổng quan kiến trúc

```
Messenger/Telegram khách
        │
        ▼
  webhook.py (chi validate + enqueue, tra 200 ngay)
        │  (Redis queue, arq)
        ▼
  tasks.py (worker) ──── telegram_customer_listener.py (kenh du phong)
        │                         │
        └────────┬────────────────┘
                  ▼
        orchestrator.py (handle_message)
        ├── RAG (rag.py + knowledge_chunks)
        ├── Tool calling (tools.py: search_products, check_stock,
        │                 create_order, escalate_to_human)
        ├── Agent notes injection (conversation_log.py)
        └── Human handoff check (handoff.py)
                  │
                  ▼
        Postgres (messages, orders, price_overrides...) + Redis (context 24h)
```

**Nguyên tắc cốt lõi:** `orchestrator.handle_message(sender_id, text) -> str`
là **hàm duy nhất** chứa toàn bộ logic AI — hoàn toàn không quan tâm kênh nào
gọi tới (Messenger, Telegram khách, hay tương lai Zalo/web widget). Thêm 1
kênh mới chỉ cần viết phần nhận/gửi tin nhắn, tái sử dụng y nguyên hàm này.

Không dùng SQLAlchemy ORM — toàn bộ service dùng **asyncpg thuần** (xem quy
ước ở `app/services/rag.py`, service đầu tiên viết theo style này).

---

## Luồng xử lý 1 tin nhắn Messenger

1. **`POST /webhook`** (`app/api/webhook.py`) — xác thực chữ ký
   `X-Hub-Signature-256` (HMAC với `META_APP_SECRET`), enqueue job
   `process_message` vào Redis (qua `arq`), trả `200` ngay lập tức. **Không
   xử lý AI trong request webhook** — tránh Meta timeout/retry gây trùng lặp.
2. **`tasks.py` (worker arq)** nhận job:
   - Nếu là **echo** (tin Page gửi đi, Meta echo lại) VÀ hội thoại đang
     `bot_paused=TRUE` → ghi vào `messages` với `role='agent'` (bắt tin thật
     nhân viên gõ tay qua Messenger Inbox — cơ chế "timetrap", xem
     `docs/DATABASE-VI.md`).
   - Nếu là tin khách thường VÀ đang `bot_paused=TRUE` → chỉ log
     (`role='customer'`), không gọi AI.
   - Ngược lại → gọi `orchestrator.handle_message()`, gửi trả lời qua
     `messenger.send_text()`.

---

## `orchestrator.py` — bộ não AI

Hàm `handle_message(sender_id: str, text: str) -> str`, các bước:

1. **`ensure_conversation()`** — đảm bảo có `customers`/`conversations` cho
   `sender_id` này (Postgres, không phải Redis).
2. **Lưới an toàn deterministic** — nếu tin nhắn khớp `handoff.wants_human()`
   (regex nhận diện "gặp nhân viên"...), escalate **ngay, không qua LLM** —
   trả lời câu xác nhận cố định, không phụ thuộc LLM có nhớ gọi tool hay
   không.
3. **Lấy lịch sử** từ Redis (`chat:{sender_id}`, TTL 24h, tối đa
   `MAX_HISTORY=10` lượt) + **profile khách** (Messenger Graph API — bỏ qua
   cho kênh không phải Messenger, xem `docs/TELEGRAM_BOT-VI.md`).
4. **RAG**: `search_knowledge()` lấy top-4 đoạn liên quan từ
   `knowledge_chunks` (kiến thức sản phẩm tĩnh — cách pha, hương vị...
   **KHÔNG dùng cho giá/tồn kho/đơn hàng**, việc đó qua tool).
5. **Bơm agent notes**: `conversation_log.get_recent_agent_messages()` — lấy
   tối đa 10 note/tin nhắn nhân viên gần nhất, bơm vào system prompt. **Không
   lọc theo `handled`** — bot luôn biết toàn bộ thoả thuận dù dashboard đã
   đánh dấu "đã xử lý" hay chưa.
6. **Bơm danh sách SKU ("Lớp 1", thêm 17/7)**: `products.get_sku_summary_text()`
   — 1 dòng liệt kê toàn bộ SKU hiện có, bơm vào system prompt **MỌI lượt**
   (không qua tool_calls) — không phụ thuộc LLM có tự quyết định gọi
   `search_products` hay không. Kèm dặn rõ "danh sách đây đầy đủ, không
   được bịa thêm SKU" và "thứ tự ưu tiên khi có mâu thuẫn" (dữ liệu sống >
   lịch sử hội thoại, kể cả câu trả lời trước đó của chính bot). Xem
   phần "Lớp 2" ở mục `products.py` bên dưới để biết nguồn chi tiết hơn (RAG).
7. **Gọi LLM** (DeepSeek, OpenAI-compatible) kèm `tools=TOOL_DEFINITIONS`,
   `tool_choice="auto"`, **`temperature=0.1`** (hạ từ 0.3 xuống 17/7 — ưu
   tiên bám sát dữ liệu hơn là "sáng tạo"). Vòng lặp tối đa
   `MAX_TOOL_ITERATIONS=4` nếu model gọi nhiều tool liên tiếp (tránh treo vô hạn).
8. **Lọc markdown** an toàn (Messenger không render `**`, `#`, `` ` ``).
9. **Lưu lịch sử** — Redis (context ngắn hạn) + Postgres `messages` (lâu dài,
   cho dashboard).

---

## 4 Tool (function calling)

Định nghĩa đầy đủ trong `app/services/tools.py:TOOL_DEFINITIONS`.
**`psid` KHÔNG nằm trong schema expose cho LLM** — `orchestrator.py` tự bơm
vào lúc thực thi (tránh model tự bịa/nhầm sender).

| Tool | Tham số LLM cung cấp | Ghi chú |
|---|---|---|
| `search_products` | `query` (tuỳ chọn) | Trả về sản phẩm + bảng giá **thật từ DB**, không hardcode trong prompt. Từ 17/7, mỗi sản phẩm kèm cả `price_vnd_default` (giá lẻ, fallback khi chưa có bậc giá nào) và 1 `note` nhắc rõ đây là danh sách đầy đủ (fix bug bot từ chối/bịa SKU) |
| `check_stock` | `sku`, `quantity` | |
| `create_order` | `customer_name`, `phone`, `address`, `sku`, `quantity` | Validate SĐT VN (regex), chặn `quantity > 100` **trừ khi** có `price_overrides` khớp chính xác (staff duyệt qua `/approve`). Transaction `FOR UPDATE` tránh race condition khi trừ tồn kho. |
| `escalate_to_human` | `reason` | Set `bot_paused=TRUE`, ghi `escalations`, gửi Telegram admin (kèm nút Resume) |

**Giới hạn giá/số lượng (`MAX_AUTO_QUANTITY=100`)** là điểm mấu chốt an
toàn: LLM không bao giờ tự "cấp phép" vượt giới hạn — chỉ được dùng khi có
bản ghi `price_overrides` do **staff thật** tạo qua lệnh `/approve` Telegram
(không có đường nào để LLM tự ghi bảng đó).

---

## Human handoff

3 cách 1 hội thoại chuyển sang `bot_paused=TRUE`:
1. **LLM tự gọi** `escalate_to_human` (khiếu nại, câu hỏi ngoài phạm vi, đơn
   >100 hũ không có phê duyệt...).
2. **Deterministic** — khách gõ đúng cụm "gặp nhân viên" (xem `handoff.wants_human`),
   escalate ngay không qua LLM.
3. **Staff tự bấm** "Tiếp quản" trên dashboard (`handoff.pause_bot()`).

**Bật lại bot** (`bot_paused=FALSE`) qua 3 kênh: dashboard, `/admin/ui`, hoặc
lệnh `/resume` Telegram — tất cả gọi chung `handoff.resume_bot()`.

---

## Router `/webhook`

File: `app/api/webhook.py`

| Method | Path | Mô tả |
|---|---|---|
| GET | `/webhook` | Meta xác thực đăng ký (echo `hub.challenge` nếu `hub.verify_token` khớp `META_VERIFY_TOKEN`) |
| POST | `/webhook` | Nhận sự kiện Messenger, xác thực chữ ký, enqueue job, trả 200 ngay |

---

## Router `/admin`

File: `app/api/admin.py` — API **nội bộ ban đầu** (issue #7), trước khi có
dashboard đầy đủ (issue #8). Vẫn còn dùng song song, không bị thay thế hoàn
toàn.

| Method | Path | Mô tả |
|---|---|---|
| POST | `/admin/conversations/{psid}/resume` | Bật lại bot |
| GET | `/admin/conversations/paused` | Liệt kê hội thoại đang chờ |
| GET | `/admin/ui` | Trang HTML đơn giản (không phải Next.js) — xem danh sách + resume bằng 1 click, dùng khi không tiện mở dashboard đầy đủ |

Bảo vệ bằng header `X-Admin-Token` (dependency `require_admin_token` trong
`app/api/auth.py`, dùng chung với router `/dashboard`).

---

## Router `/dashboard`

File: `app/api/dashboard.py` — API cho dashboard Next.js (issue #8). Xem đầy
đủ trong **`docs/DASHBOARD-VI.md`** (mỗi endpoint gắn với đúng nút/màn hình nào
trên UI).

---

## Danh sách service (`app/services/`)

| File | Trách nhiệm |
|---|---|
| `orchestrator.py` | Bộ não chính — xem mục riêng ở trên |
| `tools.py` | 4 tool function-calling — xem mục riêng ở trên |
| `handoff.py` | `bot_paused` check/pause/resume, `wants_human()` deterministic, `resolve_psid()` (mã KH ngắn), gửi Telegram (`notify_admin`), `log_note()` |
| `conversation_log.py` | Ghi/đọc `messages` + `conversations` trong Postgres — nguồn dữ liệu lâu dài (khác Redis chỉ giữ 24h) |
| `price_overrides.py` | CRUD bảng `price_overrides` — duyệt/dùng/từ chối giá đặc biệt |
| `orders.py` | `list_orders`, `update_order_status` (validate thứ tự chuyển trạng thái), `create_order_manual`, `list_products_brief` |
| `products.py` (Bat 2, 17/7) | CRUD sản phẩm/bậc giá (dashboard) + `get_sku_summary_text()` ("Lớp 1") + tự đồng bộ RAG khi sửa `description` ("Lớp 2") |
| `knowledge_entries.py` (Bat 2, 17/7) | CRUD FAQ (dashboard) — tự tính embedding, ghi/xóa `knowledge_chunks` ngay lập tức, không cần chạy `ingest.py` |
| `metrics.py` (Bat 3, 17/7) | Metrics/Analytics cho `/metrics` — tin nhắn/ngày, tỷ lệ chat→đơn, top câu hỏi bot không trả lời được — không thêm bảng mới |
| `rag.py` | `search_knowledge()` — truy vấn `knowledge_chunks` bằng cosine similarity (pgvector) |
| `embedder.py` | Tạo embedding (model `paraphrase-multilingual-MiniLM-L12-v2`, chạy local) |
| `messenger.py` | `send_text()` — gọi Facebook Send API |
| `messenger_profile.py` | Lấy tên khách qua Messenger Graph API (cache Redis 7 ngày) |

---

## Danh sách worker (`app/workers/`)

| File | Vai trò | Chạy bằng |
|---|---|---|
| `tasks.py` | Xử lý job từ Redis queue (Messenger) | `arq app.workers.tasks.WorkerSettings` |
| `telegram_listener.py` | Bot admin Telegram | `python -m app.workers.telegram_listener` |
| `telegram_customer_listener.py` | Bot khách hàng Telegram | `python -m app.workers.telegram_customer_listener` |

Xem chi tiết 2 bot Telegram trong **`docs/TELEGRAM_BOT-VI.md`**.

Script không phải worker thường trực (`scripts/`):
- `ingest.py` — nạp `data/knowledge/*.md` vào `knowledge_chunks`
- `clear_chat_history.py` (Bat 2, 17/7) — xóa lịch sử chat trong Redis (toàn
  bộ hoặc 1 sender_id) — công cụ dev, dùng khi cần test sạch sau khi sửa
  hành vi bot mà conversation cũ vẫn còn câu trả lời sai trước đó —
  **không dùng trên production**
- `test_scenarios.py` / `retest_scenarios.py` — chạy kịch bản test qua
  `handle_message()` trực tiếp, không cần webhook thật
- `push_issues_to_gitlab.py` — đồng bộ `ISSUES-VI.md` lên GitLab Issues

---

## Biến môi trường đầy đủ

Xem `.env.example` ở root repo. Nhóm theo chức năng:

| Nhóm | Biến |
|---|---|
| Meta/Messenger | `META_VERIFY_TOKEN`, `META_APP_SECRET`, `PAGE_ACCESS_TOKEN` |
| Hạ tầng | `DATABASE_URL`, `REDIS_URL` |
| LLM | `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` |
| Embedding | `EMBEDDING_MODEL`, `EMBEDDING_DIM` |
| Human handoff | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_CHAT_ID`, `ADMIN_API_TOKEN` |
| Dashboard | `DASHBOARD_CORS_ORIGINS` |
| Kênh dự phòng | `TELEGRAM_CUSTOMER_BOT_TOKEN` |

---

## Giới hạn đã biết

- **Không dùng ORM** — `app/db.py` (SQLAlchemy engine) tồn tại trong code
  nhưng **không được dùng ở đâu cả**, mọi service tự mở connection `asyncpg`
  riêng (không connection pooling) — tồn đọng kỹ thuật từ #2/#3/#4, chưa fix.
- **`embed()` (embedding model) chạy đồng bộ, CPU-bound** trong hàm async —
  có thể chặn event loop worker khi nhiều khách hỏi cùng lúc — chưa offload
  sang threadpool.
- **Không dedupe theo `mid`** — Meta có thể gửi trùng webhook event, chưa có
  cơ chế chống trùng, có thể tạo 2 câu trả lời cho 1 tin nhắn trong tình
  huống mạng chập chờn.
- **CI/CD + deploy production (#9)** chưa làm — hiện chỉ chạy Docker Compose
  trên máy dev, chưa có HTTPS, backup, alert.
- **Độ tin cậy LLM từng lượt (turn-to-turn)** — DeepSeek đôi khi tự mâu
  thuẫn với chính câu trả lời trước đó của nó trong cùng 1 hội thoại (vd
  xác nhận 1 SKU tồn tại rồi sau đó tự phủ nhận) — đã giảm thiểu qua
  `temperature=0.1` + bơm dữ liệu sống mỗi lượt, nhưng **không loại trừ
  hoàn toàn được** — giới hạn vốn có của model, xem `ISSUES-VI.md` phần
  "Fix bug 17/7" để hiểu đầy đủ bối cảnh.

Xem lịch sử phát triển đầy đủ + quyết định kỹ thuật trong `ISSUES-VI.md`
(hoặc `ISSUES-EN.md`).
