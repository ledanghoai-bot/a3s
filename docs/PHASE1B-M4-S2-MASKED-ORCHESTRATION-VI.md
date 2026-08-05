# Alpha3S Phase I-B M4-S2 — Masked Orchestration (Development)

- **id:** A3S-PHASE1B-M4-S2-MASKED-ORCH-001
- **governing spec:** A3S-PHASE1B-M4-SPEC-001 v1.0.0 §9 (+ §5 invariants)
- **governing directive:** A3S-PHASE1B-M4-DEV-DIRECTIVE-001 v1.1.0 §4 (M4-S2 AUTHORIZED)
- **ngày:** 2026-07-28 18:19+07:00
- **tiếp nối:** `PHASE1B-M4-REBASELINE-VI.md` (S2 code trên baseline `dc839ca`, migration M4 = 038)

## 1. Quyết định phạm vi quan trọng — đọc trước

Directive §8: trong authority hiện tại `m4_trusted_pii_path` "có thể tồn tại như config
placeholder default OFF, **không có active code path**"; đồng thời §4/§14 AUTHORIZED phát triển
S2. Cách dung hòa đã chọn (fail về phía chặt):

> S2 được xây thành **module độc lập** (`app/services/pii/masking.py`, `semantic_schema.py`,
> `trusted_flow.py`) chỉ được gọi từ pytest/evidence script với model **mock** — KHÔNG có call
> site nào trong orchestrator/runtime, KHÔNG tham chiếu flag `m4_trusted_pii_path` ở bất kỳ
> code path nào. Test tĩnh `test_orchestrator_khong_noi_trusted_flow` khóa bất biến này
> (orchestrator không chứa chuỗi `trusted_flow` lẫn `m4_trusted_pii_path`).

Việc nối trusted_flow vào orchestrator (canary/enforcement) là bước SAU M4-G1, cần directive
riêng — đúng spec §17.

## 2. Thành phần đã giao

| Thành phần | File | Vai trò |
|---|---|---|
| Masking | `app/services/pii/masking.py` | mask current message + MỌI turn history (kể cả assistant — receipt cũ chứa PII khách); placeholder `[PII_{SLOT}_{n}]`; mapping server-side; `rehydrate_response` fail-closed (placeholder bịa/mangle → None) |
| Schema-bounded output | `app/services/pii/semantic_schema.py` | allowlist 4 trường (intent/missing_slot_types/response_candidate/context.items); key định danh (`customer_ref`, `psid`, `tool_args`, `phone`…) ở BẤT KỲ tầng nào → violation; response candidate bị detector quét — PII thô → violation (chỉ placeholder được phép); items validate kiểu/chặn qty bool/0/âm |
| Trusted flow | `app/services/pii/trusted_flow.py` | pipeline §9: detect → D2 chặn vendor NGAY → store slot D1 (P02) → mask → model (callable inject, mock) → validate → resolve allowlist từ STORE → trusted command assembly → deterministic receipt (phone mask ***); 3 fallback đúng thứ tự spec |

**Ba fallback (spec §9):** (1) thiếu slot → câu hỏi deterministic từng slot (phone → address →
name); (2) slot có nhưng confidence dưới ngưỡng (`phone=high, address=medium, name=low`) →
structured form; (3) D2/high-risk, model lỗi, schema violation, placeholder mangle → escalate
local/human — mọi đường lỗi đều đổ về (3), không retry mù.

## 3. Ánh xạ security invariants (spec §5) → cơ chế + evidence

| Invariant | Cơ chế | Evidence |
|---|---|---|
| #1 model không có credential/quyền đọc Slot Store | model là callable nhận messages — không conn, không import slot_store; DB-role `alpha3s_vendor_path` DENY (038) | unit + `m4_slot_store_test` [9] |
| #2 model không chọn customer_ref/conversation_ref | refs chỉ lấy từ tham số trusted của `process_turn`; mọi key ref trong output model → SchemaViolation | E2E [D] d2 |
| #3 model không điều khiển rehydration thành tool argument | schema KHÔNG có trường tool nào; placeholder chỉ được echo trong response candidate; command args lắp 100% từ store | E2E [A], [D] d1 |
| #4 tool args chỉ do trusted code lắp từ slot đúng context | `resolve_slot` binding (customer, conversation) + AAD crypto | E2E [A] args, [E] cross-conv |
| #6 D2/high-risk default deny vendor | risk D2 → return trước khi `model_call` | E2E [C] — model 0 call |
| #7 slot/log/metric không lộ plaintext | log `[m4-flow]` counts/enum; quét toàn phiên | E2E [G], `m3_pii_log` static guard PASS |
| #8 cross-customer/context mismatch fail closed | binding + AAD + placeholder reject | E2E [E], unit cross-conv |
| #10 false confirmation = 0 | receipt CHỈ sinh từ committed result của executor; mọi đường khác không có câu "đã tạo đơn" | E2E [A]/[B]; guard M1 vẫn nguyên (flag OFF) |

## 4. Evidence (container `alpha3s-m4-test` + DB `alpha3s-m4-db`, baseline `dc839ca`)

| # | Lệnh | Thời điểm | Exit | Kết quả |
|---|---|---|---|---|
| 1 | `pytest -q tests/test_m4_masking_schema.py tests/test_m4_trusted_flow.py` | 2026-07-28 18:15+07:00 | 0 | 34 passed (masking 6, schema 9, flow 10 + biến thể) |
| 2 | `scripts/m4_masked_flow_test.py` (DB thật + spy model) | 2026-07-28 18:17+07:00 | 0 | **RESULT: PASS 15/15** — A: E2E 2 turn, model không thấy PII (cả history); B: tích lũy slot 3 turn thiếu→hỏi→chốt đơn; C: D2 model 0 call; D: 3 kiểu phá rào → escalate, executor 0 call; E: cross-conversation hỏi lại; F: latency p50=3.6ms p95=16.5ms; G: log sạch |
| 3 | `pytest -q` (full) | 2026-07-28 18:19+07:00 | 0 | **181 passed** (147 + 34 S2) |
| 4 | `ruff check app scripts/m4_*.py tests` | 2026-07-28 18:19+07:00 | 0 | All checks passed |
| 5 | `scripts/m3_pii_log_test.py` (static guard M3 quét app/ gồm code S2 mới) | 2026-07-28 18:19+07:00 | 0 | ALL PASS |

## 5. Known limitations (khai báo, không giấu)

1. **Placeholder chưa có integrity tag bind conversation** — S2 fail-closed theo mapping
   server-side per-turn (placeholder lạ → reject); S3 sẽ thêm tag chống trộn placeholder
   cross-context theo spec §10.
2. Intent allowlist S2 tối giản (5 intent) và `context.items` là cấu trúc non-PII duy nhất —
   đủ chứng minh đường PII; mở rộng theo nhu cầu thật là việc integration sau M4-G1.
3. `command_executor` trong evidence là stub deterministic — nối vào command bus M1
   (`order.create` thật) là việc của giai đoạn canary (S4), cần authority riêng.
4. Fallback form là marker deterministic (`[FORM_GIAO_HANG]`) — render form thật thuộc kênh
   (Customer Terminal roadmap), ngoài scope M4.
5. Multi-turn state (đã hỏi slot nào, hỏi mấy lần) chưa lưu — S2 hỏi theo ưu tiên cố định,
   đủ cho development; chống hỏi lặp vô hạn sẽ đi cùng integration.

## 6. Bước tiếp theo

M4-S3 hardening: placeholder integrity tag (bind conversation + HMAC), cross-context rejection
tests mở rộng, telemetry redaction rà lại, D2/high-risk blocking property tests, concurrency/
replay safety, flag-OFF regression tổng — rồi Delivery Package hợp nhất (§10 directive).
