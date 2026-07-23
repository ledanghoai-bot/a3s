---
id: AGW-REVIEW-002
title: Dev Re-Review & Sign-off — Alpha3S Customer Terminal v2.0.0
document_type: dev_review
domain: gateway
owner: Alpha3S
author: Dev Reviewer
role: Dev
version: 1.1.0
supersedes: AGW-REVIEW-002 v1.0.0
reviews:
  - AGW-ARCH-001 v2.0.0 (review, revised)
  - AGW-IMPL-001 v2.0.0 (review, revised)
last_updated: 2026-07-22
disposition: approve
---

# Dev Re-Review & Sign-off — Customer Terminal v2.0.0

## Document Control

Đây là vòng re-review của **Dev** sau khi CA gấp `AGW-REVIEW-002 v1.0.0` vào canonical draft. Mục tiêu: xác nhận closure và đưa disposition cuối. Hai quyết định PO đã khóa — **backup-only host** và **Zalo monitored billable budget** — **không** được mở lại ở đây; các ghi chú bên dưới chỉ là *implementation-correctness* nằm trong phạm vi đã duyệt.

## 1. Final Disposition

**APPROVE — đề nghị PO lock v2.0.0.**

- 5 finding REQUIRED (REV2-01…05): **đã khép** trong canonical, có evidence ở cả ARCH và IMPL.
- 5 finding ADVISORY (REV2-06…10): **đã xử lý/dispositioned** hợp lý.
- 2 ghi chú mới (REV2-11, REV2-12): **ADVISORY, không chặn approval** — chỉ cần gấp một dòng vào HOST-004 và CH-006 tương ứng; có thể làm ngay trong chặng liên quan mà không cần redraft.

Không còn blocker. Từ góc build, bản v2 đã đủ chặt để bắt đầu Chặng A + B.

## 2. Closure của các finding REQUIRED

| ID | Xác nhận | Vị trí đã khép |
|---|---|---|
| REV2-01 Web idempotency key | ✅ Closed | ARCH §6 rules, §7.1 note, §11; IMPL CH-001, WEB-001, WEB-003; QA "stable client message ID" |
| REV2-02 Web DELIVERED semantics | ✅ Closed | ARCH §9 (per-channel DELIVERED), §11; IMPL WEB-003, Exit gate D, QA "persisted history after tab close" |
| REV2-03 Embedding RSS timing | ✅ Closed | ARCH §2.3; IMPL A3 (đo trước KB V2 freeze) + HOST-003 revalidate |
| REV2-04 Messenger 24h window | ✅ Closed | ARCH §9 policy table; IMPL CH-003; QA send-window Required cho D-Messenger |
| REV2-05 Single-VPS SPOF | ✅ Closed | ARCH §12.4 Availability Boundary, §14 HA trigger, §18 go-live; IMPL Stop/Go + HOST-004 RPO/RTO |

## 3. Closure của các finding ADVISORY

| ID | Xác nhận | Ghi chú |
|---|---|---|
| REV2-07 Serial-worker latency | ✅ | §8.2 + Exit gate D quan sát p95 ngay trong Web pilot |
| REV2-08 Telegram durability | ✅ | §3 + TERM-005: khách Telegram đi qua `terminal_inbound_events`; Admin path log lỗi có cấu trúc |
| REV2-09 Handoff auditability | ✅ | §15 + WEB-002: structured log pause/resume/takeover kèm trace_id |
| REV2-10 Diagram queue flow | ✅ | §2.1 đã sửa: API persist → worker claim từ DB |
| REV2-06 Zalo numeric rules | ⚠️ Partial — xem §4 | Đã configurable + reverify tại CH-004; chỉ cần chỉnh một khẳng định về nguồn |

## 4. Đính chính nhỏ cho REV2-06 (accuracy)

Disposition của CA ghi: *"Official source checked 2026-07-22 does state 8/48h and 7-day eligibility."* Cần chính xác lại: trong tra cứu của vòng review, **trang chính thức Zalo (Tin Tư vấn) xác nhận 48h miễn phí và cửa sổ 7 ngày qua OpenAPI, nhưng nêu "không giới hạn số lượng"**; con số **"8 tin miễn phí"** đến từ **nguồn thứ ba** (Hana.ai), chưa khớp dứt khoát với trang official.

Hệ quả: không đổi thiết kế — cách xử lý hiện tại (để số trong config + reverify tại CH-004) **đã đúng**. Chỉ đề nghị sửa câu khẳng định nguồn để tránh coi "8 tin" là đã xác minh chính thức. Đối xử với con số 8 như **chưa xác nhận** cho tới CH-004.

## 5. Ghi chú implementation mới (trong phạm vi 2 quyết định đã khóa)

> Không mở lại quyết định. Đây là chi tiết đúng-sai khi build mà đặc tả hiện chưa nói rõ.

### REV2-11 — Nơi cất khóa giải mã backup phải sống sót khi mất production host `[ADVISORY]`

**Vị trí:** ARCH §12.2/§12.4; IMPL HOST-004.

**Finding:** Backup được **mã hóa** và đẩy off-host, restore drill chạy **từ bản off-host** — tốt. Nhưng đặc tả chưa nói **khóa giải mã / secret cần để restore nằm ở đâu**. Kịch bản chết người: nếu khóa chỉ nằm trên production VPS, mà tình huống cần restore lại chính là **production VPS chết**, thì bản backup off-host **không giải mã được** → mất khả năng phục hồi dù backup vẫn còn.

**Đề xuất (một dòng vào HOST-004):** Khóa giải mã backup + secret tối thiểu để restore phải được lưu **độc lập với production host** (password manager/secret store ngoài, hoặc bản in offline an toàn). **Restore drill phải được thực hiện trong điều kiện giả định production host đã mất hoàn toàn** — nếu vẫn restore được thì mới coi là pass. Đây chính là thứ biến "có backup" thành "thật sự phục hồi được".

### REV2-12 — Kế toán ngân sách Zalo phải idempotent theo delivery `[ADVISORY]`

**Vị trí:** ARCH §10.1; IMPL CH-006.

**Finding:** §10.1 yêu cầu **atomic reserve trước khi gửi** — đúng. Nhưng chưa nói reservation gắn với khóa nào. Rủi ro: một billable send **reserve ngân sách → fail transient → retry** cùng message có thể **reserve/tính phí lần hai**, làm hao ngân sách ảo và có thể chạm hard-stop sai. (Serial worker giảm rủi ro concurrency, nhưng **không** giải quyết chuyện retry của cùng một delivery.)

**Đề xuất (một dòng vào CH-006):** Reservation và ghi nhận chi phí phải **idempotent theo `idempotency_key` của `terminal_outbound_deliveries`** — retry của cùng một delivery **không** tạo reservation/charge mới; chỉ delivery mới (idempotency_key mới) mới trừ ngân sách. Thêm một QA case: "retry một billable send không trừ ngân sách hai lần".

## 6. Recommended Next Actions

1. CA sửa câu nguồn REV2-06 và gấp REV2-11 (HOST-004) + REV2-12 (CH-006) — đều là amendment một dòng.
2. PO lock `AGW-ARCH-001 v2.0.0` và `AGW-IMPL-001 v2.0.0`.
3. Dev khởi động **Chặng A + B song song** ngay sau lock.

## 7. Sign-off

| Item | Value |
|---|---|
| Reviewer role | Dev |
| Scope | AGW-ARCH-001 v2.0.0 + AGW-IMPL-001 v2.0.0 (revised) |
| Blockers | 0 |
| REQUIRED còn mở | 0 |
| ADVISORY mới | 2 (REV2-11, REV2-12) — non-blocking |
| Locked decisions không đụng tới | Backup-only host; Zalo monitored billable budget |
| Disposition | **Approve — recommend PO lock v2.0.0** |
