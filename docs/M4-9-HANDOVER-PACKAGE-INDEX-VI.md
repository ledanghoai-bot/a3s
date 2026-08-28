# M4-9 — Integrated Handover Package: Index (Evidence schema Addendum 61 §4)

> Nộp CA một lần theo Addendum 61. Mọi raw output tên bất biến; không secret/PII/token trong evidence.
> Branch: `feat/m4-9-dashboard-trigger` (off `main@a653392d`). **Chưa merge/deploy** (đúng Package 60).

## 01 — Summary & scope
- Thiết kế baseline (freeze): [`docs/M4-9-DASHBOARD-TRIGGER-DESIGN-VI.md`](M4-9-DASHBOARD-TRIGGER-DESIGN-VI.md) — mục tiêu, ranh giới, **state machine §3**, bước↔transition↔authority §4, CLI contract §5, credential handling §6.
- Scope: control/approval surface + orchestration bọc CLI runner. Exclusions: merge/deploy/production credential/signer/STS-KMS/customer-data/IAM-KMS-WIF mutation.

## 02 — UI / API
- UI: [`dashboard/app/signing/page.js`](../dashboard/app/signing/page.js) — state machine → nút điều kiện, abort yêu cầu reason, ceremony chỉ metadata công khai; badge classes `globals.css`; nav `layout.js`.
- API: [`app/api/m4_signing.py`](../app/api/m4_signing.py) — 10 endpoint, gate `require_permission` mỗi route, RBAC 2 tầng. Contract: create/confirm/preflight/ceremony/canary-request/canary-approve/execute/abort + list/detail.
- RBAC/approval trace: rehearsal §09 (audit event đầy đủ 7 transition).

## 03 — Policy / preflight
- Engine: [`app/services/m4_signing/policy.py`](../app/services/m4_signing/policy.py) — window/scope/quota/dormant-capture-off, fail-closed; freshness ≤15'.
- Pass/fail/negative: integration test `[7a]` PASS, `[6]/[7b]` FAIL đúng (quota hết / ngoài window); rehearsal preflight PASS + gate ceremony/execute yêu cầu preflight tươi.

## 04 — CLI / pipeline adapter
- Adapter: [`app/services/m4_signing/cli_adapter.py`](../app/services/m4_signing/cli_adapter.py) — bọc `rehearsal_runner`, `_classify` fail-closed, bắt `CLEANUP_FAILED`, `redact()`, `_worker_env` từ chối secret-key.
- Attempt/quota ledger: bảng `m4_signing_run_attempt` append-only; unit test `_classify`/`redact`/`_worker_env`.

## 05 — Security
- Threat model: [`docs/M4-9-THREAT-MODEL-VI.md`](M4-9-THREAT-MODEL-VI.md) — STRIDE, data-boundary proof, known limitations.
- Secret controls: 3 lớp no-secret (service regex + DB CHECK + adapter redact); test `test_assert_no_secret_*`, rehearsal `neg: ceremony secret bị chặn`, `8b detail không lộ secret`.
- Secret scan evidence: §Secret scan dưới.

## 06 — Monitoring / audit
- Audit: bảng `m4_signing_run_event` bất biến (transition + human action + actor + reason + timestamp).
- Correlation: rehearsal `[8]` xác minh đủ 7 event; `CLEANUP_FAILED` → FAILED + alert (adapter `danger`).

## 07 — Rollback / cleanup
- Abort mọi active state (yêu cầu reason) → ABORTED; break-glass flag. Worker fail-closed → FAILED (không treo EXECUTING).
- Cleanup thực thi do runner (`_do_cleanup_and_verify`); dormant proof = capture OFF + không signer container (kiểm ở preflight + runbook §5).

## 08 — Runbook / RACI
- [`docs/M4-9-OPERATOR-RUNBOOK-VI.md`](M4-9-OPERATOR-RUNBOOK-VI.md) — RACI, tiền điều kiện, trình tự, human checkpoints, break-glass, key/cert lifecycle.

## 09 — Rehearsal (end-to-end từ dashboard)
- Harness: [`scripts/m4_9_rehearsal.py`](../scripts/m4_9_rehearsal.py) — HTTP end-to-end, auth/RBAC/SoD **thật** trên DB thật + full migrations.
- Kết quả: **M4_9_REHEARSAL_PASS** — create→confirm→preflight→ceremony→canary→execute(enqueue) + 5 negative (thiếu quyền/transition sai/secret/SoD/abort-thiếu-reason). *(raw: §Test evidence)*
- Execution thật (worker→runner→signer) validate riêng: `scripts/m4_9_signing_run_test.py` (M4_9_ALL_PASS) + runner test suite hiện có; full signer-stack chạy trên compose (ngoài phạm vi self-contained rehearsal, khai rõ).

## 10 — Acceptance
- Tự-review exit criteria (Addendum 61 §6): dashboard không bypass/force/unlimited-retry ✓; PO approval + abort audit ✓; preflight fail-closed + window/scope/quota server-side ✓; attempt counter không reset (ledger immutable) ✓; secret scan sạch ✓; rehearsal PASS + cleanup/dormant ✓; rollback/break-glass ✓; runbook/RACI/threat model versioned ✓.
- PO/Operations sign-off: *chờ ký* (mục này PO điền khi nghiệm thu).
- Known limitations: threat model §5 (pin_secret↔JWT chưa nối — T9-03; RBAC nút frontend; production cần gate riêng).

## Test evidence (raw, tên bất biến)
| Bộ | Lệnh | Kết quả |
|---|---|---|
| Unit (CI) | `pytest tests/test_m4_9_signing_run.py` | 21 passed |
| Integration DB | `python scripts/m4_9_signing_run_test.py` | M4_9_ALL_PASS (14 check) |
| Rehearsal HTTP | `python scripts/m4_9_rehearsal.py` | M4_9_REHEARSAL_PASS |
| Migration | `psql -f migrations/046` trên PG16 | applied RC=0 + 9 schema invariant |

## Secret scan
Toàn diff M4-9: không token/khóa/PIN/plaintext PII. Cột JSON có CHECK no-secret; adapter redact;
env secret-key không nhận từ caller. *(scan command + output: §evidence khi đóng gói cuối)*

## Commits (branch feat/m4-9-dashboard-trigger)
- migration 046 + backend nền · dashboard UI · tests (unit+integration) · docs (runbook+threat) · rehearsal + index.
