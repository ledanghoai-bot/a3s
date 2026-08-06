---
document_id: PHASE1B-M4-REHEARSAL-TOOLING-MERGE-DEPLOY-DORMANT-EVIDENCE-VI
title: "Phase 1B M4 — Rehearsal Tooling Merge/Deploy Dormant Evidence"
document_type: merge_deploy_evidence
owner: Dev
status: SUBMITTED — chờ CA review/closure
created_at: 2026-08-06
answers: PHASE1B-M4-REHEARSAL-TOOLING-MERGE-DEPLOY-DORMANT-GATE-VI.md (CA, OPEN_EXACT_HEAD_DORMANT_ONLY)
gated_head: 77e17f656b411a37abd87724a1543236328d745f
merge_commit: 3e87bf91e1c0f95ae84c45bbf2d2cd958d2f6585
activation_performed: false
language: vi-VN
---

# M4 — Rehearsal Tooling Merge/Deploy Dormant Evidence

Đáp `PHASE1B-M4-REHEARSAL-TOOLING-MERGE-DEPLOY-DORMANT-GATE-VI.md` (`OPEN_EXACT_HEAD_DORMANT_ONLY`,
`authorized_head=77e17f656b411a37abd87724a1543236328d745f`). PO xác nhận trực tiếp "Tiến hành
merge + dormant deploy" trong phiên làm việc.

## 1. Merge execution report

| Mục | Giá trị |
|---|---|
| PR | `#6` (`ledanghoai-bot/a3s`) |
| Pre-merge head | `77e17f656b411a37abd87724a1543236328d745f` — xác nhận lại NGAY TRƯỚC merge qua GitHub API, khớp CHÍNH XÁC `authorized_head` của gate, delta=0 |
| Base branch trước merge | `main` @ `e96a32079bffedc8f6dbdeb3bc2006f2cf5ef77a` (không đổi kể từ dormant deploy trước) |
| Merge method | Merge commit (`merge_method=merge`) — đúng tiền lệ các merge M4 trước |
| Resulting merge commit | `3e87bf91e1c0f95ae84c45bbf2d2cd958d2f6585` |
| Merge timestamp | 2026-08-06 (giờ merge API trả về, xem log) |
| PR draft → ready | qua GraphQL `markPullRequestReadyForReview` ngay trước merge |
| Required checks tại thời điểm merge | code head CI `31014966828`: success; PR head CI `31015313670`: success; CA Readiness Review #4: `READINESS_ACCEPTED_ACTIVATION_NOT_AUTHORIZED` |

## 2. Deploy report

### 2.1. CI/CD tự động — THÀNH CÔNG (khác lần trước)

Khác với lần dormant deploy đầu tiên (CI run `30978013004` gặp SSH timeout, phải chuyển sang
tay), lần này **CI/CD tự động chạy trọn vẹn**: push-to-main run `31064548278` —
`lint-test`: **success**, `deploy`: **success** (bước "Deploy lên VPS qua SSH" hoàn tất bình
thường, không cần can thiệp tay).

### 2.2. Xác nhận trạng thái sau deploy (SSH read-only, snapshot đầy đủ đính kèm)

Snapshot đầy đủ: `E:\Alpha3s\dev\rehearsal-support\evidence-merge-deploy-dormant\
merge_deploy_dormant_snapshot.log` (sha256
`3125019853fed28f1885486d95e7baf00e4bd5ea246b14e8a137a9118464aca0`, snapshot lúc
`2026-08-06T02:06:27Z`, sau đó thêm health-check ngay sau đó cùng phiên SSH).

| Mục | Giá trị |
|---|---|
| VPS HEAD | `3e87bf91e1c0f95ae84c45bbf2d2cd958d2f6585` — khớp đúng merge commit |
| `capture_enabled` | `false` |
| Synthetic customer residual (`m4synthrehearsalv1_%`) | `0` |
| Transcript signing key active | `0` |
| Signing-auth key active | `0` |
| `m4_stage0p_capture_approvals` (tổng số dòng, kể cả cũ) | `0` — CHƯA từng có approval nào được record/consume trên production |
| Biến môi trường `M4_*`/`ENABLE_M4*` | `0` (không có) |
| Tiến trình signer/collector/rehearsal runner | không có tiến trình nào đang chạy |
| Container | 5 container app (`api`/`worker`/`dashboard`/`telegram_bot`/`telegram_customer_bot`) rebuilt sạch (`Up 40 seconds` tại thời điểm snapshot); `caddy`/`db`/`redis` không đổi (13 ngày, không bị đụng) |
| Migration | `038_m4_slot_store`/`039_m4_stage0p` vẫn `applied` từ lần dormant deploy trước — PR này KHÔNG thêm migration mới (chỉ script vận hành + tài liệu) |
| Health internal | `200` |
| Health external (`https://a3s.robanme.com/health`) | `200` |
| Dead-letter queue | `0` |
| Log khởi động `api` | sạch, `Application startup complete` x2, không traceback |

### 2.3. Không có approval_ref nào được tạo/tiêu thụ

Đúng ràng buộc gate §3 "không tạo hoặc tiêu thụ approval_ref" — xác nhận
`m4_stage0p_capture_approvals` trên production có **0 dòng** (chưa từng ghi, không chỉ "không
active"). Runner (`m4_stage0p_rehearsal_runner.py`) đã deploy lên VPS như 1 file script tĩnh
trong `/srv/alpha3s/scripts/` — KHÔNG có tiến trình nào gọi tới nó.

## 3. Đối chiếu ràng buộc gate §3 (toàn bộ giữ nguyên)

- capture/feature flags: OFF (xác nhận §2.2).
- KHÔNG provision transcript/signing-auth/sample key: xác nhận 0 key active, không có
  `M4_SAMPLE_KEY_B64`/`M4_TRANSCRIPT_HMAC_KEY_B64`/`M4_SIGNING_AUTH_VERIFY_KEY_B64` trong môi
  trường VPS.
- KHÔNG seed synthetic data: 0 customer mang psid `m4synthrehearsalv1_%`.
- KHÔNG start signer/collector/rehearsal runner: xác nhận không có tiến trình nào.
- KHÔNG tạo/tiêu thụ approval_ref: xác nhận bảng approval rỗng.
- KHÔNG truy cập production customer data: toàn bộ thao tác chỉ chạm merge/deploy pipeline +
  truy vấn đếm/trạng thái (không SELECT nội dung khách hàng).
- KHÔNG public activation: không có gì được "activate".
- KHÔNG dùng gate này như Internal Synthetic Activation Gate: xác nhận rõ trong §4 dưới.

## 4. Xác nhận rõ ràng — CHƯA có activation

Đúng gate §5: **Internal Synthetic Activation Gate vẫn NOT OPEN**. Merge + dormant deploy này
CHỈ đưa code vận hành (script generator/runner/test) vào `main`/production runtime ở dạng TĨNH,
không tự kích hoạt bất kỳ luồng nào. Bước tiếp theo (nếu có) là PO cấp `approval_ref`/scope/
window/3-principal riêng, CA kiểm preconditions rồi phát hành Internal Synthetic Activation Gate
— hồ sơ này không suy diễn quyền đó.

## 5. Đề nghị

CA review evidence §1-3 để operationally close bước merge/deploy-dormant này, theo đúng trình tự
5 bước đã nêu trong `PHASE1B-M4-INTERNAL-SYNTHETIC-REHEARSAL-READINESS-REVIEW-4-VI.md` §5
(bước 1-2 nay hoàn tất; bước 3-5 chờ PO/CA quyết định riêng).
