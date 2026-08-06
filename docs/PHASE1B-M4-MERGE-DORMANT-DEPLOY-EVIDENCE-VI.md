---
id: A3S-PHASE1B-M4-MERGE-DORMANT-DEPLOY-EVIDENCE-001
title: Alpha3S Phase I-B M4 — Merge Execution Report + Dormant Deployment Report
document_type: merge_deploy_evidence
owner: Dev
status: SUBMITTED — chờ CA review/closure
created_at: 2026-08-05
answers: PHASE1B-M4-MERGE-DORMANT-DEPLOY-GATE-DIRECTIVE-VI.md (CA, GATE_OPEN, gated_head b391db242161990d5468b11bfdf2a08ea42544d3)
po_decision: PHASE1B-M4-PO-PRODUCT-COMPLETION-PATH-DECISION-VI.md (PO, APPROVED, approved_head b391db242161990d5468b11bfdf2a08ea42544d3)
governing_review: PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-14-VI.md (CA, TECHNICAL_ACCEPTED_DEV_TEST)
language: vi-VN
---

# M4 — Merge Execution Report + Dormant Deployment Report

Đáp lại `PHASE1B-M4-MERGE-DORMANT-DEPLOY-GATE-DIRECTIVE-VI.md` (`GATE_OPEN`, gated_head
`b391db242161990d5468b11bfdf2a08ea42544d3`). PO đã xác nhận trực tiếp tiến hành merge +
dormant deploy trong phiên làm việc.

## 1. Merge execution report

| Mục | Giá trị |
|---|---|
| PR number | `#4` (`ledanghoai-bot/a3s`) |
| Pre-merge head | `b391db242161990d5468b11bfdf2a08ea42544d3` (khớp CHÍNH XÁC `gated_head`/`approved_head`, xác nhận lại NGAY TRƯỚC merge qua GitHub API — delta = 0) |
| Base branch trước merge | `main` @ `dc839ca036baef6a5f5cee3026e0741e140b71d9` |
| Merge method | Merge commit (`merge_method=merge`) — giữ nguyên toàn bộ lịch sử 14 round Technical Correction, khớp tiền lệ chính repo (`main` hiện tại trước đó cũng là merge commit từ PR #3) |
| Resulting merge commit | `e96a32079bffedc8f6dbdeb3bc2006f2cf5ef77a` |
| Merge timestamp | `2026-08-05T05:24:32Z` |
| Required checks tại thời điểm merge | `lint-test`: success; PR `mergeable_state`: `clean`; Review #14: `TECHNICAL_ACCEPTED_DEV_TEST`; CI run `30637445480`: success |
| Xác nhận không có delta ngoài gated head | Có — `git fetch`/API xác nhận PR head vẫn `b391db2` ngay trước lệnh merge, không có commit/rebase/force-push nào chen giữa |
| PR draft → ready-for-review | Thực hiện qua GraphQL `markPullRequestReadyForReview` ngay trước merge (bắt buộc — GitHub không cho merge PR đang draft) |
| PR post-merge state | `closed`, `merged=true`, `merge_commit_sha=e96a3207...` khớp |

## 2. Dormant deployment report

### 2.1. Sự cố hạ tầng tự phát hiện (khai báo minh bạch)

CI/CD job `deploy` (run `30978013004`, trigger tự động khi push `main` sau merge) **THẤT
BẠI** — không liên quan code: `ssh: connect to host *** port 22: Connection timed out` (SSH
từ GitHub Actions hosted runner tới VPS timeout sau ~2 phút). Xác nhận VPS bản thân vẫn
khỏe mạnh: SSH trực tiếp từ môi trường Dev (key `alpha3s_vps` đã cấu hình sẵn) kết nối
THÀNH CÔNG ngay lập tức, `uptime` 12 ngày, code VPS vẫn nguyên trạng pre-merge (`dc839ca`,
chưa bị đụng tới — sự cố xảy ra TRƯỚC khi lệnh remote nào chạy). Đây là lỗi kết nối
mạng/routing thoáng qua giữa runner GitHub và VPS, không phải lỗi code M4 hay lỗi VPS.

Xử lý: dùng đường **"Cách TAY"** đã tài liệu hóa sẵn tại `docs/VPS-RUNBOOK-VI.md` §4.2
(dành đúng cho tình huống "CI đang hỏng") — SSH trực tiếp, chạy lại NGUYÊN VĂN chuỗi lệnh
`deploy.sh` vẫn dùng (`git fetch && git reset --hard origin/main && bash scripts/deploy.sh`),
không có sai khác nào so với đường CI tự động ngoài việc do Dev chạy tay qua SSH thay vì
runner GitHub chạy hộ.

### 2.2. Artifact / nguồn

| Mục | Giá trị |
|---|---|
| Source commit | `e96a32079bffedc8f6dbdeb3bc2006f2cf5ef77a` (merge commit PR #4) |
| Image build | `docker compose -f docker-compose.prod.yml up -d --build` tại chỗ trên VPS (dự án không dùng registry/tag riêng — build trực tiếp từ source mỗi lần deploy, đúng quy ước sẵn có) |
| Services rebuilt | `api`, `worker`, `dashboard`, `telegram_bot`, `telegram_customer_bot` (đúng biến `SERVICES` trong `scripts/deploy.sh`, KHÔNG đổi) |
| Môi trường/target | VPS production `160.30.157.235`, thư mục `/srv/alpha3s` |

### 2.3. Backup trước khi thao tác DB

Chạy backup thủ công (`/root/bin/backup_db.sh`) NGAY TRƯỚC khi đụng tới bất kỳ thay đổi
nào (đúng quy ước §12 runbook "trước khi làm việc nguy hiểm với DB") — kết quả:
`2026-08-05T12:30:42+07:00 OK /root/backups/alpha3s_2026-08-05_1230.sql.gz 860K`. Backup
hằng ngày tự động (cron 03:00 VN) tiếp tục không đổi, giữ 14 bản gần nhất.

### 2.4. Migration precheck / execution / postcondition

**Precheck** (`python scripts/migrate.py status` — chạy TRƯỚC `up`): `001_init` →
`037_retention_policy_immutability` đều `applied`; `038_m4_slot_store` và
`039_m4_stage0p` đều `PENDING` — đúng trạng thái mong đợi, không có drift.

**Execution** (`python scripts/migrate.py up`):
```
Applying 038_m4_slot_store (transactional=True) ... OK 038_m4_slot_store
Applying 039_m4_stage0p (transactional=True) ... OK 039_m4_stage0p
Applied 2 migration(s).
  validation OK: scripts/operational_seed_validation.sql
  validation OK: scripts/m3_contract_validation.sql
Post-migration validations pass (2 file).
```
Exit code `0`. Cả 2 migration transactional — thất bại giữa chừng sẽ tự rollback (không có
migration nào thất bại thực tế round này).

**Postcheck**: `migrate.py status` xác nhận lại `038`/`039` đều `applied`.

### 2.5. Xác nhận flags/config OFF trước và sau deploy

| Kiểm tra | Kết quả |
|---|---|
| `m4_stage0p_control.capture_enabled` (DB, nguồn THẬT của kill-switch) | `f` (false) — xác nhận TRỰC TIẾP qua `SELECT` sau migration |
| Biến môi trường `M4_*`/`ENABLE_M4*` trong `.env` production | KHÔNG có biến nào được set — toàn bộ 3 flag code-level (`m4_pii_shadow`, `m4_trusted_pii_path`, `m4_stage0p_capture_enabled`) dùng mặc định Python `False` |
| `m4_stage0p_signing_socket` | Rỗng (mặc định `""`) — signing service KHÔNG được cấu hình chạy trên VPS, nên dù `capture_enabled` có vô tình bật, collector vẫn fail-closed ngay tại bước ký (lớp phòng thủ độc lập thứ 2, đúng thiết kế T10-02 "fail closed, không fallback về ký trong-process") |
| Cron job production | CHỈ có `pg_backup_daily.sh` (backup hằng ngày, không đổi) — KHÔNG có job/scheduled trigger nào liên quan M4/stage0p |
| Automatic trigger trong `app/workers/` | Rà soát (`grep -rn stage0p\|m4_`) — KHÔNG có kết quả nào ngoài import tĩnh, không có task định kỳ đăng ký |

### 2.6. Health checks

| Kiểm tra | Kết quả |
|---|---|
| `curl http://localhost:8000/health` (trong VPS) | `200` |
| `curl https://a3s.robanme.com/health` (từ ngoài, qua Caddy/HTTPS) | `200` |
| `docker compose ps` (8 container) | Tất cả `Up` — `api`/`dashboard`/`worker`/`telegram_bot`/`telegram_customer_bot` mới rebuild (~1 phút), `caddy`/`db`/`redis` không đổi (12 ngày, không bị đụng) |
| `docker compose logs api --tail 30` | Khởi động sạch, `Application startup complete` x2 (2 worker process Uvicorn), KHÔNG có traceback/lỗi |
| `redis-cli LLEN dead_letter:messages` | `0` — không có tin nhắn kẹt sau deploy |

### 2.7. Xác nhận không customer-data access / không automatic workload

Toàn bộ thao tác round này (merge, git reset, docker build/restart, migration, verification
query) KHÔNG đọc/copy/xử lý bất kỳ nội dung tin nhắn khách hàng thật nào — chỉ chạm:
schema DDL (migration), 1 hàng cấu hình singleton (`m4_stage0p_control`), biến môi trường,
health-check endpoint, container/log status. `capture_enabled=false` + signing socket rỗng
đảm bảo KHÔNG có đường vận hành nào của M4 Stage 0P có thể tự kích hoạt đọc nội dung khách
hàng thật kể cả nếu có traffic thật đi qua hệ thống trong lúc deploy.

### 2.8. Rollback readiness

- Backup thủ công MỚI (`alpha3s_2026-08-05_1230.sql.gz`) + 14 bản backup tự động gần nhất
  sẵn sàng cho §6.2 runbook (restore).
- Rollback code: `git reset --hard dc839ca036baef6a5f5cee3026e0741e140b71d9` (commit tốt gần
  nhất trước merge) + `bash scripts/deploy.sh`, đúng quy trình §11 runbook.
- Rollback migration: KHÔNG cần thiết trong tình huống thường (migration 038/039 chỉ THÊM
  object mới — bảng/hàm/role M4 — không sửa/xóa bất kỳ object nào thuộc M0-M3; nếu cần lùi
  thật sự, migration 039 tự có `-- rollback:` DROP block theo đúng quy ước migrate.py đã dùng
  suốt dự án).
- Operator: Dev (phiên làm việc này), theo ủy quyền trực tiếp của PO ("Tiến hành merge +
  dormant deploy") + `PHASE1B-M4-MERGE-DORMANT-DEPLOY-GATE-DIRECTIVE-VI.md`.
- Timestamp: merge `2026-08-05T05:24:32Z`; backup `2026-08-05T05:30:42Z`; migration
  `~2026-08-05T05:34:45Z`; health check cuối cùng `~2026-08-05T05:36Z` (giờ UTC, tương ứng
  giờ VN +7 trong log backup ở trên).

## 3. Đề nghị

CA review 3 mục theo đúng §5 directive: (1) merge execution evidence (§1); (2) dormant
deployment evidence (§2.2-2.6); (3) post-deploy OFF-state (§2.5, §2.7) — để operationally
close bước merge/dormant deploy. Dev KHÔNG suy diễn quyền internal/public activation từ báo
cáo này — activation (kể cả synthetic rehearsal) vẫn chờ hồ sơ PO approval reference + CA
Activation Gate riêng theo đúng §5 directive và §3 PO Decision Record.
