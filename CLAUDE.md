# Alpha3S — Context cho Claude Code

> File này được Claude (tab Chat) tạo ra để Claude Code hiểu đúng bối cảnh dự án khi
> làm việc trong `D:\alpha3s`. Đọc kỹ trước khi bắt đầu bất kỳ việc gì.

## 1. Dự án là gì

**Alpha3S (3S Coffee)** — chatbot bán hàng tự động cho thương hiệu cà phê sấy lạnh, chạy
Messenger (kênh chính) + Telegram (dự phòng/admin), tích hợp RAG + tool-calling + dashboard
quản trị. Đang chuyển hướng sang kiến trúc **"Customer Terminal"** (xem mục 5).

**Stack:** FastAPI + PostgreSQL/pgvector + Redis/arq worker + Next.js dashboard + DeepSeek LLM
(OpenAI-compatible) + sentence-transformers (embedding chạy local, không cần API key).

**Chạy bằng Docker Compose** — mọi thứ (API, worker, DB, Redis, dashboard, 2 bot Telegram) đều
là container riêng trong `docker-compose.yml`.

## 2. NGUỒN THÔNG TIN CHÍNH — đọc trước khi làm bất kỳ việc gì

1. **`ISSUES-VI.md`** (gốc repo) — backlog đầy đủ #1-#12, trạng thái, checklist, bug đã fix, giới
   hạn đã biết. **Đây là nguồn sự thật duy nhất về trạng thái kỹ thuật** — luôn đọc mục liên quan
   trước khi sửa code, và **cập nhật lại sau khi hoàn thành việc gì** (theo đúng format đã có:
   mỗi Bat/hạng mục có phần "Đã làm" + "Chưa test trên máy anh Hoài" + xác nhận sau khi test).
2. **`AGW-ROADMAP-001-diem-bat-dau.md`** (nếu có trong repo/được upload) — roadmap mới nhất định
   nghĩa lại Gateway thành "Customer Terminal mỏng", có 6 Chặng (A-F). Đây là điểm bắt đầu khi
   quay lại dự án — đọc §1-4 rồi nhảy thẳng §9 "Immediate Next Actions".
3. **`ISSUES-EN.md`** — bản dịch tiếng Anh của ISSUES-VI.md, giữ đồng bộ nếu sửa 1 trong 2.
4. Thư mục `docs/` — tài liệu chi tiết từng mảng (DATABASE, DASHBOARD, TELEGRAM_BOT, BACKEND_API,
   KNOWLEDGE_BASE_V2_DESIGN, NLU feedback/proposal gửi team Knowledge).

## 3. Trạng thái hiện tại (tóm tắt — chi tiết đầy đủ ở ISSUES-VI.md)

| Issue | Trạng thái |
|---|---|
| #1-#8, #10 | ✅ Closed |
| #9 CI/CD + VPS | 🟡 Đã xong phần không cần VPS thật, còn thiếu deploy |
| #11 Knowledge Base V2 (M1-M6) | ✅ Xây xong, **đã nối vào bot thật** qua NLU Bat 4-5 |
| #12 Lớp NLU | 🟡 Đã triển khai đủ 10 bước NLU-INTEGRATION-GUIDE.md, đang tích hợp production |

**Feature flag quan trọng:** `ENABLE_NLU_ROUTER` trong `.env` — kiểm soát việc bot có dùng Lớp NLU
(#12) hay không. Hiện đang **`true`**.

**⚠️ Việc dở dang cần xác nhận trước tiên:** bug `_extract_location()` trong
`app/services/nlu/entity_extraction.py` (không khớp được địa danh không dấu, vd "Ca Mau" vs
gazetteer "Cà Mau") — đã có bản vá (dạng text, dán tay do MCP mất kết nối lúc đó), **chưa xác
nhận đã áp dụng vào file thật hay chưa**. Kiểm tra lại hàm `_extract_location` trong file đó
trước khi coi Chặng A (roadmap) là đã đóng.

## 4. Môi trường máy hiện tại (ĐANG THIẾT LẬP LẠI — mới chuyển máy)

Dự án vừa chuyển từ máy cũ (`C:\alpha3s`) sang máy mới (`D:\alpha3s`). Đang cài lại môi trường
theo thứ tự: Node.js (xong) → Git → WSL2 → Docker Desktop. **Trước khi chạy bất kỳ lệnh
`docker compose` nào, xác nhận `docker --version` và `git --version` đều chạy được.**

`.env` đã được copy đầy đủ (đã xác nhận có đủ các biến quan trọng: Meta, Telegram x3, GitLab,
LLM, DB, Redis; nay thêm `GITHUB_TOKEN` cho CI/CD + đẩy code GitHub) — không cần tạo lại.
`.env.bridge` (gitignore) chứa token cầu nối Telegram 2 chiều — xem memory `telegram-bridge`.

## 5. Roadmap mới — "Customer Terminal" (nếu có AGW-ROADMAP-001 trong repo)

Đang định nghĩa lại Gateway thành lớp giao tiếp đa kênh MỎNG (Messenger → Web → Zalo) đặt trước
App hiện tại — App giữ toàn bộ "não" (KB/NLU/LLM/tools/DB). 6 Chặng A-F, chạy trên 1 VPS
2 vCPU/4GB/60GB. Quyết định đã khóa (không mở lại): xem §3 "Locked Decisions" trong file roadmap.
**Điểm nghẽn sống-còn cần đo sớm:** RSS bộ nhớ của 2 model embedding (KB V2 dùng MiniLM-L12-v2,
NLU dùng mpnet-base-v2) — script đo đã chuẩn bị sẵn nội dung, cần tạo file
`scripts/measure_embedding_rss.py` nếu chưa có (xem lịch sử chat để lấy nội dung, hoặc hỏi lại).

## 6. Quy ước làm việc BẮT BUỘC — bài học xương máu của dự án này

### Git trên Windows
- **Commit message LUÔN 1 dòng.** Message nhiều dòng trên Windows CMD từng nhiều lần sinh ra
  **file rác thật sự bị commit vào git** (ví dụ đã gặp: `0.1`, `buildBD.bat`, `don`, `dung`,
  `Entity`, `FAQ-BRAND-001`, `khong`, `python`, `results.md`...). Nếu thấy các file lạ tên ngắn/
  không rõ nghĩa ở gốc repo, khả năng cao là rác loại này — kiểm tra nội dung trước khi xóa, nếu
  đúng là rác thì xóa + commit dọn dẹp.
- Nếu cần message dài, dùng `git commit -m "dòng 1" -m "dòng 2"` (nhiều `-m` riêng) thay vì 1
  message nhiều dòng trong 1 `-m`.

### Xử lý tiếng Việt — LỚP BUG TÁI PHÁT NHIỀU LẦN NHẤT của dự án
Khi so khớp từ khóa/chuỗi tiếng Việt, **bỏ dấu để so khớp gây đồng âm giả** — đã gặp ít nhất 3
lần với hậu quả khác nhau:
- `"hỏng"` khớp nhầm substring vào `"không"` (thiếu ranh giới từ `\b`)
- `"chưa"` (rất phổ biến, "not yet") và `"chua"` (vị chua) đều thành `"chua"` sau khi bỏ dấu —
  đây là **đồng âm ở cấp TỪ HOÀN CHỈNH**, thêm `\b` KHÔNG giải quyết được
- `"ly"` (đơn vị cốc) và `"lý"` (trong "xử lý") cùng vấn đề
- `"Ca Mau"` (khách gõ không dấu) không khớp gazetteer `"Cà Mau"` (viết có dấu) — chiều ngược lại

**Quy tắc:** mặc định **giữ nguyên dấu** khi so khớp từ khóa/rule, chỉ bỏ dấu khi thật cần (số,
mã code) HOẶC khi bỏ dấu ở **CẢ HAI phía** (cả input lẫn từ điển so khớp) một cách nhất quán.
Luôn thêm ranh giới từ (`\b`) khi dùng substring match. Test bằng CẢ cặp có dấu/không dấu trước
khi tin là đúng.

### Quy trình phát triển
- **Luôn test qua sandbox (dữ liệu giả lập/logic thuần) trước khi sửa file thật.** Đây là quy
  trình chuẩn xuyên suốt dự án — không đoán, verify bằng số liệu cụ thể.
- Với bug liên quan dữ liệu tiếng Việt/regex: viết case test cụ thể (câu thật, không phải giả
  định) trước khi kết luận đã sửa đúng.
- Sau khi sửa, luôn **cập nhật `ISSUES-VI.md`** (mục tương ứng) ghi rõ: đã làm gì, bug gì phát
  hiện, đã verify bằng gì, còn gì chưa test.

### Docker Desktop trên máy dev có thể bất ổn
Từng gặp nhiều lần: lỗi I/O đọc file qua bind-mount (`OSError: Input/output error: '/srv'`), lỗi
DNS không phân giải được service Redis trong network, crash "What's next" lặp lại nhiều lần liên
tiếp — **thường tự phục hồi sau `docker compose restart`/`up -d` lại**, không phải lỗi logic
code. Nếu gặp lỗi khó hiểu ngay sau khi restart nhiều container liên tiếp, nghi ngờ nguyên nhân
hạ tầng trước khi debug sâu vào code.

### Kiến trúc — ranh giới trách nhiệm quan trọng
- **Knowledge Base V2 (#11)** và **Lớp NLU (#12)** được xây **song song, tách biệt hoàn toàn**
  khỏi hệ thống RAG cũ (`app/services/rag.py`, bảng `knowledge_chunks`) trong suốt quá trình
  phát triển — chỉ nối vào `orchestrator.py` production sau khi đã test kỹ qua CLI script riêng.
- NLU Router **không tự gọi Tool hay tự sinh câu trả lời** — chỉ trả về gợi ý (route hint) bơm
  thêm vào system prompt; Orchestrator (LLM) vẫn là nơi quyết định hành động cuối cùng. Toàn bộ
  đường NLU được bọc try/except — lỗi ở đây **không bao giờ** được làm vỡ luồng trả lời chính.
- 2 model embedding khác nhau chạy độc lập: `app/services/embedder.py` (KB V2,
  MiniLM-L12-v2) và `app/services/nlu/nlu_embedder.py` (NLU, mpnet-base-v2) — cố ý tách để không
  ảnh hưởng lẫn nhau, nhưng đây cũng là điểm cần đo RAM khi tính chuyện đưa lên VPS nhỏ (xem
  mục 5).
- **Không suy luận kênh (channel) từ prefix chuỗi** trong code mới (bài học từ `tg:` cũ dùng cho
  Telegram) — nếu roadmap Customer Terminal áp dụng, dùng field tường minh thay vì prefix ngầm
  định.
- **Không bypass hàng đợi/terminal** dù là kênh tự làm (bài học từ Telegram từng đi tắt qua
  queue chính) — mọi kênh nên đi cùng 1 đường xử lý durable.

## 7. Việc tiếp theo (theo đúng thứ tự ưu tiên hiện tại)

1. Xác nhận môi trường máy mới hoạt động đủ (Docker + Git + `docker compose up` chạy được).
2. Xác nhận bản vá `_extract_location` đã có trong file thật (mục 3 ở trên).
3. Nếu có `AGW-ROADMAP-001`: làm theo §9 "Immediate Next Actions" — đóng nốt Chặng A (bao gồm đo
   embedding RSS — A3), rồi Chặng B (VPS) có thể làm song song.
4. Nếu không có roadmap mới trong tay: ưu tiên cũ vẫn là #1 (rotate secret Meta) và #9 (VPS thật).

## 8. Ghi chú cho Claude Code

- Không có gì trong file này thay thế `ISSUES-VI.md` — file này chỉ là điểm khởi động nhanh.
- Nếu làm xong việc gì, **luôn cập nhật `ISSUES-VI.md`** theo đúng format đã thiết lập, không chỉ
  báo cáo trong chat rồi thôi.
- **Repo dùng GitHub** (`github.com/ledanghoai-bot/a3s`) từ 24/7/2026 — đã chuyển hẳn từ GitLab
  (GitLab trả phí + chặn CI vì chưa xác minh danh tính; xem #9 Bat 5). CI/CD = GitHub Actions,
  push `main` → tự deploy VPS. GitLab còn lại chỉ là remote phụ `gitlab`, sẽ hủy. Kiểm tra
  `git remote -v` nếu cần.
- **Đã có VPS production thật** (`160.30.157.235`, xem `docs/DEPLOYMENT.md` + `docs/VPS-RUNBOOK.md`
  và memory `vps-production`). HTTPS live tại `a3s.robanme.com`. Việc còn lại của #9 chỉ là cutover
  webhook Meta sang VPS (đụng khách thật — cần user chốt).
