# Sensor Inventory — Alpha3S

```yaml
document: SENSOR-INVENTORY
owner: Dev (Alpha3S) — data owner theo bảng; policy owner: PO
version: 1.0.0
status: living-document
created: 2026-07-28 (I-B M3-S0)
source_of_truth: schema Scalffold V2.0 §18 (E:/A3s-orbit/main/SCALFFOLD-V2.0-APPROVED.md); event thực = code/migrations D:\alpha3s tại base 9b49628
update_rule: mỗi sensor mới/đổi trạng thái phải cập nhật file này trong cùng PR
```

Sensor = event hệ thống **thật sự quan sát được** + giới hạn hành động mà event cho phép.
Trường theo schema §18: `sensor_id, event_name, source_system, producer, data_class, purpose_code,
identity_scope, assertion_provenance, reliability, latency, retention, journey_assertions,
maximum_action_level, owner, status`.

## 1. Nhóm Conversation (source: Alpha3S core)

| sensor_id | event_name | producer | data_class | purpose | provenance | max_action | status |
|---|---|---|---|---|---|---|---|
| CONV-01 | conversation.message_received | webhook → bảng `messages` | D1 (raw chat, có thể chứa D2 tự khai) | P01 | observed | act (trả lời tư vấn) | **active** |
| CONV-02 | conversation.tool_call | orchestrator (LLM tool-calling) | D1 (args có PII với create_order) | P01/P02 | observed | act | **active** (chưa emit event chuẩn envelope — xem Gap) |
| CONV-03 | conversation.escalation | bảng `escalations` + handoff | D1 | P04 | observed | act (chuyển người) | **active** |

- identity_scope: psid/customer_id + conversation_id. reliability: cao (ghi DB cùng luồng).
  latency: realtime. retention: theo `RETENTION-SCHEDULE.md` (raw chat).
- journey_assertions: khách đang tương tác (observed); KHÔNG suy "sắp mua" (estimated) từ message đơn lẻ.

## 2. Nhóm Commerce (source: `order_events` — migration 022, M2)

| sensor_id | event_name | producer | data_class | purpose | provenance | max_action | status |
|---|---|---|---|---|---|---|---|
| COMM-01 | order.created | order transition engine (M2) | D1 (refs, không raw PII trong event) | P02 | observed | act (receipt) | **active** |
| COMM-02 | order.confirmed / processing / ready_for_fulfillment / fulfilled / shipped / completed / done | transition engine, append-only idempotent | D1 refs | P02/P03 | observed | act (notify transactional) | **active** |
| COMM-03 | order.cancelled / cancelled_by_exception / return_requested / return_inspection | transition engine | D1 refs | P02/P04 | observed | act | **active** |
| COMM-04 | order.delivered | **M3-S1 (migration 029)** | D1 refs | P02/P03 | observed (chỉ khi có committed event) | act | **planned S1** |
| COMM-05 | order.delivery_failed | status đã có (025); transition + event chuẩn hóa ở S1 | D1 refs | P02/P04 | observed | act (retry/CSKH) | **partial → S1** |

- reliability: cao (cùng transaction với transition, idempotent). identity_scope: order_id + customer_id.
- journey_assertions: `delivered` = mốc bắt đầu Product Usage Life Cycle (estimated clock — Orbit đọc sau
  qua boundary, KHÔNG phát như observed usage).

## 3. Nhóm Web (source: web chat widget / landing — tương lai)

| sensor_id | event_name | data_class | purpose | provenance | status |
|---|---|---|---|---|---|
| WEB-01 | web.utm_captured (utm_source/medium/campaign/content[/term]) | D0–D1 (cấm PII trong UTM) | P07 | declared (client gửi) | **planned S2** (migration UTM) |
| WEB-02 | web.form_submit (đặt hàng qua form) | D1 | P02 | observed | planned (Orbit/Gateway scope) |
| WEB-03 | web.visit / landing interaction | D1 (IP/device) | P07 | observed | planned — KHÔNG thuộc M3 |

## 4. Nhóm Outbound (source: outbox M1 + Dispatcher M3-S5)

| sensor_id | event_name | producer | data_class | purpose | provenance | max_action | status |
|---|---|---|---|---|---|---|---|
| OUT-01 | outbound.sent / delivered / failed | `delivery_attempts` + worker M1 | D1 refs | P03 | observed | observe_only (đầu vào retry/dead-letter) | **active** |
| OUT-02 | outbound.opt_out | **M3-S3 consent ledger** | D1 | P06 suppression | declared | act (suppress) | **planned S3** |

## 5. Nhóm Promotion

| sensor_id | event_name | status |
|---|---|---|
| PROMO-01/02/03 | voucher.issued / redeemed / expired | **not-implemented** — chưa có voucher system; giữ chỗ schema, không code trong M3 |

## 6. Nhóm Feedback

| sensor_id | event_name | data_class | provenance | status |
|---|---|---|---|---|
| FB-01 | feedback.structured_answer (khách chủ động trả lời form/câu hỏi có cấu trúc) | D1 | declared | **not-implemented** — kênh sẽ do Gateway/Orbit định nghĩa |

## 7. Gap / Action

| # | Gap | Action | Slice |
|---|---|---|---|
| G1 | CONV-02 tool_call chưa emit event theo envelope chuẩn §6.3 (chỉ có log + command_executions) | Chuẩn hóa khi đụng luồng liên quan; không bắt buộc trong M3 | backlog |
| G2 | `delivered` chưa tồn tại trong status CHECK; `delivery_failed` có status nhưng chưa có transition+event chuẩn từ `shipped` | Migration 029 + transition matrix | **S1** |
| G3 | UTM chưa có cột | Migration S2 | **S2** |
| G4 | opt-out sensor cần consent ledger | S3 | **S3** |
| G5 | Event envelope §6.3 (correlation/causation/idempotency_key đầy đủ) mới có một phần trong `order_events` | Áp đủ cho event mới từ S1; không sửa event M2 đã commit | S1+ |

Nguyên tắc: sensor mới mở rộng system belief, **không** thay domain journey model; event append-only,
không chứa raw chat / phone / full address / health disclosure (spec §6.3).
