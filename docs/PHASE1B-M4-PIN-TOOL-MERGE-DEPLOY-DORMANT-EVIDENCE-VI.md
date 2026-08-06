---
document_id: PHASE1B-M4-PIN-TOOL-MERGE-DEPLOY-DORMANT-EVIDENCE-VI
title: "Phase 1B M4 — PIN Tool Merge/Deploy Dormant Evidence"
document_type: merge_deploy_evidence
owner: Dev
status: SUBMITTED — chờ CA review/closure
created_at: 2026-08-06
answers: CA-Docs/PHASE1B-M4-PIN-TOOL-MERGE-DEPLOY-DORMANT-GATE-VI.md (CA, OPEN_EXACT_HEAD_DORMANT_ONLY)
handoff: CA-Docs/PHASE1B-M4-DEV-CONTINUATION-HANDOFF-VI.md
authorized_head: 7a7e92f042ea0435c62872ab2bea9728a0fe613b
merge_commit: d8ef339d71f205ea57d0e489e9d95feed0aaa9b3
activation_performed: false
language: vi-VN
---

# M4 — PIN Tool Merge/Deploy Dormant Evidence

Đáp `PHASE1B-M4-PIN-TOOL-MERGE-DEPLOY-DORMANT-GATE-VI.md` (`OPEN_EXACT_HEAD_DORMANT_ONLY`,
`authorized_head=7a7e92f042ea0435c62872ab2bea9728a0fe613b`) và
`PHASE1B-M4-DEV-CONTINUATION-HANDOFF-VI.md`. PO xác nhận trực tiếp trong chat "Xác nhận cho dev
tiến hành đúng bước A→B→C trong handoff".

## 0. Ghi chú vận hành — ai chạy lệnh nào

Công cụ Claude Code (phiên Dev) tự chặn (bộ lọc auto-mode nội bộ) 2 lệnh mutating dù đã có xác
nhận PO trong chat: (1) merge PR qua GitHub API, (2) `migrate.py up` qua SSH trên production.
Hai lệnh này do chính PO (anh Hoài) tự chạy tay theo đúng nguyên văn lệnh Dev cung cấp — không
lệch bất kỳ tham số nào so với kế hoạch đã trình bày. Toàn bộ phần còn lại (backup, mọi truy vấn
đọc, health check, thu evidence) do Dev chạy qua SSH.

## 1. Merge execution report

| Mục | Giá trị |
|---|---|
| PR number | `#7` (`ledanghoai-bot/a3s`) |
| Pre-merge head | `7a7e92f042ea0435c62872ab2bea9728a0fe613b` — xác nhận lại NGAY TRƯỚC merge qua GitHub API (2 lần, cách nhau vài phút), khớp CHÍNH XÁC `authorized_head` của gate, delta=0 |
| Base branch trước merge | `main` @ `3e87bf91e1c0f95ae84c45bbf2d2cd958d2f6585` |
| Merge method | Merge commit (`merge_method=merge`) — đúng tiền lệ PR #4/#6 |
| Resulting merge commit | `d8ef339d71f205ea57d0e489e9d95feed0aaa9b3` |
| Merge timestamp | `2026-08-06T13:10:49Z` (GitHub API `merged_at`) |
| Merge commit parents | `3e87bf91e1c0f95ae84c45bbf2d2cd958d2f6585` (main cũ) + `7a7e92f042ea0435c62872ab2bea9728a0fe613b` (đúng authorized head) — xác nhận qua GitHub API, không có commit nào chen giữa |
| PR draft → ready-for-review | Qua GraphQL `markPullRequestReadyForReview` ngay trước merge (bắt buộc) |
| Required checks tại thời điểm merge | PR-head CI run `31073435188`: `lint-test` success; PR `mergeable_state`: `clean`; CA Review #4: `READINESS_ACCEPTED_MERGE_NOT_AUTHORIZED` → PO mở gate → `OPEN_EXACT_HEAD_DORMANT_ONLY` |
| PR post-merge state | `state=closed`, `merged=true`, `merge_commit_sha=d8ef339d...` khớp |

## 2. Deploy report

### 2.1. CI/CD tự động — thành công

Push-to-main run `31104714489` (trigger tự động sau merge):

| Job | Trạng thái | Bắt đầu | Kết thúc |
|---|---|---|---|
| `lint-test` | success | `13:11:02Z` | `13:12:13Z` |
| `deploy` (Deploy lên VPS qua SSH) | success | `13:12:15Z` | `13:12:39Z` |

### 2.2. Phát hiện: CI/CD deploy KHÔNG tự chạy migration

Sau khi job `deploy` xong, `migrate.py status` trên VPS cho thấy `040/041/042` vẫn `PENDING` —
CI/CD chỉ cập nhật code + restart container, đúng như tiền lệ PR #4 (migration luôn là bước tay
riêng, không nằm trong `deploy.sh`). Xử lý đúng quy trình đã dùng: backup thủ công trước, sau đó
migrate tay.

### 2.3. Backup trước khi thao tác DB

`/root/bin/backup_db.sh` chạy NGAY TRƯỚC migration (đúng quy ước §12 runbook): kết quả
`alpha3s_2026-08-06_2016.sql.gz` (902677 bytes, timestamp `2026-08-06 20:16` giờ VN =
`13:16Z`). Backup hằng ngày tự động (cron 03:00 VN) không đổi.

### 2.4. Migration execution (PO chạy tay, lệnh do Dev cung cấp nguyên văn)

```
$ ssh -i ~/.ssh/alpha3s_vps root@160.30.157.235 "cd /srv/alpha3s && docker exec alpha3s-api-1 python scripts/migrate.py up"
Applying 040_m4_pin_bootstrap (transactional=True) ...
  OK 040_m4_pin_bootstrap
Applying 041_m4_pin_bind_approval (transactional=True) ...
  OK 041_m4_pin_bind_approval
Applying 042_m4_pin_token_approval_link (transactional=True) ...
  OK 042_m4_pin_token_approval_link
Applied 3 migration(s).
  validation OK: scripts/operational_seed_validation.sql
  validation OK: scripts/m3_contract_validation.sql
Post-migration validations pass (2 file).
```

Chạy giữa `13:16Z` (ngay sau backup) và `13:25:38Z` (thời điểm Dev bắt đầu chạy lại evidence
script postcheck bên dưới, đã thấy `040/041/042 applied`). Cả 3 migration transactional — mỗi
migration tự có `DO $$ ... postcondition fail-closed` block (xem `migrations/040-042_*.sql`),
không có migration nào thất bại giữa chừng round này.

### 2.5. Xác nhận deployed HEAD

Snapshot đầy đủ (raw, toàn bộ §3-11 dưới): `E:\Alpha3s\dev\rehearsal-support\
evidence-pin-tool-merge-deploy-dormant\merge_deploy_dormant_snapshot.log` (sha256
`cc61387b1a6940a1ab256487acf21839d0ad38966b1b665fef597fd938293154`, chạy lúc `2026-08-06T13:25:38Z`
– `13:25:40Z`, sau migration).

| Mục | Giá trị |
|---|---|
| VPS HEAD (`git rev-parse HEAD` tại `/srv/alpha3s`) | `d8ef339d71f205ea57d0e489e9d95feed0aaa9b3` — khớp đúng merge commit |
| Migration `040/041/042` | `applied` (postcheck, sau khi chạy tay §2.4) |

## 3. Schema postconditions (migrations 040-042)

| Kiểm tra | Kết quả |
|---|---|
| `m4_stage0p_pin_bootstrap_tokens.approval_id` NOT NULL | `true` |
| `approval_id` có FK tới `m4_stage0p_pin_bind_approvals` | `true` |
| Bảng `m4_stage0p_pin_bind_approvals` tồn tại | `true` |
| Index `m4_pin_bind_approval_target_idx` tồn tại | `true` |
| CHECK `m4_pin_bootstrap_ttl_bounded` (1-30 phút) tồn tại | `true` |
| Index `m4_pin_bootstrap_approval_idx` tồn tại | `true` |

## 4. Grants check (không GRANT cho PUBLIC/alpha3s_app)

| Kiểm tra | Kết quả |
|---|---|
| `alpha3s_app` SELECT trên `m4_stage0p_pin_bootstrap_tokens` | `false` |
| `alpha3s_app` INSERT trên `m4_stage0p_pin_bootstrap_tokens` | `false` |
| `alpha3s_app` SELECT trên `m4_stage0p_pin_bind_approvals` | `false` |
| `alpha3s_app` INSERT trên `m4_stage0p_pin_bind_approvals` | `false` |
| `PUBLIC` SELECT trên cả 2 bảng | `false` / `false` |

## 5. Production OFF-state (dormant, đúng ràng buộc gate §3)

| Mục | Giá trị |
|---|---|
| `capture_enabled` | `false` |
| Credential rows cho staff_id 3/4/5 (`m4_stage0p_actor_credentials`) | `0` |
| `m4_stage0p_pin_bind_approvals` (tổng) | `0` — chưa record approval nào |
| `m4_stage0p_pin_bootstrap_tokens` (tổng) | `0` — chưa tạo token nào |
| `m4_stage0p_capture_approvals` (tổng) | `0` |
| Active transcript signing key (`retired_at IS NULL`) | `0` |
| Active signing-auth key (`retired_at IS NULL`) | `0` |
| Synthetic customer residual (`psid LIKE 'm4synthrehearsalv1_%'`) | `0` |
| Biến môi trường `M4_*`/`ENABLE_M4*` trong container `api` | không có |
| Tiến trình signer/collector/rehearsal_runner | không có (kiểm cả trong container lẫn host) |

## 6. Health & container status

| Kiểm tra | Kết quả |
|---|---|
| `docker compose ps` (8 container) | Tất cả `Up` — `api`/`dashboard`/`worker`/`telegram_bot`/`telegram_customer_bot` rebuilt (~13 phút tại thời điểm snapshot); `caddy`/`db`/`redis` không đổi (13 ngày) |
| `curl http://localhost:8000/health` (internal) | `200` |
| `curl https://a3s.robanme.com/health` (external, qua Caddy/HTTPS) | `200` |
| `redis-cli LLEN dead_letter:messages` | `0` |
| `docker compose logs api --tail 30` | Khởi động sạch, `Application startup complete` x2, không traceback |

## 7. Xác nhận không customer-data access / không automatic workload

Toàn bộ thao tác round này (merge, deploy, backup, migration, mọi truy vấn evidence) KHÔNG
đọc/copy/xử lý nội dung tin nhắn khách hàng thật — chỉ chạm: schema DDL (3 migration), truy vấn
đếm/trạng thái (`count(*)`, `has_table_privilege`, `to_regclass`...), biến môi trường, tiến
trình, health-check endpoint, container/log status. `capture_enabled=false` + 0 key active + 0
approval + 0 token đảm bảo không có đường vận hành nào của PIN tool có thể tự kích hoạt.

## 8. Rollback readiness

- Backup thủ công MỚI (`alpha3s_2026-08-06_2016.sql.gz`, trước migration) + 14 bản backup tự
  động gần nhất sẵn sàng cho restore.
- Rollback code: `git reset --hard 3e87bf91e1c0f95ae84c45bbf2d2cd958d2f6585` (main trước merge) +
  `bash scripts/deploy.sh`.
- Rollback migration: mỗi migration 040/041/042 tự có block `-- rollback:` DROP theo đúng quy
  ước `migrate.py` đã dùng suốt dự án — migration chỉ THÊM object mới (bảng/cột/index/constraint
  M4), không sửa/xóa object M0-M3.
- Operator: PO (2 lệnh mutating: merge PR, `migrate.py up`) + Dev/Claude Code (backup, mọi bước
  đọc), theo đúng handoff §2-3 và xác nhận PO trong chat.
- Timestamp: merge `2026-08-06T13:10:49Z`; CI/CD deploy `13:12:15Z`-`13:12:39Z`; backup
  `~13:16Z`; migration `13:16Z`-`13:25Z` (bracket, log `migrate.py` không tự in timestamp);
  evidence postcheck cuối `13:25:38Z`-`13:25:40Z` (giờ UTC).

## 9. Đề nghị

CA review evidence §1-6 để operationally close bước merge/deploy-dormant PIN tool này, theo
đúng trình tự Review #4 §5 (bước 1-2 nay hoàn tất). Dev KHÔNG suy diễn quyền activation từ báo
cáo này — Internal Synthetic Activation Gate vẫn NOT OPEN, PIN thật vẫn CHƯA đặt cho ai, chờ PO
re-baseline deployed commit + xác nhận/gia hạn activation window + CA kiểm preconditions cuối
theo đúng handoff §5.
