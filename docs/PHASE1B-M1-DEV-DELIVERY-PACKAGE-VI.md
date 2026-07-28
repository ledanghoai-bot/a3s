---
id: A3S-PHASE1B-M1-DEV-DELIVERY-PACKAGE
title: Alpha3S Phase I-B M1 — Dev Delivery Package (Submission 3 of 3, final)
milestone: M1
milestone_name: Reliable Command and Receipt
governing_spec: A3S-PHASE1B-M1-SPEC-001 v1.0.0
governing_directive: A3S-PHASE1B-M1-DEV-DIRECTIVE-001 v1.0.0
status: remediation_submission_3_pending_ca_review
production_change: NONE (flag M1_RELIABLE_ORDER_COMMAND = OFF)
language: vi-VN
---

# M1 Delivery Package — Submission 3 (of 3, final)

> Development/staging complete ≠ production authorization (Directive §8). Không thay đổi production,
> không chạy migration production, không bật flag production. Chờ CA Consolidated Review.

## 0. SHA & baseline (AC-M1-11)

```text
Immutable base SHA : 4ce5f3ab2b95846cbc5a3dd5b21528a891b36314  (tag ib-m0-rc7, migrations 001–018)
Dev branch         : feat/phase1b-m1-reliable-command  (off ib-m0-rc7, KHÔNG commit main)
Implementation SHA : 46e1169f9f6fae70eca06ef21eec62ae3ebfe70f  (Sub3 CA-remediation final; Sub2 d74d5c5; hardening 0bc4eb7; initial 59d4b2a)
Baseline proof     : origin/main == 4ce5f3ab (0/0), tag ib-m0-rc7 -> 4ce5f3ab (annotated),
                     migrations 001–018 present, RBAC_STRICT enforce present, plan v0.1.3 @baseline.
```

## 1. Changed files & migration manifest

**Migrations mới (expand-only, forward):**

| File | sha256 |
|---|---|
| migrations/019_command_bus.sql | `11097820164b819513173df569484331c09ab9b261843e3044c213e6efd26813` |
| migrations/020_command_rbac.sql | `bb68b5d64bf2a1af7c20b1e2753ab0e4f8dcabba077694aad599e38f3405c2e0` |

**Modified (flag-gated, legacy fallback nguyên vẹn khi flag OFF):**
`app/config.py` (flag), `app/services/tools.py` (AI create_order route), `app/services/orchestrator.py`
(command_ctx + deterministic reply + shadow), `app/services/orders.py` (manual route),
`app/api/dashboard.py` (3 create endpoints + receipt lookup + 6 ops endpoints + metrics),
`app/workers/tasks.py` (arq cron outbox drain), `dashboard/app/layout.js` (nav).

**New:** `app/services/command/` (hashing, errors, redaction, retry, receipt, registry, idempotency,
envelope, repository, order_service, order_gateway, outbox_worker, recovery, observability, reply_guard,
__init__), `dashboard/app/ops/page.js`, `docs/PHASE1B-M1-RUNBOOK-VI.md`, `scripts/validate_command_bus.sql`,
`scripts/command_*_test.py` (6), `tests/test_command_contract.py`, `tests/test_command_reply_guard.py`.

## 2. Contract (API / tool / receipt)

- **Command envelope** (§6.1): server-generated command_id/correlation_id; actor/customer/conversation
  injected từ trusted context (KHÔNG tin LLM); canonical-JSON sha256 request_hash; stored payload allowlist
  (masked phone, KHÔNG address raw).
- **Idempotency** (§6.2): API/dashboard header `Idempotency-Key` (16–128); AI stable key (CR-04R) =
  `sha256(channel|provider_message_id|command_type|version|business_identity)` — **KHÔNG** tool_call_id,
  ổn định qua re-execution; scope = `order.create:<channel>:<actor>`.
- **HTTP status**: 201 first / 200 duplicate / 202 in_progress (+Retry-After) / 409 conflict /
  422 validation+business reject / 400 missing-or-invalid key. Body có `receipt` + legacy fields (canary).
- **Receipt** (§6.4): dựng từ `command_executions.result_payload`, KHÔNG qua LLM. Customer template v1:
  `Đơn #123 đã được ghi nhận: 1 × 3S-100G, tổng 170.000đ.`
- **Recovery** (§9.3): `GET /dashboard/{commands,outbox,outbox/{id}}`, `POST /dashboard/outbox/{id}/{retry,cancel,replay}`
  (RBAC + reason + audit), `GET /dashboard/ops/metrics`.

## 3. Test matrix → AC (AC-M1-01…12)

| AC | Nội dung | Evidence |
|---|---|---|
| 01 | Mọi caller dùng envelope + idempotency | `test_command_contract` (envelope/idem), `command_gateway_test`, `command_http_test` (400 no-key) |
| 02 | Mutation/result/outbox atomic | `command_order_service_test` T1 (order+command+outbox+audit đồng thời) |
| 03 | Duplicate cùng payload → receipt cũ | `command_order_service_test` T2; `command_http_test` 200 dup |
| 04 | Duplicate khác payload → conflict, no side-effect | `command_order_service_test` T3+T8; `command_http_test` 409 |
| 05 | Concurrency → đúng 1 mutation | `command_order_service_test` T7 (20 concurrent=1 order, no oversell) + T8 (10/10) |
| 06 | Worker lease/retry/dead-letter/recovery | `command_outbox_worker_test` (5); `command_recovery_rbac_test` A |
| 07 | Deterministic receipt = committed truth | `test_command_contract` (receipt), `test_command_reply_guard`, `command_order_service_test` T1 |
| 08 | RBAC/audit fail-closed/PII redaction | `command_recovery_rbac_test` R/G/A/F; `test_command_contract` (redaction); T1 redaction |
| 09 | Metrics/log/alerts/runbook | `command_observability_test`; `docs/PHASE1B-M1-RUNBOOK-VI.md` |
| 10 | Rollout compat + marker guard evidence gate | `command_gateway_test` (flag on/off legacy); `test_command_reply_guard` (shadow) |
| 11 | Immutable baseline/migration evidence | §0 baseline proof; §4 rehearsal |
| 12 | Production smoke + 24h stability | **DEFERRED tới CA release gate** (dev complete ≠ production; cần canary + 24h) |

## 4. Verification (exact, exit codes)

Chạy trong container `alpha3s-api-1` (Python 3.12, pytest 9.1.1), DB throwaway `m1_itest` migrate 001–020.

```text
# Unit (pytest -q)                                         -> 81 passed, exit 0
# ruff check app/ + 9 evidence scripts                     -> All checks passed, exit 0
# Evidence scripts (mỗi cái fresh migrated DB) — 9/9 PASS:
command_order_service_test  exit 0  (T1 atomicity+redaction … T7 20-conc=1 order … T8 10/10;
                                     T9 new-customer race=2 orders/1 customer; T10 override single-use no double-spend)
command_gateway_test        exit 0  (ON/AI route+receipt+dup … OFF legacy no command row)
command_outbox_worker_test  exit 0  (delivered / retry->dead-letter / 400 terminal / timeout->unknown / reclaim)
command_http_test           exit 0  (400/201/200/202+Retry-After/409/422 stock+phone/receipt 200+404)
command_recovery_rbac_test  exit 0  (RBAC map / gate / retry-cancel-replay+audit+guards+reason / audit fail-closed)
command_observability_test  exit 0  (5 metrics + 4 alerts P1/P2 + log_event)
command_crash_recovery_test exit 0  (§13.1: fail-before-commit rollback / retry-after-commit / worker-crash reclaim)
command_ops_api_test        exit 0  (/ops e2e: commands/outbox/detail+attempts/metrics + retry 200/audit + reason 422)
command_ca_remediation_test exit 0  (CR-01 / CR-02 CAS / CR-03 durable receipt / CR-04R / CR-05 audit fail-closed)
validate_command_bus.sql    exit 0
```

**Migration rehearsal (§13.2, AC-M1-11):**
```text
Fresh DB   : migrate up -> Applied 20 migration(s), validation pass, exit 0
Existing DB: build to 018 (019/020 held out) -> Applied 18; apply 019+020 -> Applied 2; status re-run no drift
```

**Live smoke (api trên M1 code):** `/health` 200; `/dashboard/ops/metrics`, `/outbox`, `/commands/{id}/receipt`
đều 401 (route tồn tại + auth-gated); worker cron `deliver_outbox_job` chạy mỗi 10s (no-op, flag OFF).

## 5. Atomicity / concurrency / crash evidence

- **Atomic** (T1): 1 transaction → order + command(succeeded) + outbox + audit cùng tồn tại; PII chỉ
  `phone_masked` trong request_payload, KHÔNG address raw.
- **Effective-once** (T7): 20 request đồng thời cùng key → **đúng 1 order**, stock −1, 1 command, 1 outbox.
- **Conflict** (T3/T8): cùng key khác payload → 409, 0 side-effect; T8 mixed 10 success/10 conflict.
- **Crash/failure matrix** (outbox worker): provider 5xx→retry→dead-letter tại max; 4xx terminal ngay;
  timeout→unknown (không failed vội); worker crash→lease reclaim→deliver.
- **Audit fail-closed**: break audit_log → order mutation & recovery rollback (không mutation không audit).

## 6. Rollout / flags / rollback (§10.2, §13.3)

- Flag `M1_RELIABLE_ORDER_COMMAND` (default **OFF**). OFF = 3 đường tạo đơn giữ legacy byte-identical.
- Deploy order: expand migration (019/020) → app đọc/ghi schema mới với flag OFF → start outbox worker
  (cron đã có, no-op) → canary staff/manual → canary AI → quan sát 24h → enforce idempotency → marker
  guard structured. Rollback ứng dụng = tắt flag (schema expand tương thích); event đã tạo phải drain,
  không dừng worker vô thời hạn; KHÔNG rollback migration đã apply (forward-fix).
- Marker guard (§10.4): template chạy + marker quan sát (bước 1); shadow metric mọi claim có receipt
  (bước 2, `reply_guard.shadow_evaluate` + log `[cmd] command.idempotency_conflict`/succeeded); structured
  guard giữ fallback marker 1 release (bước 3) — thực thi ở canary.

## 7. Known limitations / residual risks / scope self-review

1. **AC-M1-12 chưa đạt trong dev delivery** — cần production canary staff + customer-channel + 24h stability
   (Directive §8). Đây là gate CA release, không thuộc dev complete.
2. **Dashboard HTTP endpoints** đã route qua command service (Slice 7) nhưng chỉ active khi flag ON.
3. **`command_duplicate_total` metric** chưa track (loser không persist row riêng) — có thể thêm counter sau.
4. **Ops UI e2e (login + seeded data)** verify bằng `next build` + route live; visual e2e để canary/staging.
5. **DB-role tách (runtime vs migration-owner)** vẫn là backlog M0 → đóng trước/không muộn hơn M2 (không
   suy yếu RBAC strict trong M1).
6. **Hotfix `tg-customer-dedup` (fa81ff2)** trên base pre-M0 — ngoài scope M1, cần rebase lên ib-m0-rc7
   trước khi merge (đã để nguyên, Directive §4 incident tách khỏi M1).
7. **AI idempotency key** (ĐÃ ĐÓNG CR-04/CR-04R — không còn là limitation): neo vào channel +
   **provider message ID thật** (Messenger `mid` / Telegram `message_id`) + business identity đã chuẩn
   hoá; KHÔNG dùng `tool_call_id` → ổn định qua re-execution (xem §11). Giữ nguyên đây để đối chiếu.

## 7b. Post-submission self-review & hardening

Trong lúc chờ CA, đã chạy **adversarial self-review** (agent độc lập) trên `app/services/command/*`
và **sửa 3 bug thật** + bổ sung 2 nhóm evidence. Implementation SHA cập nhật (xem §0).

| # | Sev | Bug | Fix | Regression |
|---|---|---|---|---|
| F1 | HIGH | `execute_order_create` bắt MỌI `UniqueViolationError` → race khách MỚI (customers.psid, 2 đơn khác idempotency key) bị misroute thành "duplicate" → đơn hợp lệ KHÔNG được tạo (HTTP trả 202 với command_id đã rollback → lookup 404) | Customer upsert `ON CONFLICT (psid) DO UPDATE` (loại race) + outer except gate theo `constraint_name='command_executions_idem_key'` (chỉ idempotency conflict mới là duplicate) | `command_order_service_test` T9 |
| F2 | MEDIUM (tài chính) | Price override single-use bị **double-spend**: 2 đơn khác SKU cùng psid+qty (product `FOR UPDATE` chỉ khóa cùng SKU) cùng consume 1 override | Consume ATOMIC có điều kiện `UPDATE … WHERE used=FALSE RETURNING id`; loser fallback giá thường | `command_order_service_test` T10 |
| F3 | LOW/MED | `reply_guard`: `'#12' in reply` khớp nhầm `'#123'` → bỏ sót dòng xác nhận (lớp bug substring-biên CLAUDE.md) | Match token boundary regex `(?<!\d)#12(?!\d)` | `test_command_reply_guard` |

**Findings accept-by-design (documented, không đổi code):**
- F4 (LOW): audit thất bại trên đường **conflict** → surface raw error thay vì 409 (vẫn fail-closed, KHÔNG có mutation để undo; conflict không bị nuốt).
- F5 (ĐÃ ĐÓNG ở CR-05): mô tả cũ là audit fail-**open** khi bảng `audit_log` vắng mặt. Submission 2
  (CR-05) đã BỎ guard `audit_exists` trong order_service → order mutation LUÔN gọi audit; thiếu/hỏng
  `audit_log` → `record()` raise → transaction rollback (fail-closed hoàn toàn). Không còn fail-open.
- F6 (INFO): override scoped theo psid+qty (không theo product) — theo thiết kế phê duyệt; F2 đã đóng blast-radius double-spend.

**Evidence bổ sung:** `scripts/command_crash_recovery_test.py` (§13.1 crash matrix) + `scripts/command_ops_api_test.py`
(Ops `/ops` e2e qua RBAC thật). Ops UI **visual screenshot** bị chặn bởi dev DB `alpha3s` drift (thiếu bảng
RBAC migration 016, provisioned ngoài runner) — ngoài scope M1; coverage bằng ops_api_test + `next build`.

## 8. Governance

**Submission 3 of maximum 3 (final)** (Directive §8) — remediation cho CA Consolidated Review 1 & 2
(`...REVIEW-SUBMISSION-1-VI.md`, `...REVIEW-SUBMISSION-2-VI.md`, cả hai CHANGES_REQUIRED). Production cần:
CA chấp nhận package, không P0/P1, migration/backup/forward-fix đạt, immutable SHA/tag, CA release decision riêng.

## 9. Submission 2 — Remediation CA Review 1

Base SHA `4ce5f3ab`. Remediation implementation SHA: `d74d5c57583d99b6790a366a7f03e0de8d2df1e7`. Timestamp: `2026-07-27 09:56+07:00`.
Tất cả trên nhánh dev, flag OFF, KHÔNG production.

| CR | Loại | Đã sửa | Evidence |
|---|---|---|---|
| CR-01 | blocker | `retry_outbox` giữ `attempt_count` đơn điệu, cấp budget `max_attempts+=8` (không reset 0) → hết trùng `attempt_no` | `command_ca_remediation_test` CR-01 (attempt_no [1,2,3]→delivered); `recovery_rbac_test` A |
| CR-02 | blocker | cancel cấm `delivering` (409) + worker compare-and-set `WHERE status='delivering' AND lease_owner=WORKER_ID` | `ca_remediation` CR-02; `recovery_rbac_test` cancel-delivering→409 |
| CR-03 | blocker | customer receipt qua **durable outbox** (messenger/telegram_customer, dedupe `order_receipt:{id}`); reply tức thì bỏ append (outbox là deliverer duy nhất) | `ca_remediation` CR-03 (commit ok + send fail → retry → delivered) |
| CR-04 | blocker | luồn **provider message id** (Messenger `mid` / Telegram `message_id`) → causation + `ai_stable_key`; sửa channel `telegram`→`telegram_customer` | unit `test_ai_stable_key_anchored_to_provider_message_id` |
| CR-05 | remediation | bỏ `audit_exists` guard → audit **bắt buộc** fail-closed | `ca_remediation` CR-05 (audit hỏng → mutation rollback) |
| CR-06 | remediation | replay: source `dead_lettered/cancelled` + `confirm_business_effect` bắt buộc + audit reason/source/confirm | `recovery_rbac_test` CR-06 (no-confirm→422, pending→409) |
| CR-07 | evidence | PR body + SHA đồng bộ; CI `deploy.yml` thêm `pull_request` trigger (status check, không deploy); appendix §10 | §10 + `.github/workflows/deploy.yml` |

## 10. Evidence appendix (reproducible)

Environment: `docker compose` — `alpha3s-api-1` Python 3.12.13, pytest 9.1.1, ruff; throwaway DB `m1_itest`
migrate 001–020. Mỗi evidence script chạy trên **fresh migrated DB**.

```text
# reset + migrate (Applied 20, validation pass, exit 0)
docker exec alpha3s-db-1 psql -U alpha3s -d postgres -c "DROP DATABASE IF EXISTS m1_itest;"
docker exec alpha3s-db-1 psql -U alpha3s -d postgres -c "CREATE DATABASE m1_itest;"
docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m1_itest -e PYTHONPATH=/srv -w /srv \
  alpha3s-api-1 python scripts/migrate.py up
# unit + lint
docker exec -e PYTHONPATH=/srv -w /srv alpha3s-api-1 python -m pytest -q      # 81 passed, exit 0
docker exec -w /srv alpha3s-api-1 ruff check app/                             # All checks passed, exit 0
# 9 evidence scripts — EXACT invocation cho từng cái (sau reset+migrate ở trên), tất cả exit 0:
docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@db:5432/m1_itest -e PYTHONPATH=/srv -w /srv \
  alpha3s-api-1 python scripts/<NAME>.py     # với <NAME> ∈:
#   command_order_service_test    (T1..T10: atomicity/dup/409/stock/qty/20-conc/mixed/new-customer race/override single-use)
#   command_gateway_test          (AI derive-key route / manual staff / ctx=None legacy / flag OFF legacy)
#   command_outbox_worker_test    (delivered / retry->dead-letter / terminal / timeout->unknown / reclaim)
#   command_http_test             (400 / 201 / 200 / 202+Retry-After / 409 / 422 / receipt 200+404)
#   command_recovery_rbac_test    (RBAC map+gate / CR-01 / CR-02 cancel-delivering / CR-06 replay negatives / audit fail-closed)
#   command_observability_test    (5 metrics + 4 alerts P1/P2 + log_event)
#   command_crash_recovery_test   (§13.1: fail-before-commit / retry-after-commit / worker-crash reclaim)
#   command_ops_api_test          (/ops e2e qua RBAC thật)
#   command_ca_remediation_test   (CR-01 / CR-02 CAS / CR-03 durable receipt / CR-04R / CR-05 audit fail-closed)
```

Migration rehearsal (remediation): fresh `001→020` Applied 20, validation pass, exit 0; existing-DB
`018→019/020` (migration 019/020 **không đổi** ở remediation — checksum giữ nguyên).

Checksums (sha256):
```text
migrations/019_command_bus.sql  11097820164b819513173df569484331c09ab9b261843e3044c213e6efd26813
migrations/020_command_rbac.sql bb68b5d64bf2a1af7c20b1e2753ab0e4f8dcabba077694aad599e38f3405c2e0
```

CI: `.github/workflows/deploy.yml` nay chạy `lint-test` (ruff + pytest, ubuntu-latest) trên `pull_request`
→ status check tại PR #1; job `deploy` gate `github.event_name=='push' && ref==main` → KHÔNG deploy khi PR.

## 11. Submission 3 — Remediation CA Review 2 (final)

Base `4ce5f3ab`. Remediation implementation SHA: `46e1169f9f6fae70eca06ef21eec62ae3ebfe70f` (commit 2026-07-27 17:27+07:00). Package correction: `2026-07-27 17:40+07:00`.
Submission cuối theo governance (3/3). Nhánh dev, flag OFF, KHÔNG production.

| CR | Đã sửa | Evidence |
|---|---|---|
| CR-04R blocker | `ai_stable_key` **bỏ tool_call_id**; gateway derive key = `sha256(channel + provider_message_id + type + version + business_identity)` (business_identity = request_hash của nội dung đơn đã chuẩn hoá). Cùng inbound message + cùng đơn → **cùng key** (effective-once qua re-execution dù LLM sinh tool-call mới); đơn khác nội dung → key khác (nhiều đơn/1 message vẫn phân biệt). | unit `test_ai_stable_key_no_tool_call_id_stable_across_reexecution`; `ca_remediation` CR-04R (cùng provider msg → 1 order+duplicate; msg khác → order mới) |
| CR-08 blocker | Order đã commit → reply tức thì **TRUNG TÍNH** (`reply_guard.finalize_customer_reply`), KHÔNG mang mã đơn/tổng tiền do LLM sinh; durable receipt (outbox, CR-03) là confirmation **duy nhất & đúng committed data**. | unit `test_finalize_customer_reply_neutral_when_order_created` (LLM ghi sai #999/5.000.000đ → khách nhận câu trung tính); receipt khớp committed |
| Metadata | title/frontmatter/heading + PR title → Submission 3; §10 exact per-script invocation; SHA/timestamp chuẩn `YYYY-MM-DD HH:mm+07:00` | doc này + PR body |

Verification (Submission 3, remediation SHA): **81 unit + 9 integration evidence scripts PASS**, ruff clean,
migration rehearsal fresh `001→020`. CI `lint-test` pass trên PR head Submission 3 (xem PR #1 checks).

**CR-04R closed:** cùng provider message, hai lần orchestration (tool-call ID khác) → cùng idempotency key
→ đúng một order; provider message khác → key khác → order mới. **CR-08 closed:** không có success
claim/order detail do LLM sinh tới khách; chỉ một authoritative confirmation (durable receipt).

## 12. Package-only correction (trước release gate)

Theo CA Consolidated Review 3 (DEVELOPMENT_ACCEPTED — RELEASE_GATE_PENDING), mục "Documentation
correction": đây là hiệu chỉnh **package-only**, KHÔNG phải Submission 4, KHÔNG đổi implementation.

- §7 #7: sửa mô tả cũ "tool_call_id + sender_id" → đã đóng CR-04/CR-04R (neo provider message id + business identity).
- §7b F5: sửa mô tả "audit fail-open khi thiếu bảng" → CR-05 đã chuyển audit sang bắt buộc/fail-closed.
- §11 timestamp: `18:30` (sau thời điểm CA review 17:35, bất hợp lý) → commit thực 17:27, correction 17:40 (+07).

Implementation SHA giữ nguyên `46e1169f9f6fae70eca06ef21eec62ae3ebfe70f`. `git diff 46e1169..<package-head>
-- '*.py'` RỖNG (chỉ thay tài liệu). Package-only head SHA: `17105ec2fd3660e2daf09f7c1fb4565e747cb3a7`.
