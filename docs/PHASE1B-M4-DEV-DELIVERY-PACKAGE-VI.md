# Alpha3S Phase I-B M4 — Development Delivery Package (Submission 1)

- **id:** A3S-PHASE1B-M4-DEV-DELIVERY-PACKAGE-001
- **version:** 1.0.0 — Initial Delivery (lần nộp 1/≤3 theo CA-GOVERNANCE-001)
- **governing spec:** A3S-PHASE1B-M4-SPEC-001 v1.0.0
- **governing directive:** A3S-PHASE1B-M4-DEV-DIRECTIVE-001 v1.1.0
- **ngày:** 2026-07-28 18:35+07:00
- **phạm vi chứng minh:** M4-S0..S3 trong môi trường synthetic/test (đúng Directive §10 —
  KHÔNG xin M4-G1 vì chưa có production shadow data; xem Phần 7 về Stage 0P)

---

## Phần 1 — Delivery Report (đã làm / chưa làm / sai khác plan)

**Đã làm (đủ scope authorized S0..S3):**

| Slice | Nội dung | Hồ sơ chi tiết |
|---|---|---|
| S0 | Detector PII cục bộ (phone/name/address/cccd/stk + sensitive D2), taxonomy m4d-0.1.0, shadow hook sau flag `m4_pii_shadow` (OFF), corpus synthetic 92 case + generator deterministic, eval protocol | `PHASE1B-M4-S0-BASELINE-VI.md` |
| S1 | Trusted Slot Store: migration **038** `pii_slots`, crypto AES-256-GCM AAD-binding, fingerprint HMAC keyed, role least-priv (`alpha3s_vendor_path` DENY ALL, `alpha3s_app` no-UPDATE), repository store/resolve/purge | `PHASE1B-M4-S1-SLOT-STORE-VI.md` |
| Re-baseline §11 | Rebase lên `main@dc839ca` (M2+M3), renumber 040→038, chạy lại toàn bộ evidence, existing-apply rehearsal | `PHASE1B-M4-REBASELINE-VI.md` |
| S2 | Masked orchestration MODULE ĐỘC LẬP (không nối orchestrator — Directive §8): masking message+history, schema-bounded output, trusted slot resolution allowlist, trusted command assembly, deterministic receipt, 3 fallback | `PHASE1B-M4-S2-MASKED-ORCHESTRATION-VI.md` |
| S3 | Placeholder integrity tag HMAC bind conversation (sửa/thiếu/lặp/cross-context → reject), property sweep corpus, D2 sweep, concurrency/replay, telemetry redaction, flag-OFF tổng | `PHASE1B-M4-S3-HARDENING-VI.md` |

**Chưa làm (ngoài authority — đúng thiết kế, không phải thiếu sót):** production shadow
(Stage 0P), M4-G1, canary/enforcement, nối trusted_flow vào orchestrator, vendor call thật,
nối command executor vào command bus M1. S4 chỉ mới có runbook/rollback ở mức flag-semantics
(flag OFF = baseline; kill = tắt flag) — canary runbook đầy đủ lập khi có authority S4.

**Sai khác so với plan/directive (khai báo):**
1. Migration số **038** thay vì provisional 029 (M3 chiếm 029–037 khi merge trước) — đúng cơ
   chế Directive §3/§11, có re-baseline record.
2. Dependency mới `cryptography>=42` (AES-GCM không có trong stdlib) — **image production cần
   rebuild tại release**; test container đã cài, không ảnh hưởng production hiện tại.
3. Workstream M4 phát triển trong git worktree `D:\alpha3s-m4` + container/DB test riêng
   (`alpha3s-m4-test`, `alpha3s-m4-db`, network `m4net`) do M3 active song song cùng repo —
   không đụng compose/production.

## Phần 2 — Release-candidate SHA / branch / git clean

```text
Base (integration baseline):  dc839ca036baef6a5f5cee3026e0741e140b71d9  (main, M2+M3 merged)
RC (evidence head):           e43bb9e86f64b1873f1da5873dc16d307b014f70
Branch:                       feat/phase1b-m4-trusted-pii-path  (draft PR #4, KHÔNG merge)
Git status tại RC:            clean (0 file ngoài commit)
Commit chain M4:              c5face6 (S0) → dc8193a (S1) → 2d5bf0b (re-baseline) → 668f572 (S2) → e43bb9e (S3)
Pre-rebase SHAs (lịch sử):    61e0441 (S0), e4fa948 (S1) trên base 9b49628
```

Package doc này là commit docs-only ngay sau RC (không đổi code/test/migration — mọi evidence
chạy tại đúng RC `e43bb9e`).

## Phần 3 — Evidence (lệnh, exit code, mapping assertion)

Môi trường thống nhất: container `alpha3s-m4-test` (image `alpha3s-api` + pip pytest/ruff/
cryptography), DB riêng `alpha3s-m4-db` (pgvector/pg16, network `m4net`), mount `D:/alpha3s-m4:/srv`.
Bảng evidence chi tiết theo slice nằm trong 5 doc ở Phần 1; tổng hợp lần chạy CUỐI tại RC:

| Lệnh | Thời điểm (28/7) | Exit | Kết quả |
|---|---|---|---|
| `python scripts/migrate.py up` (DB fresh) | 18:02 | 0 | 38 migrations; validations M0+M3 PASS; postcondition 038 PASS |
| existing-apply rehearsal (DB2 @037+data → 038) | 18:05 | 0 | 1 migration apply, data intact |
| `python scripts/migrate.py up` (idempotent) | 18:08 | 0 | no pending, validations PASS |
| `python scripts/m4_slot_store_test.py` | 18:08 | 0 | 20/20 PASS |
| `python scripts/m4_pii_shadow_test.py` | 18:09 | 0 | PASS (recall/precision 100% synthetic-gate; latency p95 1.2ms) |
| `python scripts/m4_masked_flow_test.py` | 18:25 | 0 | 15/15 PASS (E2E, spy model 0 PII) |
| `python scripts/m4_hardening_test.py` | 18:24 | 0 | 13/13 PASS |
| `python -m pytest -q` | 18:26 | 0 | **183 passed** (81 baseline + 102 M4) |
| `python -m ruff check app scripts/m4_*.py tests` | 18:27 | 0 | clean |
| `python scripts/m3_pii_log_test.py` (regression M3 static guard) | 18:25 | 0 | ALL PASS |

Mapping AC ↔ evidence: bảng §3 doc S3 (AC-M4-02..07 development-provable ✅; AC-M4-01/08/09
thuộc production gate). Security invariants §5 spec ↔ cơ chế: bảng §3 doc S2 + §2 doc S1.

## Phần 4 — Migration/data artifacts

- **Delta schema DUY NHẤT:** `migrations/038_m4_slot_store.sql` (bảng mới `pii_slots` + 3 index
  + 2 role-hardening + postcondition fail-closed; expand-only, transactional, forward-fix bằng
  migration mới). Không sửa/xóa object nào có sẵn; không đổi migration 001–037.
- Rehearsal: fresh full-chain / existing-apply / idempotent — bảng Phần 3. Runtime <1s.
- Dữ liệu: KHÔNG production data, KHÔNG backfill. Bảng trống cho tới khi có authority bật flow.
- COMMENT data_class/purpose đúng quy ước M3 (từ 029): bảng D1/D2 per-row, purpose P02.

## Phần 5 — Deployment/runbook

KHÔNG có thay đổi deployment trong authority này (không deploy, không bật flag). Khi release
gate mở, mục cần vào runbook: (1) rebuild image (dependency `cryptography`); (2) sinh + cấp 2
secret `M4_SLOT_KEY_B64`/`M4_SLOT_FP_KEY_B64` (base64 32B — thiếu = slot store fail-closed,
shadow vẫn chạy được vì không cần khóa); (3) migration 038 theo quy trình migrate.py chuẩn;
(4) flags giữ OFF cho tới approval từng nấc (shadow → G1 → canary).

## Phần 6 — Security / rollback / monitoring + go/no-go đề xuất

- **Rollback:** toàn bộ M4 sau flag OFF-mặc-định; tắt flag = hành vi baseline (evidence
  flag-OFF: 81 test baseline pass nguyên trạng + static check không call site). Migration 038
  expand-only — rollback không cần down-migration; bảng trống có thể giữ nguyên vô hại.
- **Monitoring (khi shadow bật):** metric `[m4-shadow]` counts-only (slot/confidence/risk/
  latency/vendor_would_block); alert `m4_slot_binding_alert` severity P1 = nghi vấn
  cross-context (spec §5.8).
- **Không secret/PII trong repo/evidence:** corpus 100% bịa; khóa test sinh ngẫu nhiên per-run;
  log quét tự động (m3 static guard + assertion no-PII trong 4 evidence script).
- **Go/no-go đề xuất của Dev:** GO cho việc CHẤP NHẬN development S0..S3; NO-GO (chưa xin)
  mọi thứ production — theo đúng phân quyền Directive §14.

## Phần 7 — Open decisions (PO/CA)

1. **Stage 0P (production shadow)** — Dev chưa đề nghị bật. Theo Directive §6, trước khi xin
   Stage 0P cần PO/CA duyệt gói governance: purpose/data-class, minimization, sampling,
   labeling roles/access matrix, retention/expiry, storage zone, reviewer audit, deletion,
   metric redaction, incident path, số lượng đại diện (14 ngày/200 hội thoại). Dev sẽ soạn gói
   này khi PO ra hiệu chuẩn bị bật shadow production (5 prerequisite §6 đã có nền từ M3:
   PII-safe logging accepted, Vendor/AI review, kill-switch rehearsed — cần CA xác nhận
   evidence mapping).
2. **Renumber cuối cùng:** 038 hiện là head sau `dc839ca`. Nếu có workstream khác merge trước
   M4, cần renumber lại lần nữa tại merge review (cơ chế §11 giữ nguyên).
3. **Image rebuild** (dependency cryptography) gộp vào release nào — PO/CA quyết khi mở gate.
4. **PO decision (từ trước):** ping Telegram khi tới gate cần approve — M4-G1/Stage 0P thuộc
   diện này.

## Phần 8 — Submission Index

| # | File | Loại | Trạng thái tại RC |
|---|---|---|---|
| 1 | `docs/PHASE1B-M4-DEV-DELIVERY-PACKAGE-VI.md` | package (file này) | v1.0.0 |
| 2 | `docs/PHASE1B-M4-S0-BASELINE-VI.md` | slice evidence | final |
| 3 | `docs/PHASE1B-M4-S1-SLOT-STORE-VI.md` | slice evidence | final |
| 4 | `docs/PHASE1B-M4-REBASELINE-VI.md` | re-baseline record §11 | final |
| 5 | `docs/PHASE1B-M4-S2-MASKED-ORCHESTRATION-VI.md` | slice evidence | final |
| 6 | `docs/PHASE1B-M4-S3-HARDENING-VI.md` | slice evidence | final |
| 7 | Changed-file manifest (31 file vs `dc839ca`) | code/test/migration | xem dưới |

<details><summary>Changed-file manifest đầy đủ (git diff --name-status dc839ca..e43bb9e)</summary>

```text
M  .env.example                                   M  app/config.py
M  app/services/orchestrator.py                   M  requirements.txt
A  app/services/pii/__init__.py                   A  app/services/pii/crypto.py
A  app/services/pii/detector.py                   A  app/services/pii/masking.py
A  app/services/pii/normalize.py                  A  app/services/pii/semantic_schema.py
A  app/services/pii/shadow.py                     A  app/services/pii/slot_store.py
A  app/services/pii/taxonomy.py                   A  app/services/pii/trusted_flow.py
A  datasets/pii/synthetic_corpus_v1.jsonl         A  migrations/038_m4_slot_store.sql
A  scripts/m4_gen_synthetic_corpus.py             A  scripts/m4_hardening_test.py
A  scripts/m4_masked_flow_test.py                 A  scripts/m4_pii_shadow_test.py
A  scripts/m4_slot_store_test.py                  A  tests/test_m4_masking_schema.py
A  tests/test_m4_pii_detector.py                  A  tests/test_m4_pii_shadow.py
A  tests/test_m4_slot_crypto.py                   A  tests/test_m4_trusted_flow.py
A  docs/PHASE1B-M4-S0-BASELINE-VI.md              A  docs/PHASE1B-M4-S1-SLOT-STORE-VI.md
A  docs/PHASE1B-M4-REBASELINE-VI.md               A  docs/PHASE1B-M4-S2-MASKED-ORCHESTRATION-VI.md
A  docs/PHASE1B-M4-S3-HARDENING-VI.md
```
</details>

**Corpus provenance (§10):** `datasets/pii/synthetic_corpus_v1.jsonl` sinh deterministic từ
`scripts/m4_gen_synthetic_corpus.py` — 100% giá trị bịa do Dev soạn trong M4-S0, không dữ liệu
thật, không random; datasheet đầy đủ §4 doc S0. Known limitations hợp nhất: §6 doc S0 (detector
G01-G06 + synthetic≠production), §5 doc S1 (key management, in-transit, image rebuild), §5 doc
S2 (intent allowlist tối giản, executor stub, form marker, multi-turn state), §4 doc S3 (tag 32
bit là binding marker).

## Self-check CA-GOVERNANCE-001 §4 (trước submission)

- [x] Scope khớp spec/directive + acceptance (AC map §3 doc S3) — không tràn sang S4 production.
- [x] Code committed, git clean tại RC; evidence chạy tại ĐÚNG RC `e43bb9e`.
- [x] Mọi PASS đều có command + exit code (bảng Phần 3 + 5 doc slice).
- [x] Version/metadata nhất quán (spec v1.0.0, directive v1.1.0, package v1.0.0).
- [x] Không "sẽ gửi SHA/log sau"; không secret/PII trong hồ sơ.
- [x] Tách rõ PO decision (Phần 7) khỏi technical blocker (không có blocker mở).
