# Alpha3S Phase I-B M4-S3 — Hardening (Development)

- **id:** A3S-PHASE1B-M4-S3-HARDENING-001
- **governing spec:** A3S-PHASE1B-M4-SPEC-001 v1.0.0 §10 (+ §5, §13)
- **governing directive:** A3S-PHASE1B-M4-DEV-DIRECTIVE-001 v1.1.0 §4 (M4-S3 AUTHORIZED)
- **ngày:** 2026-07-28 18:27+07:00
- **tiếp nối:** `PHASE1B-M4-S2-MASKED-ORCHESTRATION-VI.md`

## 1. Nội dung hardening

### 1.1. Placeholder integrity — bind conversation (spec §10, nâng từ S2)

Placeholder trusted flow nâng lên dạng **`[PII_{SLOT}_{n}_{tag8}]`** với
`tag8 = HMAC-SHA256(m4_slot_fp_key_b64, "ph|{conversation_ref}|{slot}|{n}")[:8 hex]`
(`app/services/pii/masking.py`). `rehydrate_response` giờ reject đủ 4 lớp spec §10:

| Tình huống | Kết quả |
|---|---|
| Placeholder bị **sửa** (tag sai format / tag giả `deadbeef` — kể cả khi mapping bị trộn theo) | None (reject) |
| Placeholder **thiếu** trong mapping (model bịa) | None |
| Placeholder **lặp** (>1 lần trong cùng candidate) | None |
| Placeholder **cross-context** (đúc từ conversation khác — tag không khớp tag tính lại cho hội thoại hiện tại) | None |

Mọi None → trusted_flow escalate (fallback 3), không đoán, không retry.
Dạng không tag `[PII_SLOT_n]` vẫn hợp lệ cho tiện ích masking đứng riêng, nhưng
**trusted flow luôn truyền `conversation_ref`** nên placeholder không tag bị reject trong flow.

### 1.2. Property/fuzz theo Directive §9

- Sweep MASK trên **toàn bộ corpus 92 case** (có dấu/không dấu/Unicode): masked text không
  chứa giá trị của bất kỳ span nào; re-detect masked text: 0 slot số (phone/nid/bank) sót.
- D2 sweep: **12/12 case D2** của corpus qua `process_turn` → escalate, model **0 call**.
- Concurrency/replay: 8 `process_turn` song song cùng (customer, conversation) với cùng
  message → không exception, outcome hợp lệ, phone dedupe 1 row, **0 row re-bind context khác**.
- Telemetry: toàn bộ stdout `[m4-*]` của phiên sweep không chứa giá trị PII nào từ corpus.
- Flag-OFF tổng: `Settings(_env_file=None)` → cả 2 flag m4 False; static check orchestrator
  không chứa `trusted_flow`/`m4_trusted_pii_path`.

## 2. Evidence

| # | Lệnh | Thời điểm | Exit | Kết quả |
|---|---|---|---|---|
| 1 | `scripts/m4_hardening_test.py` | 2026-07-28 18:24+07:00 | 0 | **RESULT: PASS 13/13** ([1] sweep 92 case, [2] integrity 5 kiểu, [3] D2 12/12, [4] concurrency/replay, [5] telemetry, [6] flag-OFF+static) |
| 2 | `pytest -q` (full) | 2026-07-28 18:26+07:00 | 0 | **183 passed** (181 + 2 test integrity mới; 1 test cũ cập nhật assertion placeholder-có-tag) |
| 3 | `scripts/m4_masked_flow_test.py` (E2E DB thật, re-run sau đổi placeholder) | 2026-07-28 18:25+07:00 | 0 | RESULT: PASS 15/15 |
| 4 | `ruff check app scripts/m4_*.py tests` | 2026-07-28 18:27+07:00 | 0 | All checks passed |
| 5 | `scripts/m3_pii_log_test.py` (static guard M3) | 2026-07-28 18:25+07:00 | 0 | ALL PASS |

## 3. Trạng thái AC development (spec §14 — phần chứng minh được trong synthetic/test)

| AC | Trạng thái development |
|---|---|
| AC-M4-02 flag OFF tương đương baseline | ✅ 183 pytest (bao trọn suite baseline), static check, defaults OFF |
| AC-M4-03 model không tạo tool call chứa PII/rehydrated placeholder | ✅ schema không có trường tool; forbidden keys; command args chỉ từ store (E2E [A]/[D]) |
| AC-M4-04 slot không ghép sai customer/conversation (concurrency/retry/replay) | ✅ UNIQUE+AAD (S1 [3][4][5]) + hardening [4] |
| AC-M4-05 placeholder mangle/cross-context reject an toàn | ✅ hardening [2] + unit tests |
| AC-M4-06 high-risk/low-confidence không qua vendor | ✅ D2 sweep 12/12 + form fallback (confidence thấp) |
| AC-M4-07 message/history/log masking đúng | ✅ E2E [A] (spy model 0 PII kể cả history), sweep [1], telemetry [5] |
| AC-M4-01/08/09 (shadow report production, canary, AI/Vendor record) | ⏳ ngoài authority development — cần Stage 0P/M4-G1/canary gate |

## 4. Known limitations

1. Tag 8 hex (32 bit) — đủ chống nhầm/trộn placeholder; không nhằm chống brute-force offline
   (giá trị thật không nằm trong tag; tag chỉ là binding marker).
2. Mapping placeholder sống per-turn trong bộ nhớ process — chưa có cross-turn placeholder
   (không cần cho thiết kế hiện tại: mỗi turn mask lại từ đầu).
3. Các known limitations S0 (detector G01-G06) và S2 (§5 doc S2) giữ nguyên, không đổi.
