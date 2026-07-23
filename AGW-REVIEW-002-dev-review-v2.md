---
id: AGW-REVIEW-002
title: Dev Review — Alpha3S Customer Terminal v2.0.0 (ARCH + IMPL)
document_type: dev_review
domain: gateway
owner: Alpha3S
author: Dev Reviewer
role: Dev
version: 1.0.0
status: submitted
reviews:
  - AGW-ARCH-001 v2.0.0 (review)
  - AGW-IMPL-001 v2.0.0 (review)
depends_on:
  - AGW-REVIEW-001 v2.0.0
last_updated: 2026-07-22
disposition: approve_with_required_changes
---

# Dev Review — Alpha3S Customer Terminal v2.0.0

## Document Control

Đây là review của **Dev** đối với bản CA draft `AGW-ARCH-001 v2.0.0` và `AGW-IMPL-001 v2.0.0`, theo PO–CA–Dev Working Agreement: *Dev review architecture/contract trong boundary đã duyệt, và gửi impact note cho CA khi phát hiện constraint mới ở góc độ triển khai.*

Review này **không** thay đổi canonical; nó là evidence đầu vào cho vòng PO review. Các finding `REQUIRED` đề nghị CA gấp vào canonical text **trước khi PO lock v2.0.0**; các finding `ADVISORY` có thể log lại và xử lý sau.

## 1. Summary Verdict

**Disposition: APPROVE WITH REQUIRED CHANGES (conditional go).**

Từ góc độ người sẽ build: bản v2 là một revision tốt và **khả thi để triển khai** trong ràng buộc một dev + VPS 2 vCPU / 4 GB. Việc thu hẹp từ platform xuống thin Customer Terminal làm giảm đáng kể rủi ro và khối lượng, giữ đúng phần lõi reliability. **Không có architectural blocker.**

Tuy nhiên có **5 finding REQUIRED** cần khép lại trong canonical text trước khi baseline v2.0.0 được duyệt — trong đó 2 finding (REV2-01, REV2-02) là *thực chất*: nếu không xử lý, kênh Web sẽ có bug dedupe/delivery ngay khi vận hành, vì canonical §6/§9 hiện mô tả contract/delivery theo mô hình provider-API và **chưa phủ đúng kênh Web tự-sở-hữu** — mà Web lại là kênh mới #1.

### 1.1 Implementability Statement

- Serial worker `max_jobs=1` + durable event status: **build được, ít rủi ro**, đúng cho tải hiện tại. Đồng ý.
- Schema 2 bảng: **đủ** để chống mất/nhân đôi message. Đồng ý.
- Contract text tối giản: **đủ cho MVP**, với điều kiện vá REV2-01 cho Web.
- VPS budget: **khả thi nhưng biên hẹp**; điểm sống-còn là embedding RSS (REV2-03).

## 2. Severity Legend

| Mức | Nghĩa |
|---|---|
| BLOCKER | Sai kiến trúc, phải sửa trước mọi thứ | *(không có finding nào)* |
| REQUIRED | Phải khép trong canonical trước khi PO lock v2.0.0 (hoặc trước chặng liên quan) |
| ADVISORY | Nên làm; không chặn approval |

## 3. Findings Index

| ID | Severity | Chủ đề | Vị trí |
|---|---|---|---|
| REV2-01 | REQUIRED | Web inbound thiếu idempotency key | ARCH §6, §7.1; IMPL CH-001/WEB-001 |
| REV2-02 | REQUIRED | Ngữ nghĩa "DELIVERED" của Web khác provider | ARCH §9, §7.2; IMPL WEB-002/003 |
| REV2-03 | REQUIRED | Đo embedding RSS phải làm ở Chặng A, không đợi Chặng B | IMPL Chặng A vs HOST-003; ARCH §2.3 |
| REV2-04 | REQUIRED | Messenger cũng có send-window (24h), không chỉ Zalo | ARCH §9/§10; IMPL CH-002/003 |
| REV2-05 | REQUIRED | Single VPS = SPOF; thiếu tuyên bố uptime | ARCH §2/§14/§15 |
| REV2-06 | ADVISORY | Con số Zalo volatile — đóng khung "cần xác minh" | ARCH §10; IMPL CH-004/006 |
| REV2-07 | ADVISORY | Serial worker vs UX latency của Web | ARCH §8.2; IMPL TERM-004 |
| REV2-08 | ADVISORY | Mức độ durable của Telegram-fallback chưa rõ | ARCH §3; IMPL TERM-005 |
| REV2-09 | ADVISORY | Giữ structured-log tối thiểu cho handoff transition | ARCH §4.2/§5.2; IMPL WEB-002 |
| REV2-10 | ADVISORY | Nit: sơ đồ §2.1 lệch mô hình DB-as-claim §8.1 | ARCH §2.1 |

---

## 4. Required Findings

### REV2-01 — Web inbound thiếu idempotency key `[REQUIRED]`

**Vị trí:** ARCH §6 (Minimal Contract v2), §7.1 `terminal_inbound_events UNIQUE(channel, external_event_id)`; IMPL CH-001, WEB-001.

**Finding:** §6 quy định `external_message_id`/`external_event_id` là khóa dedupe *"khi provider cung cấp"*. Web widget do Alpha3S tự làm **không có provider message id**. Trong khi đó `terminal_inbound_events` bắt buộc `UNIQUE(channel, external_event_id)`. Nếu không định nghĩa nguồn của khóa này cho Web, các trường hợp **double-click, resend khi mạng chập chờn, gửi lại khi reconnect** sẽ tạo event trùng mà không dedupe được → khách thấy bot trả lời hai lần, hoặc tệ hơn nếu message kích hoạt tool/order.

**Impact khi build:** WEB-001/WEB-003 có yêu cầu "duplicate-send tests" nhưng không có cơ chế để test pass. Đây là gap contract, không phải chi tiết implementation.

**Đề xuất sửa (gấp vào §6 Rules):**

> Với kênh `web` (Alpha3S tự sở hữu), **widget sinh `client_message_id` (UUID v4) ổn định cho mỗi message của người dùng**; giá trị này được dùng làm `external_event_id`. Khi resend/reconnect, widget **phải gửi lại đúng `client_message_id` cũ** để terminal dedupe qua `UNIQUE(channel, external_event_id)`. Contract widget→terminal bắt buộc trường này.

**Verdict:** Khép trong canonical trước khi bắt đầu Chặng D.

---

### REV2-02 — Ngữ nghĩa "DELIVERED" của Web khác provider channel `[REQUIRED]`

**Vị trí:** ARCH §9 (Delivery and Channel Capabilities), §7.2 outbound statuses; IMPL WEB-002, WEB-003.

**Finding:** Lịch retry §9 (`now→+5s→+30s→+2m→+10m→+1h→dead-letter`) được thiết kế cho **API provider** (Messenger/Zalo) có thể fail transient. Đích của kênh Web là **một tab trình duyệt qua SSE/WebSocket**. Nếu tab đóng, đây **không phải** transient failure và **không được** retry suốt 1 giờ rồi dead-letter. Bản v2 đưa mọi kênh qua cùng delivery pipeline (đúng theo khuyến nghị REVIEW-001) nhưng **chưa cho phép mỗi adapter định nghĩa "thế nào là DELIVERED"**, dẫn tới worker sẽ hiểu nhầm "tab đóng" = lỗi cần retry.

**Đề xuất sửa (gấp vào §9):**

> Mỗi adapter định nghĩa tiêu chí delivery-success của kênh mình:
> - **Provider-API channels (Messenger, Zalo):** áp lịch retry/dead-letter §9. `DELIVERED` = provider chấp nhận (có `provider_message_id`).
> - **Web (self-owned):** `DELIVERED` = **outbound đã persist vào message history của App**. Push live qua SSE/WebSocket là **best-effort**, không đổi trạng thái DELIVERED; tab rớt → hiển thị lại khi load/poll sau, **không** vào retry-backoff/dead-letter. Reconnect dùng lại `client_message_id` (REV2-01) để tránh nhân đôi.

**Verdict:** Khép trong canonical trước khi bắt đầu Chặng D.

---

### REV2-03 — Đo embedding RSS thuộc Chặng A, không đợi Chặng B `[REQUIRED]`

**Vị trí:** IMPL Chặng A (Finish Core) vs HOST-003/HOST-005; ARCH §2.3.

**Finding:** Điểm sống-còn của VPS 4 GB là RSS của embedding model (§2.3 đã nhận diện đúng). Nhưng v2 đặt việc **đo RSS ở Chặng B** (trên VPS, *sau* khi Chặng A đã nối và đóng KB V2). Nếu model vượt budget, cách chữa (đổi model nhỏ/quantized/hosted embedding API) **có thể buộc sửa lại KB V2 retrieval vừa finalize** → rework đúng thứ vừa đóng.

**Đề xuất sửa:** Thêm vào **Chặng A** một task đo RSS embedding trên máy dev và **chốt lựa chọn model trước khi finalize KB V2**. HOST-003 giữ vai xác nhận lại trên VPS, không phải nơi *phát hiện* lần đầu.

**Verdict:** Chỉnh work-order trong IMPL. Rẻ, tránh rework tốn kém.

---

### REV2-04 — Messenger cũng có send-window (24h) `[REQUIRED]`

**Vị trí:** ARCH §9/§10; IMPL CH-002/CH-003; QA matrix ("Send-window/cost policy — Channel rule" cho D-Messenger).

**Finding:** §10 tả kỹ cửa sổ Zalo, nhưng kiến trúc chưa nêu **Meta cũng có 24-hour standard messaging window** (ngoài cửa sổ phải dùng message tag hợp lệ). Bot reactive phần lớn nằm trong cửa sổ, nhưng reply trễ sau handoff người thật kéo dài, hoặc thông báo trạng thái đơn, có thể rơi ngoài 24h.

**Đề xuất sửa:** Ghi rõ `evaluate_send_policy` của **Messenger adapter cũng mã hóa cửa sổ 24h** (allowed/billable/permanent theo cùng khung §9), không để trống chỉ vì mặc định reactive.

**Verdict:** Khép trong canonical; effort thấp.

---

### REV2-05 — Single VPS là SPOF; thiếu tuyên bố uptime `[REQUIRED]`

**Vị trí:** ARCH §2, §14 (Scale Triggers), §15.

**Finding:** Backup/restore (§12) lo **phục hồi**, nhưng v2 chưa tuyên bố **kỳ vọng uptime**. Single VPS + single worker + single Postgres → VPS sập là **chết toàn bộ kênh**, không có failover tự động. Với bot bán hàng, đây là rủi ro kinh doanh cần PO **chấp nhận có ý thức**, không để thành điểm mù.

**Đề xuất sửa:** Thêm một mục "Availability expectation": nêu rõ *no automatic failover trong MVP*, mức downtime chấp nhận được, và mitigation = restore nhanh (RTO đo ở HOST-004). Đưa "Larger/redundant host" vào §14 khi có yêu cầu uptime cao hơn (đã có dòng "Larger VPS" — bổ sung nhánh HA).

**Verdict:** Là *decision gap* — đề nghị đưa thành mục PO acknowledge ở §18.

---

## 5. Advisory Findings

### REV2-06 — Con số Zalo volatile `[ADVISORY]`
ARCH §10 trình bày "8 tin đầu tiên trong 48h miễn phí" như fact hiện hành. Kiểm chứng: tài liệu **chính thức** Zalo (Tin Tư vấn) *không nêu giới hạn số lượng*; con số "8 tin" đến từ nguồn thứ ba; Zalo đổi chính sách phí thường xuyên. v2 đã xử lý đúng hướng (CH-004 confirm at impl, số nằm trong config). Chỉ đề nghị **đóng khung §10 là "cần xác minh tại thời điểm triển khai"** thay vì số cố định.

### REV2-07 — Serial worker vs UX latency của Web `[ADVISORY]`
`max_jobs=1` gắn latency mọi kênh vào nhau. Web là kênh **nhạy latency nhất** (real-time, khách có thể chat đồng thời). Ngưỡng trigger "queue wait p95 > 5s" (§8.2) nhiều khả năng chạm **ngay sau khi Web launch**, sớm hơn Messenger/Zalo. Không phải blocker — chỉ nên lường trước rằng trigger nâng cấp ordering có thể kích hoạt sớm hơn dự kiến sau Chặng D.

### REV2-08 — Mức durable của Telegram-fallback `[ADVISORY]`
Telegram bị hạ xuống fallback và v2 **bỏ story durable inbound cho Telegram** (v1 có AGW-0005). Đề nghị nêu rõ: Telegram-fallback giữ path hiện tại hay vẫn đưa qua `terminal_inbound_events`. Nếu vẫn là kênh khách (dù fallback), nên tối thiểu không nuốt lỗi (TERM-005 đã có) + ghi rõ mức reliability chấp nhận.

### REV2-09 — Structured-log tối thiểu cho handoff `[ADVISORY]`
Defer bảng `conversation_state_changes` là hợp lý, nhưng nên giữ **structured-log cho mọi pause/resume/takeover kèm `trace_id`** — để trả lời được "vì sao bot reply khi có người thật" mà không cần cả bảng audit. Gắn vào WEB-002 (staff inbox) và §5.2.

### REV2-10 — Nit sơ đồ `[ADVISORY]`
Sơ đồ §2.1 vẽ `API --> Q` trực tiếp, trong khi §8.1 là mô hình DB-as-claim (API ghi event → worker claim từ DB). Chỉnh hình cho khớp để tránh hiểu nhầm terminal dùng in-memory queue.

---

## 6. Impact Notes gửi CA (constraint mới từ góc build)

Theo Working Agreement, ba điểm sau là *constraint phát hiện khi soi ở góc triển khai*, không phải thay đổi scope — đề nghị CA cập nhật canonical:

1. **Kênh self-owned (Web) cần mô hình idempotency & delivery riêng** so với provider-API channel (REV2-01, REV2-02). Đây là hệ quả tất yếu của quyết định "một pipeline chung cho mọi kênh" — pipeline chung vẫn giữ, nhưng contract phải cho mỗi adapter khai báo nguồn idempotency-key và tiêu chí DELIVERED.
2. **Send-window là thuộc tính của *mọi* channel adapter** (Messenger 24h, Zalo 48h/7d), không phải đặc thù Zalo (REV2-04).
3. **Embedding memory gate là dependency của KB V2**, nên phải đo trước khi đóng Chặng A (REV2-03).

## 7. Xác nhận phần đã tốt (giữ nguyên)

Thin terminal + App giữ source of truth; VPS budget thành ràng buộc kiến trúc + guardrails; Chatwoot self-host thành non-goal minh bạch; schema 2 bảng; **ordering đã chốt (serial `max_jobs=1`) với trigger có số đo**; `evaluate_send_policy` capability; backup + restore drill là exit gate; scale triggers evidence-driven; giữ forcing-function review. Web-before-Zalo đúng cả về thị trường lẫn kỹ thuật (Web là adapter đơn giản nhất, chứng minh seam trước khi vào ràng buộc Zalo).

## 8. Recommended Disposition & Next Actions

**Đề nghị PO:** duyệt v2.0.0 theo hướng **approve-with-required-changes** — tức yêu cầu CA gấp REV2-01…05 vào canonical text, rồi lock. Không cần một vòng redraft lớn; đây là các amendment cục bộ vào §6, §9, §10, §2, và work-order Chặng A.

Thứ tự hành động đề xuất:

1. CA cập nhật §6 (idempotency Web), §9 (DELIVERED per-channel), §10 (Messenger 24h + đóng khung số Zalo), §2 (availability expectation).
2. CA chuyển task "đo embedding RSS" sang Chặng A trong IMPL.
3. PO acknowledge REV2-05 (chấp nhận SPOF/uptime MVP) trong §18.
4. Log REV2-06…10 vào changelog để xử lý trong chặng tương ứng.
5. Sau khi khép REQUIRED → PO lock v2.0.0 → Dev bắt đầu Chặng A + B song song.

## 9. Sign-off

| Item | Value |
|---|---|
| Reviewer role | Dev |
| Scope | AGW-ARCH-001 v2.0.0 + AGW-IMPL-001 v2.0.0 |
| Blockers | 0 |
| Required findings | 5 (REV2-01…05) |
| Advisory findings | 5 (REV2-06…10) |
| Disposition | Approve with required changes |
| Gửi tới | CA (amend) → PO (lock decision) |
