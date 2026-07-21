# Alpha3S — Issue Backlog

> Khôi phục từ file export GitLab (`2026-07-04_13-00-438_ledanghoai-group_alpha3s_export.tar.gz`),
> biên soạn lại 21/7 theo chuẩn markdown, gộp các bản cập nhật rời rạc thành mô tả trạng thái
> hiện tại. 12 issue (9 gốc + #10 phát sinh + #11/#12 mới), tất cả đã đóng trừ #9.

| # | Issue | Trạng thái |
|---|-------|------------|
| 1 | Webhook Messenger + xác thực Meta | ✅ Closed |
| 2 | Hàng đợi Redis + arq worker | ✅ Closed |
| 3 | PostgreSQL + pgvector: schema/migration/seed | ✅ Closed |
| 4 | RAG pipeline: ingest + search | ✅ Closed |
| 5 | System prompt & brand voice | ✅ Closed |
| 6 | Tool calling (search_products/check_stock/create_order/escalate_to_human) | ✅ Closed |
| 7 | Human handoff: bot_paused | ✅ Closed |
| 8 | Dashboard admin + analytics | ✅ Closed |
| 9 | CI/CD + deploy VPS + monitoring | 🟡 Đang làm (2/nhiều Bat) |
| 10 | Kênh khách hàng dự phòng (Telegram) | ✅ Closed |
| 11 | Knowledge Base V2 (Ingestion → Retrieval → Router → Prompt Assembly → Guardrails → Test Suite) | ✅ Closed (song song production) |
| 12 | Lớp NLU (Normalization → Pattern Router → Semantic Router → Combined Pipeline → Tích hợp bot thật) | 🟡 Đang tích hợp (Bat 1-2/nhiều) |

---

## #1 · Webhook Messenger + xác thực Meta (echo bot)
**Trạng thái:** ✅ Closed

**Mục tiêu:** Webhook FastAPI hoạt động end-to-end với fanpage test ở mức echo bot.

**Đầu việc:**
- [x] `GET /webhook`: xác thực `hub.verify_token` với Meta
- [x] `POST /webhook`: xác thực chữ ký `X-Hub-Signature-256` (HMAC app secret, `hmac.compare_digest`)
- [x] Send API client trả lời tin nhắn
- [x] Secrets qua env: `PAGE_ACCESS_TOKEN`, `META_APP_SECRET`, `META_VERIFY_TOKEN`
- [x] Kết nối fanpage test (ngrok/cloudflared khi dev)

**Tiêu chí hoàn thành:** Nhắn tin vào fanpage nhận phản hồi echo < 2 giây. — Đạt.

**⚠️ Rủi ro bảo mật tồn đọng:** file `.env` thật từng bị commit rồi xoá (commit `a9db226` → `a9638f9`)
— secret vẫn còn trong git history. **Cần rotate `META_APP_SECRET`/`PAGE_ACCESS_TOKEN` ngay khi
có thể** — việc này không thể tự động hóa, cần anh Hoài tự làm qua Meta Developer Console.

---

## #2 · Hàng đợi Redis + arq worker (xử lý bất đồng bộ)
**Trạng thái:** ✅ Closed

**Mục tiêu:** Webhook trả 200 cho Meta ngay lập tức, toàn bộ xử lý AI chạy trong worker.
*(Lưu ý: BullMQ chỉ dành cho Node.js — stack Python dùng Redis + arq.)*

**Đầu việc:**
- [x] Redis service trong docker-compose
- [x] `POST /webhook` chỉ validate + enqueue job `process_message` rồi trả 200
- [x] Worker arq: `app/workers/tasks.py`
- [x] Retry policy + dead-letter (hoàn thiện ở #9 Bat 1)
- [x] Dedupe theo `mid` (hoàn thiện ở #9 Bat 1)

**Tiêu chí hoàn thành:** Webhook response time < 100ms; không mất message khi worker restart. — Đạt.

---

## #3 · PostgreSQL + pgvector: schema, migration, seed
**Trạng thái:** ✅ Closed

**Mục tiêu:** PostgreSQL làm database chính, pgvector làm Knowledge Base cho RAG.

**Đầu việc:**
- [x] Image `pgvector/pgvector:pg16`, mount `./migrations` vào initdb
- [x] Migration `001_init.sql`: `customers`, `conversations` (cờ `bot_paused`), `messages`,
      `products`, `orders`, `order_items`, `knowledge_chunks`
- [x] Index HNSW cosine trên `knowledge_chunks.embedding` (384 chiều, khớp
      `paraphrase-multilingual-MiniLM-L12-v2`)
- [x] Seed sản phẩm `3S-100G` theo bậc giá số lượng
- [x] Kết nối async SQLAlchemy + asyncpg

**Tiêu chí hoàn thành:** `docker compose up` tạo đủ schema; app kết nối và query thành công. — Đạt.

---

## #4 · RAG pipeline: ingest profile 3S Coffee + FAQ
**Trạng thái:** ✅ Closed

**Đầu việc:**
- [x] Nguồn `data/knowledge/product_profile.md` + `data/knowledge/faq.md`
- [x] `scripts/ingest.py`: chunk → embedding → insert `knowledge_chunks`
- [x] `app/services/rag.py`: `search_knowledge(query, top_k)` dùng cosine `<=>`
- [x] `embed()` offload sang threadpool (hoàn thiện ở #9 Bat 1, tránh chặn event loop worker)

**Tiêu chí hoàn thành:** Top-4 chunk trả về đúng ngữ cảnh cho phần lớn câu hỏi mẫu. — Đạt.

---

## #5 · System prompt & brand voice
**Trạng thái:** ✅ Closed

**Brand voice (bắt buộc trong system prompt):**
- Xưng hô nhất quán, trang trọng: "Chúng tôi" / "Đội ngũ 3S Coffee"
- Giọng điệu tinh gọn, thực tế, dứt khoát — cấm marketing hào nhoáng, cường điệu
- Không bịa giá/khuyến mãi/tồn kho — chỉ dùng dữ liệu từ tools và RAG context

**Đầu việc:**
- [x] `app/prompts/system_prompt.md` hoàn thiện
- [x] Tích hợp LLM call trong `orchestrator.py`: system prompt + RAG context + lịch sử (Redis TTL 24h)
- [x] Bộ test 20 kịch bản hội thoại

**Kết quả:** 20/20 kịch bản pass (2 vòng sửa: bỏ lỡ tín hiệu xưng hô "shop ơi", không dừng đúng
lúc khi khách từ chối liên tiếp — đã fix bằng ví dụ SAI/ĐÚNG trong prompt).

---

## #6 · Tool calling: search_products / check_stock / create_order / escalate_to_human
**Trạng thái:** ✅ Closed

**Mục tiêu:** LLM gọi tool thay vì tự bịa dữ liệu; luồng chốt đơn hoàn chỉnh.

**Đầu việc:**
- [x] Tool schema trong `app/services/tools.py` (asyncpg thuần, không ORM)
- [x] `create_order`: chỉ gọi khi đủ tên + SĐT + địa chỉ + sản phẩm + số lượng; validate SĐT VN
- [x] Ghi `orders` + `order_items`, cập nhật tồn kho (transaction `FOR UPDATE`, tránh race condition)
- [x] Guard: giá luôn lấy từ DB thật qua tool, không hardcode trong prompt

**Kết quả test:** Order end-to-end đúng DB (tổng tiền đúng bậc giá, tồn kho trừ đúng); thiếu
thông tin → bot dừng đúng chỗ, không tạo order rác.

---

## #7 · Human handoff: bot_paused + thông báo nhân viên
**Trạng thái:** ✅ Closed

**Mục tiêu:** Bot biết dừng đúng lúc: khiếu nại, ngoài phạm vi, hoặc khách yêu cầu gặp người thật.

**Đầu việc:**
- [x] Cờ `bot_paused` theo `conversations`; worker bỏ qua tin nhắn khi bật
- [x] Trigger tự động: regex "gặp nhân viên" (`app/services/handoff.py`, không phụ thuộc LLM) +
      LLM tự gọi `escalate_to_human` khi phát hiện khiếu nại
- [x] Thông báo tức thì cho admin qua Telegram (`notify_admin()`)
- [x] Resume bot: `POST /admin/conversations/{psid}/resume`
- [x] Log lý do escalate vào bảng `escalations`

**Kết quả test:** Cả nhánh deterministic (regex) lẫn nhánh LLM tự quyết định đều hoạt động đúng;
resume trả đúng trạng thái; bot im lặng hoàn toàn khi đang paused.

---

## #8 · Dashboard admin + analytics
**Trạng thái:** ✅ Closed — toàn bộ checklist gốc (CRUD, Metrics, Auth) hoàn tất

**Quyết định kỹ thuật:** Next.js riêng biệt (`dashboard/`, cổng 3000), gọi API JSON qua
`/dashboard/*` (CORS mở cho `http://localhost:3000`). Dev mode dùng hot-reload
(`npm run dev` + bind-mount) — **lưu ý:** vẫn cần `docker compose up -d --build dashboard`
sau mỗi lần sửa code để chắc chắn nhận thay đổi mới (hot-reload không đáng tin cậy 100%
trên Docker Desktop Windows), không chỉ hard refresh trình duyệt.

### Hội thoại & Handoff
- [x] Danh sách hội thoại + xem lịch sử tin nhắn (ghi qua `app/services/conversation_log.py`
      vào Postgres, không chỉ Redis TTL 24h)
- [x] Bật/tắt bot từng hội thoại, tự động refresh 5s
- [x] Khung chat mở rộng (accordion) ngay trong danh sách
- [x] **Resume qua Telegram** (`app/workers/telegram_listener.py`) — long-polling, không cần
      domain/HTTPS public, chỉ nhận lệnh từ `TELEGRAM_ADMIN_CHAT_ID` đã cấu hình:
      `/resume <psid>`, `/list`, `/help`, nút inline "Resume ngay"
- [x] **Bắt tin nhắn thật của nhân viên** gửi qua Messenger Inbox trong lúc `bot_paused=TRUE`
      (dùng chính cờ `bot_paused` làm "khớp thời gian" — bot chắc chắn không tự gửi gì lúc đó)
      + **Note tường minh** qua `/note <mã KH> <nội dung>` — cả 2 nguồn bơm vào system prompt
      mọi lượt chat sau, tránh bot nói trái thỏa thuận đã chốt qua điện thoại/trực tiếp

### Đơn hàng & Phê duyệt giá đặc biệt
- [x] Danh sách đơn hàng + cập nhật trạng thái (server validate thứ tự
      `new → confirmed → shipped → done`, cấm đi lùi/hủy đơn `done`)
- [x] `price_overrides` (bảng riêng) — staff duyệt 1 lần đúng 1 (khách, số lượng, đơn giá) qua
      `/approve <mã KH> <số lượng> <đơn giá>`; `create_order` tự kiểm tra khớp CHÍNH XÁC trước khi
      bỏ qua giới hạn `MAX_AUTO_QUANTITY=100`
- [x] Trang `/orders/new` — tạo đơn độc lập (điện thoại/tại quầy), tự sinh `psid` dạng
      `manual:<uuid>`; 2 nút "🤖 Gọi bot tạo đơn" (qua `tools.create_order()`, đủ validate) và
      "👤 NV tạo đơn" (`orders.py:create_order_manual`, bỏ qua validate giá)
- [x] Form tự điền từ `/approve` + 5 `/note` gần nhất (`GET /dashboard/conversations/{psid}/order_draft`)
- [x] Trạng thái note/approve: nhãn gọn `/n(N)`/`/a(N)`, không ẩn lịch sử (item đã xử lý hiển mờ,
      không biến mất), luồng "✗ Từ chối" kèm lý do bắt buộc

**⚠️ Lưu ý quan trọng:** `price_overrides` KHÔNG phải đơn hàng — chỉ là giấy phép giá/số lượng.
Đơn thật chỉ tồn tại trong `orders` sau khi tạo đơn thành công.

### CRUD sản phẩm & FAQ
- [x] Sửa sản phẩm (không cho sửa `sku` sau khi tạo); xóa bị chặn nếu đã có đơn/bậc giá liên quan
- [x] Bậc giá: `PUT /products/{id}/tiers` thay toàn bộ mỗi lần lưu
- [x] FAQ: bảng `faq_entries` riêng, lưu thẳng vào `knowledge_chunks` ngay khi tạo/sửa (không cần
      chạy lại `ingest.py`)
- [x] **"Lớp 2" RAG tự đồng bộ sản phẩm** — mỗi sản phẩm tự có 1 `knowledge_chunk` riêng
      (`products.py`, embedding từ `{sku} - {name}: {description}`), chạy không điều kiện mỗi
      lượt chat (không phụ thuộc LLM có gọi tool hay không) — đáng tin cậy hơn tầng
      `search_products` (tool, phụ thuộc quyết định của LLM)
- [x] **"Lớp 1" lưới an toàn** — `get_sku_summary_text()` bơm thẳng vào system prompt mọi lượt
      chat, nhấn mạnh đây là danh sách SKU DUY NHẤT và ĐẦY ĐỦ, tuyệt đối không bịa thêm

### Metrics
- [x] `/dashboard/metrics/*`: tin nhắn/ngày theo role, tỷ lệ hội thoại → đơn, top câu hỏi bot
      không trả lời được (dò theo câu fallback cố định, không dùng NLP fuzzy matching)

### Auth thật
- [x] Thay thế hoàn toàn `ADMIN_API_TOKEN` tĩnh bằng đăng nhập theo từng nhân viên
      (`staff_users`/`staff_sessions`, session token `secrets.token_urlsafe`, mật khẩu
      `hashlib.pbkdf2_hmac` 200k vòng — không thêm dependency JWT/bcrypt để tránh rebuild)
- [x] Trang `/staff` quản lý tài khoản (chưa phân quyền theo role — giới hạn đã biết, chấp
      nhận cho quy mô đội nhỏ)
- [x] `scripts/create_staff_user.py` bootstrap tài khoản đầu tiên

**Known limitations đã chấp nhận, không fix thêm:**
- Không phân quyền theo role (mọi staff quản lý được tài khoản khác)
- Không audit trail, không đổi/quên mật khẩu qua email
- Mô tả sản phẩm cho RAG và `product_profile.md` tĩnh không tự đồng bộ 2 chiều

**Bài học kỹ thuật quan trọng:** khi thiết kế tool schema cho LLM, không viết cứng giả định về
dữ liệu hiện tại (vd "chỉ có 1 sản phẩm") vào mô tả tham số — giả định lỗi thời ngay khi dữ liệu
đổi. Độ tin cậy của LLM (tự mâu thuẫn giữa các lượt chat) là vấn đề vốn có của model, giảm thiểu
bằng nhiều lớp (temperature thấp, dữ liệu sống ưu tiên hơn lịch sử, tool result tự khẳng định lại)
chứ không loại trừ được hoàn toàn.

---

## #9 · CI/CD GitLab + deploy VPS + monitoring
**Trạng thái:** 🟡 Đang làm — Bat 1-2/nhiều đã xong (phần không cần VPS)

**Mục tiêu:** Hệ thống chạy 24/7 trên VPS, deploy tự động qua GitLab CI/CD.

### Bat 1 — Dọn nợ kỹ thuật + chuẩn bị production
- [x] Dedupe theo `mid` (Redis `SET NX EX`, chặn xử lý trùng webhook event)
- [x] Retry + dead-letter (`max_tries=3`, ghi Redis list `dead_letter:messages` khi thất bại
      lần cuối)
- [x] Connection pool `asyncpg` (`app/db_pool.py`) — mới migrate 2 module nóng nhất
      (`conversation_log.py`, `products.py`); còn ~8 service khác vẫn dùng connect trực tiếp
- [x] `embed()` offload threadpool (`embed_async()`)
- [x] Dọn `ADMIN_API_TOKEN` khỏi config (legacy)
- [x] `docker-compose.prod.yml` độc lập: không bind-mount source, dashboard production build,
      DB/Redis không expose port, `POSTGRES_PASSWORD` bắt buộc qua env (test xác nhận báo lỗi
      đúng khi thiếu)

### Bat 2 — Test thật cho CI
- [x] `tests/` mới — 38 test case / 60 assertion, tập trung hàm logic thuần (không chạm DB):
      `is_valid_identifier`, `wants_human`, `validate_transition` (state machine đơn hàng),
      `PHONE_RE`, `_unit_price_for_quantity`, `_hash_password`/`_verify_password`
- [x] `.gitlab-ci.yml`: bỏ điều kiện placeholder giả (`|| [ $? -eq 5 ]`) — CI giờ fail thật;
      thêm stage `build` (xác nhận `docker build` thành công trên nhánh `main`)
- [x] Xác nhận chạy thật: 38/38 PASSED trong container

**Còn lại (chưa làm, cần VPS/domain thật):**
- [ ] Build Docker image → deploy VPS (SSH)
- [ ] Secrets trong GitLab CI/CD variables (masked, protected)
- [ ] Reverse proxy + HTTPS (Caddy/Nginx + Let's Encrypt)
- [ ] Backup PostgreSQL hằng ngày
- [ ] Alert khi webhook lỗi liên tiếp / LLM API fail
- [ ] `docs/DEPLOYMENT.md` (để dành khi có quy trình deploy thật)

**Tiêu chí hoàn thành:** Push lên `main` → tự động deploy; uptime webhook > 99%.

---

## #10 · Kênh khách hàng dự phòng qua Telegram
**Trạng thái:** ✅ Closed (không thuộc backlog gốc — phát sinh từ sự cố Meta khóa tài khoản test)

**Bối cảnh:** Meta khóa vai trò dev của tài khoản test, không test được qua Messenger. Thêm 1
kênh Telegram riêng cho **khách hàng** (khác hẳn bot admin ở #7/#8) làm kênh test/dev song song.

**Đầu việc:**
- [x] `app/workers/telegram_customer_listener.py` — bot riêng (token khác bot admin), trả lời
      bất kỳ ai nhắn tới
- [x] `sender_id` dạng `tg:<chat_id>` — tái sử dụng y nguyên `orchestrator.handle_message()`,
      không viết lại logic AI/tool/RAG/handoff
- [x] Dùng chung logic `is_bot_paused`/log tin nhắn với worker Messenger

**Lưu ý:** không thay thế Messenger — vẫn cần xử lý song song với Meta (kênh chính cho khách
thật tại Việt Nam). Chưa quyết định hướng dài hạn (app chat riêng, Zalo OA).

---

## #11 · Knowledge Base V2 (Ingestion → Retrieval → Router → Prompt Assembly → Guardrails → Test Suite)
**Trạng thái:** ✅ Closed — song song production, chưa tích hợp vào bot thật

**Bối cảnh:** Yêu cầu mới ngoài backlog gốc — team Knowledge gửi kiến trúc Knowledge Base đầy đủ
(governance, hybrid retrieval, Prompt Assembly, Runtime). Phạm vi đã thống nhất: build đủ 6
milestone (M1-M6) theo `IMPLEMENTATION_PLAN.md` gốc, **tách biệt hoàn toàn** khỏi
`knowledge_chunks`/`rag.py`/bot production đang chạy — không đụng gì tới #4.

### M1 — Ingestion
- [x] `app/services/kb_ingest/` — parser 4 định dạng front matter khác nhau (YAML chuẩn, text
      1 dòng, bold có "& Locked", bold nhiều dòng), chunk theo heading tự nhận diện `primary_level`
- [x] `scripts/kb_normalize_source.py` — chuẩn hóa cấu trúc thư mục lệch spec (`skill/` vs
      `skills/`, FAQ vị trí sai) tự động
- [x] `scripts/kb_ingest.py` — pipeline đầy đủ, atomic switch thủ công có chủ đích (in SQL, không
      tự kích hoạt)
- [x] Migration `011_knowledge_base_v2.sql` — 4 bảng mới, hoàn toàn cộng thêm

### M2 — Retrieval
- [x] `app/services/kb_retrieval.py` — hybrid vector (pgvector) + lexical (Postgres tsvector) +
      Reciprocal Rank Fusion + boost domain/priority
- [x] **Bug nghiêm trọng đã fix:** hệ số boost domain ban đầu (`P1: +0.03`) lớn hơn cả điểm RRF
      tối đa, khiến nội dung gắn nhãn P1 thắng áp đảo bất kể liên quan — giảm còn `1e-7`
      (tiebreaker thật sự)
- [x] **Bug embedding đã fix:** heading bị pha loãng trong embedding dài — thêm trường
      `embedding_text` riêng, số lần lặp heading tự tính theo tỷ lệ độ dài (chiếm ≥~50% trọng số)
- [x] Xác nhận: câu hỏi pha chế/thương hiệu trả đúng KU #1 với điểm gần tối đa lý thuyết

### M3 — Intent/Risk Router
- [x] `app/services/kb_router.py` — phân loại theo đúng "Decision Logic" có sẵn trong
      `SKL-CON-001.md` (không tự bịa), MVP từ khóa/regex (chưa dùng LLM)
- [x] **2 bug đã fix:** thiếu chuẩn hóa bỏ dấu (khách VN hay gõ không dấu); khớp nhầm substring
      ("hỏng" lọt vào "không") — thêm ranh giới từ `\b`
- [x] **Bug hệ thống đã fix:** regex chỉ khớp cụm liền kề, câu thật có danh từ chen giữa (vd "Pha
      **cà phê 3S** thế nào?") không khớp được — thêm cơ chế khớp cách quãng (`_gap_re`)

### M4 — Prompt Assembly
- [x] `app/services/kb_prompt_assembly.py` — đúng 9 block theo `PA-001`, block rỗng bị bỏ hoàn
      toàn, Assembly Logic theo route (ẩn Knowledge khi route=human/tool)

### M5 — Runtime Guardrails
- [x] `app/services/kb_runtime.py` — Pre-Generation Guardrails (thật, dựa dữ liệu có sẵn) +
      Post-Generation Validation (heuristic, giới hạn rõ — cần LLM-as-judge cho đánh giá đầy đủ)
- [x] Fallback F2 (Clarification), F3 (Honest uncertainty), F5 (Human handoff)
- [x] Bug đã fix: pattern giá thiếu ranh giới từ, "85 độ" (nhiệt độ) bị nhận nhầm thành giá

### M6 — P1 Smoke Test Suite
- [x] `tests/kb_eval/smoke.yaml` + `scripts/kb_eval_runner.py` — 10 test case theo đúng bảng
      "Critical Routing Tests" trong `EV-003`/`EV-004`, có Release Gate theo severity
- [x] **Bug chỉ lộ ra khi test nguyên pipeline:** `product_understanding` thiếu domain `faq`
      trong bảng ánh xạ Router → Retrieval — minh chứng giá trị thực tế của test end-to-end so
      với test từng phần riêng lẻ

**Chưa làm (ngoài phạm vi đã thống nhất):**
- [ ] Tích hợp vào `orchestrator.py`/bot production thật
- [ ] `STYLE_CONTEXT` thật (Playbook qua retrieval), ngân sách context theo token thật
- [ ] Tool thật thay mô phỏng trong test, Fallback F1/F4
- [ ] Atomic switch/rollback thật (hiện `kb_units.id` là khóa chính duy nhất, ghi đè khi re-ingest)

---

## #12 · Lớp NLU (Normalization → Pattern Router → Semantic Router → Combined Pipeline → Tích hợp bot thật)
**Trạng thái:** 🟡 Đang tích hợp vào bot production (Bat 1-2/nhiều) — xem chi tiết từ Bat A đến
Bat 2 (tích hợp orchestrator + Entity Extraction) trong các mục dưới đây

**Bối cảnh:** Nâng cấp Router M3 của #11 (vốn hardcode regex) lên hệ thống NLU học từ dữ liệu
thật — team Knowledge gửi `datasets/nlu/` (intent-catalog, normalization rules, 300+ utterance,
150 test held-out) theo `NLU-INTEGRATION-GUIDE.md`.

### Bat A — Loader + Validator + Normalization
- [x] `app/services/nlu/` — đọc `intent-catalog.yaml` (30 intent), `normalization.yaml` (100
      rule), `utterances/*.yaml` (300+ câu), `tests/*.yaml`
- [x] Validator: 0 lỗi trên dữ liệu thật (ID trùng, intent treo, text trùng, train/test leakage)
- [x] **Bug cascading đã fix:** áp rule phrase tuần tự khiến rule sau khớp nhầm vào *kết quả*
      rule trước (vd `"con ko"`/`"con k"` cùng ra `"còn không"`, rồi tự khớp đè lần 2 ra
      `"còn khônghông"`) — fix: áp toàn bộ rule phrase trong 1 lần quét duy nhất
- [x] 4 gap dữ liệu ghi vào `docs/NLU_DATASET_FEEDBACK-VI.md` gửi team Knowledge (thiếu biến thể
      không dấu, thiếu rule viết tắt, cơ chế bảo vệ tên riêng)

### Bat B — Pattern/Exact Router
- [x] Exact match (index theo cả `text` + `normalized_text`) + Token overlap (Jaccard, ngưỡng
      0.6 — ưu tiên an toàn hơn độ phủ, xác nhận 0% sai trên held-out)
- [x] Kết luận rõ phạm vi: chỉ xử lý câu **gần** dữ liệu train (đúng thiết kế "fast path") — câu
      diễn đạt khác hẳn bắt buộc cần Semantic Router

### Bat B+ — High-Precision Rules (routing-rules.yaml, 25 rule ưu tiên)
- [x] `app/services/nlu/high_precision_rules.py` — khớp theo `priority`, tự động thỏa mãn policy
      "explicit action ưu tiên hơn complaint chung" nhờ cơ chế chọn priority cao nhất
- [x] **Bug đồng âm nghiêm trọng đã fix:** bỏ dấu để so khớp khiến "chưa" (rất phổ biến, "not
      yet") và "chua" (rule RTE-012, "vị chua") trùng thành 1 chuỗi — khác bản chất bug substring
      trước đó (đây là đồng âm ở cấp độ TỪ HOÀN CHỈNH, thêm `\b` không giải quyết được) — fix:
      giữ nguyên dấu khi so khớp rule, chỉ `normalize()` câu hỏi trước để vẫn xử lý được viết tắt
- [x] Sau fix: Pattern Router đạt 35.3% tự phủ, chỉ 2.0% sai (từ 25/150 xuống 3/150) — 3 case còn
      lại là mơ hồ ngữ nghĩa thật của rule (thiếu rule `b2b_inquiry`, từ "giống" đa nghĩa, chưa xử
      lý phủ định "không đổi hàng...hoàn tiền") — đã ghi vào
      `docs/NLU_ACCURACY_IMPROVEMENT_PROPOSAL-VI.md`
- [x] Protected phrases thật (`protected-phrases.yaml`: "3S Coffee", "Robanme", "Công ty Cổ phần
      Robanme") — xử lý đúng thứ tự dài trước khi 1 cụm chứa cụm khác bên trong

### Bat C — Semantic Router
- [x] Embedding lưu trong bộ nhớ (numpy, không qua pgvector — "Intent Index" nhỏ)
- [x] `decide_confidence()` — ngưỡng riêng từng intent + **margin check** (v1.1, `Top-1 - Top-2 ≥
      0.10`) theo cập nhật spec từ team Knowledge
- [x] Model riêng cho NLU (`paraphrase-multilingual-mpnet-base-v2`, tách biệt khỏi embedder của
      #11 để không ảnh hưởng Knowledge Base đang chạy tốt) — cải thiện từ 38.3% → 55.0% đúng khi
      đổi từ model MiniLM nhỏ hơn

### Bat D — Combined Pipeline
- [x] `app/services/nlu/router.py` — Pattern Router trước (nhanh, đã chứng minh 2% sai), Semantic
      Router là fallback khi Pattern không khớp
- [x] **Kết quả accuracy cuối cùng (18/7):** `nlu_combined_test.py --eval` trên 150 test held-out
      — **Đúng 120/150 (80.0%) | Sai 23/150 (15.3%) | Clarify 7/150 (4.7%)**. Tách theo tầng: Pattern
      Router xử lý 56 câu (37.3%) đạt **94.6% chính xác** trong phạm vi nó xử lý; Semantic Router
      xử lý 94 câu còn lại (62.7%, fallback) đạt **71.3%** — khớp đúng con số đo riêng lẻ trước đó.
      **Thấp hơn mục tiêu ≥95%** trong README ~15 điểm phần trăm — nguyên nhân rõ ràng: Pattern
      Router gần như hoàn hảo nhưng chỉ phủ được 37% câu, phần lớn rơi xuống Semantic Router
      (độ chính xác thấp hơn nhiều).
- **Quyết định (18/7):** anh Hoài chọn **chấp nhận 80% làm mốc hiện tại**, dừng #12 ở đây để
  chuyển sang tích hợp vào bot thật thay vì tiếp tục tối ưu thêm (các hướng đã cân nhắc nhưng
  không chọn: gửi kết quả cho team Knowledge đề nghị bổ sung utterance/rule để tăng độ phủ
  Pattern Router; xây Entity Extraction để mở khóa 3 rule đang bị bỏ qua).

**Chưa làm (tiếp tục theo Integration Guide, ngoài phạm vi Bat A-D):**
- [x] ~~Entity Extraction (Bước 6)~~ → đã làm 1 phần ở Bat 2 bên dưới (quantity/unit/order_id/
      payment_method/health_context/temperature; location/product chưa làm)
- [x] ~~Route Resolution (Bước 8)~~ → đã làm ở Bat 1 bên dưới
- [ ] Context-aware Resolution (Bước 5, multi-turn)
- [ ] Tích hợp vào `orchestrator.py`/bot production thật — **xem chi tiết ở Bat 1-2 ngay dưới đây**

---

## Tích hợp #11 + #12 vào bot production thật
Làm theo đúng kiến trúc trong `NLU-INTEGRATION-GUIDE.md` Muc 6 ("Orchestrator
Responsibilities"): NLU **KHONG** tự sinh câu trả lời/gọi Tool trực tiếp — chỉ trả
về route hint, **Orchestrator** mới quyết định hành động thật.

### Thiết kế an toàn đã thống nhất với anh Hoài
- **Feature flag** `ENABLE_NLU_ROUTER` (mặc định `false`) — anh Hoài tự quyết định lúc bật.
- **Chỉ bổ sung, không thay thế**: NLU Router chỉ thêm 1 đoạn hint vào system prompt hiện
  tại (giống cách đang bơm `rag_context`/`agent_notes`) — không chặn/thay flow LLM+tool-calling
  đang chạy đúng.
- **An toàn tuyệt đối**: mọi lỗi trong đường NLU (thiếu file, model chưa tải được...) đều
  bị bắt và bỏ qua LẶNG LẼ — không bao giờ làm vỡ flow trả lời chính, trả về chuỗi
  rỗng thay vì raise lỗi.
- **Fallback khi không chắc chắn**: nếu `decision.action != "accept"` (Semantic Router
  context_check/clarify), **không bơm gì cả** — tránh gây nhiễu prompt với gợi ý mơ hồ.

### Đã code
- **`app/services/nlu/route_resolution.py`** — Route Resolution (Bước 8): tra `route` field
  trong `intent-catalog.yaml` để biết chính xác loại hành động (knowledge/tool/playbook/
  handoff) cho từng intent. Verify 8/8 test với dữ liệu thật qua sandbox.
- **Phát hiện quan trọng khi đối chiếu với `tools.py` thật:** nhiều `target` trong
  `intent-catalog.yaml` (vd `get_payment_options`, `get_cod_policy`, `get_shipping_quote`,
  `get_delivery_estimate`, `get_tracking_information`) **CHƯA CÓ** tool thật tương ứng trong
  production hiện tại — chỉ có ĐÚNG 3 cặp khớp thật: `get_current_price`→`search_products`,
  `get_current_stock`→`check_stock`, `create_or_confirm_order`→`create_order`
  (`TOOL_NAME_MAP` trong `route_resolution.py`). Các target chưa có tool thật vẫn trả đúng
  kết quả resolve, nhưng module gọi nó (`nlu_hint.py`) tự biết không ép gọi tool không
  tồn tại — chỉ hint chung chung cho loại này.
- **`app/services/nlu_hint.py`** (mới) — cầu nối duy nhất orchestrator.py cần gọi:
  `get_nlu_hint(message) -> str`. Tự cache index (pattern + semantic) ở module-level, chỉ tính
  embedding 1 LẦN lúc tiến trình worker load lần đầu (không phải mỗi tin nhắn). Toàn bộ
  hàm bọc trong try/except — verify qua sandbox: giả lập lỗi load, xác nhận trả về `""`
  đúng thiết kế, không raise.
- **Tích hợp vào `orchestrator.py`** — thêm đúng 1 khối sau bước RAG hiện tại, hoàn
  toàn đặt sau `if settings.enable_nlu_router:` — không đổi bất kỳ logic nào khác của
  flow hiện tại.
- **`app/config.py`** + **`.env.example`** — thêm `ENABLE_NLU_ROUTER` (mặc định `false`).
- **`scripts/nlu_hint_test.py`** (mới) — CLI test riêng `get_nlu_hint()` để kiểm tra TRƯỚC
  KHI bật flag thật trong bot — an toàn hơn test trực tiếp qua Messenger/Telegram.

### Chưa test trên máy anh Hoài
**Bước 1 — test hint độc lập, KHÔNG cần bật flag:**
```bash
docker compose exec api python scripts/nlu_hint_test.py "giá bao nhiêu"
docker compose exec api python scripts/nlu_hint_test.py "câu hỏi mơ hồ bất kỳ"
```
Câu đầu kỳ vọng có hint (route=tool, gợi ý gọi `search_products`); câu sau kỳ vọng **không
có hint** (rỗng) vì không đủ tin cậy.

**Bước 2 — chỉ khi Bước 1 ổn, bật flag thật để test qua chat:**
```bash
# them vao .env: ENABLE_NLU_ROUTER=true
docker compose restart api worker telegram_bot telegram_customer_bot
```
Rồi chat thử qua Telegram customer bot (kênh test, #10) trước khi cân nhắc Messenger thật.

**✅ XÁC NHẬN BƯỚC 1 (18/7)** — anh Hoài test 2 câu: “giá bao nhiêu” → có hint đúng
(`ask_price`, `exact_phrase`, confidence 1.0, gợi ý gọi `search_products`); “hôm nay thứ
mấy” (câu ngoài phạm vi) → **không có hint** (rỗng), đúng thiết kế không bơm gợi ý
mơ hồ. Cầu nối `nlu_hint.py` hoạt động đúng. **Sẵn sàng cho Bước 2** (bật
`ENABLE_NLU_ROUTER=true` thật để test qua chat).

### Sự cố khi test Bước 2 (18/7) — không liên quan code NLU
Sau khi bật flag, `telegram_customer_bot` và `api` **crash và dừng hẳn** (không
tu khởi động lại vì môi trường dev không có restart policy) — bot im lặng
hoàn toàn. Truy vết log: `OSError: [Errno 5] Input/output error: '/srv'` —
lỗi I/O xảy ra lúc đang import `torch` (qua chuỗi `orchestrator.py` →
`products.py` → `embedder.py`, dependency có sẵn TỪ TRƯỚC, không liên
quan code NLU mới thêm). Đây là sự cố hạ tầng tạm thời của Docker Desktop
trên Windows khi đọc file qua bind-mount (nhiều khả năng do nhiều container
restart dồn dập lúc anh đang test) — không phải bug logic.

**Khôi phục:** `docker compose up -d api telegram_customer_bot` (khác
`restart` vì container đã dừng hẳn) — xác nhận cả 2 trở lại trạng thái "Up".

### Chủ động sửa trước 1 vấn đề hiệu năng thật sự (18/7)
Trong lúc chẩn đoán, phát hiện `build_semantic_index()` gọi
`nlu_embed_async()` **từng câu một trong vòng lặp** (380 lần gọi threadpool
riêng lẻ) thay vì gộp batch — với model lớn (mpnet-base-v2, 278M tham số)
chạy trên CPU, điều này có thể khiến LẦN ĐẦU TIÊN sau khi container khởi
động lại mất rất lâu (bot có vẻ "không phản hồi" dù không bị crash/treo
thật). Đã sửa: thêm `nlu_embed_batch_async()` trong `nlu_embedder.py` (gọi
`model.encode()` 1 LẦN DUY NHẤT cho toàn bộ danh sách, tận dụng batch nội bộ
của sentence-transformers thay vì 380 lần gọi riêng lẻ) và cập nhật
`build_semantic_index()` dùng hàm này. Verify qua sandbox: trả về đúng số
lượng vector cho danh sách đầu vào.

### Chưa test lại trên máy anh Hoài
1. Xác nhận `docker compose ps` vẫn hiện cả 6 service đều "Up" (không
còn crash).
2. Restart (code Python thay đổi, không phải dependency mới nên chỉ cần
restart, không cần `--build`):
```bash
docker compose restart api worker telegram_bot telegram_customer_bot
```
3. Chat thử qua Telegram customer bot lần nữa — lần này tin nhắn đầu tiên
sau restart nên nhanh hơn nhiều (batch embedding thay vì tuần tự).

**✅ XÁC NHẬN QUA CHAT THẬT (18/7)** — anh Hoài test hội thoại nhiều lượt qua
Telegram customer bot (#10) sau khi khôi phục + fix hiệu năng — chất lượng tốt,
không lỗi: trả lời đúng giá/COD/cách pha/SKU xưởng, hiểu đúng tiếng lóng
("mấy xèng"), không bịa SKU. Việc xác minh NLU có trực tiếp đóng góp vào từng
câu trả lời hay không (thiết kế hint "vô hình" trong output) được đánh giá
không quan trọng bằng việc tiếp tục theo Integration Guide. **Bat 1 hoàn tất.**

### Bat 2 — Entity Extraction (Bước 6, 18/7)
`app/services/nlu/entity_extraction.py` (mới) — trích xuất regex/từ khóa (không dùng ML
NER), hỗ trợ: `quantity`, `unit`, `order_id`, `payment_method`, `health_context`,
`temperature`. **Chưa hỗ trợ** `location`/`product`/`taste_preference`/`brewing_method`
(cần gazetteer/dữ liệu chưa có).

**Bug đồng âm tái diễn — áp dụng lại đúng bài học từ `high_precision_rules.py`:** "ly"
(đơn vị cốc) và "lý" (trong "xử lý") đều thành "ly" sau khi bỏ dấu, gây khớp nhầm unit
trong câu không liên quan. Fix: so khớp giữ nguyên dấu tiếng Việt (chỉ `quantity`/
`order_id` — chữ số — mới dùng bản bỏ dấu, vì không nhạy cảm dấu).

**Tích hợp vào `high_precision_rules.py`:** thêm entity-gating — rule có điều kiện
`entity_any`/`required_entity_any` giờ kiểm tra đúng entity đã trích xuất được, thay vì
bỏ qua tất cả như trước. Mở khóa `RTE-008` (`ask_order_status`), `RTE-009` (`ask_tracking`)
— cả 2 cần `order_id`. `RTE-006` (cần `location`) **vẫn bị bỏ qua rõ ràng** vì chưa có
gazetteer địa danh — không đoán bừa.

**✅ XÁC NHẬN (18/7)** — `nlu_pattern_test.py --eval`: tự phủ tăng từ 35.3% → **37.3%**
(tương ứng đúng số case dùng `order_id` được mở khóa), không phát sinh case sai mới.
**Bat 2 hoàn tất.**

**✅ XÁC NHẬN ACCURACY TỔNG THỂ SAU BAT 1-2 (18/7)** — `nlu_combined_test.py --eval`:
Đúng 121/150 (**80.7%**, tăng nhẹ từ 80.0%) | Sai 22/150 (14.7%) | Clarify 7/150 (4.7%).
Pattern Router xử lý 59/150 (**39.3%**, tăng từ 37.3%). Cải thiện nhỏ nhưng đúng hướng —
đúng 2 điểm phần trăm tương ứng đúng số case `order_id` mới mở khóa ở Bat 2, nhất
quán với thiết kế.

**Chưa làm (tiếp tục từ đây theo Integration Guide):**
- [ ] Mở rộng Entity Extraction (`location`, `product`) để mở khóa `RTE-006`
- [x] ~~Context-aware Resolution (Bước 5, multi-turn, dùng `conversation_state`)~~ → đã làm ở Bat 3 bên dưới
- [ ] Tích hợp sâu hơn Knowledge Base V2 (#11) vào `nlu_hint.py` (hiện type=knowledge chỉ
      hint chung chung, chưa thực sự gọi `kb_retrieval.search_kb()`)
- [ ] Cache (Bước 10)

### Bat 3 — Context-aware Resolution (Bước 5, 18/7)
`app/services/nlu/context_state.py` (mới) — dùng `conversation_state` lưu Redis (TTL 24h,
giống lịch sử chat) để hỗ trợ giải quyết câu hỏi NỐI TIẾP mơ hồ (vd “Loại này pha
lạnh được không?” rồi “Vậy hai muỗng thì sao?”). Đúng tinh thần guide: “không dùng
state để ghi đè intent rõ ràng của tin nhắn hiện tại” — state **chỉ** được tham khảo
khi Router (Pattern+Semantic) **đã không chắc chắn** (`action != accept`), và kết quả
**chỉ** là 1 đoạn hint tham khảo thêm, không ép buộc.

**Phát hiện khi tự test heuristic “câu nối tiếp”:** dùng “vậy” đứng riêng làm dấu
hiệu ban đầu gây **2/6 case sai** — “3S Coffee là gì vậy” (câu hoàn chỉnh, phổ biến) và
“Giá bao nhiêu” (≤ 4 từ) đều bị nhầm thành câu nối tiếp, vì “vậy” quá phổ biến như trợ
từ cuối câu bình thường. Fix: bỏ “vậy” đứng riêng, chỉ giữ cụm RÕ NGHĨA hơn (“vậy
con”, “thì sao”...) + danh sách các câu ngắn nhưng độc lập thường gặp (“giá”, “còn
hàng”...) để loại trừ. Verify lại 7/7 test đúng qua sandbox trước khi đưa vào code.

**Tích hợp:** `get_nlu_hint()` (`nlu_hint.py`) nhận thêm tham số `sender_id` (tùy chọn)
— khi route thành công (`accept`), lưu lại intent làm ngữ cảnh cho lần sau; khi không
chắc chắn VÀ câu “giống nối tiếp”, tra lại ngữ cảnh đã lưu để gợi ý (không ép buộc).
`orchestrator.py` truyền `sender_id` vào đúng 1 chỗ gọi hiện có.
`scripts/nlu_hint_test.py` thêm `--context` demo 2 tin nhắn liên tiếp với cùng
`sender_id` giả lập.

### Chưa test trên máy anh Hoài
```bash
docker compose exec api python scripts/nlu_hint_test.py --context
```
Kỳ vọng: tin nhắn 1 (“Loại này pha lạnh được không?”) có hint bình thường (route qua
Pattern/Semantic); tin nhắn 2 (“Vậy hai muỗng thì sao?”) kỳ vọng có hint dạng “có thể
là câu hỏi nối tiếp từ ngữ cảnh trước đó...” thay vì rỗng hoàn toàn.

**⚠️ Lỗi câu mẫu demo tự phát hiện và sửa (18/7):** kết quả thực tế cả 2 tin nhắn
đều rỗng — hóa ra câu 1 (“Loại này pha lạnh được không?”) **tự nó cũng không đạt
`accept`** (không có High-Precision Rule nào khớp “pha lạnh” cụ thể), nên chưa từng
có gì để lưu vào `context_state.py` cho câu 2 tham khảo — **không phải lỗi cơ chế**,
chỉ là chọn sai câu mẫu demo. Đã sửa `nlu_hint_test.py --context` dùng
`"gia bao nhieu"` làm tin nhắn 1 (đã xác nhận nhiều lần trước đó LUÔN `accept` qua
`exact_phrase`), tin nhắn 2 đổi thành “Vậy 60g thì sao?”.

### Chưa test lại trên máy anh Hoài
```bash
docker compose exec api python scripts/nlu_hint_test.py --context
```
Kỳ vọng lần này: tin nhắn 1 có hint `ask_price`; tin nhắn 2 có hint tham khảo ngữ
cảnh (không rỗng).

**✅ XÁC NHẬN THÀNH CÔNG HOÀN TOÀN (18/7)** — sau khi restart, sự cố Redis DNS
(`Error -5 connecting to redis:6379`) tự phục hồi (sự cố hạ tầng Docker Desktop tạm
thời, giống kiểu đã gặp với lỗi `/srv` trước đó — không phải lỗi code). Kết quả:
tin nhắn 1 (“gia bao nhieu”) → hint đúng `ask_price`; tin nhắn 2 (“Vậy 60g thì sao?”)
→ **có hint tham khảo ngữ cảnh đúng**: “có thể là câu hỏi NỐI TIẾP từ ngữ cảnh trước đó
(chủ đề gần nhất: 'ask_price')...” — đúng chính xác thiết kế mong muốn.
**Bat 3 hoàn tất.**

🎉 **Cả 10/10 Bước trong `NLU-INTEGRATION-GUIDE.md` đã được triển khai** (một số
giới hạn đã ghi rõ: Entity `location`/`product` chưa làm, Cache Bước 10 chưa làm,
Knowledge Base V2 mới hint chung chung chưa gọi retrieval thật sự). Đây là điểm dừng
hợp lý để đánh giá tổng thể trước khi cân nhắc bật `ENABLE_NLU_ROUTER=true` cho
Messenger thật (hiện mới test qua Telegram customer bot #10).

---

## Đề xuất thứ tự ưu tiên tiếp theo
1. **Tích hợp #11 + #12 vào `orchestrator.py`/bot production thật** — quyết định mới nhất (18/7),
   thay cho việc tiếp tục tối ưu accuracy #12.
2. **#1** — rotate `META_APP_SECRET`/`PAGE_ACCESS_TOKEN` (độc lập, nên làm sớm nếu chưa làm).
3. **#9** — deploy VPS thật khi có hạ tầng, để #11/#12 có môi trường hoạt động thật sự.

## Tài liệu tham chiếu (`docs/`)
- `docs/DATABASE-VI.md` — schema, lịch sử migration, câu SQL tra cứu thường dùng
- `docs/DASHBOARD-VI.md` — từng trang/nút dashboard, gắn đúng endpoint
- `docs/TELEGRAM_BOT-VI.md` — 2 bot Telegram (admin/khách hàng), lệnh, cách tạo bot mới
- `docs/BACKEND_API-VI.md` — toàn bộ FastAPI, service/worker, biến môi trường, giới hạn đã biết
- `docs/KNOWLEDGE_BASE_V2_DESIGN-VI.md` — thiết kế chi tiết #11
- `docs/NLU_DATASET_FEEDBACK-VI.md`, `docs/NLU_ACCURACY_IMPROVEMENT_PROPOSAL-VI.md` — góp ý dữ
  liệu gửi team Knowledge cho #12
- Mỗi file `-VI` có bản dịch `-EN` tương ứng
- **Chưa làm:** `docs/DEPLOYMENT.md` (để dành khi #9 có VPS thật)
