# Alpha3S Phase I-B M4-S0 — Baseline Evidence + Detector Shadow (Development)

- **id:** A3S-PHASE1B-M4-S0-BASELINE-001
- **governing spec:** A3S-PHASE1B-M4-SPEC-001 v1.0.0
- **governing directive:** A3S-PHASE1B-M4-DEV-DIRECTIVE-001 v1.1.0
- **milestone/slice:** M4 (Trusted PII Path) — S0 (Dataset và shadow mode, development/synthetic)
- **ngày:** 2026-07-28 00:45+07:00
- **tác giả:** Dev (Claude Code)

## 1. Baseline verification (Directive §3)

| Hạng mục | Giá trị | Khớp directive |
|---|---|---|
| Implementation base SHA | `9b49628a83ba1fe02b97913f20f33e4883560b5b` | ✅ exact |
| Branch | `feat/phase1b-m4-trusted-pii-path` (tạo tại đúng base SHA) | ✅ |
| Migration head tại branch point | `028_products_stock_nonneg.sql` (28 file `001`–`028`) | ✅ |
| Manifest checksum (sha256 của danh sách sha256 `migrations/*.sql`) | `67a003865ea3b64fd8bc317ecbd18e541bd67303b7666ed8a52d8be9773b0ead` | — |
| Regression baseline tại base SHA (trước khi sửa) | `pytest -q` → **81 passed**, exit 0 | ✅ |

**Ghi chú môi trường quan trọng:** tại thời điểm bắt đầu M4, workstream M3 đang phát triển
**đồng thời** trên cùng máy, cùng thư mục `D:\alpha3s` (branch
`feat/phase1b-m3-compliance-sensor-foundations`, đã thấy `migrations/029_order_delivered.sql`
uncommitted trong tree M3). Để 2 workstream độc lập đúng Directive §13, M4 được tách ra
**git worktree riêng `D:\alpha3s-m4`** trỏ vào branch M4 tại exact base SHA; mọi test M4 chạy
trong container riêng `alpha3s-m4-test` (image `alpha3s-api`, mount `D:\alpha3s-m4:/srv`),
KHÔNG đụng container/dữ liệu đang chạy của tree chính.

→ **Xác nhận trực quan xung đột migration `029` mà Directive §3 tiên liệu**: M3 đã dùng
`029_order_delivered.sql` (chưa commit tại thời điểm quan sát). Workstream merge sau sẽ
renumber theo migration head thực tế tại integration re-baseline (Directive §11). M4-S0
**không tạo migration nào** nên chưa đụng số 029.

## 2. Phạm vi S0 đã giao (Directive §4 M4-S0)

| Thành phần | File | Ghi chú |
|---|---|---|
| Taxonomy slot/confidence/risk/reason/failure | `app/services/pii/taxonomy.py` | `DETECTOR_VERSION = m4d-0.1.0` |
| Chuẩn hóa offset-preserving | `app/services/pii/normalize.py` | fold dấu CẢ HAI PHÍA, giữ ánh xạ offset 1:1 |
| Detector PII cục bộ | `app/services/pii/detector.py` | regex/rule thuần, KHÔNG model, KHÔNG vendor, KHÔNG I/O |
| Shadow wrapper + metric PII-safe | `app/services/pii/shadow.py` | containment lỗi; emit `[m4-shadow]` JSON chỉ counts/enum |
| Hook orchestrator | `app/services/orchestrator.py` (bước -0.5) | chỉ chạy khi `settings.m4_pii_shadow`; không đổi flow |
| Feature flags | `app/config.py`, `.env.example` | `m4_pii_shadow=OFF`, `m4_trusted_pii_path=OFF` (placeholder, không code path) |
| Synthetic corpus + generator | `datasets/pii/synthetic_corpus_v1.jsonl`, `scripts/m4_gen_synthetic_corpus.py` | 92 case (86 gate / 6 known-limit), deterministic |
| Unit tests | `tests/test_m4_pii_detector.py`, `tests/test_m4_pii_shadow.py` | 51 test mới, thuần logic |
| Evidence script | `scripts/m4_pii_shadow_test.py` | recall/precision/risk/latency/no-PII/containment/flag-OFF |

**No schema/migration delta:** S0 không thêm/sửa file nào trong `migrations/` (manifest ở §1
không đổi trước/sau S0). Không đổi model/tool/vendor flow: hook shadow là call-site duy nhất,
sau flag check, trước các guard deterministic, không chạm `turn_messages`/LLM call.

## 3. Detection protocol (spec §6, Directive §4/§7)

**Slots:** `phone`, `name`, `address`, `national_id` (CMND/CCCD), `bank_account` (STK).
**Sensitive categories (classification, không phải slot):** `health`, `identity_doc`, `finance`.
**Risk class:** `D0` (không PII) / `D1` (PII cơ bản) / `D2` (sensitive hoặc slot high-risk
`national_id`/`bank_account`) — D2 map vào `vendor_would_block=true` trong metric (spec §5.6
default-deny vendor path khi enforcement; S0 chỉ đo).

**Confidence:** `high` (0.9) / `medium` (0.7) / `low` (0.4) — gán theo reason code
(`taxonomy.ReasonCode`), ví dụ: prefix di động VN hợp lệ = high; dãy 9–11 số chỉ có cue liên
hệ = low; cue + họ VN = high; cụm ≥2 thành phần địa chỉ = high; số nhà + đường đơn lẻ = medium.

**Nguyên tắc tiếng Việt (CLAUDE.md §6 — lớp bug tái phát nhiều nhất của dự án):**
- Fold dấu ở CẢ HAI PHÍA (văn bản + từ điển), fold theo từng ký tự trên bản NFC → offset 1:1.
- Ranh giới từ `\b` cho mọi so khớp keyword.
- Chống đồng âm sau fold đã xử lý cụ thể: `quận↔quán`, `xã↔xa`, `phường↔phương` (từ khóa hành
  chính chỉ là thành phần "mạnh" khi theo sau là chữ số/chữ hoa; dạng thường không dấu thành
  "admin_weak" — chỉ nối cluster, không quyết định multi); `phố↔phở` (1 thành phần đơn lẻ không
  bao giờ tạo span); "TP/thành phố + tên tỉnh" gộp làm MỘT địa danh (không phải 2 thành phần);
  test có cả cặp bẫy `chua/chưa`, `ly/lý`, `hong/khong`.

**An toàn PII trong chính detector:** `PIISpan` CHỈ lưu offset + enum (không plaintext);
metric shadow chỉ counts/max-confidence/risk/latency/text_len; dòng lỗi chỉ chứa tên class
exception (không `str(e)` vì message có thể chứa mảnh văn bản khách).

## 4. Corpus datasheet (Directive §9 — datasheet + generation provenance)

- **File:** `datasets/pii/synthetic_corpus_v1.jsonl` — 92 case: A phone (21), B name (15),
  C address (13), D combo đơn hàng (5), E sensitive/high-risk (12), F negative/bẫy đồng âm (20),
  G known-limitation `gate=false` (6).
- **Provenance:** 100% tổng hợp tay bởi Dev trong M4-S0 (template + giá trị BỊA: SĐT/tên/địa
  chỉ/CCCD/STK đều tự chế). KHÔNG dữ liệu production, KHÔNG hội thoại thật, KHÔNG PII người
  thật. Generator `scripts/m4_gen_synthetic_corpus.py` deterministic (không random) — corpus
  tái sinh identical, provenance = chính script + git history.
- **Labeling:** nhãn `expect` (số instance theo slot) + `risk` do Dev gán khi soạn case và
  review lại bằng eval loop. Chưa có labeled sample từ traffic thật — restricted zone/access
  matrix/retention cho production shadow sẽ nộp theo Directive §6 TRƯỚC khi xin Stage 0P.
- **Trường `gate`:** `false` = case khó đã biết (kỳ vọng detector v0.1 MISS) — báo cáo riêng
  trong failure taxonomy, KHÔNG tính vào recall/precision gate, KHÔNG bị xóa để làm đẹp số.
- **Variant:** mỗi nhóm có cả `dau` / `khong_dau` (và `digits`) đúng quy trình test 2 chiều.

## 5. Evidence (môi trường: container `alpha3s-m4-test`, image `alpha3s-api`, mount `D:\alpha3s-m4:/srv`)

| # | Lệnh | Thời điểm | Exit | Kết quả |
|---|---|---|---|---|
| 1 | `docker exec alpha3s-m4-test python -m pytest -q` (tại base, TRƯỚC khi sửa) | 2026-07-28 00:21+07:00 | 0 | 81 passed (baseline) |
| 2 | `docker exec alpha3s-m4-test python scripts/m4_gen_synthetic_corpus.py` | 2026-07-28 00:33+07:00 | 0 | wrote 92 cases (86 gate, 6 known-limit) |
| 3 | `docker exec alpha3s-m4-test python scripts/m4_pii_shadow_test.py` | 2026-07-28 00:44+07:00 | 0 | RESULT: PASS (chi tiết dưới) |
| 4 | `docker exec alpha3s-m4-test python -m pytest -q` (SAU S0) | 2026-07-28 00:41+07:00 | 0 | **132 passed** (81 cũ + 51 mới, flag OFF mặc định) |
| 5 | `docker exec alpha3s-m4-test python -m ruff check app scripts/m4_*.py tests` | 2026-07-28 00:44+07:00 | 0 | clean |

**Kết quả eval synthetic (lệnh 3, gate cases, instance-level):**

| Slot | Recall | Precision | Ngưỡng recall (Directive §7) |
|---|---:|---:|---:|
| phone | 100% (27/27) | 100% | ≥ 99% ✅ |
| name | 100% (21/21) | 100% | ≥ 90% ✅ |
| address | 100% (19/19) | 100% | ≥ 95% ✅ |
| national_id | 100% (2/2) | 100% | — |
| bank_account | 100% (2/2) | 100% | — |

Risk class: mọi case D2 → D2, mọi case D0 → D0 (0 sai). Latency `detect()`:
p50 ≈ 0.23ms, p95 ≈ 1.2ms (ngưỡng dev < 20ms). Metric output: không chứa giá trị PII đã gieo,
không dãy ≥7 chữ số. Containment: detector raise → `shadow_scan` trả None + emit
`m4_shadow_error` chỉ có `error_type`. Flag OFF: không scan, không output, 81 test baseline
không đổi hành vi.

**⚠️ Caveat trung thực (bắt buộc đọc trước M4-G1):** 100% recall trên synthetic KHÔNG phải
bằng chứng đạt gate. Corpus được thiết kế cùng detector (cùng tác giả) nên số này chỉ chứng
minh *protocol đo hoạt động và detector xử lý đúng các dạng đã liệt kê*. Recall/precision
THẬT phải đo trên production shadow data (Stage 0P, sample 14 ngày / 200 hội thoại) sau khi
có approval theo Directive §6 — không suy diễn từ bảng trên.

## 6. Failure taxonomy — known limitations v0.1 (gate=false, kỳ vọng miss)

| ID | Dạng | Kết quả | Hướng nếu tần suất thật đáng kể |
|---|---|---|---|
| G01 | Phone đọc bằng chữ ("không chín một hai…") | MISS (kỳ vọng) | từ điển số-bằng-chữ |
| G02 | Tên thường không dấu, không cue mạnh ("goi cho hoa nhe") | MISS (kỳ vọng) | cần context/NER — không ép bằng rule (tăng FP) |
| G03 | Phone tách rời nhiều cụm cách xa | MISS (kỳ vọng) | ghép digit-run xuyên câu (rủi ro FP cao) |
| G04 | Phone chèn emoji giữa cụm số | MISS (kỳ vọng) | mở rộng separator class |
| G05 | Địa chỉ mô tả lời nói ("hẻm thứ hai bên trái…") | MISS (kỳ vọng) | structured form (spec §9 fallback 2) |
| G06 | Tên gọi miền Tây không họ ("tui ten Ut Nho") | DETECTED (vượt kỳ vọng) | — |

Ngoài ra (không có case trong corpus, ghi nhận thiết kế): detector không đọc PII trong ảnh/
sticker; không phát hiện PII của bên thứ ba nhắc gián tiếp không cue; "đt" cue dễ nhiễu.

## 7. Flag semantics (Directive §8)

- `m4_pii_shadow=false` mặc định; **missing config = OFF** (pydantic default, có test).
- OFF = không call path nào chạy (orchestrator check flag trước khi gọi) — tương đương baseline
  (evidence: 81 test cũ pass nguyên trạng, flag-OFF test khẳng định không output).
- `m4_trusted_pii_path` tồn tại như placeholder default OFF, **không có active code path**.
- Detector exception contained trong `shadow_scan`; guard permission/security/logging hiện có
  không phụ thuộc flag M4.

## 8. Bước tiếp theo

1. **M4-S1** Trusted Slot Store: schema + migration (số provisional `029` — biết trước đụng M3,
   xử lý renumber tại integration re-baseline §11), repository, isolation, encryption boundary,
   least-privilege role, retry/replay guards — synthetic fixtures.
2. **M4-S2** masked orchestration + schema-bounded output + 3 fallback (mock external model).
3. **M4-S3** hardening (placeholder integrity, cross-context reject, telemetry redaction).
4. Delivery Package hợp nhất `docs/PHASE1B-M4-DEV-DELIVERY-PACKAGE-VI.md` khi S0..S3 đủ evidence.
