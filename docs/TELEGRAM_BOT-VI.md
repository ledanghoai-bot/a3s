# Alpha3S — Tài liệu Telegram Bot

> Mô tả 2 bot Telegram độc lập trong hệ thống — bot **admin** (nội bộ) và bot
> **khách hàng** (kênh dự phòng). Dùng khi deploy, cấu hình token mới, hoặc
> debug lỗi không nhận được tin nhắn.
> Cập nhật lần cuối: 16/7.

## Mục lục nhanh
- [Tổng quan — 2 bot khác nhau](#tổng-quan--2-bot-khác-nhau)
- [Bot Admin (telegram_listener.py)](#bot-admin-telegram_listenerpy)
- [Bot Khách hàng (telegram_customer_listener.py)](#bot-khách-hàng-telegram_customer_listenerpy)
- [Mã khách hàng ngắn (resolve_psid)](#mã-khách-hàng-ngắn-resolve_psid)
- [Cách tạo bot mới qua @BotFather](#cách-tạo-bot-mới-qua-botfather)
- [Cấu hình (.env)](#cấu-hình-env)
- [Kiến trúc kỹ thuật](#kiến-trúc-kỹ-thuật)
- [Debug thường gặp](#debug-thường-gặp)

---

## Tổng quan — 2 bot khác nhau

| | Bot Admin | Bot Khách hàng |
|---|---|---|
| File | `app/workers/telegram_listener.py` | `app/workers/telegram_customer_listener.py` |
| Service Docker | `telegram_bot` | `telegram_customer_bot` |
| Token | `TELEGRAM_BOT_TOKEN` | `TELEGRAM_CUSTOMER_BOT_TOKEN` |
| Ai nhắn được | **CHỈ** đúng `TELEGRAM_ADMIN_CHAT_ID` đã cấu hình — mọi chat khác bị bỏ qua im lặng | **Bất kỳ ai** nhắn vào bot (kênh public) |
| Vai trò | Nhận thông báo escalate + gõ lệnh quản trị (`/resume`, `/note`, `/approve`, `/list`) | Trả lời khách hàng thật — dùng khi Messenger gặp sự cố (vd Meta khoá test user) |
| Dùng chung logic AI? | Không — chỉ xử lý lệnh, không gọi `orchestrator.handle_message` | **Có** — gọi thẳng `orchestrator.handle_message()`, y hệt luồng Messenger |

**⚠️ 2 bot PHẢI dùng 2 token khác nhau** — không được dùng chung 1 bot
Telegram cho cả 2 vai trò, vì bot admin có logic bảo mật giới hạn 1 chat_id
duy nhất, còn bot khách hàng phải mở cho mọi người.

Cả 2 đều dùng **long-polling** (`getUpdates`), không cần webhook/HTTPS public
— phù hợp giai đoạn dev/chưa deploy domain thật (#9).

---

## Bot Admin (`telegram_listener.py`)

### Lệnh hỗ trợ

| Lệnh | Cú pháp | Mô tả |
|---|---|---|
| `/resume` | `/resume <mã KH> [ghi chú]` | Bật lại bot cho 1 hội thoại. Ghi chú tuỳ chọn — nếu có, lưu vào `messages` (`role='agent'`) và bơm vào context bot |
| `/note` | `/note <mã KH> <nội dung>` | Thêm ghi chú **bất kỳ lúc nào**, không cần đi kèm resume — dùng khi staff đang thương lượng qua điện thoại trong lúc bot vẫn hoạt động bình thường |
| `/approve` | `/approve <mã KH> <số lượng> <đơn giá> [ghi chú]` | Duyệt giá/số lượng đặc biệt (ghi vào `price_overrides`) — cho phép bot tự tạo đơn vượt giới hạn chuẩn nếu khách xác nhận đúng số lượng này |
| `/list` | `/list` | Liệt kê mọi hội thoại đang `bot_paused=TRUE`, mỗi hội thoại 1 tin kèm nút **"▶️ Resume ngay"** |
| `/help` | `/help` | Hướng dẫn |

### Nút bấm (inline keyboard / callback_query)
- Tin thông báo escalate (`notify_admin`) và mỗi dòng trong `/list` đều kèm
  nút **"▶️ Resume bot ngay"** — bấm là gọi thẳng `resume_bot()`, không cần
  gõ lệnh/copy PSID.
- Sau khi bấm, Telegram gọi **`answerCallbackQuery`** để tắt icon loading trên
  nút (bắt buộc theo Telegram Bot API, nếu không nút sẽ "treo" loading mãi).

### Bảo mật
Mọi update (tin nhắn thường VÀ callback_query) đều so sánh `chat_id` với
`TELEGRAM_ADMIN_CHAT_ID` trước khi xử lý — không khớp thì **bỏ qua hoàn
toàn**, không phản hồi gì (kể cả không báo lỗi), tránh lộ thông tin cho người
lạ tìm ra bot.

### Validate input (`is_valid_identifier`)
Sau sự cố 16/7 (staff gõ nhầm nguyên cụm `"Mã KH: 4"` từ tin thông báo, tạo ra
khách hàng rác với `psid = "Mã"`), mọi lệnh `/resume`, `/note`, `/approve` đều
validate identifier trước khi xử lý — chỉ chấp nhận:
- Chuỗi số thuần (mã KH ngắn, vd `4`)
- `tg:<số>` hoặc `manual:<hex>` (PSID hệ thống đầy đủ)

Sai định dạng → bot trả lỗi rõ ràng, **không tạo dữ liệu rác**.

---

## Bot Khách hàng (`telegram_customer_listener.py`)

Kênh dự phòng khi Messenger gặp sự cố — **KHÔNG thay thế Messenger về lâu
dài**, chỉ dùng song song để không bị động lúc dev/test hoặc khi Meta có vấn
đề (như vụ khoá tài khoản test 16/7).

### Cách hoạt động
1. Nhận **bất kỳ** tin nhắn text nào gửi tới bot.
2. Gán `sender_id = f"tg:{chat_id}"` — prefix `tg:` đảm bảo không bao giờ
   trùng với PSID Facebook thật (luôn là số thuần dài).
3. Check `is_bot_paused(sender_id)` — nếu đang paused, chỉ log tin khách,
   không trả lời (y hệt logic `app/workers/tasks.py` cho Messenger).
4. Nếu không paused: gọi thẳng `orchestrator.handle_message(sender_id, text)`
   — **dùng chung 100% logic AI** với Messenger (RAG, tool calling, human
   handoff, agent notes context...), không có bản sao code riêng.
5. Gửi câu trả lời qua Telegram `sendMessage`.

### Khác biệt so với khách Messenger thật
- `orchestrator.py` **bỏ qua** việc gọi Messenger Graph API lấy tên (chỉ gọi
  khi `sender_id` không có prefix `tg:`/`manual:`) — khách Telegram sẽ không
  có gợi ý giới tính từ tên hiển thị, bot phải dựa vào cách khách tự xưng
  trong hội thoại như bình thường.
- Không có cơ chế "echo capture" (bắt tin nhân viên gõ tay) như Messenger,
  vì Telegram không có khái niệm "Page Inbox" nhân viên trả lời thay bot.
  Nhân viên vẫn dùng `/note`/`/approve` từ bot Admin để bổ sung thông tin.

---

## Mã khách hàng ngắn (`resolve_psid`)

PSID Facebook (15-17 chữ số) hoặc `tg:<chat_id>` khó gõ tay trên mobile. Hệ
thống dùng **`customers.id`** (số nguyên tự tăng, thường 1-2 chữ số) làm "mã
KH ngắn":

- Mọi tin thông báo/`​/list` hiển thị kèm dòng **"Mã số khách — CHỈ gõ số
  này vào lệnh"**.
- `handoff.resolve_psid(identifier)`: nếu `identifier` là chuỗi số thuần và
  khớp 1 `customers.id` có thật → trả về đúng PSID tương ứng. Nếu không (đã
  là PSID đầy đủ, hoặc mã không tồn tại) → coi `identifier` chính là PSID
  (tương thích ngược, vẫn gõ được PSID đầy đủ nếu muốn).

---

## Cách tạo bot mới qua @BotFather

1. Mở Telegram, chat với **@BotFather**.
2. `/newbot` → đặt tên hiển thị → đặt username (phải kết thúc bằng `bot`,
   vd `alpha3s_customer_bot`).
3. BotFather trả về **token** dạng `123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`
   — copy nguyên chuỗi này.
4. Dán vào `.env` đúng biến (`TELEGRAM_BOT_TOKEN` cho bot admin, hoặc
   `TELEGRAM_CUSTOMER_BOT_TOKEN` cho bot khách hàng) — **không dùng lại
   token cũ cho vai trò khác**.
5. **Lấy `TELEGRAM_ADMIN_CHAT_ID`** (chỉ cần cho bot admin): nhắn thử 1 tin
   bất kỳ vào bot admin vừa tạo, sau đó gọi:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
   Tìm trường `message.chat.id` trong JSON trả về — đó là `TELEGRAM_ADMIN_CHAT_ID`.

---

## Cấu hình (.env)

| Biến | Dùng cho | Bắt buộc? |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot admin | Có (nếu muốn dùng tính năng handoff qua Telegram) |
| `TELEGRAM_ADMIN_CHAT_ID` | Bot admin — giới hạn chat được phép gõ lệnh | Có, đi kèm với trên |
| `TELEGRAM_CUSTOMER_BOT_TOKEN` | Bot khách hàng | Tuỳ chọn — chỉ cần nếu dùng kênh dự phòng |

Nếu thiếu token tương ứng, service sẽ tự in log cảnh báo và **không khởi
động vòng lặp** (không crash container, chỉ đứng yên chờ cấu hình) — xem
hàm `_configured()`/`main()` trong từng file.

---

## Kiến trúc kỹ thuật

- **Long-polling**, không webhook — mỗi service tự gọi `deleteWebhook` lúc
  khởi động (đề phòng từng có ai set webhook thủ công, tránh xung đột).
- Cả 2 chạy trong Docker service riêng, `restart: unless-stopped` (tự khởi
  động lại nếu crash) — xem `docker-compose.yml`.
- Không dùng chung process với `worker` (arq, xử lý queue Messenger) — 3
  tiến trình nền độc lập: `worker`, `telegram_bot`, `telegram_customer_bot`.

---

## Debug thường gặp

**Bot không phản hồi gì cả:**
```bash
docker compose logs telegram_bot --tail 100
# hoặc
docker compose logs telegram_customer_bot --tail 100
```
Tìm dòng `Da ket noi, bat dau long-polling...` — nếu không thấy, token sai
hoặc thiếu cấu hình.

**Gõ lệnh admin nhưng không thấy phản hồi:** kiểm tra đúng đang nhắn từ chat
có `chat_id` khớp `TELEGRAM_ADMIN_CHAT_ID` — log sẽ có dòng
`Bo qua tin nhan tu chat la (chat_id=...)` nếu bị chặn do sai chat.

**Đổi code xong không thấy hiệu lực:** 2 service này build từ `Dockerfile`
gốc (không phải dev mode như dashboard) — sau khi sửa code Python, cần
`docker compose restart telegram_bot` (hoặc `telegram_customer_bot`), không
tự hot-reload.
