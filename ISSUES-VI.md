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

### Bat 4 — Kết nối thật Knowledge Base V2 (#11) vào `nlu_hint.py` (18/7)
**Phát hiện nghiêm trọng khi anh Hoài rà soát lại toàn bộ tích hợp:** đọc lại code thật
xác nhận `nlu_hint.py` (từ Bat 1) **CHƯA BAO GIỜ gọi** `kb_retrieval.search_kb()` —
nhánh `type="knowledge"` chỉ trả về **1 câu gợi ý chung chung**, không hề lấy nội dung
Knowledge Unit thật từ M1-M6. Đây chính là lý do hội thoại thật trước đó (“3s coffee
của ai?”) bot trả lời “chưa có thông tin cụ thể” thay vì “Công ty Cổ phần Robanme” (đã
ingest ở `SKL-BRAND-001` từ M1) — bot vẫn đang dùng RAG cũ (#4), **không phải** Knowledge
Base V2.

**Xác minh trước khi sửa:** kiểm tra `kb_config.active_index_version` — xác nhận đã
được kích hoạt (`value = 3`), nên `search_kb()` sẵn sàng hoạt động đúng.

**Đã sửa:** thêm `_build_knowledge_hint()` (async) gọi thật
`kb_retrieval.search_kb(message, top_k=2)`, bơm nội dung Knowledge Unit thật (không phải
câu chung chung) vào hint. **Không lọc theo domain cụ thể** — `targets` trong
`intent-catalog.yaml` là asset-level (vd `SKL-PRD-001`), không khớp trực tiếp với domain-
level filter của `search_kb()` (vd `product`/`brand`) — để đơn giản và an toàn, dùng xếp
hạng ngữ nghĩa+lexical của `search_kb()` tự tìm nội dung phù hợp nhất.
Toàn bộ bọc try/except — giữ đúng nguyên tắc an toàn đã áp dụng xuyên suốt.

### Chưa test trên máy anh Hoài
```bash
docker compose exec api python scripts/nlu_hint_test.py "3s coffee cua ai"
```
Kỳ vọng: hint giờ bao gồm đoạn “Kiến thức liên quan từ Knowledge Base...” kèm nội
dung thật từ `SKL-BRAND-001` (nhắc tới “Robanme”), thay vì chỉ câu chung chung như trước.
Sau đó test lại qua Telegram customer bot đúng câu đã gặp bug trước đó (“3s coffee của
ai?”) để xác nhận bot trả lời đúng “Công ty Cổ phần Robanme”.

**✅ XÁC NHẬN CƠ CHẾ HOẠT ĐỘNG (18/7)** — test `"nguyên liệu là gì"` (`ask_ingredients`,
`high_precision_rule`, conf 0.95) → hint giờ **có nội dung Knowledge Unit thật**
(`[SKL-SAL-002]`, `[SKL-PRD-001]`) thay vì câu chung chung như trước — xác nhận cơ chế
kết nối Knowledge Base V2 hoạt động đúng.

**Lưu ý đã quan sát (không chặn, chỉ là điểm tinh chỉnh sau này):** `SKL-SAL-002`
(“Customer Intent Recognition”) lộ ra trong kết quả — đây là tài liệu hướng dẫn NỘI BỘ
(dạng playbook nhận diện ý định), không phải nội dung trả lời khách hàng thật — bị
lẫn vào vì cũng nhắc “nguyên liệu” như ví dụ minh họa trong tài liệu. Đề xuất sau này:
lọc loại domain `conversation`/`playbook` khỏi `_build_knowledge_hint()` (chỉ giữ
`product`/`brand`/`faq`/`sales` mang tính nội dung thật), để tránh lẫn tài liệu quy trình
nội bộ vào context trả lời khách.

Câu “3s coffee của ai?”/“3S Coffee là gì” riêng cần Semantic Router (Bat C) mới
phân loại được (Pattern Router đơn thuần báo “Khong match duoc”) — chưa test end-to-end
đúng câu này qua `nlu_hint_test.py` (cần Semantic Router thật sự accept, không phải
chỉ Pattern), nhưng cơ chế kết nối đã xác nhận đúng. **Bat 4 hoàn tất về mặt cơ chế.**

### Bat 5 — Loc tai lieu noi bo khoi context tra khach (18/7)
Điều tra qua SQL xác nhận: `SKL-SAL-002` (domain=`sales`) là **toàn bộ 1 tài liệu
playbook nội bộ** (26 mục: “Purpose”, “Priority rules”, “Do”/“Don't”, “Escalation”,
“Traceability”...), không phải nội dung trả lời khách hàng — vẫn cả 5 asset trong domain
`sales` (SKL-SAL-001..005) đều cùng dạng playbook. Domain `sales` có **113 unit** (nhiều
nhất trong 7 domain), nên nếu không lọc, rủi ro lấy nhầm tài liệu quy trình nội bộ vào
context trả khách rất cao.

**Đã sửa:** `_build_knowledge_hint()` giờ gọi `search_kb(message, top_k=2,
allowed_domains=["brand", "product", "faq"])` — chỉ 3 domain đã xác nhận NHIỀU LẦN trong
phiên này là nội dung thật sự cho khách (FAQ-BREW-001, FAQ-BRAND-001, thông tin freeze-
dried...). Loại trừ `sales`/`conversation`/`customer_service`/`playbook`.

### Chưa test trên máy anh Hoài
```bash
docker compose exec api python scripts/nlu_hint_test.py "nguyen lieu la gi"
```
Kỳ vọng: hint **không còn** `[SKL-SAL-002]` nữa, chỉ còn nội dung từ `product`/`brand`/`faq`
(vd `SKL-PRD-001`/`SKL-PRD-002`/`SKL-FAQ-001`).

### Bat 6 — Mở rộng Entity Extraction: `location`/`product` (18/7)
`app/services/nlu/entity_extraction.py` — thêm `_extract_location()` (gazetteer 34
địa danh Việt Nam phổ biến, dùng tên gọi ổn định không phụ thuộc thay đổi địa giới
hành chính) và `_extract_product()` (MVP — chỉ nhận diện biến thể kích thước như
“100g”/“25kg”, chưa phải tên SKU đầy đủ). Cập nhật `high_precision_rules.py`: bỏ
`location`/`product` khỏi `_ENTITY_UNSUPPORTED` — **mở khóa nốt `RTE-006`** (`ask_shipping_
availability`, cần `location`) — cả 3 rule có điều kiện entity trong `routing-rules.yaml`
giờ đều đã mo khóa (RTE-006/008/009). Chỉ còn `taste_preference`/`brewing_method` chưa
hỗ trợ (mơ hồ hơn, cần nhiều từ khóa hơn để chính xác).

Đã verify 7/7 test entity + 2/2 test mở khóa `RTE-006` qua sandbox trước khi đưa vào code.

#### Bản vá "Ca Mau không dấu" — phát hiện dán lỗi, đã sửa (23/7, máy mới D:\alpha3s)
Bản vá `_extract_location` (khớp địa danh khi khách gõ không dấu — bỏ dấu CẢ 2 phía,
trả về dạng canonical có dấu) trước đây dán tay do MCP mất kết nối. Kiểm tra lại trên
máy mới phát hiện **dán lỗi: dòng `def` cũ không bị xóa → 2 `def` lồng nhau →
SyntaxError, cả module không import được** (bot chạy mà không có entity extraction,
lỗi bị nuốt im lặng bởi try/except của đường NLU). Đã xóa dòng `def` thừa — thân hàm
bản vá còn lại đúng nguyên bản.

- Đã verify: logic bản vá mô phỏng y hệt bằng Node (máy mới chưa có Python/Docker) —
  14/14 PASS, gồm các cặp có dấu/không dấu thật ("ship ve Ca Mau giup em",
  "giao hang di da nang", "minh o buon ma thuot"...) + case ranh giới từ ("camau"
  dính liền không được khớp).
- Thêm `scripts/nlu_entity_test.py` (CLI test theo chuẩn các script nlu_*_test.py
  sẵn có) để chạy xác nhận bằng Python thật khi Docker lên.

### ✅ Đã test trên máy anh Hoài (23/7, sau khi Docker lên)
- `nlu_entity_test.py --eval` — **14/14 PASS** bằng Python thật: module import được,
  location khớp cả có dấu/không dấu, các entity khác không vỡ.
- `nlu_pattern_test.py "shop có giao tới Cà Mau không"` (CÓ dấu) —
  `intent=ask_shipping_availability, conf=0.95, via=high_precision_rule` → **RTE-006
  mở khóa thật sự**.
- ⚠️ **Giới hạn phát hiện thêm:** câu HOÀN TOÀN không dấu ("shop co giao toi Ca Mau
  khong") KHÔNG kích được RTE-006 — `normalize()` trả nguyên xi (normalization.yaml
  chưa có mapping khôi phục "co giao toi" → "có giao tới"), nên `any_phrases` có dấu
  không khớp → câu rơi xuống Semantic Router. Entity location VẪN bắt được "Ca Mau"
  (so khớp bỏ dấu 2 phía), chỉ phần phrase của rule là không khớp. Kỳ vọng ghi hôm
  18/7 (test bằng câu không dấu) là lạc quan quá mức. **Đề xuất gửi team Knowledge:**
  bổ sung mapping CẤP CỤM TỪ vào normalization.yaml (vd "co giao toi" → "có giao
  tới", "ship ve" → "ship về") — cụm ≥2 từ nên không dính đồng âm như từ đơn
  ("toi" = tôi/tới/tối).

### Bat 7 — Cache (Bước 10, 18/7)
`app/services/nlu/cache.py` (mới) — chỉ cache đúng theo danh sách được phép trong
guide (“Normalized query → intent candidate”), TTL 1h. **Chỉ cache kết quả
`action="accept"`** (đã chắc chắn) — không cache `context_check`/`clarify` (phụ thuộc
ngữ cảnh Bat 3, cache có thể gây sai lệch giữa các khách khác nhau). **Không cache**
nội dung Knowledge Base (`search_kb()` vẫn luôn gọi mới mỗi lần) — đúng tinh thần
“không cache dữ liệu động” của guide.

Tích hợp vào `get_nlu_hint()`: tra cache trước khi gọi `route()`, chỉ ghi cache khi
kết quả là `accept`.

### ✅ Đã test trên máy anh Hoài (23/7)
`nlu_hint_test.py "gia bao nhieu"` chạy 2 lần liên tiếp — kết quả **giống hệt nhau**
(`ask_price`, conf 1.0, exact_phrase, hint gọi `search_products`) — cache đúng hành vi
"tối ưu nội bộ, không đổi kết quả hiển thị".

Ghi chú hạ tầng: lần chạy ĐẦU TIÊN (khi 2 model chưa có trong cache HF của container)
bị **SIGILL (exit 132)** — nghi CPU cũ (i7-3720QM không AVX2) nhưng đã loại trừ qua
cô lập từng tầng (torch matmul OK, capability=DEFAULT đúng, MiniLM/mpnet encode đơn lẻ
OK, mpnet batch 380 câu OK) rồi chạy lại chính test đó thì PASS — kết luận: **sự cố
nhất thời của Docker Desktop/WSL2 lúc mới boot + đang tải model**, đúng lớp lỗi hạ tầng
đã ghi trong CLAUDE.md, không phải lỗi code.

### Bat 8 — Kiểm tra không hồi quy (18/7)
Sau toàn bộ Bat 4-7 (gọi KB V2 thật, lọc domain, entity mới, cache), cần chạy lại
`nlu_combined_test.py --eval` để xác nhận không làm giảm accuracy 150 test held-out
(về lý thuyết không nên ảnh hưởng vì bộ test đo intent classification, không đo nội
dung trả lời/cache, nhưng entity `location`/`product` mới CO THE thay đổi kết quả
vi mo khoa them RTE-006).

### ✅ Đã test trên máy anh Hoài (23/7)
`nlu_combined_test.py --eval` — **Đúng 121/150 (80.7%) | Sai 22 (14.7%) | Clarify 7
(4.7%)**. Pattern Router phủ 60/150 (40.0%, tăng từ 39.3%). **Không hồi quy** — giữ
đúng mốc 80.7% sau toàn bộ Bat 4-7 + bản vá Ca Mau.

---

## Chặng A — AGW-ROADMAP-001 (23/7, máy mới D:\alpha3s)
Roadmap `AGW-ROADMAP-001-diem-bat-dau.md` đã được thả vào gốc repo (22/7). Trạng thái
Chặng A theo §9 roadmap:

- [x] **A2 (một phần)** — vá `_extract_location`: phát hiện bản vá cũ dán lỗi gây
      SyntaxError, đã sửa + sandbox 14/14 PASS (chi tiết ở mục "Bản vá Ca Mau không
      dấu" phía trên, Bat 6).
- [x] **A3 (chuẩn bị)** — tạo `scripts/measure_embedding_rss.py`: đo VmRSS/VmHWM của
      2 model embedding (MiniLM-L12-v2 + mpnet-base-v2) trong 4 kịch bản, mỗi kịch
      bản 1 process con riêng, đo cả sau khi `encode()` thật. Chạy trong container
      (đọc `/proc`), in bảng + kết luận sơ bộ so với budget VPS 4GB.
- [x] **A3 (ĐÃ ĐO — 23/7, máy dev, chạy một mình không tải khác):**

      | Kịch bản | Peak VmHWM |
      |---|---|
      | Baseline interpreter | 12 MB |
      | Chỉ KB (MiniLM-L12-v2) | 1.126 MB |
      | Chỉ NLU (mpnet-base-v2) | 1.132 MB |
      | **Cả 2 model, 1 process** | **1.532 MB** |

      Phần lớn là runtime torch/sentence-transformers dùng chung (load model thứ 2
      trong cùng process chỉ +400 MB thay vì +1.100 MB). **Phân tích so với VPS 4GB:**
      hiện `worker` (arq → orchestrator → nlu_hint + tools) là process load CẢ 2 model
      (~1,6 GB); nhưng `api` CŨNG có thể load MiniLM khi dashboard sửa KB/products
      (`knowledge_entries.py`, `products.py` import `embed_async`) → thêm ~1,1 GB.
      - Nếu ÉP embedding chỉ sống trong 1 process (worker): worker ~1,6-1,8 GB + api
        ~0,3 GB + PG ~0,35 GB + Redis ~0,05 GB + dashboard ~0,2 GB + OS/Docker ~0,4 GB
        ≈ **2,9-3,1 GB → VỪA 4 GB** (có swap 2-4 GB đỡ lưng). ✅ Freeze KB V2 ĐƯỢC.
      - Nếu để cả api lẫn worker cùng load model: ~4 GB chỉ riêng app → **KHÔNG an
        toàn**. ⚠️ Vi phạm guardrail "embedding chỉ load 1 process" (roadmap §5).
      - ~~Khuyến nghị (cần PO chốt ở Chặng B/HOST-003)~~ → **PO ĐÃ QUYẾT (23/7,
        sau bản phân tích độc lập `docs/KB_NLU_RESOURCE_ASSESSMENT-VI.md`):** làm CẢ
        HAI phương án — (1) nâng ngân sách VPS lên **6-8 GB RAM**, (2) **chop
        Semantic Router** (tầng mpnet), và (3) **KHÔNG freeze KB V2**.

### Chop Semantic Router (PA2-5a) — đã triển khai (23/7)
- `app/config.py` — thêm flag `enable_semantic_router` (mặc định **False**);
  `.env` đặt tường minh `ENABLE_SEMANTIC_ROUTER=false`.
- `app/services/nlu_hint.py::_ensure_loaded()` — chỉ `build_semantic_index()` khi
  flag bật; khi tắt: **mpnet không bao giờ được load** (~-1,1 GB RAM worker).
- `app/services/nlu/router.py` — bỏ import `semantic_router` cấp module (import đó
  kéo torch ~300MB vào mọi process import router, kể cả khi flag tắt) → lazy import
  trong nhánh semantic; `route()` nhận `semantic_index=None` → trả `action="clarify",
  matched_by="none"` (không đoán, không hint; nhánh Context-aware Resolution phía
  sau vẫn hoạt động).
- **Đã verify (máy anh Hoài, 23/7):**
  - `nlu_hint_test "gia bao nhieu"` → hint như cũ (`ask_price`, exact_phrase),
    chạy tức thì, log xác nhận "Semantic Router TAT", không load model nào.
  - `nlu_hint_test "minh can duoc goi y lua chon"` (câu trước đây rơi xuống
    semantic và bị đoán SAI `end_conversation`) → nay trả rỗng đúng thiết kế —
    không hint còn tốt hơn hint sai.
  - `nlu_pattern_test --eval` (pipeline mới, 150 held-out): **match 60 (40%),
    đúng 56 (93,3% trong phạm vi phủ), sai 4**.
- **Phát hiện quan trọng biện minh cho quyết định:** soi lại eval cũ — các câu do
  Semantic Router xử lý hầu hết trả `action=context_check` (KHÔNG phải `accept`)
  → vốn dĩ **không sinh hint** bơm vào prompt trong production. Tức là chop semantic
  gần như không thay đổi hành vi bot thật; chỉ thuần tiết kiệm ~1,1 GB RAM.
- Đường lui: bật lại `ENABLE_SEMANTIC_ROUTER=true` (vd sau khi quantize mpnet
  PA2-5d) — code semantic_router giữ nguyên, không xóa.

### Test hệ thống hoàn chỉnh trên máy dev 16GB (23/7 tối — LLM DeepSeek thật)
Chạy `scripts/test_scenarios.py` (8 kịch bản, orchestrator + NLU pattern-only +
KB V2 + RAG cũ + tools + DB/Redis thật). Trước đó khôi phục RAG cũ trên DB mới:
`scripts/ingest.py` → 51 chunks. Kết quả chấm theo tiêu chí từng kịch bản:

| # | Kịch bản | Kết quả |
|---|---|---|
| 01 | Hỏi giá (bậc 170/160/140) | ✅ PASS — đúng cả 3 bậc, quy đổi ~3.400đ/ly |
| 02 | Danh xưng "c" → chị/em xuyên suốt | ✅ PASS |
| 03 | Chê đắt → quy đổi ly, không phản bác | ✅ PASS — lượt 2 khách rút, bot lịch sự không nài |
| 04 | Câu y khoa (đau dạ dày) | ✅ PASS có ghi chú — khuyên bác sĩ đúng, nhưng (a) vẫn đưa số 400mg/3-4 ly dù có disclaimer, (b) xưng "bạn/mình" lệch brand voice "anh chị/em" |
| 05 | Khiếu nại giao trễ | ⚠️ PASS một phần — escalate + xin lỗi đúng tone, nhưng **không hỏi mã đơn** (tiêu chí yêu cầu) |
| 21 | Chốt đơn đủ thông tin → phải gọi `create_order` | ⚠️ CHƯA ĐẠT trong 2 lượt — bot xin xác nhận thêm 1 lượt rồi mới tạo (thận trọng tốt nhưng kịch bản hết lượt; `orders`=0 xác nhận qua DB). Cần thêm lượt "đúng rồi" vào kịch bản HOẶC chấp nhận hành vi xác nhận là đúng |
| 22 | Thiếu tên → KHÔNG được tạo đơn | ✅ PASS — hỏi thêm tên, `orders`=0 |
| 23 | Handoff → bot im lặng | ✅ PASS — escalate ngay lượt 1, im lặng lượt 2, `escalations`=2 |

**RAM thực đo sau chop** (process chạy `handle_message` thật, đọc /proc):
trước xử lý 435 MB → sau câu knowledge (load MiniLM + KB search + LLM) peak
**1.168 MB** → sau câu giá 1.170 MB. So với ~1,9 GB trước chop → **tiết kiệm
~740 MB**. Trên máy dev 16GB chạy thoải mái; số này là ước lượng tốt cho worker
trên VPS 6-8GB.

**Phát hiện giới hạn sau chop (đúng dự đoán PA2-5a):** câu knowledge NGOÀI phủ
pattern (vd "3s coffee là thương hiệu của công ty nào" — cả có dấu lẫn không dấu)
không còn được bơm nội dung KB V2 vào prompt → bot dựa vào RAG cũ, có lần chọn
escalate thay vì trả lời.

### Fallback knowledge hint bằng search_kb() — PO duyệt qua Telegram, đã làm (23/7)
Khi Pattern miss (và không phải câu nối tiếp), gọi `search_kb()` bằng MiniLM —
model VỐN ĐÃ load cho KB V2 → **0 RAM thêm**, ~65ms/câu. Dùng retrieval thay
classification: không đoán intent, chỉ hỏi "có nội dung KB gần câu này không".

- `kb_retrieval.py` — thêm trường `vector_distance` (cosine distance thật) vào kết
  quả `search_kb()` (cộng thêm, không đổi hành vi cũ; RRF vứt distance khi xếp hạng
  nên caller cần nó để lọc liên quan thật).
- `nlu_hint.py` — thêm `_build_knowledge_fallback_hint()`: `top_k=4`, lọc
  `vector_distance <= 0.55`, không tìm thấy thì trả `""` (im lặng, KHÔNG trả hint
  chung chung vì chưa chắc là câu hỏi kiến thức). Preamble dặn LLM rõ: "chưa chắc
  chắn — lạc đề thì bỏ qua hoàn toàn".
- **Ngưỡng 0.55 chọn từ SỐ ĐO THẬT** (probe trên index v1): câu liên quan
  d=0.354-0.531, câu không liên quan d=0.530-0.727. Ca biên chấp nhận: "cho anh 5
  hũ" (d=0.530) có thể lọt hint FAQ nhẹ. `top_k=4` vì đáp án chuẩn câu không dấu
  (KU-FAQ-001-003, d=0.5156) xếp hạng 4.
- **Verify end-to-end:** câu không dấu "3s coffee la thuong hieu cua cong ty nao"
  (ca fail trước đó → escalate) giờ trả lời đúng nguyên văn FAQ-BRAND-001: *"đóng
  gói bởi Công ty Cổ phần Robanme..."*. Câu địa chỉ "giao ve 45 Le Loi" → hint rỗng
  đúng thiết kế.
- **Chạy lại full 8 kịch bản (LLM thật):** không hồi quy — S01-03/22/23 PASS như
  cũ, S04/05/21 giữ nguyên các điểm prompt-level có sẵn từ trước (không liên quan
  fallback).

### Orchestrator chuyển nguồn kiến thức: RAG cũ → KB V2 (23/7 tối, sau khi PO test Telegram thật)
PO test qua bot Telegram khách phát hiện bot trả lời sai kiến thức ("muỗng 2g",
cách pha không theo quy trình KB V2). Nguyên nhân: **xung đột 2 nguồn** — RAG cũ
(`data/knowledge`, "định lượng chuẩn 2g/ly") được bơm cho MỌI câu, KB V2 ("1 muỗng
≈ 1g", không công thức cứng) chỉ vào khi hint kích hoạt → LLM nghe nguồn sai.
Thêm nữa `products.description` (seed migration) cũng ghi "2g/ly ~50 ly".

**Đã sửa:**
- `orchestrator.py` — mục "Thông tin tham khảo" đổi nguồn từ `search_knowledge`
  (RAG cũ #4) sang `search_kb` (KB V2, top_k=4, domain brand/product/faq); RAG cũ
  GIỮ NGUYÊN làm đường lui trong nhánh except khi KB V2 lỗi.
- `migrations/001_init.sql` + DB live — mô tả `3S-100G` đồng bộ KB V2 (muỗng ~1g,
  bỏ "2g/ly ~50 ly").
- Verify trực tiếp: "1 muong la bao nhieu gam" → "khoảng 1g"; "cach pha sao cho
  chuan" → đúng quy trình KB V2 (nóng 80-90°C khuấy ~30s, nguội 16-18°C khuấy
  ~3 phút, chỉnh muỗng theo khẩu vị).

### Kết quả 8 kịch bản LẦN 3 (prompt mới + KB V2 context + fallback, 23/7 tối)
Chạy sau khi session bridge sửa `system_prompt.md` đồng bộ KB V2 (mục dưới):
**7/8 PASS trọn** — cải thiện rõ so với 2 lần trước:
- ✅ S04 y khoa: **hết hẳn "400mg/3-4 ly"** — từ chối đưa số ly/ngày chung, khuyên
  bác sĩ đúng chuẩn KB (giải quyết xong ý 2; còn xưng "bạn/mình" — minor).
- ✅ S21: **bot gọi `create_order` THẬT ngay khi đủ thông tin** — đơn #1 nằm trong
  DB (Nguyễn Thị Lan, 800.000đ), hết cả vấn đề "xin thêm 1 lượt xác nhận".
- ✅ S22: vẫn không tạo đơn khi thiếu tên (DB xác nhận chỉ có đúng 1 đơn của S21).
- ✅ S02: cách pha nguội 16-18°C/3 phút đúng KB V2; không bịa flavor notes.
- ✅ S03: không còn quy đổi "3.400đ/ly" — ĐÚNG quyết định PO mới (logic quy đổi
  thuộc về tool). **Tiêu chí kịch bản S03 trong `scenarios_20.md` cần cập nhật**
  (đang ghi "quy đổi ra đơn giá/ly" theo prompt cũ).
- ⚠️ S05 khiếu nại: duy nhất còn lại — bot escalate + xin lỗi đúng nhưng vẫn
  **không hỏi mã đơn** trước khi escalate (prompt đã ghi bước 3 nhưng LLM bỏ qua
  khi khách chưa đưa mã — cần thử ép thứ tự bước trong prompt hoặc chấp nhận).
- [x] **Môi trường máy mới HOÀN TẤT (23/7):** WSL2 + Docker Desktop cài xong (VT-x
      sẵn trong BIOS, chỉ thiếu WSL2 — `wsl --install --no-distribution` + reboot),
      7/7 container Up. **DB volume mới tinh không mang dữ liệu máy cũ theo** — đã
      ingest lại KB V2: `kb_ingest.py` 24/24 asset → 364 Knowledge Unit (0 thiếu
      embedding), kích hoạt `active_index_version=1`, verify `kb_search_test.py
      "3s coffee cua ai"` trả đúng SKL-BRAND-001/FAQ-BRAND-001 (có "Công ty Cổ phần
      Robanme"). Lưu ý: `conversations`/`orders`/`messages` cũng trống — lịch sử
      chat/đơn máy cũ KHÔNG còn (chấp nhận vì là dữ liệu dev test).
- [x] **Việc 1 §9 (CA amendments)** — anh Hoài đã thả 4 file AGW vào gốc repo (23/7):
      `ALPHA3S_GATEWAY_ARCHITECTURE_SPEC_V2.md` (= AGW-ARCH-001 v2.0.0),
      `ALPHA3S_GATEWAY_DEV_HANDOFF_V2.md` (= AGW-IMPL-001 v2.0.0), 2 file AGW-REVIEW-002.
      Kiểm tra nội dung: **cả 3 amendment đã được gấp sẵn trong bản v2** — REV2-11 trong
      HOST-004 (key ngoài production host + total-loss restore drill), REV2-12 trong
      CH-006 (reserve chi phí idempotent theo `idempotency_key`), câu nguồn REV2-06 đã
      sửa ("8 tin" = unconfirmed tới CH-004, REV2-06 Closed trong traceability).
      **PO (anh Hoài) đã xác nhận lock v2.0.0 ngày 23/7** — roadmap §4 đã cập nhật
      tương ứng. Chặng A + B song song chính thức bắt đầu.

### Rà soát đồng bộ system prompt ↔ KB V2 — PO yêu cầu qua Telegram, đã làm (23/7, session bridge)
PO phát hiện đúng: system prompt (viết từ #5, trước khi có KB V2) chứa nhiều claim
mà KB V2 (nguồn chuẩn PO đã duyệt) viết ra ĐỂ CẤM. Rà bằng agent đọc toàn bộ 25
file `knowledge-base/` đối chiếu `app/prompts/system_prompt.md`.

**Xung đột đã sửa trong `system_prompt.md` (KB là chuẩn):**
- [x] "100% Robusta" (bị SKL-PRD-002 cấm đích danh) → nhân xanh Robusta + Arabica
      VN, không công bố tỷ lệ; "phôi Ro-Express R100 (Robanme)" (không tồn tại
      trong KB) → Robanme = đơn vị ĐÓNG GÓI, không nêu tên nhà cung cấp phôi,
      đòi hồ sơ nguồn gốc → escalate.
- [x] Pha nguội "khuấy 30 giây" → **16–18°C khuấy ~3 phút** (KB lặp 6 lần); pha
      nóng 85°C/10-15s → **80–90°C khuấy ~30s**; bỏ mốc 99°C (nhiệt độ kỹ thuật
      cũ PO đã loại); định lượng "2g/ly, 50 ly/hũ" (không có trong KB) → chuẩn
      "1 muỗng ≈ 1g", không ấn định số muỗng chung.
- [x] Caffeine ">1%" → **4,1%** (≈41mg/muỗng) + Total Glucose 1,06% / Moisture
      3,43%; bỏ "400mg ≈ 3-4 ly/ngày" (KB cấm quy đổi chung — đồng thời giải
      quyết ý 2 của mục S04 y khoa ở trên); bỏ "Robusta gấp đôi Arabica".
- [x] Hương "Caramel–Chocolate, không đắng gắt" (SKL-FAQ-002 cấm bịa flavor
      notes/mức đắng tuyệt đối) → chỉ nói cảm nhận chung nóng-thơm/nguội-êm.
- [x] Bỏ claim "nhuận tràng trước khi tập" (vi phạm cấm tuyên bố y khoa
      PBK-BRAND-VOICE); target "runners/sức bền" → định vị đối tượng, không hứa
      công dụng thể thao.
- [x] Bổ sung từ KB: quy trình khách báo TRIỆU CHỨNG (dừng bán → khuyên ngừng →
      escalate); cấm suy diễn "không đường"/calorie/tiểu đường; cấm tư vấn tương
      tác thuốc; cấm gọi pha nguội là "cold brew"; không tự đưa "pha xong để được
      bao lâu"; mở rộng danh sách từ cấm (tốt nhất/ngon nhất/duy nhất/độc quyền);
      cấm emoji trong khiếu nại/hoàn tiền/sức khỏe; câu chuẩn thiếu thông tin đổi
      sang ngôi "em" theo PBK-RESPONSE-STANDARD (bỏ "Chúng tôi").
- [x] **Quyết định PO qua Telegram (23/7):** bỏ phép quy đổi "170k/50 ly =
      3.400đ/ly" khỏi prompt — logic này thuộc về tool. Đã sửa mục "Đắt quá"
      thành: lấy giá thật từ `search_products`, không dùng số thuộc lòng. Việc
      thêm dữ liệu quy đổi vào tool: đã tạo task riêng (chip trên máy PO).

**Chưa test:** cần chạy lại 8 kịch bản (đặc biệt S02 giá/chê đắt, S04 y khoa) với
prompt mới — phối hợp session đang làm search_kb() chạy chung trước khi commit+push.
**ISSUES-EN.md:** chưa dịch mục này — để session đồng bộ EN xử lý (đang có worktree riêng).

## Đề xuất thứ tự ưu tiên tiếp theo
> **Từ 22/7: thứ tự ưu tiên theo AGW-ROADMAP-001 §9** (Chặng A → B song song). Danh
> sách dưới đây là thứ tự cũ trước khi có roadmap, giữ lại để tham chiếu.
1. **Tích hợp #11 + #12 vào `orchestrator.py`/bot production thật** — quyết định mới nhất (18/7),
   thay cho việc tiếp tục tối ưu accuracy #12.
2. **#1** — rotate `META_APP_SECRET`/`PAGE_ACCESS_TOKEN` (độc lập, nên làm sớm nếu chưa làm).
3. **#9** — deploy VPS thật khi có hạ tầng, để #11/#12 có môi trường hoạt động thật sự (nay = Chặng B).

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
