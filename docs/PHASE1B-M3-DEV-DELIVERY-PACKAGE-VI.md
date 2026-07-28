# M3 Delivery Package — Submission 1 (Initial Delivery)

```yaml
milestone: Alpha3S Phase I-B M3 — Compliance and Sensor Foundations
directive: A3S-PHASE1B-M3-DEV-DIRECTIVE-001 v1.0.0 (issued 2026-07-28 00:04+07:00)
spec: A3S-PHASE1B-M3-SPEC-001 v1.0.0
submission: 1/3 (Initial Delivery)
prepared_at: 2026-07-28 01:00+07:00
author_role: Dev
```

## 1. Release candidate

| Mục | Giá trị |
|---|---|
| Implementation base (Directive §2.1) | `9b49628a83ba1fe02b97913f20f33e4883560b5b` (exact M2 accepted RC — checkout detached, object verified, `git status` sạch; evidence `docs/PHASE1B-M3-SLICE0-BASELINE-VI.md`) |
| **Code/evidence head (RC M3)** | `a3b88e76605ac25d6a1c5ef578c6cc76b3aadeb1` |
| Package head (re-baseline, CA đã review) | `9775daf74f20c463de6cf89fbedc8b760fd68950` (C-M3-RB-01) |
| Package tail (code head → package head) | **evidence-script + docs** — 2 commit / 2 file: `scripts/m3_existing_apply_rehearsal.py` (executable evidence, thuộc reviewed/tested scope) + `docs/PHASE1B-M3-DEV-DELIVERY-PACKAGE-VI.md` (C-M3-RB-02; KHÔNG phải docs-only) |
| Correction tail | commit Correction Note C-M3-RB-01..04 (docs-only — xem §10) |
| Branch / PR | `feat/phase1b-m3-compliance-sensor-foundations` — PR #3 (draft, KHÔNG merge) |
| CI | CI/CD **success** tại `a3b88e7`: https://github.com/ledanghoai-bot/a3s/actions/runs/30291350048 |
| Diff so với base | 48 files, +2689/−50 (pre-rebase) / 50 files vs main (post-rebase) |
| Re-baseline (Directive §2.2) | **ĐÃ THỰC HIỆN — xem §9** (M2 merge `main` 28/7, notice A3S-PHASE1B-M2-M3-COORDINATION-NOTICE-001 Work order B) |

## 2. Scope đã triển khai (slice → commit)

| Slice | Nội dung | Commit |
|---|---|---|
| S0 | Baseline verification + 7 governance artifacts + PII log audit; Moment Memory seed tại repo Orbit (`E:\A3s-orbit\Dev\moment-memory\`, 3 moment) | `ced423e` |
| S1 | Delivered lifecycle: migration **029** (`delivered` + `delivered_at`), matrix `fulfilled→mark_delivered`, `delivered→complete/request_return`, `delivery_failed→retry_delivery/cancel` (EFFECT_NONE, perm `order.cancel.exception`), command types mới, notify delivered, flag `m3_delivered_lifecycle` | `21c0d1d` |
| S2 | UTM attribution: migration **030** (5 cột `utm_*` orders+conversations), `attribution.py` mapping v1 (allowlist, PII guard, `utm_term` chỉ khi có input, không suy từ prefix), order.create nhận utm optional (không vào request_hash), flag `m3_utm_attribution` | `d44f853` |
| S3 | Consent: migration **031** `consent_records` append-only (authority_system/revision monotonic), `consent.py` `check_permission → allow/deny/unavailable + reason + decision_ref`, complaint suppression | `04a6d0c` |
| S4 | PII-safe logging: `safe_log.py` áp toàn app (~30 điểm), dead-letter TTL + refs-only, `log_event` enforce redaction, static guard | `659503e` |
| S5 | Outbound Dispatcher: migration **032** `outbound_templates` (immutable, seed = text M2 nguyên văn), `dispatcher.py` (consent lúc gửi, suppressed+decision_ref trong delivery_attempts, P05/P06 unavailable fail-closed, zalo_zns stub), notify M2 qua dispatcher flag `m3_outbound_dispatcher` | `d0327e6` |
| S6 | Retention executor: migration **033** (policies version hóa seed DRAFT, legal_holds, run_log counts-only), `retention.py` (dry-run/approve-để-apply, legal hold, non-resurrection), cron 03:15 flag `m3_retention_executor` | `a3b88e7` |
| S7 | Verification + rehearsal + package này | (docs) |

Ngoài scope giữ đúng Directive §4: KHÔNG Slot Store/masked orchestration (M4 — đang chạy riêng theo directive M4), KHÔNG Content Engine/NBA/campaign, KHÔNG Zalo production, KHÔNG đổi invariant M1/M2.

## 3. Evidence — chạy tại code head `a3b88e7` (exit 0 = PASS)

Môi trường: Docker Desktop Windows, container `alpha3s-api-1` (Python 3.12), throwaway DB per-script
(tên chứa `test`, tự DROP/CREATE), synthetic fixtures 100% — KHÔNG production data.

| Thời điểm | Lệnh (docker exec …) | EXIT |
|---|---|---|
| 2026-07-28 00:56+07:00 | `scripts/m3_delivered_lifecycle_test.py` (DB m3s1_itest) | 0 |
| 2026-07-28 00:57+07:00 | `scripts/m3_utm_test.py` (m3s2_itest) | 0 |
| 2026-07-28 00:57+07:00 | `scripts/m3_consent_test.py` (m3s3_itest) | 0 |
| 2026-07-28 00:57+07:00 | `scripts/m3_pii_log_test.py` (không DB) | 0 |
| 2026-07-28 00:57+07:00 | `scripts/m3_dispatcher_test.py` (m3s5d_itest) | 0 |
| 2026-07-28 00:57+07:00 | `scripts/m3_retention_test.py` (m3s6r_itest) | 0 |
| 2026-07-28 00:57+07:00 | `scripts/m3_existing_apply_rehearsal.py` (m3exist_itest) | 0 |
| 2026-07-28 00:58+07:00 | `python -m pytest -q` → 81 passed | 0 |
| 2026-07-28 00:58+07:00 | `python -m ruff check app` → All checks passed | 0 |
| 2026-07-28 00:58+07:00 | `scripts/m2_transitions_test.py` (regression M2) | 0 |
| 2026-07-28 00:58+07:00 | `scripts/m2_lifecycle_test.py` | 0 |
| 2026-07-28 00:58+07:00 | `scripts/m2_rbac_test.py` | 0 |
| 2026-07-28 00:59+07:00 | `scripts/m2_customer_notify_test.py` | 0 |
| 2026-07-28 00:59+07:00 | `scripts/m2_worker_api_test.py` | 0 |
| 2026-07-28 00:59+07:00 | `scripts/m2_balance_authority_test.py` | 0 |
| 2026-07-28 00:59+07:00 | `scripts/m2_inventory_domain_test.py` | 0 |
| 2026-07-28 00:59+07:00 | `scripts/m2_db_role_test.py` | 0 |
| 2026-07-28 00:59+07:00 | `scripts/m2_existing_apply_rehearsal.py` (regression M2 rehearsal) | 0 |

**18/18 EXIT=0** (7 M3 + 9 M2 regression + pytest + ruff). CI: run `30291350048` success.

## 4. AC mapping

| AC | Evidence |
|---|---|
| AC-M3-01 artifacts thực, có owner/version/gap | 7 docs (`SENSOR-INVENTORY`, `DATA-CLASSIFICATION-CATALOG`, `PROCESSING-PURPOSE-REGISTRY`, `VENDOR-SUBPROCESSOR-REGISTER` — DeepSeek review facts từ policy chính thức 10/2/2026 + cross-border gap 91/2025, `AI-USE-CASE-REGISTER` UC-001..003, `RETENTION-SCHEDULE` RET-01..11, `DSR-RUNBOOK` + propagation map 16 mục verified trên code) — mỗi doc có bảng Gap/Action |
| AC-M3-02 lifecycle matrix/idempotency/provenance, không phá M2 | `m3_delivered_lifecycle_test` [1]-[8] (flag OFF = M2 nguyên trạng; effective-once; delivered_at COALESCE; RBAC F02; balances bất biến) + toàn bộ regression M2 PASS |
| AC-M3-03 UTM optional/validated/lineage/compat | `m3_utm_test` [1]-[6] (request_hash không đổi; mapping v1; PII guard; origin_channel giữ nghĩa) |
| AC-M3-04 consent tests | `m3_consent_test` = §13.19 #1 (opt-out P06 không chặn P03), #2 (rút P05 chặn), #3 (complaint suppress + resolved), #13 (version truy xuất) + revision monotonic + unavailable fail-closed |
| AC-M3-05 PII không lọt log | `m3_pii_log_test` (raw/encoded/Unicode/httpx-token + log_event enforce + static guard) + audit doc §2b; known limitation: PSID trong URL path (xem §7) |
| AC-M3-06 transactional qua dispatcher, receipt/dedupe giữ | `m3_dispatcher_test` [2]-[9] (flag OFF byte-đúng M2; cùng dedupe_key; template seed = text M2 nguyên văn; suppressed có decision_ref trong delivery_attempts; run_once end-to-end) + `m2_customer_notify_test`/`m2_worker_api_test` PASS |
| AC-M3-07 retention dry-run/deletion/non-resurrection | `m3_retention_test` [2]-[8] (dry-run không mutation; draft bị từ chối apply; legal hold; restore-non-resurrection; flag OFF no-op). **Dry-run "được duyệt" = open input cho PO** (§7) |

## 5. Migration manifest + flags + rollback

Migrations M3 (đầu = **029** đúng Directive §6; 001–028 KHÔNG sửa — đã verify checksum tại Slice 0):

```text
bae1020452477df2c21c2461546d09c5e4eb451d4a920df11d6164b49d7dfe36  029_order_delivered.sql
c9781112df6a915b021a321fe9bd39e0bdb8069f1b15ac53d9375f16961128d8  030_utm_attribution.sql
a83320ba88afd7cd90522c5affee58e0a514da43a77c8e69c847ee05a58f704c  031_consent_ledger.sql
cb631c2baca12ee22110b0079c3cf4bc6b783331826e192ce74763af8a64f2b1  032_outbound_templates.sql
cc5cda36eefdaec30919fdbff61228536b5d1fe58d92f582bbfcff0684da3517  033_retention.sql
```

Mỗi migration: precondition + postcondition tự-validate + runtime estimate + forward-fix (ghi trong
file). Rehearsal: fresh (mỗi evidence script apply 001..033) + existing-apply (`m3_existing_apply_rehearsal`:
028→033 trên data đại diện, checksum dữ liệu bảo toàn, reconcile M2 vẫn OK). Forward-fix rehearsal:
mỗi file idempotent (chạy lại an toàn — IF NOT EXISTS/ON CONFLICT).

Flags (đều **default OFF**, missing config fail-safe, OFF = behavior M2 nguyên trạng — evidence từng test):

| Flag | Mở gì | Rollback |
|---|---|---|
| `m3_delivered_lifecycle` | transitions delivered/retry/cancel-sau-df (gate tại engine) | tắt flag |
| `m3_utm_attribution` | ghi UTM đã validate xuống orders | tắt flag (cột NULL) |
| `m3_outbound_dispatcher` | notify qua consent+template | tắt flag → đường M2, cùng dedupe |
| `m3_retention_executor` | cron apply policy approved | tắt flag (dry-run vẫn được) |

Không flag nào bypass permission/suppression/audit/invariant. Production ON = gate riêng (Directive §7).
Vận hành: cron retention 03:15 (worker, tường minh); alert/metric giữ M1/M2; runbook chi tiết sẽ gộp
khi release (open input — xem §7).

## 6. Contracts + security/privacy

- Event mới append-only/idempotent, không raw chat/phone/full address (order.mark_delivered qua
  `append_order_event` idempotency_key; outbound qua dedupe_key).
- `origin_channel` không đổi nghĩa (evidence m3_utm [5]); observed/estimated không nhập nhằng
  (delivered chỉ từ committed transition; Sensor Inventory ghi provenance).
- P03 độc lập P06; unavailable fail-closed cho P05/P06 (m3_consent [7], m3_dispatcher [6]).
- Content/Insight consumer chưa được mở đọc Personal Data Zone (không có consumer nào trong M3).
- Receipt/false-confirmation-zero M1 giữ nguyên (regression + reply_guard không đổi).
- Security: RBAC command-boundary F02 phủ command mới (m3_delivered [8]); DB-role least-priv M2 giữ
  (m2_db_role PASS); log sạch PII/credential (S4); không production data trong test.

## 7. Open decisions / release inputs (PO/CA)

1. **Retention Schedule các giá trị [PROPOSED]** (raw chat 24 tháng, backup 30 ngày, v.v.) — PO duyệt
   thì Dev nâng policy 033 lên `approved` (migration/seed riêng tại release). Dry-run report có sẵn.
2. **DeepSeek cross-border 91/2025/QH15**: hồ sơ đánh giá + xác minh opt-out training — owner PO/legal
   (VENDOR-SUBPROCESSOR-REGISTER gap #1/#2); mitigate dài hạn = M4.
3. **PSID trong URL path → uvicorn access log** (S4 known limitation): đề xuất xử lý ở release
   (log format/tắt access log) hoặc milestone riêng — đổi route là breaking dashboard API.
4. Text notify `fulfilled` hiện là "đã được giao" (M2 nguyên văn) — sau khi có `delivered` nên đổi
   thành "đã bàn giao vận chuyển"? Đổi = behavior change → chờ CA/PO, làm bằng template version 2.
5. ~~Re-baseline sau M2 merge main~~ — **ĐÃ HOÀN THÀNH** (xem §9).
6. (sửa theo C-M3-RB-04) `baseline_manifest` **không** pin migration head/count — nó quản lý
   baseline-through + danh sách validation; pin `028/28` nằm trong `scripts/m2_r1_remediation_test.py`
   (historical release evidence). Open input đúng: **đánh giá riêng** liệu M3 cần thêm post-migration
   validation cho contract 029–033; nếu cần thay manifest/runner thì đó là implementation/release delta
   phải được review + test (new exact head + CI); KHÔNG sửa manifest chỉ để script lịch sử PASS.

## 8. Submission Index

| # | Nội dung | Trạng thái |
|---|---|---|
| 1 | Governance artifacts (7) + Moment Memory seed | trong repo + E:\A3s-orbit |
| 2 | Code slices S1-S6 + flags OFF | `a3b88e7` |
| 3 | Evidence 18/18 EXIT=0 + CI success | §3 |
| 4 | Migration manifest 029-033 + rehearsal fresh/existing/forward-fix | §5 |
| 5 | AC-M3-01..07 mapping | §4 |
| 6 | Open decisions | §7 |

## 9. Re-baseline evidence (Directive §2.2 / Coordination Notice Work order B — 2026-07-28 14:10..14:16+07:00)

| Bước §2.2 | Kết quả |
|---|---|
| 1. Exact M2 merge SHA trên main | `42aab7192a94b259538f7591b9268945256f6b4e` (Merge PR #5: M2 + F-R1-01) |
| 2. Accepted RC là ancestor | `git merge-base --is-ancestor 9b49628… origin/main` → EXIT=0 ✓; impl head release = `66db876` (descendant của RC, app/+migrations 001-028 unchanged theo remediation package M2) |
| 3. Rebase M3 lên merged baseline | `git rebase origin/main` — 8/8 commit apply sạch |
| 4. Conflict resolution | **Không phát sinh conflict nào** (M3 additive; F-R1-01 chỉ chạm migrate.py/validations/scripts — không giao file với M3) |
| 5. Re-run migration + regression + checksum | Fresh: mọi evidence script apply 001..033 PASS; existing-apply `m3_existing_apply_rehearsal` (028→033) PASS; **current regression suite 18/18 PASS** (denominator không gồm script lịch sử — C-M3-RB-03, xem ghi chú dưới); migrations 001–028 `git diff` với main = **rỗng** (identical); manifest sha256 toàn bộ 001-033 chốt tại head mới |
| 6. Pre/post-rebase SHA | pre: code `a3b88e76605ac25d6a1c5ef578c6cc76b3aadeb1` / package `79de5ae0eba120963068040356e038244392705f` → post: **code `17d094d19d0dd4655e3fc854ca9c048ecec645f6`** / package = commit chứa bản cập nhật này |
| 7. Drift check | Không drift ngoài M2 accepted RC + approved release changes (main chỉ thêm docs-only tail + release-prep + F-R1-01 đã qua gate R1/R2 closure) |

Evidence re-run tại post-rebase head, 2026-07-28 14:12→14:16+07:00 (C-M3-RB-03 — tách rõ 2 nhóm):

1. **Current regression suite: 18/18 EXIT=0** — pytest 81, ruff, 7 script M3, 9 script regression M2
   (đúng danh mục §3).
2. **Ngoài denominator — script lịch sử release M2:** `m2_r1_remediation_test.py` đã chạy và EXIT=1
   do **expected scope mismatch**: script tự pin `FULL-CHAIN 018→028, expected head=028, count=28`
   (pin nằm TRONG chính script — C-M3-RB-04), trong khi nhánh M3 hợp lệ có head 033. Đây KHÔNG phải
   bằng chứng M2 invariant regression; các case khác của script PASS. Không tuyên bố "toàn bộ lệnh
   PASS" — 1 lệnh lịch sử đã chạy exit 1 với lý do scope nêu trên.

## 10. Correction Note (theo A3S-PHASE1B-M3-CA-REBASELINE-REVIEW-001 §6-§7 — docs-only, không dùng submission slot)

| ID | Sửa gì | Ở đâu |
|---|---|---|
| C-M3-RB-01 | Package head ghi full SHA `9775daf74f20c463de6cf89fbedc8b760fd68950` | §1 |
| C-M3-RB-02 | Tail code→package = **evidence-script + docs** (2 commit / 2 file: `scripts/m3_existing_apply_rehearsal.py` + package doc), không ghi docs-only | §1 |
| C-M3-RB-03 | Tách denominator: current suite 18/18 PASS; `m2_r1_remediation_test` = historical, expected scope mismatch, ngoài denominator; không tuyên bố toàn bộ lệnh PASS | §9 |
| C-M3-RB-04 | Bỏ phát biểu "baseline_manifest pin 001-028"; pin 028/28 nằm trong script lịch sử; open input viết lại thành đánh-giá-riêng validation 029-033 (delta nếu có phải review+test) | §7.6, §9 |

Correction này KHÔNG thay code/evidence script/migrations — chỉ package metadata. Code head giữ nguyên
`17d094d19d0dd4655e3fc854ca9c048ecec645f6`.

## Self-check checklist (CA-GOVERNANCE-001 §4)

- [x] MỘT package hợp nhất, không status report rời
- [x] Full 40-char SHA base + code head; package head = commit doc này
- [x] Evidence exact command + timestamp `+07:00` + exit code; synthetic fixtures
- [x] Migration manifest + checksums; 001-028 không sửa
- [x] Regression M1 (pytest suite chứa M1 tests) + M2 (9 script) + M3 tại cùng head
- [x] Flags default OFF, không đổi behavior khi OFF (evidence per-flag)
- [x] Không merge main / không production access / không bật flag production
- [x] Known limitations khai báo trung thực (§7)
