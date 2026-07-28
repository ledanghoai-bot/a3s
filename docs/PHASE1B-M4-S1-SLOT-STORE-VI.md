# Alpha3S Phase I-B M4-S1 — Trusted Slot Store (Development)

- **id:** A3S-PHASE1B-M4-S1-SLOT-STORE-001
- **governing spec:** A3S-PHASE1B-M4-SPEC-001 v1.0.0 §8
- **governing directive:** A3S-PHASE1B-M4-DEV-DIRECTIVE-001 v1.1.0 §4 (M4-S1 AUTHORIZED)
- **ngày:** 2026-07-28 07:25+07:00
- **tiếp nối:** `PHASE1B-M4-S0-BASELINE-VI.md` (S0 evidence + worktree/DB riêng của M4)

## 1. Thành phần đã giao

| Thành phần | File | Ghi chú |
|---|---|---|
| Migration Slot Store | `migrations/040_m4_slot_store.sql` | **SỐ 040 PROVISIONAL** (xem §4) — expand-only, transactional, postcondition fail-closed |
| Crypto AES-256-GCM + AAD binding | `app/services/pii/crypto.py` | khóa từ settings; thiếu khóa = fail closed; exception không plaintext |
| Repository | `app/services/pii/slot_store.py` | nhận `conn` (convention M1); store/resolve/purge; log `[m4-slot]` counts-only |
| Config | `app/config.py` | `m4_slot_key_b64`, `m4_slot_fp_key_b64` (base64 32B, rỗng mặc định), `m4_slot_ttl_hours=24` |
| Dependency mới | `requirements.txt` | `cryptography>=42` — **image production cần rebuild tại release** (đã cài trong container test M4) |
| Unit tests (pure) | `tests/test_m4_slot_crypto.py` | 15 test: roundtrip, AAD 3 chiều, tamper, thiếu khóa, fingerprint |
| Evidence script (DB) | `scripts/m4_slot_store_test.py` | 20 check trên DB riêng `alpha3s-m4-db` |

Slot Store trong S1 là **mã nằm im (dormant)**: chưa có call site nào trong runtime path
(orchestrator/tools không import `slot_store`); chỉ S2 masked orchestration mới nối vào sau
schema-bounded output. Flag OFF = baseline nguyên trạng (147 pytest pass, không đổi hành vi).

## 2. Ánh xạ yêu cầu spec §8 → cơ chế

| Yêu cầu spec §8 | Cơ chế |
|---|---|
| Schema 13 trường | `pii_slots` đủ 13 trường + CHECK slot_type/confidence/data_class/purpose/fingerprint-hex/expiry-sau-capture |
| customer/conversation isolation enforced | (1) mọi query filter đủ (customer_ref, conversation_ref); (2) **AAD của AES-GCM = customer_ref\|conversation_ref\|slot_type** → dù query/bug/tamper đưa row sang context khác, giá trị KHÔNG THỂ giải mã — fail closed tại tầng crypto |
| Encryption at rest | mã hóa Ở TẦNG APP trước khi chạm DB (blob `v1‖nonce‖ct+tag`); DB không bao giờ thấy plaintext; evidence [8] quét dump không có giá trị gieo |
| Encryption in transit | dev: network nội bộ Docker; production: DB cùng host/VPC — ghi nhận **environment control tại release gate** (không phải code S1) |
| Short retention có policy | `expires_at` NOT NULL, TTL config 24h; `purge_expired` DELETE + đếm counts-only; row bất biến (không UPDATE) |
| Source provenance + detector version | `source_message_ref` (chỉ mã tham chiếu), `detector_version` bắt buộc |
| Runtime role external-model path không đọc table | External model (DeepSeek) vốn không có credential DB. Thêm chốt chặn: role `alpha3s_vendor_path` (NOLOGIN, đại diện mọi thành phần vendor-path có credential trong tương lai) bị REVOKE ALL — postcondition 040 + evidence [9] chứng minh DENY. Runtime `alpha3s_app`: INSERT/SELECT/DELETE, **KHÔNG UPDATE** |
| Fingerprint không dùng làm public identifier | HMAC-SHA256 **có khóa riêng** (`m4_slot_fp_key_b64`, tách khỏi khóa mã hóa), cắt 32 hex — không suy ngược/đối chiếu được nếu không có khóa; không log fingerprint |
| Retry/replay/idempotency không bind slot sang context khác | UNIQUE (context, slot_type, fingerprint) + `ON CONFLICT DO NOTHING`: replay cùng context → dedupe cùng slot_id; cùng giá trị KHÁC context → row riêng (evidence [4], [5] concurrency 5-way → 1 row) |
| Address/sensitive slot không vào semantic history | thuộc S2 (masked orchestration) — ghi nhận, chưa claim |

## 3. Evidence (container `alpha3s-m4-test` + DB riêng `alpha3s-m4-db` [pgvector/pgvector:pg16], network `m4net`)

| # | Lệnh | Thời điểm | Exit | Kết quả |
|---|---|---|---|---|
| 1 | `docker exec -e DATABASE_URL=postgresql://alpha3s:***@alpha3s-m4-db:5432/alpha3s alpha3s-m4-test python scripts/migrate.py up` (DB FRESH) | 2026-07-28 07:18+07:00 | 0 | Applied **29 migration** (001→028 + 040), postcondition 040 PASS, `fresh_db_seed_validation.sql` PASS |
| 2 | như trên, chạy LẦN 2 (idempotent) | 2026-07-28 07:20+07:00 | 0 | "Khong co migration pending" + validations PASS |
| 3 | `... python scripts/m4_slot_store_test.py` | 2026-07-28 07:25+07:00 | 0 | **RESULT: PASS — 20/20** ([1] roundtrip, [2] isolation, [3] tamper→None+alert P1, [4] replay/dedupe + khác-context=row-riêng, [5] concurrency, [6] expiry+purge, [7] min-confidence, [8] no-plaintext-at-rest, [9] role DENY, [10] log không PII) |
| 4 | `docker exec alpha3s-m4-test python -m pytest -q` | 2026-07-28 07:23+07:00 | 0 | **147 passed** (81 baseline + 51 S0 + 15 S1) |
| 5 | `docker exec alpha3s-m4-test python -m ruff check app scripts/m4_*.py tests` | 2026-07-28 07:25+07:00 | 0 | All checks passed |

Ghi chú quá trình: lần chạy đầu evidence script tự vấp CHECK `pii_slots_expiry_after_capture`
khi mô phỏng hết hạn (UPDATE chỉ expires_at về quá khứ) — chứng minh ngoài dự kiến rằng
constraint hoạt động; script sửa lại lùi cả `captured_at` lẫn `expires_at`. DETAIL của lỗi
CHECK chỉ hiển thị ciphertext hex + fingerprint, không plaintext (đúng thiết kế at-rest).

## 4. Migration numbering & re-baseline (Directive §3/§11)

- Directive cho provisional `029`, nhưng thực tế M3 (workstream song song) đã dùng `029`–`033`.
  M4-S1 lấy **`040` provisional** để 2 workstream không giẫm nhau trong development.
- Tại **integration re-baseline** (trước merge review): renumber theo migration head thực tế,
  chạy lại checksum/migration/regression evidence, ghi pre/post-rebase SHA. **Existing-apply
  rehearsal** (apply 040 lên DB có sẵn data 001–028) thực hiện tại thời điểm đó với số cuối
  cùng — 040 là expand-only (CREATE TABLE mới + role) nên fresh + idempotent re-run là evidence
  chính của S1; đây là known limitation khai báo, không phải bỏ sót.

## 5. Known limitations / open items

1. `cryptography>=42` là dependency mới — production image phải rebuild tại release (khai báo
   để CA/PO thấy; không deploy trong authority hiện tại).
2. Key management: khóa AES/HMAC là env secret (chưa có KMS/rotation) — đủ cho development;
   rotation policy là release-gate item.
3. Encryption in transit tới DB: environment control (localhost/VPC), không phải code S1.
4. Existing-apply rehearsal với số migration cuối cùng: thực hiện tại integration re-baseline (§4).
5. Slot Store chưa có caller — S2 sẽ nối resolve→trusted command assembly với allowlist slot type.

## 6. Bước tiếp theo

M4-S2: masked orchestration — mask message/history trước vendor (mock), schema-bounded model
output, trusted slot resolution (allowlist), trusted command assembly, 3 fallback
(deterministic prompt → structured form → local/human), flag `m4_trusted_pii_path` vẫn OFF.
