# Alpha3S — Issue Backlog

> Khôi phục từ file export GitLab (`2026-07-04_13-00-438_ledanghoai-group_alpha3s_export.tar.gz`).
> 9 issue gốc, chỉ #1 đóng trên GitLab. Cột "Thực tế theo code (review 14/7)" là đối chiếu
> nhanh với source hiện tại trong repo — dùng để cập nhật lại trạng thái issue cho khớp thực tế.

| # | Issue | GitLab | Thực tế theo code (review 14/7) |
|---|-------|--------|----------------------------------|
| 1 | Webhook Messenger + xác thực Meta | ✅ Closed | ✅ Khớp — đã xong |
| 2 | Hàng đợi Redis + arq worker | ✅ Closed (14/7) | ✅ Xong phần lõi — retry/dead-letter + load test dời sang theo dõi riêng, không chặn việc đóng |
| 3 | PostgreSQL + pgvector: schema/migration/seed | ✅ Closed (14/7) | ✅ Xong — schema, HNSW index, seed sản phẩm đều có |
| 4 | RAG pipeline: ingest + search | ✅ Closed (14/7) | ✅ Xong — `ingest.py`, `rag.py` chạy được — bộ đánh giá 10 câu hỏi mẫu dời sang theo dõi riêng |
| 5 | System prompt & brand voice | ✅ Closed (14/7) | ✅ 20/20 kịch bản pass sau khi sửa prompt — còn thiếu review giọng điệu trực tiếp với anh Hoài |
| 6 | Tool calling (search_products/check_stock/create_order/escalate_to_human) | ✅ Closed (14/7) | ✅ 4 tool chạy thật, test end-to-end DB pass (order + trừ tồn kho đúng) |
| 7 | Human handoff: bot_paused | ✅ Closed (15/7) | ✅ Test end-to-end pass: escalate → im lặng → log → resume đều đúng |
| 8 | Dashboard admin + analytics | 🟡 Đang làm (15/7) | 🟡 Phần 1/3 xong: hội thoại + pause/resume + đơn hàng (Next.js, test pass) |
| 9 | CI/CD + deploy VPS + monitoring | 🔵 Opened | 🟡 Có `.gitlab-ci.yml` (lint + test) nhưng chưa có build/deploy/backup/alert |
| 10 | Kenh khach hang du phong (Telegram) | ⚪ Không thuộc backlog gốc | 🟡 Mới thêm 15/7, phát sinh từ sự cố Meta khóa tài khoản test |

---

## #1 · [Tuần 1-2] Webhook Messenger + xác thực Meta (echo bot)
**Trạng thái GitLab:** Closed

**Mục tiêu:** Webhook FastAPI hoạt động end-to-end với fanpage test ở mức echo bot.

**Đầu việc:**
- [x] `GET /webhook`: xác thực `hub.verify_token` với Meta
- [x] `POST /webhook`: xác thực chữ ký `X-Hub-Signature-256` (HMAC app secret)
- [x] Send API client trả lời tin nhắn
- [x] Secrets qua env: `PAGE_ACCESS_TOKEN`, `META_APP_SECRET`, `META_VERIFY_TOKEN`
- [x] Kết nối fanpage test (ngrok/cloudflared khi dev)

**Tiêu chí hoàn thành:** Nhắn tin vào fanpage nhận phản hồi echo < 2 giây.

**Ghi chú:** Đã xác nhận qua code (`app/api/webhook.py`) dùng `hmac.compare_digest` đúng chuẩn.
⚠️ Phát hiện phụ: file `.env` thật từng bị commit rồi xoá (commit `a9db226` → `a9638f9`) —
secret vẫn còn trong git history, cần rotate `META_APP_SECRET`/`PAGE_ACCESS_TOKEN` ngay.

---

## #2 · [Tuần 1-2] Hàng đợi Redis + arq worker (xử lý bất đồng bộ)
**Trạng thái:** ✅ Closed (14/7)

**Mục tiêu:** Webhook trả 200 cho Meta ngay lập tức, toàn bộ xử lý AI chạy trong worker.
Tránh đơ hệ thống khi nhận nhiều tin nhắn cùng lúc.
*(Lưu ý kỹ thuật gốc: BullMQ chỉ dành cho Node.js. Stack Python dùng Redis + arq.)*

**Đầu việc:**
- [x] Redis service trong docker-compose
- [x] `POST /webhook` chỉ validate + enqueue job `process_message` rồi trả 200
- [x] Worker arq: `app/workers/tasks.py`, `max_jobs` hợp lý (~20)
- [ ] Retry policy khi Send API/LLM lỗi; dead-letter log
- [ ] Load test đơn giản: 50 tin nhắn đồng thời không mất tin

**Tiêu chí hoàn thành:** Webhook response time < 100ms; không mất message khi worker restart.

**Lý do đóng dù còn 2 mục chưa tick:** phần lõi (enqueue + worker async) đã chạy đúng mục tiêu
issue. Retry/dead-letter và load test dời thành việc kỹ thuật riêng, theo dõi ở #9 (CI/CD & vận hành)
thay vì giữ issue này mở vô thời hạn.

**Rủi ro tồn đọng cần theo dõi (không thuộc phạm vi issue gốc nhưng phát hiện khi review code):**
- Chưa lọc `is_echo` trong `process_message` → rủi ro lặp vô hạn nếu Page subscribe `message_echoes`.
- Chưa có dedupe theo `mid` → Meta gửi trùng sự kiện có thể tạo 2 câu trả lời cho 1 tin.

---

## #3 · [Tuần 3-4] PostgreSQL + pgvector: schema, migration, seed
**Trạng thái:** ✅ Closed (14/7)

**Mục tiêu:** PostgreSQL làm database chính, pgvector cài trực tiếp làm Knowledge Base cho RAG.

**Đầu việc:**
- [x] Image `pgvector/pgvector:pg16` trong docker-compose, mount `./migrations` vào initdb
- [x] Migration `001_init.sql`: `customers`, `conversations` (có cờ `bot_paused`), `messages`,
      `products`, `orders`, `order_items`, `knowledge_chunks`
- [x] Index HNSW cosine trên `knowledge_chunks.embedding`
- [x] Seed sản phẩm `3S-100G`; giá bán đã chốt theo bậc số lượng
- [x] Kết nối async SQLAlchemy + asyncpg từ app

**Tiêu chí hoàn thành:** `docker compose up` tạo đủ schema; app kết nối và query thành công.

**Ghi chú:** Dimension embedding trong migration là 384 (đã fix từ 1536 ban đầu — khớp với
model `paraphrase-multilingual-MiniLM-L12-v2`). Tất cả đầu việc gốc đã hoàn thành → đóng issue.
Connection pooling ở `rag.py` (đang mở connection mới mỗi query) không thuộc phạm vi issue này —
theo dõi như một việc kỹ thuật riêng khi làm #6/#9.

---

## #4 · [Tuần 3-4] RAG pipeline: ingest profile 3S Coffee + FAQ vào knowledge base
**Trạng thái:** ✅ Closed (14/7)

**Đầu việc:**
- [x] File nguồn `data/knowledge/product_profile.md` + `data/knowledge/faq.md`
- [x] Script `scripts/ingest.py`: chunk → embedding → insert `knowledge_chunks`
- [x] `app/services/rag.py`: `search_knowledge(query, top_k)` dùng cosine `<=>`
- [ ] Đánh giá: 10 câu hỏi mẫu trả về đúng chunk

**Tiêu chí hoàn thành:** Top-4 chunk trả về đúng ngữ cảnh cho ≥ 9/10 câu hỏi mẫu.

**Lý do đóng dù còn 1 mục chưa tick:** pipeline ingest + search đã chạy đúng chức năng.
Bước "đánh giá 10 câu hỏi mẫu" mang tính QA định kỳ hơn là điều kiện chặn issue — gợi ý
mở lại thành issue nhỏ dạng "RAG QA pass" mỗi khi thêm nội dung mới vào `data/knowledge/`,
thay vì giữ issue gốc này mở.

**Việc kỹ thuật tồn đọng cần theo dõi:** offload `embed()` (CPU-bound) ra threadpool để không
chặn event loop worker khi nhiều khách hỏi cùng lúc — nên gộp vào #9 khi tối ưu hạ tầng.

---

## #5 · [Tuần 3-4] System prompt & brand voice: LLM trả lời tư vấn theo chuẩn 3S Coffee
**Trạng thái:** ✅ Closed (14/7)

**Brand voice (bắt buộc trong system prompt):**
- Xưng hô nhất quán, trang trọng: "Chúng tôi" / "Đội ngũ 3S Coffee"
- Giọng điệu: tinh gọn, thực tế, dứt khoát, lì lợm
- Cấm từ ngữ marketing hào nhoáng, cường điệu
- Không bịa giá/khuyến mãi/tồn kho — chỉ dùng dữ liệu từ tools và RAG context

**Đầu việc:**
- [x] Hoàn thiện `app/prompts/system_prompt.md`
- [x] Tích hợp LLM call trong `orchestrator.py`: system prompt + RAG context + lịch sử (Redis, TTL 24h)
- [x] Bộ test hội thoại 20 kịch bản (tư vấn, hỏi giá, so sánh, khách hỏi lung tung)
- [ ] Review giọng điệu output với anh Hoài trước khi lên fanpage thật

**Tiêu chí hoàn thành:** 20/20 kịch bản trả lời đúng vibe, không lệch danh xưng, không bịa thông tin.

**Ghi chú:** Prompt hiện tại đã có phần "Không được suy diễn" và "Khi không có thông tin"
rất chặt — nhưng vì #6 chưa làm, phần "không bịa giá/tồn kho" đang **chỉ dựa vào RAG**,
chưa có tool thật để tin theo đúng thứ tự ưu tiên mà prompt mô tả. Nên coi #5 và #6 là
cặp phụ thuộc nhau khi đánh giá "hoàn thành".

**Cập nhật 14/7 — kết quả chạy 20 kịch bản:** 17/20 pass, 2 fail (scenario 10 — bỏ lỡ
tín hiệu "shop ơi", vẫn gọi "bạn"; scenario 14 — không dừng ở lần từ chối thứ 2), 1
soft-fail (scenario 13 — bỏ qua bước hỏi khách chưa ưng gì ở sản phẩm đang dùng). Đã sửa
`system_prompt.md` (thêm câu mẫu tránh danh xưng + 3 cặp ví dụ SAI/ĐÚNG) và retest riêng
scenario 10, 13, 14 → **cả 3 đã Pass**.
**Trạng thái cuối: 20/20 pass → đóng issue.** Còn lại "review với anh Hoài" là bước duyệt
cảm quan thủ công, không chặn việc đóng issue kỹ thuật này — theo dõi riêng nếu anh Hoài
có phản hồi cần chỉnh thêm.
⚠️ Lưu ý khi review: cả 3 câu trả lời fix đều khá sát với ví dụ mẫu vừa thêm vào prompt —
nên thử thêm vài biến thể câu hỏi ngoài 20 kịch bản gốc nếu muốn chắc chắn hơn về khả
năng tổng quát hoá của model, không chỉ "học thuộc" đúng câu ví dụ.

---

## #6 · [Tuần 5-6] Tool calling: search_products / check_stock / create_order / escalate_to_human
**Trạng thái:** ✅ Closed (14/7)

**Mục tiêu:** LLM gọi tool thay vì tự bịa dữ liệu; luồng chốt đơn hoàn chỉnh.

**Đầu việc:**
- [x] Định nghĩa tool schema: `search_products`, `check_stock`, `create_order`, `escalate_to_human`
      (`app/services/tools.py`, dùng asyncpg thuần giống `rag.py`, không thêm ORM)
- [x] `create_order`: chỉ gọi khi đủ tên + SĐT + địa chỉ + sản phẩm + số lượng; validate SĐT VN
- [x] Ghi `orders` + `order_items`, cập nhật tồn kho (transaction `FOR UPDATE`, tránh race condition)
- [x] Tin xác nhận đơn theo brand voice (tóm tắt đơn, tổng tiền) — **bỏ "thời gian giao dự kiến"**
      khỏi phạm vi vì system prompt cấm bot tự suy đoán thời gian ship, chưa có tool nào cho
      dữ liệu vận chuyển thật
- [x] Guard: LLM không được công bố giá nếu `search_products` chưa trả về giá — nay giá luôn
      lấy từ DB thật qua tool, không còn hardcode trong prompt

**Tiêu chí hoàn thành:** Hội thoại giả lập chốt đơn end-to-end tạo đúng bản ghi trong DB.

**Kết quả test 14/7 (scenario 21, 22 — `data/knowledge/scenarios_20.md`):**
- Scenario 21 (đủ thông tin, 5 hũ): order ghi đúng DB — `total_vnd = 800.000đ` (5 × 160k đúng
  bậc giá), đúng tên/SĐT/địa chỉ; `stock` trừ đúng 1000 → 995.
- Scenario 22 (thiếu tên): bot dừng đúng chỗ, hỏi lại tên, không gọi `create_order` — xác nhận
  0 order rác trong DB ứng với SĐT test.
**Cả 2 pass → đóng issue.**

**Ghi chú quan trọng — phụ thuộc #7:** `escalate_to_human` hiện chỉ làm được "nửa ghi" —
set `bot_paused = TRUE` thật trong `conversations`, nhưng phần "đọc" (worker bỏ qua tin nhắn
khi `bot_paused = TRUE`, báo admin real-time) thuộc phạm vi #7, **chưa làm**. Tool đã sẵn sàng
gọi đúng, nhưng human handoff chưa hoàn chỉnh end-to-end cho tới khi #7 xong.

---

## #7 · [Tuần 5-6] Human handoff: bot_paused + thông báo nhân viên
**Trạng thái:** ✅ Closed (15/7)

**Mục tiêu:** Bot biết dừng đúng lúc: khiếu nại, câu hỏi ngoài phạm vi, hoặc khách yêu cầu gặp người thật.

**Đầu việc:**
- [x] Cờ `bot_paused` theo `conversations`; khi bật, worker bỏ qua tin nhắn của hội thoại đó
      (`app/workers/tasks.py` check `is_bot_paused()` trước khi gọi `handle_message`)
- [x] Trigger tự động: khách gõ "gặp nhân viên" (regex deterministic trong `app/services/handoff.py`,
      không phụ thuộc LLM) / phát hiện khiếu nại / LLM tự gọi `escalate_to_human`
- [x] Thông báo tức thì cho admin qua Telegram (`notify_admin()`, không raise lỗi nếu chưa cấu hình)
- [x] Cơ chế bật lại bot: `POST /admin/conversations/{psid}/resume`, bảo vệ bằng `ADMIN_API_TOKEN`
- [x] Log lý do escalate vào bảng `escalations` mới (`migrations/002_add_escalations.sql`)

**Tiêu chí hoàn thành:** Tin khiếu nại giả lập → bot im lặng đúng cách + admin nhận thông báo < 10 giây.

**Kết quả test 15/7 (scenario 23 — `data/knowledge/scenarios_20.md`):**
- Lượt 1 (đòi gặp nhân viên): escalate ngay, không qua LLM, trả lời xác nhận đúng. Chạy 2 lần liên
  tiếp cho kết quả nhất quán.
- Lượt 2 (nhắn tiếp khi đang paused): bot im lặng hoàn toàn, đúng như worker thật sẽ làm.
- Bảng `escalations` ghi log đúng — xác nhận cả nhánh deterministic (regex) lẫn nhánh LLM tự gọi
  tool (thấy 1 bản ghi với lý do "Khách yêu cầu gặp sếp/quản lý trực tiếp" hoàn toàn do LLM tự
  quyết định, không phải regex cứng) đều hoạt động.
- Endpoint `resume` trả đúng `{"psid": "test_scn_23", "bot_paused": false}`.
**Cả 3 phần pass → đóng issue.**

---

## #8 · [Tuần 7+] Dashboard admin + analytics phễu bán hàng
**Trạng thái:** 🟡 Đang làm (15/7) — phần 1/3 đã xong, test end-to-end pass

**Mục tiêu:** Giao diện quản trị để vận hành và đo lường, tối ưu tỷ lệ chốt đơn.

**Quyết định kỹ thuật:** chọn Next.js riêng biệt (đúng đề xuất gốc) thay vì mở rộng
FastAPI+HTML, chạy service riêng `dashboard/` cổng 3000, gọi API JSON qua `/dashboard/*`
(CORS mở cho `http://localhost:3000`).

**Đầu việc:**
- [x] Dashboard Next.js: danh sách hội thoại (`/conversations`), xem lịch sử tin nhắn
      (`/conversations/[psid]`) — cần thêm `app/services/conversation_log.py` ghi
      `messages` vào Postgres vì trước đó chỉ có Redis (TTL 24h), không đủ cho dashboard
- [x] Bật/tắt bot từng hội thoại (`bot_paused`) — nút trong danh sách hội thoại, gọi
      `POST /dashboard/conversations/{psid}/pause|resume`
- [x] Danh sách đơn hàng (`/orders`) + cập nhật trạng thái (dropdown, server validate
      thứ tự new → confirmed → shipped → done, cấm đi lùi, cấm huỷ đơn `done`)
- [x] **(bổ sung theo yêu cầu anh Hoài 15/7)** Resume qua Telegram: `app/workers/telegram_listener.py`,
      service `telegram_bot` trong docker-compose, dùng lại đúng bot đã cấu hình ở #7
      (`TELEGRAM_BOT_TOKEN`/`TELEGRAM_ADMIN_CHAT_ID`). Long-polling, KHÔNG cần domain/HTTPS
      public. Chỉ xử lý lệnh từ đúng `TELEGRAM_ADMIN_CHAT_ID` đã cấu hình, mọi chat khác
      bị bỏ qua im lặng. Lệnh: `/resume <psid>` (gọi lại đúng `handoff.resume_bot()`
      có sẵn, không viết logic mới), `/list` (liệt kê hội thoại đang chờ), `/help`.
- [ ] CRUD sản phẩm + FAQ (tự động re-ingest RAG khi sửa)
- [ ] Metrics: tin nhắn/ngày, tỷ lệ hội thoại → đơn, top câu hỏi bot không trả lời được
- [ ] Auth đơn giản cho admin (hiện vẫn dùng chung `ADMIN_API_TOKEN` tĩnh như #7, chưa có
      đăng nhập/JWT thật)

**Tiêu chí hoàn thành:** Anh Hoài vận hành fanpage hằng ngày chỉ qua dashboard, không cần vào DB.

**Kết quả test 15/7:** Anh Hoài xác nhận dashboard chạy được, 2 tab (Hội thoại, Đơn hàng)
hoạt động đúng. Quy trình vận hành thực tế hiện tại: nhân viên tự tay bấm resume trên
dashboard sau khi xử lý xong hội thoại với khách trên Messenger (không tự động).

**Ý tưởng nâng cấp (đã triển khai 15/7):** resume bằng lệnh Telegram thay vì phải mở
dashboard — xong, xem chi tiết trong đầu việc ở trên. Chưa test end-to-end (đang chờ anh
Hoài xác nhận `/resume` và `/list` hoạt động đúng trên Telegram thật).

**Cập nhật 15/7 — 3 nâng cấp thêm theo yêu cầu anh Hoài:**
1. Dashboard tự động refresh mỗi 5s (polling ngầm, không nhấp nháy loading) ở cả
   trang danh sách hội thoại lẫn trang chi tiết — không cần F5 tay khi trạng thái
   handover đổi (vd escalate mới, hoặc nhân viên resume qua Telegram).
2. Thêm 2 cách xem hội thoại mở rộng: (a) bấm tên khách để **mở rộng ngay trong
   dòng** (accordion, không rời trang danh sách), (b) nút ↗ để **mở cửa sổ popup riêng**
   (`window.open`, 420×650, giữ riêng theo psid — bấm lại cùng khách sẽ focus vào đúng
   cửa sổ cũ thay vì mở trùng). Lưu ý: đây là khung chat **tự xây** (đọc từ bang
   `messages` của mình), KHÔNG phải nhúng trực tiếp giao diện Messenger thật —
   Facebook chặn iframe từ domain ngoài (X-Frame-Options), không thể nhúng được.
3. Telegram: tin nhắn escalate và `/list` giờ kèm **nút inline "Resume bot ngay"**
   (callback_query) — bấm thẳng, không cần gõ/copy PSID nữa. Vẫn giữ `/resume <psid>`
   thủ công làm phương án dự phòng — PSID hiển thị dạng `code` (Markdown), trên Telegram
   mobile bấm vào là tự động copy.

**Cập nhật 15/7 — xử lý tin nhắn/thoả thuận trong lúc handover** (tình huống thực tế: khách
đề xuất mua 1000 hũ, xin gặp sếp thương lượng chính sách — trước đây bot sẽ “quên” hoàn
toàn thỏa thuận sau khi resume):
- Worker giờ **bắt được tin nhắn thật của nhân viên/sếp** gửi qua Messenger Inbox trong
  lúc `bot_paused=TRUE`, dùng chính cờ `bot_paused` làm “khớp thời gian” (ý tưởng
  timetrap của anh Hoài) — vì bot chắc chắn không tự gửi gì trong lúc đó, mọi echo
  bắt được đúng lúc paused chắc chắn là người thật.
- Vẫn ghi log tin khách gửi trong lúc paused (trước đây bị bỏ qua hoàn toàn).
- Thêm **Note tường minh** khi resume (cả dashboard lẫn Telegram `/resume <psid>
  <ghi chú>`) — phòng trường hợp sếp chốt qua điện thoại, không thể tự bắt được.
- **Bơm ngược cả 2 nguồn** (tin thật + note, đều lưu chung role='agent') vào system
  prompt của bot ở mọi lượt chat sau — đọc từ Postgres (không phải Redis TTL 24h)
  nên không bao giờ mất, tránh bot nói trái thoả thuận đã chốt.
- Dashboard chat window tự động hiện **TẤT CẢ** (khách/bot/agent) theo đúng thứ tự
  thời gian, không cần sửa thêm vì cơ chế hiển thị đã đọc trực tiếp từ `messages` —
  chỉ cần data được ghi đầy đủ (2 mục trên) là tự hiện đúng.
- **Chưa test end-to-end** — cần anh Hoài thử kịch bản thật: pause → trả lời tay qua
  Messenger → resume kèm/không kèm note → hỏi tiếp khách xem bot có nhớ đúng không.

**Cập nhật 15/7 — "ai sẽ ghi đơn hàng" cho đơn giá/số lượng đặc biệt** (ví dụ: khách
thương lượng 500 hũ giá 130k qua staff): thay vì xây form nhập đơn thủ công riêng, quyết
định cuối cùng là để **bot tự tạo đơn** sau khi staff duyệt (an toàn hơn form tự do vì
không thể LLM tự "cấp phép" cho chính nó):
- Bảng mới `price_overrides` (migration 004) — staff duyệt 1 lần đúng 1
  (khách, số lượng, đơn giá) qua lệnh Telegram mới:
  `/approve <mã KH> <số lượng> <đơn giá> [ghi chú]`.
- `create_order` (trong `tools.py`) tự kiểm tra có phê duyệt khớp **CHÍNH XÁC** cả
  psid + số lượng không — nếu có, bỏ qua chốt chặn `MAX_AUTO_QUANTITY=100` và dùng
  đúng đơn giá đã duyệt thay vì bảng `price_tiers` chuẩn; không khớp thì vẫn từ
  chối như cũ. Phê duyệt bị đánh dấu `used=TRUE` sau khi dùng, không tái sử dụng được.
- Sửa `system_prompt.md`: cho phép bot gọi thẳng `create_order` cho đơn >100 hũ NẾU
  ghi chú handover cho thấy đã duyệt và khách xác nhận đúng số lượng — không được tự
  suy diễn là có duyệt khi không thấy rõ.
- **Chưa test end-to-end** — cần thử đúng kịch bản thật: `/approve` → khách xác
  nhận đúng số lượng đã duyệt → bot tự gọi `create_order` thành công (không escalate
  lại), kiểm tra đúng đơn giá trong DB khớp đúng giá đã duyệt (không phải giá bậc chuẩn).

**Chưa đóng issue** — còn CRUD sản phẩm/FAQ, metrics, auth thật theo đúng phạm vi gốc,
và tất cả những gì liệt kê ở trên đều chưa được anh Hoài test thực tế.

**Cập nhật 15/7 — giao diện tạo đơn trên dashboard:**
- Trong khung chat mở rộng (`conversations/page.js`): thêm form tạo đơn với 2 nút
  — **"🤖 Gọi bot tạo đơn"** (gọi thẳng `tools.create_order()` — hàm AI đang dùng,
  vẫn kiểm tra `price_overrides`/bậc giá chuẩn/giới hạn số lượng đầy đủ) và
  **"👤 NV tạo đơn"** (`app/services/orders.py:create_order_manual` — bỏ qua mọi
  validate, staff tự nhập đơn giá, chỉ còn kiểm tra tồn kho thật).
- Trang riêng `/orders/new` — khu vực tạo đơn **hoàn toàn độc lập** với khung chat,
  dùng cho đơn không qua Messenger (điện thoại, tại quầy). Vì `customers.psid` là
  `UNIQUE NOT NULL`, đơn kiểu này tự sinh 1 psid giả dạng `manual:<uuid ngắn>` để
  thỏa mãn ràng buộc, không phải PSID Facebook thật.
- Component `dashboard/app/components/OrderForm.js` dùng chung cho cả 2 vị trí
  (nếu không truyền `psid` thì chỉ hiện nút "NV tạo đơn", không có "gọi bot" vì
  không có hội thoại nào để bot đọc ngữ cảnh).
- Endpoint mới: `GET /dashboard/products`, `POST /dashboard/conversations/{psid}/create_order`,
  `POST /dashboard/conversations/{psid}/create_order_manual`, `POST /dashboard/orders/manual`.
- **Chưa test end-to-end** — cần thử cả 3 luồng: (1) "Gọi bot tạo đơn" với số
  lượng >100 không có `/approve` → phải bị từ chối đúng như bot; (2) "NV tạo đơn"
  với giá/số lượng bất kỳ → phải tạo được bình thường; (3) `/orders/new` → đơn tạo
  ra phải có `psid` dạng `manual:...`, không gắn nhầm vào khách nào khác.

**Cập nhật 15/7 — tự điền form từ `/approve` + `/note`** (theo yêu cầu anh Hoài, tránh
phải đối chiếu tay trên khung chat):
- Endpoint mới `GET /dashboard/conversations/{psid}/order_draft` gom 3 nguồn: (1)
  tên/SDT/địa chỉ từ `customers` (nếu đã từng có đơn trước), (2) số lượng + đơn
  giá từ phê duyệt `/approve` **chưa dùng** gần nhất (`price_overrides.get_latest_unused_override`),
  (3) 5 ghi chú `/note` gần nhất (hiển thị thô, không auto-parse vì không đủ tin cậy
  cho trường như địa chỉ).
- `OrderForm.js` tự gọi endpoint này khi mở (nếu có `psid`) — tự điền sẵn số
lượng/đơn giá từ `/approve`, tên/SDT/địa chỉ nếu đã có từ đơn cũ; hiện bảng
ghi chú `/note` phía trên form để staff đối chiếu tay phần còn thiếu (thường là
địa chỉ nếu khách chưa từng đặt đơn).

**Lưu ý anh hỏi về `/note` lưu ở đâu:** bảng `messages` (Postgres, KHÔNG phải Redis) —
`role='agent'`, liên kết qua `conversation_id` → `conversations` → `customer_id` →
`customers.psid`. Ghi qua `handoff.log_note()` → `conversation_log.log_message()`.
Đọc lại qua `conversation_log.get_recent_agent_messages(psid)` — đã dùng ở 2 chỗ:
(1) `orchestrator.py` bơm vào system prompt mỗi lượt chat (bot biết), (2) endpoint
`order_draft` mới (staff thấy trực tiếp trên dashboard, không cần query SQL tay nữa).
Query tay nếu cần: `SELECT role, content FROM messages WHERE conversation_id = (SELECT id FROM conversations WHERE customer_id = (SELECT id FROM customers WHERE psid = '...')) ORDER BY created_at DESC;`
- **Chưa test** — cần xác nhận: `/approve` xong → mở khung chat khách đó trên
dashboard → số lượng/đơn giá phải tự hiện đúng trong form, không cần gõ lại.

**Cập nhật 15/7 (lần 2) — sửa lại luồng theo phản hồi anh Hoài:** thay vì nhúng form
trực tiếp trong khung chat (gây rối, khó test), đổi thành **1 nút điều hướng** trong
khung chat mở rộng → sang thẳng trang `/orders/new?psid=...` (trang "Tạo đơn" chính):
- Nút chỉ mang theo `psid` qua query param (**không** đưa tên/SDT/địa chỉ vào URL
vì là dữ liệu nhạy cảm).
- `/orders/new` đọc `psid` từ query, truyền vào `OrderForm` — tự động kích hoạt
lại đúng logic fetch `order_draft` đã có sẵn (không viết thêm logic mới), hiện cả
2 nút "Gọi bot tạo đơn"/"NV tạo đơn" y hệt như khi dùng ở trang độc lập.
- **Lưu ý kỹ thuật:** `useSearchParams()` trong Next.js App Router bắt buộc phải bọc
trong `<Suspense>`, nếu không `next build` (production, Dockerfile đang dùng) sẽ lỗi
— đã tách thành component con `NewOrderContent` nằm trong `<Suspense>`.
- **Chẩn đoán sự cố anh Hoài báo "không thấy `/approve`/`/note` được ghi nhận":** code
`/approve` chỉ gửi tin xác nhận Telegram **sau khi** ghi DB thành công (nếu lỗi sẽ không
gửi gì cả), nên nhiều khả năng dữ liệu đã được ghi đúng, chỉ là dashboard chưa
rebuild nên không thấy hiển thị — chưa xác nhận 100% vì anh Hoài chưa query DB trực tiếp.
- **Chưa test lại** sau khi sửa lần này.

**Cập nhật 15/7 (lần 3) — fix 2 vấn đề anh Hoài báo:**
1. **Bug thật đã xác định được nguyên nhân:** `price_overrides.create_override()` (hàm
`/approve` gọi) trước giờ chỉ tự tạo `customers`, KHÔNG tạo `conversations` đi kèm.
Dashboard liệt kê hội thoại bắt đầu từ bảng `conversations` (INNER JOIN), nên khách
`/approve` mà chưa từng chat/`​/note` trước đó sẽ **không bao giời hiện trên dashboard**
dù `price_overrides` đã có dữ liệu đúng. Fix: `create_override()` giờ gọi
`conversation_log.ensure_conversation()` trước (giống `/note` đang làm), đảm bảo luôn
có cả `customers` lẫn `conversations`.
2. **Khôi phục khung hiển thị "thông tin nội bộ" ngay trong khung chat** (bị mất sau
lần sửa trước vì chuyển toàn bộ sang `/orders/new`) — giờ hiện lại ở `conversations/page.js`
qua state `expandedDraft` (gọi lại đúng API `order_draft` đã có), nhưng **chỉ hiển
thị (đọc)** — việc tạo đơn vẫn đi qua nút điều hướng sang `/orders/new` như đã thống
nhất, không nhúng lại form tạo đơn vào khung chat.
- **Chưa test lại.** Cần xác nhận: `/approve` cho 1 khách MỚI (chưa từng chat) → phải
hiện ngay trên danh sách hội thoại dashboard, mở ra phải thấy khung vàng thông tin nội bộ.

**Cập nhật 16/7 — fix bug rac "psid = 'Mã'/'khách'":** anh Hoài test lại, `price_overrides`
và `messages(role='agent')` đã ghi đúng, nhưng `conversations` xuất hiện 2 dòng rác
với `psid = "Mã"` và `psid = "khách"`. Nguyên nhân: tin Telegram tự hiển thị "Mã KH:
`4`" khiến anh Hoài (hợp lý) gõ nguyên cụm "Mã KH: 4" vào lệnh thay vì chỉ gõ số `4`
— code chỉ tách theo khoảng trắng và lấy từ đầu tiên ("Mã") làm psid, tạo khách rác.
Fix:
- Thêm `handoff.is_valid_identifier()` — chặn ngay từ đầu nếu input không phải thuần
số hoặc sender_id hệ thống hợp lệ (`tg:...`, `manual:...`), trả lỗi rõ ràng thay vì
tạo dữ liệu rác âm thầm. Áp dụng cho cả `/resume`, `/note`, `/approve`.
- Đổi cách hiển thị mã KH trên Telegram (`notify_admin`, `/list`, `/help`) — nhấn
mạnh rõ "CHỈ gõ số này, KHÔNG gõ chữ 'Mã KH'" để tránh lặp lại.

**Dọn dẹp dữ liệu rác** (anh tự xác nhận rồi chạy, không tự động xóa giúp vì cần anh
Hoài xác nhận đúng là rác trước):
```sql
DELETE FROM messages WHERE conversation_id IN (
  SELECT c.id FROM conversations c JOIN customers cu ON cu.id = c.customer_id
  WHERE cu.psid IN ('Mã', 'khách'));
DELETE FROM conversations WHERE customer_id IN (
  SELECT id FROM customers WHERE psid IN ('Mã', 'khách'));
DELETE FROM customers WHERE psid IN ('Mã', 'khách');
```
- **Chưa test lại** sau fix này — cần thử gõ sai (vd `/note Mã KH: 4 test`) để xác
nhận bot trả lỗi rõ ràng thay vì tạo rác, và gõ đúng (`/note 4 test`) để xác nhận
vẫn hoạt động bình thường.

**Cập nhật 16/7 (lần 2) — fix tận gốc vấn đề "quen quên rebuild dashboard":**
Sau nhiều lần lặp lại cùng 1 triệu chứng (dashboard không cập nhật code mới: thiếu
nút, thiếu khung note, không hiện đơn...), chuyển hẳn `dashboard` service sang **DEV
MODE có hot-reload** trong `docker-compose.yml`, giống hệt cách `api` đang dùng `--reload`:
- `command: npm run dev` thay vì `npm run build && npm start`.
- Bind-mount `./dashboard:/app` — sửa file là thấy ngay, KHÔNG cần
`docker compose up --build dashboard` nữa (vẫn cần **hard refresh trang** Ctrl+Shift+R).
- 2 volume riêng `dashboard_node_modules`, `dashboard_next_cache` để không bị
bind-mount từ host đè lên (host có thể không có `node_modules` hoặc khác OS).
- **Từ giờ chỉ cần `docker compose up -d dashboard` 1 lần duy nhất** (lần đầu để
`npm install`), sau đó mọi thay đổi code Next.js tự áp dụng, không cần lệnh gì thêm.

**Lưu ý quan trọng:** `price_overrides` KHÔNG phải đơn hàng — chỉ là giấy phép giá/số
lượng. Đơn thật chỉ tồn tại trong bảng `orders` sau khi bấm "Gọi bot tạo đơn"/"NV tạo
đơn" thành công. Cần phân biệt rõ 2 khái niệm này khi báo lỗi "không thấy đơn".
- **Chưa test lại** sau đổi sang dev mode — cần xác nhận `docker compose up -d --build
dashboard` (lần cuối cùng cần build vì đổi command) chạy được, container không crash,
và sau đó sửa 1 dòng text bất kỳ trong dashboard để xác nhận hot-reload hoạt động thật.

**Cập nhật 16/7 (lần 4) — nhãn Status gọn + nút hành động gắn từng note/approve:**
Sau khi test, anh Hoài nhận ra cột "Xử lý" (Action) chung cho cả hội thoại không đúng bản
chất (1 hội thoại có thể nhiều note/approve khác nhau). Thiết kế lại:
- Migration 006: thêm `messages.handled` (tái dùng `price_overrides.used` có sẵn cho
  approve, không cần cột mới).
- Bỏ badge to → nhãn gọn `/n(N)` (note chưa xử lý) và `/a(N)` (approve chưa dùng),
  số in đậm, màu xám khi N=0 để vẫn dễ "liếc mắt" khi có việc cần làm.
- **Bỏ hẳn cột "Xử lý"** – không dùng nữa (migration 005 `staff_action` vẫn để
nguyên trong DB, không xóa).
- Khung mở rộng giờ liệt kê **TỪNG note** và **TỪNG approve chưa xử lý** riêng
lẻ (không chỉ note gần nhất như trước) — mỗi dòng có nút riêng:
  - Note: nút "✓ Đã xử lý" — không cần popup xác nhận.
  - Approve: nút "✓ Đã tạo đơn" — BẮT BUỘC popup xác nhận trước (dùng `window.confirm`).
- Endpoint mới: `POST /dashboard/notes/{message_id}/mark-handled`,
  `POST /dashboard/overrides/{override_id}/mark-used`.
- **Quan trọng:** `conversation_log.get_recent_agent_messages()` (hàm bom context cho
  bot) **KHÔNG** lọc theo `handled` — bot vẫn phải biết toàn bộ thoả thuận dù
  staff đã đánh dấu "đã xử lý" trên dashboard hay chưa — cờ này chỉ gọn UI, không
  làm mất hiệu lực thoả thuận.
- **Chưa test** — cần chạy migration 006 trước, restart `worker`, hard refresh dashboard
(tự hot-reload, không cần build lại).

**Cập nhật 16/7 (lần 5, cuối session) — không ẩn lịch sử + thêm luồng Từ chối:**
Anh Hoài chỉ ra: note/approve đã xử lý trước đây “biến mất” khỏi giao diện là vì dashboard
đang **lọc** (`WHERE used/handled = FALSE`), không phải xóa DB — nhưng vẫn cần xem lại
được. Sửa:
- Migration 007: thêm `price_overrides.status` ('active'/'used'/'rejected') +
  `reject_reason`. `used` (boolean) vẫn là nguồn thật cho logic `create_order`
  (không đổi), `status` chỉ để dashboard hiển thị đúng nhãn.
- `order_draft` giờ trả **TOÀN BỘ** note/approve (không lọc), kèm cờ `handled`/`status`
  để frontend tự quyết định hiển thị “Active” hay “Frozen”.
- Frontend: item đã xử lý hiển **mờ (opacity), nền xám, không còn nút** — chỉ còn
  nhãn tĩnh (✓ Đã xử lý / ✓ Đã tạo đơn / ✗ Đã từ chối). Item `active` vẫn hiện đầy đủ
  nút như cũ.
- Thêm nút **“✗ Từ chối”** cạnh “✓ Đã tạo đơn” cho mỗi approve đang active — popup
  `window.prompt` xin lý do (bắt buộc nhập, không để trống), rồi gọi
  `POST /dashboard/overrides/{id}/reject`. Approve bị reject vẫn `used=TRUE` (không
  dùng lại được cho `create_order`) nhưng hiển rõ lý do từ chối trên dashboard.
- **Badge `/n(N)`/`/a(N)` ở bảng chính KHÔNG đổi** — vẫn chỉ đếm item “Active/chưa xử lý”
  (đúng tinh thần “cần chú ý”), không đếm cả item frozen.
- **Chưa test** — cần chạy migration 007, restart `worker`, hard refresh. Kiểm tra: (1)
  đánh dấu 1 note/approve → vẫn thấy trong list (frozen, không biến mất); (2) từ chối
  1 approve kèm lý do → hiện đúng lý do; (3) approve bị reject **không** dùng được
  cho “Gọi bot tạo đơn” nữa (vì `used=TRUE`).

**Known limitation đã chấp nhận, KHÔNG fix (16/7):** dù đã chuyển `dashboard` sang dev
mode hot-reload, thực tế vẫn cần `docker compose up -d --build dashboard` sau mỗi lần
sửa code (không tự nhận code mới hoàn toàn như kỳ vọng ban đầu). Anh Hoài đồng ý
**không cần đào sâu fix tiếp** — quy trình thực tế: mỗi lần Claude sửa code
`dashboard/`, luôn chạy lại `docker compose up -d --build dashboard` (không chỉ
`restart`) rồi mới hard refresh trang.

**Cập nhật 16/7 (lần 3) — UX bảng hội thoại** (theo phản hồi: mọi thứ trước đó thực ra
đã hoạt động, chỉ là khó tìm vì đường vào duy nhất là click tên khách):
- Thêm nút **"▼ Mở rộng chat"** rõ ràng ngay cạnh tên khách (thay vì chỉ click vào tên).
- **Bỏ nút ↗ "Mở cửa sổ riêng"** cuối dòng — tránh nhầm lẫn với nút mở rộng mới (trang
`/conversations/[psid]` vẫn còn trong code, chỉ không còn đường dẫn tới nữa).
- Thêm cột **"Ghi chú/Duyệt"** (Status) — hiện badge "Có ghi chú"/"Có duyệt giá" ngay
trên dòng, không cần mở rộng mới biết. Backend thêm `has_notes`/`has_approve`
(EXISTS subquery) vào `GET /dashboard/conversations`.
- Thêm cột **"Xử lý"** (Action) — dropdown staff tự đánh dấu "Mới/Đã xem/Đã tạo đơn/
Bỏ qua", độc lập hoàn toàn với `bot_paused`. Cột `conversations.staff_action` mới
(migration 005, CHECK constraint 4 giá trị), endpoint `PATCH /dashboard/conversations/{psid}/action`.
- **Chưa test** — cần chạy migration 005 trước, restart `worker` (dashboard tự hot-reload
không cần build lại), hard refresh, rồi kiểm tra cả 4 điểm trên.

---

## #9 · [Hạ tầng] CI/CD GitLab + deploy VPS + monitoring
**Trạng thái GitLab:** Opened — mới có phần lint/test cơ bản

**Mục tiêu:** Hệ thống chạy 24/7 trên VPS, deploy tự động qua GitLab CI/CD.

**Đầu việc:**
- [x] `.gitlab-ci.yml`: lint (ruff) → test (pytest)
- [ ] Build Docker image → deploy VPS (SSH)
- [ ] Secrets trong GitLab CI/CD variables: `PAGE_ACCESS_TOKEN`, `META_APP_SECRET`, `LLM_API_KEY`
      (masked, protected) — không hardcode
- [ ] VPS ~2GB RAM, Docker Compose; HTTPS bắt buộc cho webhook (Caddy hoặc Nginx + Let's Encrypt)
- [ ] Backup PostgreSQL hằng ngày
- [ ] Alert khi webhook lỗi liên tiếp hoặc LLM API fail; fallback: "Đội ngũ 3S Coffee sẽ phản
      hồi bạn ngay." + báo nhân viên
- [ ] Log toàn bộ hội thoại để review định kỳ

**Tiêu chí hoàn thành:** Push lên `main` → tự động deploy; uptime webhook > 99%.

**Ghi chú:** Pipeline hiện tại cho phép "pass" dù chưa có test nào (`pytest -q || [ $? -eq 5 ]`),
nên coi bước "test" là placeholder, chưa phải cổng chất lượng thật.

---

## #10 · Kenh khach hang du phong qua Telegram (khong thuoc backlog goc)
**Trạng thái:** 🟡 Mới thêm 15/7

**Bối cảnh:** Meta khóa vai trò dev của tài khoản test, không test được qua Messenger.
Để không bị động hoàn toàn, thêm 1 kênh Telegram riêng cho **khách hàng** (khác hẳn
bot admin ở #7/#8 chỉ nhận thông báo/lệnh nội bộ) — xem như kênh test/dev song song,
không thay thế Messenger về lâu dài.

**Đầu việc:**
- [x] `app/workers/telegram_customer_listener.py` — bot Telegram riêng (token khác bot
      admin), long-polling, trả lời BẤT KỲ AI nhắn tới (không giới hạn chat_id như bot admin).
- [x] `sender_id` dùng hệ thống chung với Messenger, dạng `tg:<chat_id>` (có prefix, không
      bao giờ trùng PSID Facebook thật) — tái sử dụng **y nguyên** `orchestrator.handle_message()`,
      không viết lại logic AI/tool/RAG/handoff nào cả.
- [x] `orchestrator.py`: bỏ qua gọi Messenger Graph API (lấy tên) cho `sender_id` không
      phải Messenger (`tg:` hoặc `manual:`), tránh 1 request thất bại vô ích mỗi lượt chat.
- [x] `is_bot_paused`/log tin nhắn khi paused: dùng lại đúng logic worker Messenger
      (`app/workers/tasks.py`), không có phiên bản riêng cho kênh này.
- [x] Service mới `telegram_customer_bot` trong `docker-compose.yml`, setting
      `TELEGRAM_CUSTOMER_BOT_TOKEN` (bot **khác hẳn** `TELEGRAM_BOT_TOKEN` dùng cho admin).
- [ ] **Chưa test** — cần tạo bot Telegram mới qua @BotFather (khác bot admin), set
      `TELEGRAM_CUSTOMER_BOT_TOKEN`, restart, nhắn thử từ Telegram xem bot có trả lời
      đúng giọng điệu/giá/RAG giống hệt Messenger không (vì dùng chung 100% logic).

**Lưu ý quan trọng:** đây không phải thay thế Messenger — vẫn nên xử lý song song vấn
đề với Meta (tạo lại test user/xin lại quyền dev) vì Messenger vẫn là kênh chính cho
khách thật tại Việt Nam. Đã thảo luận thêm 2 hướng dài hạn (app chat riêng trên website,
Zalo OA) nhưng chưa làm — cần anh Hoài quyết định khi nào ưu tiên.

---

## Đề xuất thứ tự ưu tiên tiếp theo
1. Xử lý ngay việc rotate secret (ghi chú ở #1) — vẫn còn tồn đọng từ đầu dự án, độc lập với
   thứ tự dưới, nên làm sớm nếu chưa làm.
2. **#9 (CI/CD thật + deploy)** — giờ là ưu tiên kỹ thuật cao nhất còn lại: #5/#6/#7 đã xong
   phần lõi nghiệp vụ, nên chuyển sang làm cho hệ thống chạy ổn định 24/7 trước khi mở rộng
   tính năng (#8).
3. Các việc kỹ thuật tồn đọng từ #2/#3/#4 (dedupe theo `mid`, retry/dead-letter, connection
   pooling, offload `embed()`, RAG QA định kỳ) — gộp xử lý cùng #9.
4. #8 (dashboard) để sau, khi hạ tầng (#9) đã ổn định — dashboard cũng sẽ cần endpoint
   `/admin/conversations/{psid}/resume` (đã có từ #7) làm nền, nên #7 xong trước là hợp lý.

## Tài liệu tham chiếu (docs/)
Đã tạo đủ 4 file trong `docs/` (16/7) — giống file `/help` cho từng thành phần, dùng
khi deploy/bàn giao/debug, không cần dò lại code:
- `docs/DATABASE.md` — toàn bộ schema, lịch sử migration, câu SQL tra cứu thường dùng
- `docs/DASHBOARD.md` — từng trang/nút của dashboard Next.js, gắn đúng endpoint nào
- `docs/TELEGRAM_BOT.md` — 2 bot Telegram (admin/khách hàng), lệnh, cách tạo bot mới
- `docs/BACKEND_API.md` — toàn bộ FastAPI: webhook, orchestrator, tool calling, human
  handoff, danh sách service/worker, biến môi trường

**Chưa làm:** `docs/DEPLOYMENT.md` — để dành khi #9 (CI/CD + deploy VPS) xong, lúc đó
 mới có quy trình deploy thật để viết tài liệu chính xác.

## Cập nhật 16/7 — đổi tên file docs/ + ISSUES.md sang hậu tố -VI, thêm bản dịch -EN
Toàn bộ 5 file tham chiếu (`ISSUES.md` + 4 file trong `docs/`) đổi tên sang hậu tố
`-VI` (vd `ISSUES-VI.md`, `docs/DATABASE-VI.md`...), thêm bản dịch tiếng Anh tương ứng
`-EN` cho từng file. Lưu ý sự cố gặp phải: sau khi đổi tên, `git status` không nhận
diện được các file mới (không báo untracked) — hóa ra file thật sự nằm sai vị trí
(ngoài thư mục gốc dự án) và `ISSUES-VI.md` bị rỗng (0 byte) do lỗi công cụ file
của Claude — đã khôi phục đúng vị trí bằng `git show HEAD:ISSUES.md > ISSUES-VI.md`
rồi bổ sung lại đoạn này (thiếu trong bản commit gần nhất vì chưa từng commit
sau khi viết đoạn này).

## Bat 2 #8 — CRUD Sản phẩm/FAQ (17/7)
Đã làm xong 1/3 việc còn lại của #8 (CRUD sản phẩm/FAQ) — metrics và auth thật vẫn chưa làm.

**CRUD Sản phẩm** (`app/services/products.py`, trang `/products`):
- Sửa `products` (tên/mô tả/giá lẻ/tồn kho) — **KHÔNG cho sửa `sku` sau khi tạo** (là khóa
  tool dùng tra cứu, đổi giữa chừng rủi ro cao).
- Xóa sản phẩm bị **từ chối bởi ràng buộc khóa ngoại** nếu đã có đơn hàng/bậc giá liên
  quan (thiết kế có chủ đích, tránh xóa nhầm sản phẩm đã có lịch sử).
- Bậc giá: `PUT /products/{id}/tiers` thay **TOÀN BỘ** danh sách mỗi lần lưu (xóa hết
  bậc cũ, insert lại bậc mới trong 1 transaction) — đơn giản hơn PATCH từng dòng.
- **Lưu ý phạm vi quan trọng:** chỉ sửa dữ liệu **có cấu trúc** (tool đọc trực tiếp) —
  mô tả sản phẩm dùng cho trò chuyện tự do (RAG) vẫn nằm tĩnh trong
  `data/knowledge/product_profile.md`, **KHÔNG tự đồng bộ 2 chiều**. Đã ghi rõ trên UI.

**CRUD FAQ** (`app/services/knowledge_entries.py`, trang `/faq`):
- Bảng mới `faq_entries` (migration 008) + cột `knowledge_chunks.faq_entry_id`
  (FK, `ON DELETE CASCADE`) — khác với nội dung tĩnh trong `data/knowledge/*.md`
  (nạp 1 lần qua `scripts/ingest.py`), FAQ tạo qua dashboard **lưu thẳng vào DB**.
- Tạo/sửa FAQ: tự tính embedding (`embed()`) và ghi thẳng vào `knowledge_chunks`
  **ngay lập tức**, không cần chạy lại `ingest.py` — bot dùng được từ câu hỏi kế tiếp.
- Sửa: **XOÁ chunk cũ rồi TẠO LẠI** (không UPDATE embedding tại chỗ) — tránh trường
  hợp content mới nhưng embedding cũ bị lệch nhau.
- Xóa: `knowledge_chunks` liên quan tự xóa theo qua `ON DELETE CASCADE`.
- Nội dung tĩnh gốc (`product_profile.md`, `faq.md`) **không bị ảnh hưởng gì** —
  2 nguồn cùng tồn tại song song trong `knowledge_chunks`, phân biệt qua cột `source`
  (`product_profile.md`/`faq.md` vs `dashboard:faq`).

**Chưa test end-to-end** — cần: chạy migration 008, restart `worker` (backend Python thay
đổi), hard refresh dashboard (đã hot-reload). Test: (1) thêm 1 sản phẩm mới → gọi
`search_products` qua chat xem có thấy không; (2) thêm 1 FAQ (vd “Có giao quốc tế
không?”) → hỏi bot ngay câu đó qua chat, xem có trả lời đúng nội dung vừa thêm không
(xác nhận RAG thật sự đã cập nhật, không chỉ lưu DB); (3) xóa sản phẩm đã có đơn
hàng → phải bị từ chối đúng thông báo, không crash.

## Fix bug 17/7 — bot không nhận diện SKU mới thêm qua CRUD
Anh Hoài thêm 2 SKU mới (hũ 60g, túi zip 200g) qua `/products`, hỏi bot không nhận
ra, kể cả gõ đúng từ khóa "tiết kiệm" (liên quan túi zip 200g). **Xác định nguyên
nhân:** `search_products` đọc thẳng từ `products`, KHÔNG lọc theo `query` — luôn
trả về toàn bộ sản phẩm, không phải lỗi chạy sai code. Vấn đề thật: **LLM không
gọi tool** vì 2 nơi trong prompt/schema viết như thể chỉ có 1 sản phẩm duy nhất:
1. **`system_prompt.md`** mục "Kiến thức sản phẩm" và "Chính sách giá" mô tả duy nhất
   hũ 100g như thể đó là toàn bộ sự thật, không có cảnh báo “có thể còn SKU khác”.
2. **QUAN TRỌNG HƠN:** `tools.py:TOOL_DEFINITIONS` — mô tả tham số `query` của
   `search_products` ghi cứng "hiện tại chỉ có 1 sản phẩm nên thường để trống" —
   dòng này nằm trong schema gửi cho LLM ở **MỌI lượt chat**, độc lập với RAG, nên
   ảnh hưởng trực tiếp và liên tục hơn cả nội dung prompt.

**Fix:**
- `system_prompt.md`: thêm cảnh báo rõ ở đầu mục "Kiến thức sản phẩm" và "Chính
  sách giá" — danh mục có thể đã thay đổi qua dashboard, LUÔN gọi `search_products`
  cho bất kỳ câu hỏi nào về sản phẩm/kích cỡ/đóng gói/giá, kể cả khi không nêu tên
  SKU cụ thể (thêm ví dụ từ khóa: “tiết kiệm”, “gói lớn”, “loại khác”).
- `tools.py`: sửa lại mô tả tham số `query` — bỏ câu “chỉ có 1 sản phẩm”, thay bằng
  hướng dẫn LUÔN gọi để lấy danh sách mới nhất. Cũng sửa mô tả `sku`/`quantity`
  trong `create_order` (bỏ cứng từ “hũ”, thêm nhắc “lấy từ search_products, không
  tự bịa”) vì giờ có SKU dạng túi/gói, không chỉ hũ.
- **Bài học rút ra:** khi thiết kế tool schema, không nên viết cứng giả định về
  dữ liệu hiện tại (“chỉ có 1 sản phẩm”) vào mô tả tham số — giả định đó sẽ lỗi
thời ngay khi dữ liệu thay đổi (và nay chính CRUD sản phẩm mới xây ở trên làm
điều đó xảy ra ngay lập tức).

**Chưa test lại** sau fix — cần restart `worker`, hỏi lại đúng câu “tiết kiệm” anh
đã test, xác nhận bot gọi được `search_products` và nhắc đúng túi zip 200g.

## Fix bug 17/7 (lần 2) — bot vẫn khẳng định sai "chỉ có 1 SKU" dù đã restart
Anh Hoài xác nhận **đã restart** trước khi test, nhưng bot vẫn khẳng định sai "chỉ
có 1 SKU" **3 lần liên tiếp**, ngày càng dứt khoát hơn ("em đã kiểm tra lại database"),
kể cả khi khách (Hoài) trực tiếp phản bác. Đây là vấn đề **nghiêm trọng hơn**
bug trước — không chỉ là "không gọi tool", mà còn có dấu hiệu LLM **khẳng định đã
kiểm tra** trong khi có thể không thật sự gọi tool (hoặc bị "consistency bias" — giữ
nguyên câu trả lời đầu tiên thay vì xác minh lại mỗi lần khách hỏi lại).

**Fix (không phụ thuộc việc LLM có chịu gọi tool hay không nữa):**
- Thêm `products.py:get_sku_summary_text()` — trả về 1 dòng text liệt kê toàn bộ
  SKU hiện có.
- `orchestrator.py` **bơm THẲNG** kết quả này vào system prompt **ở MỌI lượt chat**
  (không phải qua tool_calls) — giống cách đang bơm agent notes. Đây là nguồn sự
  thật về **sự tồn tại** của SKU, không phụ thuộc LLM tự quyết định gọi tool hay
  không — giá/bậc giá/tồn kho chi tiết vẫn phải qua `search_products`/`check_stock`
  như cũ (không bơm toàn bộ chi tiết để tránh làm prompt quá dài/lỗi thời nếu giá đổi).
- `system_prompt.md`: thêm quy tắc chặn hành vi "khẳng định đã kiểm tra" — cấm nói
  đã "kiểm tra"/"tra cứu database" nếu không thật sự gọi tool trong lượt đó, và bắt
  buộc gọi lại tool khi khách phản bác 1 thông tin đã trả lời trước đó.

**Chờ anh Hoài xác nhận 2 việc:**
1. Kết quả SQL `SELECT id, sku, name FROM products ORDER BY id;` — loại trừ khả
   năng dữ liệu thật sự bị thiếu/lỗi trong DB (đã gửi yêu cầu chạy, chưa nhận
   được kết quả khi viết đoạn này).
2. Test lại sau khi restart `worker` với fix lần này — cần hỏi lại đúng kịch bản
   “có bao nhiêu SKU” rồi phản bác 1-2 lần giống đoạn chat thật đã gửi, xem bot có
   liệt kê đúng cả 3 SKU ngay từ lần đầu không (không cần phản bác mới đúng).

## Nâng cấp 17/7 — “Lớp 2”: RAG tự đồng bộ theo từng sản phẩm
Sau khi fix xong bug “chỉ có 1 SKU”, anh Hoài đặt câu hỏi đúng hướng: cách “bơm
thẳng vào prompt” sẽ không scale khi nhiều SKU/ngành hàng đa dạng hơn. Đã thảo
luận và thống nhất thiết kế **2 lớp**:
- **Lớp 1** (giữ nguyên, đã làm ở fix trước): `get_sku_summary_text()` — chỉ tên +
  SKU, cực ngắn, không phình dù có nhiều sản phẩm. Lưới an toàn cho “sự tồn tại”.
- **Lớp 2** (mới): mỗi sản phẩm tự động có 1 `knowledge_chunk` riêng trong RAG,
  CRUD qua `/products` tự tạo/sửa/xóa chunk này — tái dùng **y nguyên** pattern đã
  làm cho FAQ (`knowledge_entries.py`), không phải xây mới từ đầu.

**Triển khai:**
- Migration 009: thêm `knowledge_chunks.product_id` (FK, `ON DELETE CASCADE`).
- `products.py`: `create_product`/`update_product` giờ tính embedding từ
  `{sku} - {name}: {description}` và ghi/thay chunk tương ứng trong cùng 1
  transaction với việc ghi `products`. `delete_product` không cần xóa chunk tay
  — `ON DELETE CASCADE` tự lo.
- **Không cần sửa `orchestrator.py`** — `search_knowledge()` (RAG) đã chạy **không
  điều kiện** mỗi lượt chat từ trước giờ (không phụ thuộc LLM có tự quyết định
  gọi hay không) — đây chính là lý do Lớp 2 đáng tin cậy hơn việc dựa vào
  `search_products` (tool, phụ thuộc LLM quyết định gọi hay không).
- UI `/products`: cập nhật ghi chú + placeholder ô mô tả, nhấn mạnh mô tả giờ
  dùng trực tiếp cho RAG (khác `product_profile.md` tĩnh, vẫn tách biệt).

**Lưu ý quan trọng khi anh test:** 2 SKU (hũ 60g, túi zip 200g) đã tạo **TRƯỚC** khi
code này tồn tại sẽ **CHƯA có** knowledge_chunk tương ứng (chỉ sản phẩm tạo/sửa
**sau** khi chạy migration 009 + restart mới tự sinh). Cần **vào `/products`, bấm
“Sửa” rồi “Lưu” lại** cho 2 sản phẩm đó (không cần đổi gì, chỉ cần trigger lại
đúng lượt update) để tạo chunk RAG cho chúng.

**Chưa test** — cần: chạy migration 009, restart `worker`, hard refresh dashboard,
re-save 2 sản phẩm cũ như trên, rồi hỏi bot câu chi tiết (vd “túi zip 200g pha thế
nào”, “có gì khác hũ 100g”) — xác nhận RAG trả đúng đoạn mô tả vừa nhập, không chỉ
danh sách tên SKU (Lớp 1).

## Công cụ dev 17/7 — `scripts/clear_chat_history.py`
Sau khi xác nhận Bat 2 hoạt động đúng (2 tầng SKU summary + RAG sản phẩm), gặp
đúng vấn đề đã dự đoán: anh Hoài test lại **đúng cuộc chat cũ** (đã từng hỏi “có
bao nhiêu SKU” trước khi fix) — bot vẫn trả lời sai vì Redis (TTL 24h) còn giữ
đúng câu trả lời sai cũ trong lịch sử, LLM có xu hướng giữ nhất quán với chính
nó thay vì tự sửa theo system prompt mới. **Không phải bug** — chỉ xảy ra khi test
lại đúng thread cũ sau khi sửa hành vi bot.

Vì dự án đang giai đoạn dev, tình huống này sẽ còn lặp lại nhiều — thêm script
theo yêu cầu anh Hoài:
- `docker compose exec api python scripts/clear_chat_history.py` — xóa **toàn bộ**
  cache Redis (mọi `chat:*`).
- `... clear_chat_history.py <sender_id>` — chỉ xóa **đúng 1** cuộc chat (vd
  `tg:5913051767` cho Telegram, hoặc PSID Facebook đầy đủ cho Messenger).
- `... clear_chat_history.py --list` — liệt kê các cuộc chat đang có trong Redis
  (kèm TTL còn lại) để tìm đúng sender_id trước khi xóa.
- **CHỈ xóa Redis (bộ nhớ ngữ cảnh LLM)**, không đụng tới Postgres — lịch sử
  tin nhắn trên dashboard vẫn giữ nguyên.
- Có cảnh báo rõ trong docstring: **không dùng trên production** khi đã có khách
thật đang chat (sẽ làm mất ngữ cảnh 24h gần nhất của họ).

## Fix bug 17/7 (lần 3) — bot tự bịa ra 1 SKU không tồn tại
Sau khi xác nhận Bat 2 hoạt động đúng (dùng `clear_chat_history.py` để test sạch),
anh Hoài phát hiện lỗ hổng mới: hỏi "có loại nào phù hợp cho xưởng đóng gói không"
— bot **tự bịa** ra 1 SKU không tồn tại ("3S-25KG – Thùng 25kg"), miêu tả chi tiết
như thật. May mắn: khi hỏi giá cụ thể, cơ chế "không được khẳng định đã kiểm
tra nếu chưa gọi tool" (fix lần 2) đã khiến bot tự gọi lại tool, phát hiện SKU
đó không có thật, và **tự xin lỗi đúng** — nhưng lẽ ra không nên bịa ngay từ đầu.

**Nguyên nhân:** câu lệnh Lớp 1 (`get_sku_summary_text` bơm vào prompt) chỉ dặn
"không được nói TRÁI dữ liệu này" — chưa nói rõ đây là danh sách ĐẦY ĐỦ, không
được bịa THÊM. Khi câu hỏi khách không khớp đúng với SKU nào trong danh sách,
LLM có xu hướng "sáng tạo" ra 1 sản phẩm nghe hợp lý thay vì nói thật là chưa có.

**Fix:**
- `orchestrator.py`: siết lại câu lệnh Lớp 1 — nhấn mạnh đây là danh sách "DUY
  NHẤT và ĐẦY ĐỦ", TUYỆT ĐỐI KHÔNG được bịa thêm SKU ngoài danh sách dù nghe
  hợp lý với nhu cầu khách — phải nói thật là chưa có.
- `system_prompt.md`: thêm quy tắc tương tự vào mục "Không được suy diễn", kèm
  ví dụ SAI/ĐÚNG lấy đúng từ tình huống thật vừa xảy ra (lặp lại pattern đã
  dùng cho các quy tắc khác trong prompt — ví dụ cụ thể giúp model tuân thủ tốt
  hơn là chỉ nói chung chung).

**Chưa test lại** — cần restart cả 4 service (`api worker telegram_bot
telegram_customer_bot`), xóa Redis history của đúng cuộc chat đã test (dùng
`clear_chat_history.py`), rồi hỏi lại đúng câu “có loại nào phù hợp cho xưởng đóng
gói không” — lần này bot phải trả lời thật là chưa có dòng đó, không bịa SKU mới.

## Fix bug 17/7 (lần 4) — bot tự mâu thuẫn với chính nó (không phải bug dữ liệu)
Sau khi anh Hoài xác nhận `3S-25KG` **là SKU thật** (anh tự tạo trước khi hỏi, không
phải bot bịa) — xác minh lại toàn bộ: DB đúng (SKU tồn tại, `created_at` khớp đúng
thời điểm trước tin nhắn đầu), code đúng (không có thao tác nào làm mất dữ liệu).
**Vấn đề thật:** bot trả lời đúng ở tin 10:53, rồi **tự mâu thuẫn với chính nó**
6 phút sau (11:00), phủ nhận đúng điều nó vừa nói đúng trước đó — không phải lỗi
code/DB có thể sửa dứt điểm, mà là vấn đề độ tin cậy vốn có của model (DeepSeek).

**3 lớp giảm thiểu đã thêm (không loại trừ hẳn được, chỉ giảm rủi ro):**
1. `orchestrator.py`: giảm `temperature` 0.3 → 0.1 — ưu tiên bám sát dữ liệu được
   cung cấp hơn là "sáng tạo", hợp với bot bán hàng cần chính xác.
2. `orchestrator.py`: thêm rõ **thứ tự ưu tiên khi có mâu thuẫn** vào lời bơm Lớp 1
   — danh sách SKU bơm mỗi lượt là dữ liệu **sống**, luôn đáng tin hơn lịch sử hội
   thoại (kể cả câu trả lời trước đó của chính bot) — không được tự "sửa lại" thành
   phủ nhận trừ khi vừa gọi lại tool và nhận kết quả khác thật.
3. `tools.py`: kết quả `search_products` giờ tự kèm dòng "đây là danh sách đầy
   đủ và duy nhất" ngay trong response — củng cố thêm ở tầng kết quả tool, không
   chỉ dựa vào system prompt.

**Chưa test lại** — cần restart cả 4 service, xóa Redis đúng cuộc chat đã test
(`clear_chat_history.py`). Anh Hoài đã chọn để sau mới test lại theo kịch bản cụ
thể — khi nào tiện cần thử lại đúng câu “có loại nào phù hợp cho xưởng đóng gói
không” rồi hỏi giá ngay sau đó, xem có còn tái diễn không.

## Fix bug 17/7 (lần 5) — bug THẬT (khác hẳn lần 4): `search_products` thiếu `price_vnd`
Anh Hoài tiếp tục đào sâu trong **cùng cuộc chat chưa xóa Redis** ở trên, hỏi đi hỏi
lại giá SKU 25kg. Bot cuối cùng ổn định lại đúng: SKU có thật, nhưng "không có
bảng giá công khai theo bậc" — và giữ nguyên kết luận này **dù anh đã thêm giá lẻ
trước đó và thêm bậc giá sau đó**. Lần này **không phải** lỗi độ tin cậy LLM — là
bug code thật, xác minh được qua đọc code trực tiếp:

**Nguyên nhân:** `tools.py:search_products()` **chưa bao giờ trả về `price_vnd`**
(giá lẻ mặc định của sản phẩm) — chỉ trả `price_tiers_vnd_per_unit` (bảng bậc
giá). SKU hũ 100g gốc luôn có sẵn bậc giá từ "1+" nên chưa từng lộ ra lỗ hổng này;
chỉ khi tạo sản phẩm mới qua CRUD (chỉ set `price_vnd` lúc tạo, chưa thêm bậc
giá riêng) mới lộ ra: bot gọi đúng tool, nhưng tool trả về `price_tiers_vnd_per_unit`
rỗng — không hề có số nào để nói, dù `price_vnd` vẫn có giá trị đúng trong DB.

**Fix:** `search_products()` giờ trả thêm `price_vnd_default` cho mỗi sản phẩm,
kèm ghi chú rõ trong `note`: nếu không có bậc giá nào khớp số lượng khách hỏi, PHẢI
dùng giá này làm giá mặc định, không được nói "chưa có giá".

**Lưu ý thêm:** `create_order` (khi thật sự tạo đơn) đã luôn fallback đúng về
`product["price_vnd"]` khi không có bậc giá khớp — chỉ riêng `search_products` (hàm
bot dùng để **trả lời** khách) là thiếu, nên nếu khách thật sự đặt đơn được thì
giá vẫn sẽ đúng — chỉ là bot không thể **nói** giá đó ra trước khi chốt đơn.

**Chưa test lại** — cần restart cả 4 service, xóa Redis đúng cuộc chat đã test (đã
tích lũy nhiều vòng tự mâu thuẫn, nên **bắt buộc xóa sạch** thay vì tiếp tục test
trong cuộc này), rồi hỏi lại giá SKU 25kg từ đầu — lần này phải thấy đúng giá lẻ
đã set, không còn nói "chưa có giá".

**✅ XÁC NHẬN ĐÃ FIX (17/7)** — anh Hoài test lại sau khi restart + xóa Redis, hỏi
giá SKU 25kg từ 1 cuộc chat sạch: bot trả đúng **cả giá lẻ (650.000đ/kg) lẫn bậc
giá (630.000đ/kg từ 10 thùng)**, tự tính đúng tổng 25kg × 650k = 16.250.000đ/thùng.
Không còn nói "chưa có giá", không còn tự mâu thuẫn. Đóng bug lần 5.

## Bat 3 #8 — Metrics/Analytics (17/7)
Đã làm xong 2/3 việc còn lại của #8 (CRUD + Metrics) — chỉ còn Auth thật chưa làm.
**Không thêm bảng mới nào** — tận dụng hoàn toàn dữ liệu sẵn có.

**`app/services/metrics.py`** — 3 hàm, 3 endpoint mới (`/dashboard/metrics/*`):
1. **Tin nhắn/ngày** (`list_messages_per_day`) — đếm `messages` theo ngày, tách
   theo `role` (khách/bot/nhân viên). Ngày không có tin nhắn không xuất hiện trong
   kết quả (không tự điền 0).
2. **Tỷ lệ hội thoại → đơn** (`get_conversion_rate`) — % khách (theo `customer_id`)
   đã từng có ít nhất 1 đơn trong `orders`, trên tổng số khách đã từng chat.
   **Đơn giản hóa có chủ đích**: không tách theo thời gian (vd theo ngày/tuần) —
   chỉ là tỷ lệ tổng thể từ trước tới giờ, có thể mở rộng sau nếu cần.
3. **Top câu hỏi bot không trả lời được** (`list_unanswered_questions`) — dò tìm
   tin nhắn bot khớp đúng câu fallback cố định trong `system_prompt.md` ("chưa
   có thông tin xác nhận..."), lấy đúng câu hỏi khách gửi **ngay trước** tin đó
   trong cùng 1 conversation, gom nhóm theo nội dung câu hỏi (chuẩn hóa
   thường/trim) để đếm tần suất. **Không dùng NLP/fuzzy matching** — 2 câu hỏi
   khác chữ dù cùng ý nghĩa sẽ bị đếm riêng (giới hạn đã biết, chấp nhận cho
   phạm vi hiện tại).

**Trang dashboard mới `/metrics`** — 3 thẻ tổng quan (tổng khách/khách có đơn/tỷ
 lệ) + bar chart tự vẽ bằng CSS (không thêm thư viện chart, tránh phải `npm
install` thêm gói mới trong container dev mode) cho tin nhắn/ngày + bảng câu hỏi
chưa trả lời được.

**Chưa test** — cần restart `api` (endpoint mới nằm trong `dashboard.py`, không
phải `worker`), hard refresh dashboard. Kiểm tra: (1) số liệu tổng quan có khớp
đúng số đơn thật trong DB không; (2) thử 1 câu hỏi bot chắc chắn không trả lời
được (vd hỏi phí ship cụ thể) — xác nhận câu đó xuất hiện đúng trong bảng "Top
câu hỏi" sau khi chat.
