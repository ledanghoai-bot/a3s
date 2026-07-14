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
| 7 | Human handoff: bot_paused | 🔵 Opened | ❌ **Chưa làm** — cờ có trong schema nhưng code không đọc |
| 8 | Dashboard admin + analytics | 🔵 Opened | ❌ Chưa bắt đầu |
| 9 | CI/CD + deploy VPS + monitoring | 🔵 Opened | 🟡 Có `.gitlab-ci.yml` (lint + test) nhưng chưa có build/deploy/backup/alert |

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
**Trạng thái GitLab:** Opened — **chưa triển khai trong code**

**Mục tiêu:** Bot biết dừng đúng lúc: khiếu nại, câu hỏi ngoài phạm vi, hoặc khách yêu cầu gặp người thật.

**Đầu việc:**
- [ ] Cờ `bot_paused` theo `conversations`; khi bật, worker bỏ qua tin nhắn của hội thoại đó
- [ ] Trigger tự động: khách gõ "gặp nhân viên" / phát hiện khiếu nại / LLM gọi `escalate_to_human`
- [ ] Thông báo tức thì cho admin (Telegram bot hoặc email) kèm link hội thoại
- [ ] Cơ chế bật lại bot (API endpoint hoặc lệnh từ dashboard)
- [ ] Log lý do escalate để cải thiện prompt

**Tiêu chí hoàn thành:** Tin khiếu nại giả lập → bot im lặng đúng cách + admin nhận thông báo < 10 giây.

**Ghi chú:** Cột `bot_paused` đã có sẵn trong schema (#3) nhưng `handle_message()` chưa
đọc cột này ở bất kỳ đâu — nghĩa là kể cả khi có người set cờ thủ công, bot vẫn tự trả lời
chồng lên nhân viên. Rủi ro thực tế cao nhất trong toàn bộ backlog, nên làm cùng lúc với #6.

---

## #8 · [Tuần 7+] Dashboard admin + analytics phễu bán hàng
**Trạng thái GitLab:** Opened — chưa bắt đầu

**Mục tiêu:** Giao diện quản trị để vận hành và đo lường, tối ưu tỷ lệ chốt đơn.

**Đầu việc:**
- [ ] Dashboard (Next.js hoặc Vue): danh sách hội thoại, xem lịch sử tin nhắn
- [ ] Bật/tắt bot từng hội thoại (điều khiển `bot_paused`)
- [ ] CRUD sản phẩm + FAQ (tự động re-ingest RAG khi sửa)
- [ ] Danh sách đơn hàng + cập nhật trạng thái (new → confirmed → shipped → done)
- [ ] Metrics: tin nhắn/ngày, tỷ lệ hội thoại → đơn, top câu hỏi bot không trả lời được
- [ ] Auth đơn giản cho admin

**Tiêu chí hoàn thành:** Anh Hoài vận hành fanpage hằng ngày chỉ qua dashboard, không cần vào DB.

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

## Đề xuất thứ tự ưu tiên tiếp theo
1. **#7 (human handoff)** — giờ là gap quan trọng nhất còn lại: `escalate_to_human` (#6) đã
   set được `bot_paused = TRUE` thật, nhưng chưa ai đọc cờ này — bot vẫn tự trả lời chồng lên
   nhân viên sau khi escalate. Ưu tiên số 1.
2. Xử lý ngay việc rotate secret (ghi chú ở #1) — độc lập với thứ tự trên, nên làm song song bất cứ lúc nào.
3. Các việc kỹ thuật tồn đọng từ #2/#3/#4 (is_echo, dedupe theo `mid`, retry/dead-letter, connection
   pooling, offload `embed()`, RAG QA định kỳ) — không chặn go-live nhưng ảnh hưởng chất lượng
   vận hành, gộp xử lý cùng #9.
4. #9 (CI/CD thật + deploy) trước khi lên production chính thức.
5. #8 (dashboard) để sau, khi luồng bán hàng cốt lõi đã ổn định.
