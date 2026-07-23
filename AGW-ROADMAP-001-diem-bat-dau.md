---
id: AGW-ROADMAP-001
title: Alpha3S Customer Terminal — Master Roadmap & Resumption Brief
document_type: roadmap
domain: gateway
owner: Alpha3S
author: Dev + CA
version: 1.0.0
status: active
purpose: single_entry_point_when_returning_to_project
last_updated: 2026-07-22
related:
  - AGW-ARCH-001 v2.0.0 (review)
  - AGW-IMPL-001 v2.0.0 (review)
  - AGW-REVIEW-001 v2.0.0
  - AGW-REVIEW-002 v1.1.0
  - ISSUES-VI.md (#9, #11, #12)
---

# Alpha3S Customer Terminal — Master Roadmap & Resumption Brief

## 0. Cách dùng tài liệu này

Đây là **điểm bắt đầu** khi quay lại dự án Alpha3S. Đọc §1–§4 để nhớ bối cảnh và trạng thái, rồi nhảy thẳng tới **§9 — Immediate Next Actions**. Các tài liệu canonical chi tiết (ARCH/IMPL/REVIEW) nằm ở §11; tài liệu này là bản đồ, không thay thế chúng.

Một câu tóm tắt toàn dự án: *Alpha3S Gateway được định nghĩa lại thành một **Customer Terminal mỏng** — cổng giao tiếp đa kênh (Messenger → Web → Zalo) đặt trước App hiện tại; App vẫn giữ toàn bộ não và kho dữ liệu. Tất cả chạy trên một VPS 2 vCPU / 4 GB / 60 GB.*

## 1. Project Snapshot

Alpha3S (3S Coffee) là chatbot bán cà phê sấy lạnh, chạy Messenger + Telegram, tích hợp RAG + tool-calling + dashboard admin. Stack: FastAPI + PostgreSQL/pgvector + Redis/arq + Next.js dashboard + DeepSeek LLM + sentence-transformers (embedding local). Repo `C:\alpha3s`.

Công việc "Gateway/Terminal" này **không viết lại Core** — nó bọc một lớp giao tiếp đáng tin quanh App hiện tại và mở thêm kênh khách hàng. Quan hệ với backlog cũ:

| Issue cũ | Liên hệ với roadmap này |
|---|---|
| #11 KB V2 | Đóng trong **Chặng A** (kèm đo embedding RSS trước khi freeze) |
| #12 NLU router | Đóng trong **Chặng A** (+ vá bug `_extract_location` bỏ dấu còn treo) |
| #9 CI/CD deploy thật | Giải quyết bằng **Chặng B** (dựng VPS + deploy Alpha3S lên staging/production) |

## 2. The Core Decision (một trang)

- Gateway = **thin Customer Terminal**, KHÔNG phải integration platform. Chỉ làm 4 việc: **verify + normalize** (vào) · **dedupe + order + chuyển tới App** · **deliver + retry + dead-letter** (ra) · **trace**.
- **App hiện tại là source of truth**: customer, conversation, `bot_paused`/handoff, message history, KB/NLU/LLM/tools, product/price/stock/order/approval, business decision.
- Terminal **không** tạo customer/conversation model thứ hai, **không** tự quyết AI/human ownership.
- Kênh ưu tiên theo thị trường VN: **Messenger (đang có) → Web chatbox (mới #1) → Zalo OA (mới #2)**; Telegram lùi về fallback/admin.
- **Web trước Zalo** vì: web e-commerce đã sẵn (không chờ duyệt), web là adapter đơn giản nhất (chứng minh seam trước), còn Zalo cần đăng ký OA + xác minh (có lead time).
- Chatwoot **không** self-host (nặng, không vừa 4 GB). Web chatbox tự làm nhẹ + dùng **dashboard #8 làm staff inbox**. Chatwoot Cloud chỉ xét sau nếu cần.

## 3. Locked Decisions (PO-approved — không mở lại)

1. Customer Terminal, không phải platform.
2. Một VPS `2 vCPU / 4 GB / 60 GB` cho toàn bộ Alpha3S.
3. Thứ tự kênh: Messenger → Web → Zalo; Telegram fallback.
4. Web widget nhẹ trên website hiện có, Alpha3S sở hữu toàn bộ.
5. **Backup-only host** chi phí thấp để lưu backup off-host — KHÔNG phải failover node.
6. **Zalo billable send được phép** trong ngân sách có giám sát; hard stop khi chạm trần.
7. PO/CA review giữ vai **forcing function** (buộc đọc kỹ trước khi duyệt).
8. Deferred (chỉ mở khi có trigger thật): tenant/multi-brand, identity graph, gateway-owned conversation model, 5-mode state machine, tách microservice, attachment/voice/video, Chatwoot self-host.

## 4. Current Status — Chúng ta đang ở đâu

- Thiết kế đã **hội tụ ở v2** (Customer Terminal). v1 là baseline lịch sử, đang được thay bằng v2.
- `AGW-ARCH-001 v2.0.0` + `AGW-IMPL-001 v2.0.0`: trạng thái **review**, đã tích hợp REVIEW-001 + REVIEW-002.
- Dev re-review (`AGW-REVIEW-002 v1.1.0`): **APPROVE, 0 blocker.**
- ~~**Còn treo trước khi execute** (3 việc nhỏ của CA rồi PO lock)~~ → **ĐÃ XONG (xác nhận 23/7):**
  1. ✅ **REV2-11** đã gấp vào HOST-004 (ALPHA3S_GATEWAY_DEV_HANDOFF_V2.md — key/secrets cất ngoài production host, restore drill giả định total loss).
  2. ✅ **REV2-12** đã gấp vào CH-006 (reserve chi phí idempotent theo `idempotency_key`, retry không trừ phí 2 lần).
  3. ✅ Câu nguồn **REV2-06** đã sửa ("8 tin miễn phí" = unconfirmed cho tới CH-004; Closed trong traceability).
- **PO đã lock v2.0.0** (baseline 22/7, PO xác nhận lại 23/7 trên máy mới) → **Chặng A + B song song chính thức bắt đầu.**

## 5. Deployment Target & Resource Reality

| Item | Baseline |
|---|---|
| Host | 1 VPS Linux, 2 vCPU / 4 GB / 60 GB, Docker Compose |
| DB / cache | PostgreSQL + pgvector và Redis trên cùng VPS |
| Entry | Reverse proxy + HTTPS; `restart: always` + healthcheck |
| Backup | Daily, mã hóa, off-host (backup-only host), restore drill, ghi RPO/RTO |
| Availability | **Single point of failure — không auto-failover** (PO chấp nhận cho MVP) |

**Điểm nghẽn sống-còn = embedding model RSS.** Phải đo ở Chặng A (task A3) trước khi freeze KB V2. Nếu vượt budget → model nhỏ/quantized hoặc hosted embedding API. Guardrails: swap 2–4 GB; Postgres `shared_buffers`~256MB + pool; Redis `maxmemory`+TTL; embedding chỉ load 1 process; Next.js production build; disk alert 70/85/95%.

**Chatwoot self-host = KHÔNG** trên VPS này (cần ~2–4 GB riêng).

## 6. The Roadmap — 6 Chặng

Nguyên tắc: **mỗi chặng phải tự giao được giá trị nhìn thấy.** Chặng D (Web) và E (Zalo) là ROI thật; A–C là nền để tới đó an toàn.

### Chặng A — Hoàn tất Core hiện tại
- A1 đóng KB V2 (#11); A2 đóng NLU router (#12) + vá `_extract_location`.
- **A3 đo embedding RSS trước khi freeze KB V2** (REV2-03).
- *Exit:* Core baseline ổn định, không phải debug KB/NLU song song với terminal.

### Chặng B — VPS Foundation (làm sớm, song song A) ★ mở khóa
- HOST-001 provision VPS + swap; HOST-002 compose profile (RP+HTTPS, API, worker, TG poller, PG, Redis, dashboard); HOST-003 tune + revalidate embedding RSS; HOST-004 backup/restore drill (+ REV2-11 key recoverability); HOST-005 deploy Alpha3S hiện tại lên staging, đo tài nguyên, test rollback.
- *Exit:* HTTPS/health/off-host backup/restore/resource baseline/rollback đều pass. Đóng luôn #9.

### Chặng C — Thin-Terminal Reliability ★ giá trị độc lập
- TERM-001 dedupe/retry · TERM-002 typed errors · TERM-003 idempotent order · TERM-004 serial ordering (`max_jobs=1`) · TERM-005 delivery errors (+ Telegram khách qua durable inbound) · TERM-006 DB pool · TERM-007 migration runner · TERM-008 durable outbound · TERM-009 trace + metrics.
- *Exit:* test duplicate/retry/order/ordering/delivery pass trên VPS; crash test không mất message.

### Chặng D — Messenger parity + Web Customer Terminal ★ kênh mới #1
- CH-001 contract tối giản (+ `client_message_id` cho web) · CH-002 thin adapter · CH-003 Messenger parity (+ enforce cửa sổ 24h) · WEB-001 widget nhẹ · WEB-002 dashboard làm staff inbox (+ log handoff) · WEB-003 web security + `DELIVERED`=persisted-to-history.
- *Exit:* Messenger regression + 24h policy xanh; một khách web hoàn tất hội thoại E2E; reconnect cùng ID không nhân đôi; response còn thấy sau khi đóng tab/reload; handoff hoạt động; không rời source-of-truth khỏi App.

### Chặng E — Zalo OA ★ đích ROI thị trường
- CH-004 OA/OpenAPI setup + xác minh chính sách hiện hành (đừng coi số 2026-07-22 là vĩnh viễn) · CH-005 reactive text flow · CH-006 cost/window policy + **budget idempotent** (REV2-12) + hard stop tại trần.
- *Exit:* khách Zalo hoàn tất tư vấn reactive; retry không gửi ngoài cửa sổ/không vượt trần; cap test chứng minh hard stop; Messenger + Web regression xanh.

### Chặng F — Evidence-Driven Hardening
- Chỉ mở khi trigger thật: multi-worker ordering, richer identity, tenant, full handoff state machine, tách service, VPS lớn hơn / HA.

## 7. Channel Plan & External Dependencies

| Kênh | Trạng thái | Ràng buộc cần nhớ |
|---|---|---|
| Messenger | Đang chạy → vào terminal (Chặng D) | Cửa sổ gửi chuẩn **24h**; ngoài cửa sổ chỉ gửi qua message tag hợp lệ + PO duyệt |
| Web chatbox | Mới #1 (Chặng D) | Không có provider send-window; cần auth/session, CORS, rate-limit; `client_message_id` cho dedupe; `DELIVERED`=persisted |
| Zalo OA | Mới #2 (Chặng E) | **Cần đăng ký OA + xác minh doanh nghiệp — có lead time.** Tin Tư vấn miễn phí trong 48h; cửa sổ eligibility 7 ngày (OpenAPI); số "8 tin" **chưa xác nhận official**, verify tại CH-004 |
| Telegram | Fallback | Khách vẫn qua durable inbound; Admin path log lỗi có cấu trúc, không nuốt lỗi |

> **Việc chạy nền cần khởi động sớm (Chặng B–C):** bắt đầu **đăng ký/xác minh Zalo OA ngay**, để khi tới Chặng E là OA đã sẵn sàng — không chờ nối tiếp.

## 8. Open Items Pending PO

- Số tiền + kỳ ngân sách + người nhận cảnh báo cho **Zalo billable send** (trước khi enable).
- Xác nhận mức downtime/RTO thực đo (từ HOST-004) trước khi promote production.

## 9. Immediate Next Actions (khi quay lại, làm theo thứ tự)

1. **CA:** gấp 2 amendment một dòng (REV2-11 vào HOST-004, REV2-12 vào CH-006) + sửa câu nguồn REV2-06 → **PO lock `v2.0.0`**.
2. **Chặng A:** đóng nốt #11/#12, vá `_extract_location`, và **chạy A3 đo embedding RSS trước khi freeze KB V2**.
3. **Chặng B (song song):** provision VPS → compose profile → backup/restore drill → deploy Alpha3S hiện tại làm staging. (Đóng #9.)
4. **Khởi động đăng ký Zalo OA** (chạy nền, chờ duyệt).
5. Sau khi B xong nền → vào **Chặng C** (reliability).

*Hỗ trợ sẵn sàng khi bắt đầu:* soạn `docker-compose` production profile + checklist HOST-001…005; hoặc script đo embedding RSS cho A3.

## 10. Engineering Guardrails & Lessons (mang theo)

- **Git trên Windows CMD:** luôn dùng commit message **1 dòng** (nhiều dòng sinh file rác — đã gặp nhiều lần).
- **Tiếng Việt bỏ dấu để so khớp gây đồng âm giả** ("chưa/chua", "ly/lý", "Ca Mau/Cà Mau") — giữ dấu khi so khớp từ khóa, chỉ bỏ dấu khi thật cần (số/mã). Đây là loại bug tái phát; cẩn thận với mọi lớp ID/chuỗi.
- **Docker Desktop trên máy dev bất ổn** (I/O `/srv`, DNS Redis, crash) — thường tự phục hồi sau restart, không phải lỗi code. VPS staging (Chặng B) sẽ giảm phụ thuộc vào môi trường này.
- **Test qua sandbox trước khi vào file thật** — quy trình chuẩn của dự án.
- **Không suy ra channel từ prefix chuỗi** trong code mới (bài học từ `tg:` cũ).
- **Không bypass terminal** dù là web của mình (bài học Telegram bypass queue) — mọi kênh đi cùng đường durable inbound/outbound.

## 11. Document Index

| Doc | Vai trò |
|---|---|
| **AGW-ROADMAP-001** (bản này) | Điểm bắt đầu / bản đồ tổng |
| AGW-ARCH-001 v2.0.0 | Kiến trúc canonical (Customer Terminal) |
| AGW-IMPL-001 v2.0.0 | Kế hoạch triển khai story-level (A–F) |
| AGW-REVIEW-001 v2.0.0 | Phản biện + phương hướng (descope, hosting, kênh) |
| AGW-REVIEW-002 v1.0.0 | Dev review lần 1 (10 finding) |
| AGW-REVIEW-002 v1.1.0 | Dev re-review & sign-off (APPROVE) |
| ISSUES-VI.md | Backlog gốc #1–#12 (đọc trước khi làm gì) |

## 12. Quick Stop/Go Reference

**STOP nếu:** backup/restore chưa chứng minh · RAM baseline vượt budget · message/order có thể nhân đôi · rule/budget Zalo chưa cấu hình · ai đó định self-host Chatwoot trên VPS 4 GB · terminal bắt đầu sở hữu business/customer/conversation state · PO chưa acknowledge SPOF + RPO/RTO trước production.

**GO khi:** exit gate của chặng hiện tại pass; công việc platform về sau không chặn giá trị của chặng trước.
