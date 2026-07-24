# Báo cáo hoàn thành Issue #9 & Tổng kết Giai đoạn I — Alpha3S

> **Ngày:** 24/07/2026 · **Người soạn:** Claude Code (theo yêu cầu anh Hoài)
> **Mục đích:** Xác nhận Giai đoạn I hoàn tất để team thiết kế confirm và mở **Giai đoạn II —
> Alpha3S Gateway (Customer Terminal)**.
> Bản EN: `docs/PHASE1-COMPLETION-REPORT-EN.md`.

---

## 1. Tóm tắt điều hành

**Giai đoạn I của Alpha3S đã hoàn tất và đang chạy production 24/7 trên VPS thật.** Chatbot bán
hàng (RAG + Knowledge Base V2 + Lớp NLU + tool-calling + dashboard) đã được đóng gói, kiểm thử,
và **cutover toàn bộ kênh khách hàng (Messenger + Telegram) sang hạ tầng VPS**, với CI/CD tự động,
HTTPS, backup hằng ngày và cảnh báo.

12/12 issue trong backlog Giai đoạn I đã đóng. Việc cuối cùng còn mở — #9 (CI/CD + deploy VPS +
monitoring) — đã hoàn thành trong phiên 23–24/07/2026. Hệ thống hiện đủ điều kiện làm **nền tảng
"não" (App)** cho kiến trúc Gateway của Giai đoạn II.

---

## 2. Issue #9 — CI/CD + Deploy VPS + Monitoring (hạng mục cuối GĐ I)

| Hạng mục | Kết quả |
|---|---|
| **VPS production** | Ubuntu 24.04, 4 vCPU / 8GB / 60GB (`160.30.157.235`). Docker + Compose, swap 2G, `ufw` chỉ mở 22/80/443. |
| **Bảo mật SSH** | Chỉ đăng nhập bằng key (`PasswordAuthentication no`); mật khẩu root đã tắt hẳn. |
| **CI/CD** | **GitHub Actions** — push `main` → lint (ruff) + test (pytest) + tự deploy VPS qua SSH. Đã chuyển từ GitLab (trả phí + chặn CI vì chưa xác minh danh tính). |
| **HTTPS** | Caddy + Let's Encrypt tự động cho `a3s.robanme.com` (API/webhook) + `a3s-dash.robanme.com` (dashboard). |
| **Backup** | `pg_dump` hằng ngày 03:00 (giờ VN), giữ 14 bản; đã chạy thật. |
| **Cảnh báo** | Cron 5 phút: hàng đợi lỗi (dead-letter) / container chết / đĩa >85% → Telegram nhóm admin. |
| **Cutover** | Toàn bộ kênh khách + admin (Messenger + 2 bot Telegram) đã chuyển sang VPS (xem §4). |
| **Tài liệu** | `DEPLOYMENT-{VI,EN}.md` (tham chiếu kỹ thuật) + `VPS-RUNBOOK-{VI,EN}.md` (cầm-tay-chỉ-việc cho staff tự vận hành, không cần AI). |

**Tiêu chí hoàn thành đạt được:** push `main` → tự động deploy (đã chứng minh nhiều lần liên tiếp);
hệ thống chạy 24/7 trên VPS.

---

## 3. Tổng kết Giai đoạn I (Issue #1–#12)

| # | Hạng mục | Trạng thái |
|---|---|---|
| 1 | Webhook Messenger + xác thực Meta | ✅ |
| 2 | Hàng đợi Redis + arq worker | ✅ |
| 3 | PostgreSQL + pgvector (schema/migration/seed) | ✅ |
| 4 | RAG pipeline (ingest + search) | ✅ |
| 5 | System prompt & brand voice | ✅ |
| 6 | Tool calling (search_products / check_stock / create_order / escalate) | ✅ |
| 7 | Human handoff (`bot_paused`) | ✅ |
| 8 | Dashboard admin + analytics | ✅ |
| 9 | CI/CD + deploy VPS + monitoring | ✅ (hoàn thành phiên này) |
| 10 | Kênh khách dự phòng qua Telegram | ✅ |
| 11 | **Knowledge Base V2** (Ingestion→Retrieval→Router→Prompt Assembly→Guardrails→Test) | ✅ đã nối vào bot thật |
| 12 | **Lớp NLU** (Normalization→Pattern→Semantic→Combined→tích hợp production) | ✅ đã chạy production |

**Năng lực cốt lõi đã có ở cuối GĐ I:**
- **Knowledge Base V2**: hybrid retrieval (vector + lexical + RRF), Intent/Risk Router, Prompt
  Assembly 9-block, Runtime Guardrails (bao gồm honest-uncertainty), bộ smoke test có Release Gate.
- **Lớp NLU**: chuẩn hóa tiếng Việt (có/không dấu), Pattern Router + Semantic Router học từ dữ
  liệu thật, Entity Extraction, cache — bọc try/except để không bao giờ làm vỡ luồng trả lời.
- **Đa kênh**: Messenger (chính) + Telegram khách + Telegram admin, dùng chung một orchestrator.
- **Vận hành**: dashboard quản trị, human handoff, tool đặt hàng thật, CI/CD + backup + alert.

---

## 4. Hiện trạng production (đã kiểm chứng)

**Hạ tầng (8/8 container Up trên VPS):** `caddy`, `api`, `worker`, `dashboard`, `db`, `redis`,
`telegram_bot` (admin), `telegram_customer_bot` (khách).

**Cutover kênh — hoàn tất 24/07/2026:**
- **Messenger**: callback webhook cấp app (app `robanme.com`, page "3S Coffee") đã đổi từ ngrok
  máy local → `https://a3s.robanme.com/webhook` (Meta tự verify endpoint, `success:true`).
- **Telegram khách** `@CSKH_3S_Coffee_bot` + **Telegram admin**: chạy trên VPS; bot local đã gỡ
  hẳn để không tranh token (`getUpdates` 409). Cả hai poll sạch (pending 0, không lỗi).

**Kiểm thử end-to-end trên VPS (kênh Customer Care):**
- Tư vấn pha chế dựa trên Knowledge Base (liều lượng, nhiệt độ, số liệu caffeine).
- Guardrail **honest-uncertainty** hoạt động đúng: không bịa tỷ lệ phối trộn Robusta/Arabica.
- **Lên đơn thật thành công** (đơn #1: 1 hũ 100g × 170.000đ, thu đúng tên/SĐT/địa chỉ, status `new`).
- Độ trễ gần như tức thời (VPS đặt tại VN).

**Số liệu kiểm chứng (VPS ≡ Local — chứng minh tính ổn định qua môi trường):**
- KB smoke test: **10/10 PASS** (cả VPS lẫn local), Release Gate PASS.
- NLU held-out 150 câu: **121 đúng (80.7%)** trên cả hai; các case sai trùng khớp, điểm
  confidence trùng tới 4 chữ số thập phân → ngưỡng embedding **ổn định qua CPU khác nhau**.
- RAM: bot (2 model embedding) ~1.0GB; toàn stack ~2.7GB / 7.8GB → còn dư ~5GB.

> Kết luận đo lường: các phép đo **logic/độ chính xác** trên máy local là đáng tin (cùng code +
> dữ liệu → cùng kết quả); chỉ các phép đo **hiệu năng** (độ trễ, RAM) mới phụ thuộc môi trường
> và cần đo trên chính VPS (đã đo).

---

## 5. Việc còn treo (không chặn việc mở Giai đoạn II)

| Việc | Ghi chú | Người xử lý |
|---|---|---|
| **Rotate secret Meta** | `META_APP_SECRET`/`PAGE_ACCESS_TOKEN` từng lộ trong git history (#1) — cần thay mới. | Anh Hoài (Meta Developer Console) |
| **Meta App review** | Xin approve app trước khi mở Messenger cho khách thật. Fanpage hiện chưa có khách nên đã cutover sớm để dev/test. | Anh Hoài |
| **Catalog sản phẩm** | Hiện đúng 1 SKU thật (Hũ 100g). Khi mở rộng dòng sản phẩm cần nhập thêm qua dashboard. | Vận hành/kinh doanh |
| **FAQ table / staff_users** | Bảng `faq_entries` và `staff_users` đang rỗng (FAQ phục vụ qua KB; dashboard chưa tạo tài khoản đăng nhập). | Vận hành |

Không hạng mục nào ở trên chặn việc khởi động Giai đoạn II về mặt kỹ thuật.

---

## 6. Sẵn sàng cho Giai đoạn II — Alpha3S Gateway (Customer Terminal)

Giai đoạn I cung cấp đúng thứ Giai đoạn II cần: một **"App" hoàn chỉnh giữ toàn bộ não**
(KB V2 / NLU / LLM / tools / DB / dashboard) đang chạy ổn định trên 1 VP(2–4 vCPU / 8GB) — chính
là tiền đề của kiến trúc "Customer Terminal mỏng" mà team thiết kế đề xuất (roadmap
`AGW-ROADMAP-001`).

**Những gì đã sẵn làm nền cho Gateway:**
- Một orchestrator/endpoint xử lý tin nhắn dùng chung cho mọi kênh (đã chứng minh với Messenger +
  2 Telegram) → Gateway chỉ cần là lớp giao tiếp mỏng phía trước, không phải viết lại "não".
- Hạ tầng deploy tự động + HTTPS + backup + alert đã có → thêm kênh mới (Web/Zalo) đi cùng quy trình.
- Đã đo điểm nghẽn RAM 2 model embedding trên VPS thật (~1GB) → dữ liệu thật để quyết định kiến
  trúc Gateway trên VPS nhỏ (một trong các câu hỏi mở của roadmap).

**Đề xuất mở Giai đoạn II:** team thiết kế confirm báo cáo này, sau đó khởi động theo
`AGW-ROADMAP-001` — bắt đầu §9 "Immediate Next Actions", chạy Chặng A (chuẩn hóa + đo RSS
embedding — nay đã có số liệu thật) song song Chặng B (VPS — đã có sẵn).

---

## 7. Tài liệu tham chiếu

- `ISSUES-VI.md` / `ISSUES-EN.md` — backlog đầy đủ #1–#12, trạng thái, bug đã fix.
- `docs/DEPLOYMENT-{VI,EN}.md` — tham chiếu kỹ thuật hạ tầng production.
- `docs/VPS-RUNBOOK-{VI,EN}.md` — hướng dẫn vận hành VPS cho staff.
- `docs/KNOWLEDGE_BASE_V2_DESIGN-VI.md`, `docs/NLU_LAYER-{VI,EN}.md` — thiết kế KB V2 (#11) & NLU (#12).
- `AGW-ROADMAP-001-diem-bat-dau.md` — roadmap Giai đoạn II (Alpha3S Gateway).
