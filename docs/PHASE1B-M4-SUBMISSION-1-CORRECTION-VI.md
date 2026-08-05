# Alpha3S Phase I-B M4 — Submission 1 Correction Package

- **id:** A3S-PHASE1B-M4-SUBMISSION-1-CORRECTION-001
- **đáp lại:** `A3S-PHASE1B-M4-CA-SUBMISSION-1-REVIEW` (CHANGES_REQUIRED, 4 finding P1 + metadata)
- **governing spec:** A3S-PHASE1B-M4-SPEC-001 **v1.1.0** (metadata correction — xem §3)
- **governing directive:** A3S-PHASE1B-M4-DEV-DIRECTIVE-001 v1.1.0
- **ngày:** 2026-07-28 20:10+07:00

## 1. Heads (điều kiện re-review #2)

```text
Evidence head cũ (bị review): e43bb9e86f64b1873f1da5873dc16d307b014f70
Package head cũ:              967b3125c28eab8acc7bc844e225ff8072cf60aa
Correction/evidence head MỚI: 766c69b77a241512b7306123c775272353ba9821
CI run head mới:              30361588502 — completed / success
Branch:                       feat/phase1b-m4-trusted-pii-path (PR #4 DRAFT, không merge)
Delta:                        967b312..766c69b = 1 commit code/test (10 file, +240/−23)
Flags:                        m4_* vẫn OFF; không vendor call; không production data; không deploy
```

Changed files trong delta: `app/services/pii/{crypto,masking,semantic_schema,trusted_flow}.py`,
`migrations/038_m4_slot_store.sql`, `scripts/{m4_masked_flow_test,m4_slot_store_test}.py`,
`tests/{test_m4_slot_crypto,test_m4_masking_schema,test_m4_trusted_flow}.py`.

## 2. Mapping finding → correction → adversarial test (điều kiện #1, #4)

### F-M4-S1-01 — AAD collision → FIXED

- `crypto.py`: AAD **v2 canonical**: domain-tag `a3s-m4-slot-aad-v2` + **length-prefix (4-byte BE)**
  từng field — không tồn tại 2 bộ (customer, conversation, slot_type) khác nhau cho cùng byte AAD.
  Blob version bump `v1`→`v2` (byte đầu blob); blob v1 bị từ chối (không có dữ liệu v1 — dev-only,
  bảng trống, đã ghi rõ trong code). Ref validation (correction 4): non-empty, ≤128 byte UTF-8,
  không control char — vi phạm → `SlotCryptoError` fail-closed.
- Adversarial tests: `TestAADCanonical` (test_m4_slot_crypto.py) — collision `("a|b","c")` ↔
  `("a","b|c")` cả 2 chiều phải `SlotBindingError`; ref rỗng/dài/NUL/newline fail-closed; blob v1
  bị từ chối. Row-transplant trên DB thật: `m4_slot_store_test.py` [3] (giữ nguyên, re-run PASS).

### F-M4-S3-02 — Placeholder namespace collision history/current → FIXED

- `masking.py`/`trusted_flow.py`: **MỘT namespace `counters` duy nhất** cho history + current
  (mask_history nhận counters, current mask tiếp cùng dict) → placeholder không bao giờ trùng
  trong cùng payload. Guard phòng thủ sâu: nếu mapping key collision vẫn xảy ra →
  `escalate("placeholder_collision")` fail-closed (correction 2).
- Regression test (correction 3): `test_history_current_placeholder_khong_va_cham` — history phone
  A + current phone B, echo placeholder history → rehydrate ra **A** (không bị B ghi đè), echo
  placeholder current → **B**; model thấy 2 placeholder khác nhau.

### F-M4-S3-03 — D2 trong history lọt vendor → FIXED

- `trusted_flow.py`: sweep `detect().risk_class` **từng history turn** trước `model_call`.
  **Policy fail-closed đã chọn (trình CA duyệt): minimize** — turn D2 bị thay TOÀN BỘ nội dung
  bằng marker `[TURN_REDACTED_D2]` (không đến vendor; hội thoại vẫn tiếp tục — D2 cũ không chặn
  vĩnh viễn conversation; current-turn D2 vẫn escalate như cũ). Telemetry
  `m4_flow_history_d2_redacted` chỉ count (correction 4).
- Tests (correction 3): `test_history_d2_bi_redact_truoc_vendor` (history D2 health không có
  slot số + current D0 → model được gọi, payload KHÔNG chứa nội dung D2, chứa marker, turn sạch
  giữ nguyên) + E2E DB thật `m4_masked_flow_test.py` case d6.

### F-M4-S2-04 — Smuggle PII qua `sku` → FIXED

- `semantic_schema.py`: (1) **SKU grammar** `^(?=.*[A-Z])[A-Z0-9][A-Z0-9-]{1,19}$` — bắt buộc
  ≥1 chữ cái ⇒ dãy số thuần (phone/CCCD/STK) không bao giờ qua; (2) **không phân loại theo tên
  key**: mọi string leaf được phép vào command context bị quét thêm `_leaf_is_clean` = detector
  + placeholder-pattern + digit-run ≥7 (sau khi bỏ separator); vi phạm → `sku_invalid` →
  schema violation → escalate, executor không chạy. Resolve qua trusted catalog: ghi nhận là
  integration item sau M4-G1 (module S2 standalone chưa chạm catalog) — grammar + scan đáp ứng
  correction 1-3 ở tầng schema.
- Adversarial tests (correction 4): pytest parametrize sku = phone/CCCD/STK/`0912-345-678`/
  placeholder/lowercase/khoảng trắng/quá ngắn → đều violation; sku hợp lệ `3S-500G` v.v. qua
  được; `test_sku_smuggle_qua_flow_bi_escalate` (executor 0 call); E2E DB thật case d5.

### Phát hiện thêm trong quá trình sửa (khai báo)

Tag placeholder 8-hex có xác suất ~2%/tag ra toàn chữ số → đứng cạnh cue ("STK [PII_…]") bị
chính detector re-detect nhầm là bank account (bắt được nhờ chạy lặp hardening sweep). Sửa tận
gốc: ký tự đầu tag luôn là chữ cái a–f (suy deterministic từ hex đầu HMAC) — placeholder không
bao giờ tạo digit-run. Hardening sweep chạy 3 lần liên tiếp PASS (không còn flaky).

## 3. Metadata correction

1. **Governing spec version:** package v1.0.0 ghi spec v1.0.0 do đọc file trước thời điểm CA
   reissue (spec cập nhật v1.1.0 lúc 00:18 — sau khi Dev đọc lúc 00:17). Toàn bộ hồ sơ từ
   correction này chuẩn theo **spec v1.1.0**; Dev đã đối chiếu spec v1.1.0 — không có thay đổi
   scope development S0..S3 ảnh hưởng deliverable đã nộp (nếu CA thấy khác, Dev sẽ xử lý trong
   re-review).
2. **purpose_code canonical:** `P02` → **`P02_COMMERCE`** (đúng `docs/PROCESSING-PURPOSE-REGISTRY.md`):
   CHECK migration 038 đổi thành `^P[0-9]{2}_[A-Z][A-Z_]{1,40}$`, code (`trusted_flow`),
   evidence script, COMMENT bảng — đồng bộ cả 4 nơi.

## 4. Evidence tại head mới `766c69b` (điều kiện #3, #5)

Môi trường: container `alpha3s-m4-test` + DB riêng `alpha3s-m4-db` **RECREATE FRESH** (vì 038
đổi CHECK). Toàn bộ 28/7:

| # | Lệnh | Giờ | Exit | Kết quả |
|---|---|---|---|---|
| 1 | `migrate.py up` DB fresh | 19:56 | 0 | 38 migrations, validations M0+M3 PASS, postcondition 038 PASS |
| 2 | `migrate.py up` lần 2 (idempotent) | 19:57 | 0 | no pending, validations PASS |
| 3 | existing-apply: DB2 @037+data → apply đúng 1 migration 038 | 19:58 | 0 | data intact, schema_migrations=38 |
| 4 | `m4_slot_store_test.py` | 19:59 | 0 | 20/20 PASS |
| 5 | `m4_masked_flow_test.py` (E2E + d5 sku-smuggle + d6 D2-history) | 20:03 | 0 | 17/17 PASS |
| 6 | `m4_pii_shadow_test.py` | 19:59 | 0 | PASS |
| 7 | `m4_hardening_test.py` **×3 liên tiếp** | 20:03 | 0 | 13/13 PASS cả 3 lần |
| 8 | `pytest -q` | 20:04 | 0 | **204 passed** (183 + 21 adversarial mới) |
| 9 | `ruff check app scripts/m4_*.py tests` | 20:04 | 0 | clean |
| 10 | `m3_pii_log_test.py` (regression M3 static guard) | 20:00 | 0 | ALL PASS |
| 11 | CI GitHub Actions head `766c69b` | 20:09 | — | run `30361588502` completed/**success** (regression M1/M2/M3/M4: pytest full + ruff trong CI) |

Điều kiện #6 giữ nguyên: flags OFF (default, test khẳng định), không vendor call (model
mock/callable — static test + spy), không production data (corpus synthetic), PR #4 draft.

## 5. Đề nghị

CA re-review Submission 1 với 4 finding mapped ở §2, metadata §3, evidence §4. Không thay đổi
scope; không xin thêm quyền.
