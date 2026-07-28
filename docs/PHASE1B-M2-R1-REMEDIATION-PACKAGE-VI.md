---
id: A3S-PHASE1B-M2-DEV-R1-REMEDIATION-001
title: Alpha3S Phase I-B M2 — F-R1-01 Remediation Package (DEV)
document_type: remediation_package
milestone: M2
responds_to: A3S-PHASE1B-M2-CA-R1-EVIDENCE-REVIEW-001
finding: F-R1-01
accepted_rc_base_sha: 9b49628a83ba1fe02b97913f20f33e4883560b5b
branch_point_sha: 71425fdd944d348fde90110a99f74d7811e6dbc5
implementation_new_rc_sha: 66db876e559ac79756d06519dc4e5f0ddc53791d
branch: remediation/m2-r1-seed-validation-split
language: vi-VN
---

# M2 — F-R1-01 Remediation Package

CA quyết (`PHASE1B-M2-CA-R1-EVIDENCE-REVIEW-001` §4): **tách fresh-seed assertion khỏi operational
post-migration validation**. Package này thực thi đúng §4.1 + §4.2, không vi phạm điều cấm §4 (không sửa
price tier prod, không skip validation, không fail-open, không manifest tạm, không waiver).

## 1. SHA (§6.1)

| Loại | SHA |
|---|---|
| Accepted RC base (migrations/app đối chiếu) | `9b49628a83ba1fe02b97913f20f33e4883560b5b` |
| Branch point (docs-only tail của RC, = M2 PR head) | `71425fdd944d348fde90110a99f74d7811e6dbc5` |
| **Implementation (NEW RC)** | `66db876e559ac79756d06519dc4e5f0ddc53791d` |
| Package (docs-only successor của NEW RC) | = commit thêm doc này, ghi ở PR head / `git log` |

Implementation change tạo **NEW RC** `66db876`. M2 Development Acceptance tại `9b49628` KHÔNG tự mở rộng —
CA review exact delta.

## 2. Changed-file manifest (§6.2)

| File | Loại | Nội dung |
|---|---|---|
| `scripts/operational_seed_validation.sql` | **NEW** | Operational existing-safe validation (§4.1) |
| `scripts/fresh_db_seed_validation.sql` | MOD (chỉ header) | Canonical assertions **byte-unchanged**; header ghi rõ fresh-only |
| `scripts/baseline_manifest.json` | MOD | `post_migration_validations`→operational; +`fresh_install_validations`→fresh |
| `scripts/baseline_manifest_13.json` | MOD | Split y hệt (đồng bộ) |
| `scripts/migrate.py` | MOD (additive) | +`run_fresh_validations` + `cmd_fresh_validate` + dispatch `fresh-validate`; `up`/`baseline`/`validate` KHÔNG đổi hành vi |
| `scripts/m2_r1_remediation_test.py` | **NEW** | Evidence harness (fresh/existing/negative/full-chain) |
| `docs/PHASE1B-PROD-MIGRATION-RUNBOOK-VI.md` | MOD | §3.1 hai validation layers |

**KHÔNG** đụng `migrations/`, `app/`.

## 3. Proof migrations `001–028` + `app/` không đổi (§6.3)

```text
git diff --stat 9b49628 -- migrations/   -> (empty)  = UNCHANGED
git diff --stat 9b49628 -- app/          -> (empty)  = UNCHANGED
```

## 4. Thiết kế split

- **Operational** (`operational_seed_validation.sql`, trong `post_migration_validations` → `migrate.py up`
  LUÔN chạy, fresh + existing): 1 product `3S-100G` · description approved · không "100% Robusta" ·
  `serving_size_g NULL` · `net_weight_g=100` · **≥1** price tier · structural invariant tier (`min_qty≥1`,
  `unit_price_vnd>0`; dup `min_qty` đã bị chặn bởi `UNIQUE(product_id,min_qty)`). **KHÔNG** exact count/canonical.
- **Fresh-install-only** (`fresh_db_seed_validation.sql`, exact `1/170k,5/160k,20/140k`, đúng 3 tier): rời khỏi
  `up`; đặt ở manifest key `fresh_install_validations`; gọi tường minh `migrate.py fresh-validate`
  (command riêng, **không heuristic đoán môi trường**). Fresh bootstrap = `up` + `fresh-validate`; existing prod = chỉ `up`.

## 5. Evidence tests — `scripts/m2_r1_remediation_test.py` (20/20 PASS)

Chạy: `docker run --rm --network alpha3s_default -v <worktree>:/srv -w /srv --entrypoint python alpha3s-api scripts/m2_r1_remediation_test.py`

- **[1] Fresh (§6.4):** `migrate.py up` exit 0 (operational chạy trong up); `fresh-validate` (exact canonical) exit 0; head=028.
- **[2] Existing + 2 extra valid tiers = 5 tier như prod (§6.5):** `migrate.py up` **exit 0** (operational tolerate);
  extra tiers **PRESERVED** (count=5); `fresh-validate` **exit 1** (canonical exact reject) → minh chứng vì sao canonical ngoài `up`.
- **[3] Negative existing-data (§6.6):** operational **REJECT** — wrong/unapproved description · non-NULL serving ·
  missing product (`3S-100G` absent) · no price tier. Control: operational PASS trên clean canonical.
- **[4] Full-chain 018→028 synthetic (§6.7):** existing tại `018` → `migrate.py up` 019..028 **exit 0** (operational in-path) → head=028 count=28.
- **[5] Negative qua runner deploy path:** `migrate.py validate` **exit 1** trên wrong description (`VALIDATION FAIL`).

## 6. Regression + CI (§6.8)

| Check | Kết quả | Exit |
|---|---|---|
| `ruff check app scripts/migrate.py scripts/m2_r1_remediation_test.py` (0.16.0) | All checks passed | 0 |
| `pytest -q` (tests/) | **81 passed** | 0 |
| `m2_r1_remediation_test.py` | 20/20 PASS | 0 |
| `m2_existing_apply_rehearsal.py` (accepted) | PASS — data preserved | 0 |

CI (`.github/workflows`) chạy `ruff check app` + `pytest -v` — sẽ chạy trên PR.

## 7. Commands / environment / timestamps / exit codes (§6.9)

- Environment: local dev, image `alpha3s-api`, throwaway container mount worktree
  `remediation/m2-r1-seed-validation-split` @ `66db876`, network `alpha3s_default` (postgres `db:5432`,
  throwaway DBs `r1_fresh/r1_exist/r1_chain/r1_negrun`, drop sau chạy). KHÔNG chạm production.
- Consolidated run: `TS_START=2026-07-28 10:15:26 +0700` … `TS_END=2026-07-28 10:16:19 +0700`;
  RUFF_EXIT=0 · PYTEST_EXIT=0 (81 passed) · REMEDIATION_EXIT=0 · REHEARSAL_EXIT=0.
- Sanitized artifact paths (scratchpad, no PII): `r1_remediation_evidence_out.txt` (consolidated log).
- No PII: output chỉ rc/count/boolean/head.

## 8. Runbook (§6.10)

`docs/PHASE1B-PROD-MIGRATION-RUNBOOK-VI.md` §3.1 ghi rõ 2 lớp: `up`→operational (existing-safe, deploy path);
`fresh-validate`→canonical (fresh-only, tường minh). Existing prod deploy KHÔNG chạy `fresh-validate`.

## 9. R1 re-run (chưa thực hiện — cần CA cấp session, §7 review)

Sau khi CA chấp nhận NEW RC `66db876`: CA cấp R1 re-run production-access session mới → DEV backup mới +
restore mới + rehearsal exact deploy path → `migrate.py up` **phải exit 0** trên restored production artifact
(giá thật 5 tier). Production DB thật vẫn KHÔNG migrate trong R1. **DEV chưa chạm production lại** (đúng §5 cấm).

## 10. Go/No-Go

Đề xuất: NEW RC `66db876` sẵn sàng CA re-review. Sau khi accepted → R1 re-run → nếu `up` exit 0 trên restored
prod → R1 PASS → Stage R2 Go/No-Go.
