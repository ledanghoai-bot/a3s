# Alpha3S Phase I-B M4 — Submission 3 (Final Closure)

- **id:** A3S-PHASE1B-M4-SUBMISSION-3-FINAL-001
- **đáp lại:** `A3S-PHASE1B-M4-CA-SUBMISSION-2-REVIEW` (PARTIAL_PASS — F-M4-S1-01/S3-02/S3-03
  CLOSED; **F-M4-S2-04 REMAINS OPEN** + stale comments)
- **governing spec/directive:** A3S-PHASE1B-M4-SPEC-001 v1.1.0 / DEV-DIRECTIVE-001 v1.1.0
- **ngày:** 2026-07-28 20:40+07:00
- **tính chất:** Final Closure theo CA-GOVERNANCE-001 — CHỈ correction cho finding còn mở +
  documentation; KHÔNG feature/scope mới.

## 1. Heads (điều kiện #1)

```text
Submission 2 heads:            766c69b77a241512b7306123c775272353ba9821 (evidence) /
                               b243f04b60ca91ee6a7fec4dfd079bf1a2a50b67 (package)
Submission 3 evidence head:    5fee922e8f0726b94627be942caf294087174edb
CI tại head mới:               run 30364083661 — completed / success
Delta b243f04..5fee922:        1 commit code/test (8 file, +229/−14):
  A app/services/pii/sku_catalog.py        A tests/test_m4_sku_catalog.py
  M app/services/pii/trusted_flow.py       M tests/test_m4_trusted_flow.py
  M app/services/pii/crypto.py (comment)   M migrations/038_m4_slot_store.sql (comment)
  M scripts/m4_masked_flow_test.py         M scripts/m4_hardening_test.py
Branch: feat/phase1b-m4-trusted-pii-path — PR #4 DRAFT, không merge/deploy.
Flags:  m4_* OFF; no vendor call; no production data (điều kiện #6).
```

## 2. F-M4-S2-04 — correction cuối (điều kiện #2)

**Nguyên tắc mới: SKU authority = trusted catalog, không phải model.**

1. **`app/services/pii/sku_catalog.py`** — trusted resolver trên bảng `products` (catalog thật):
   normalize (upper + bỏ ký tự ngoài A-Z0-9) → map về **canonical SKU của catalog**; alias
   ("3S100G") về canonical ("3S-100G"); **unknown/ambiguous → None** (2 canonical trùng khóa
   normalize = ambiguous, fail closed); lỗi DB → raise. Không log raw model string (chỉ count).
2. **`trusted_flow.py`**: mọi model-proposed SKU resolve qua resolver **trước command assembly**;
   `command_args["items"]` **chỉ nhận canonical string do resolver trả về — không bao giờ copy
   raw model string** (correction 2). Unknown → deterministic fallback hỏi lại sản phẩm,
   **không echo** chuỗi raw (có thể là PII transliterate); resolver lỗi/unavailable →
   escalate `catalog_error`. Executor **không chạy** trong mọi nhánh trên (correction 3).
   Resolver inject được (`sku_resolver` param) — mock trong dev test, mặc định catalog DB.

**Adversarial tests (correction 4, đủ danh sách CA):**

| Yêu cầu CA | Test | Kết quả |
|---|---|---|
| alias/canonical → canonical catalog SKU | `test_sku_alias_resolve_ve_canonical` + unit `test_exact_va_alias_ve_canonical` + **E2E d7 catalog THẬT** (`3S100G` → executor nhận `3S-100G`) | PASS |
| `12-LE-LOI` reject | `test_sku_dang_dia_chi_ten_bi_tu_choi[12-LE-LOI]` + E2E d8 | PASS — fail closed |
| `NGUYEN-VAN-AN` reject | `test_sku_dang_dia_chi_ten_bi_tu_choi[NGUYEN-VAN-AN]` | PASS — fail closed |
| numeric/placeholder tiếp tục reject | giữ nguyên parametrize S2 (phone/CCCD/STK/placeholder) + E2E d5 | PASS |
| resolver error/unavailable → fail closed | `test_catalog_loi_fail_closed` (escalate, executor 0) | PASS |
| executor chỉ nhận canonical | assertion trong alias tests + E2E d7 | PASS |
| ambiguous | unit `test_ambiguous_fail_closed` (2 canonical cùng khóa normalize → None) | PASS |

**Khai báo minh bạch (defense in depth):** 2 chuỗi `12-LE-LOI`/`NGUYEN-VAN-AN` thực tế bị chặn
**sớm hơn dự kiến** ở tầng schema (detector nhận ra dạng địa chỉ/tên trong string leaf →
`sku_invalid` → escalate) — chưa cần tới catalog. Đúng lo ngại của CA rằng detector là heuristic,
nên đã thêm case `SO-12-P5-Q3` (qua được schema scan) chứng minh **tầng catalog là authority
cuối**: unknown → fallback, executor 0 call (`test_sku_qua_schema_nhung_khong_thuoc_catalog` +
E2E d9 trên catalog thật). Kết quả: chuỗi lạ chết ở tầng schema HOẶC tầng catalog — không đường
nào cho raw model string vào command args.

## 3. Stale comments + metadata (điều kiện #5)

- `crypto.py` docstring: mô tả AAD delimiter cũ → viết lại theo AAD v2 canonical length-prefix.
- `migrations/038` header + `COMMENT ON COLUMN encrypted_value`: `v1||nonce` / AAD delimiter →
  blob `v2`, AAD v2 domain-tag + length-prefix. (Comment-only nhưng checksum đổi → re-run đủ
  fresh/existing/idempotent, xem §4.)
- Package này chuẩn theo spec v1.1.0 (đã chuẩn hóa từ correction trước).

## 4. Evidence tại head `5fee922` (điều kiện #3, #4 — 28/7)

| # | Lệnh | Giờ | Exit | Kết quả |
|---|---|---|---|---|
| 1 | `migrate.py up` DB **recreate fresh** | 20:29 | 0 | 38 migrations, validations M0+M3 PASS |
| 2 | `migrate.py up` lần 2 (idempotent) | 20:29 | 0 | no pending, validations PASS |
| 3 | existing-apply DB2 @037+data → đúng 1 migration 038 | 20:30 | 0 | data intact, schema_migrations=38 |
| 4 | `m4_slot_store_test.py` | 20:31 | 0 | 20/20 PASS |
| 5 | `m4_masked_flow_test.py` (E2E 19 check, +d7/d8/d9 catalog thật) | 20:31 | 0 | RESULT: PASS |
| 6 | `m4_pii_shadow_test.py` | 20:31 | 0 | PASS |
| 7 | `m4_hardening_test.py` ×3 | 20:32 | 0 | 13/13 PASS cả 3 lần |
| 8 | `pytest -q` | 20:28 | 0 | **214 passed** (204 + 10 mới: sku_catalog 4 + flow 6) |
| 9 | `ruff check app scripts/m4_*.py tests` | 20:33 | 0 | clean |
| 10 | `m3_pii_log_test.py` (static guard M3) | 20:33 | 0 | ALL PASS |
| 11 | CI GitHub Actions head `5fee922` | 20:44 | — | run `30364083661` completed/**success** |

## 5. Trạng thái finding tổng

| Finding | S1 | S2 | S3 |
|---|---|---|---|
| F-M4-S1-01 AAD collision | OPEN | **CLOSED** (CA xác nhận) | — |
| F-M4-S3-02 placeholder namespace | OPEN | **CLOSED** (CA xác nhận) | — |
| F-M4-S3-03 D2 history | OPEN | **CLOSED** (CA xác nhận) | — |
| F-M4-S2-04 SKU smuggle | OPEN | partial | **correction đủ 4 mục — đề nghị CLOSE** |
| Stale AAD comments | — | ghi nhận | **đã dọn** |

Đề nghị CA đóng F-M4-S2-04 và ra quyết định acceptance cho M4 development S0..S3
(Submission 1 → 3 theo đúng giới hạn CA-GOVERNANCE-001).
