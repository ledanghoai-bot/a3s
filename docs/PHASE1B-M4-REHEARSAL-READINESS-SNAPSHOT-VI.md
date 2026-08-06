---
document_id: PHASE1B-M4-REHEARSAL-READINESS-SNAPSHOT-VI
title: "Phase 1B M4 — Readiness Snapshot for Internal Synthetic Activation Gate"
document_type: activation_readiness_snapshot
owner: Dev
status: SUBMITTED — chờ CA review, mở Internal Synthetic Activation Gate
created_at: 2026-08-06
answers:
  - PHASE1B-M4-REHEARSAL-PRINCIPAL-ASSIGNMENT-REVIEW-1-VI.md (CA, P-M4-PA-01/02/03)
  - PHASE1B-M4-INTERNAL-SYNTHETIC-REHEARSAL-PO-DECISION-RECORD-VI.md (PO, §6)
deployed_commit: 3e87bf91e1c0f95ae84c45bbf2d2cd958d2f6585
approval_ref: m4-internal-synthetic-rehearsal-20260806-01
activation_performed: false
language: vi-VN
---

# M4 — Readiness Snapshot cho Internal Synthetic Activation Gate

Đáp `PHASE1B-M4-REHEARSAL-PRINCIPAL-ASSIGNMENT-REVIEW-1-VI.md` (P-M4-PA-01/02/03) và
`PHASE1B-M4-INTERNAL-SYNTHETIC-REHEARSAL-PO-DECISION-RECORD-VI.md` §6 — **1 readiness snapshot
duy nhất** theo đúng format PO Decision §6 yêu cầu.

## 0. Xác nhận phạm vi

CHƯA record `approval_ref`, CHƯA provision key, CHƯA seed/start bất kỳ gì. Toàn bộ dưới đây là
**xác nhận trạng thái hiện tại** (read-only) + **1 công cụ mới** (chưa được dùng để đặt PIN thật
cho ai). Snapshot lấy lúc `2026-08-06T03:10:03Z`, tại `deployed_commit`
`3e87bf91e1c0f95ae84c45bbf2d2cd958d2f6585` (khớp PO Decision Record).

## 1. P-M4-PA-01 — Bằng chứng quyền trên production

Snapshot đầy đủ:
`E:\Alpha3s\dev\rehearsal-support\evidence-principal-readiness\principal_readiness_snapshot.log`
(sha256 `515b3763a989a32ca4905df328e7ae67b6a19113c27e4962cb529b98d59cf174`).

| Mục | Kết quả |
|---|---|
| Production HEAD | `3e87bf91e1c0f95ae84c45bbf2d2cd958d2f6585` — khớp `deployed_commit` |
| staff_id 3 (`m4-approval-recorder`) | active=true, role_key=NULL, quyền = **CHỈ** `m4.stage0p.approve` |
| staff_id 4 (`m4-control-operator`) | active=true, role_key=NULL, quyền = **CHỈ** `m4.stage0p.operate` |
| staff_id 5 (`m4-reviewer-evaluator`) | active=true, role_key=NULL, quyền = **CHỈ** `m4.stage0p.review` + `m4.stage0p.evaluate` |
| Quyền M4 gán cho staff_id NGOÀI 3/4/5 | `0` |
| `role_key` (quyền dashboard nghiệp vụ khác) trên cả 3 | không có (NULL) — đúng least privilege |

Đúng bảng CA đã khoá ở Review #1 §2 — không sai lệch.

## 2. P-M4-PA-02 — Secure PIN provisioning procedure

### 2.1. Công cụ

`scripts/m4_stage0p_provision_pin.py` (PR draft
[ledanghoai-bot/a3s#7](https://github.com/ledanghoai-bot/a3s/pull/7), CI run `31067597291`:
lint-test=success). Thiết kế:

- Argparse **chỉ** có `--staff-id` — cấu trúc không thể truyền PIN qua CLI (không có `--pin`/
  `--secret`/`--password`).
- Đọc qua `getpass.getpass()` — không echo, không lưu shell history.
- Yêu cầu nhập lại xác nhận; từ chối nếu 2 lần khác nhau hoặc <8 ký tự — **không ghi gì** nếu
  từ chối.
- Ghi `pin_secret_hash` qua `crypt($2, gen_salt('bf'))` tham số hoá (không nội suy chuỗi).
- `del` biến PIN ngay sau khi dùng.
- Output **chỉ** xác nhận row/metadata tồn tại (staff_id, provisioned_at, failed_attempts,
  locked_until) — **không bao giờ in `pin_secret_hash`**.

### 2.2. Actor và phương thức thực thi

Mỗi principal (approval recorder, PO reviewer/evaluator) **tự SSH vào VPS và tự chạy**:

```
docker exec -it alpha3s-api-1 python scripts/m4_stage0p_provision_pin.py --staff-id <ID của họ>
```

Dev **không** chạy lệnh này thay ai — công cụ điều khiển của Dev (SSH/Bash qua tool call) chỉ
thấy cặp lệnh+kết quả, không có kênh riêng cho người thứ 3 gõ PIN mà Dev không thấy được. Đây là
lý do buộc phải tự chạy, không phải Dev chạy hộ dù chỉ 1 lần.

### 2.3. Evidence (sandbox, không phải production — CHƯA đặt PIN thật cho ai)

`scripts/m4_stage0p_provision_pin_test.py`, 4 kịch bản, **RESULT: PASS**:

1. Xác nhận cấu trúc: `--pin`/`--secret`/`--password` không tồn tại, argparse từ chối ngay.
2. Round-trip thật (PIN test qua stdin trong sandbox): row được tạo, `crypt()` xác minh khớp,
   VÀ **`m4_stage0p_pin_actor()` (hàm DB thật) chấp nhận PIN đó** — chứng minh credential dùng
   được thật cho rehearsal, không chỉ "có hash".
3. 2 lần nhập không khớp → từ chối, không ghi gì.
4. PIN <8 ký tự → từ chối, không ghi gì.
5. Toàn bộ stdout/stderr của mọi lần chạy (kể cả thành công) không bao giờ chứa PIN thật hay
   giá trị bcrypt hash thật.

**Xác nhận production hiện tại (§1 snapshot):** `m4_stage0p_actor_credentials` có `0` dòng cho
staff_id 3/4/5 — PIN **chưa** được đặt cho ai, đúng như mong đợi ở giai đoạn readiness này.

## 3. Trạng thái OFF hiện tại (production, snapshot §1)

| Mục | Giá trị |
|---|---|
| `capture_enabled` | `false` |
| Synthetic customer residual | `0` |
| Active transcript signing key | `0` |
| Active signing-auth key | `0` |
| `m4_stage0p_capture_approvals` (tổng dòng) | `0` — chưa record approval_ref nào |
| Tiến trình signer/collector/rehearsal runner | không có |
| Biến môi trường `M4_*`/`ENABLE_M4*` | `0` |

## 4. Đề nghị

CA xác nhận P-M4-PA-01/02 đã đóng (evidence §1-2), đối chiếu PO Decision Record §6 (mục 1-2-4-5
đã có trong snapshot này; mục 3 — "secure PIN provisioning procedure" — đã mô tả ở §2, PIN thật
CHƯA đặt và sẽ chỉ đặt ngay trước cửa sổ thực thi bởi chính từng principal). Sau khi CA chấp
nhận, đề nghị CA phát hành Internal Synthetic Activation Gate cho `approval_ref`
`m4-internal-synthetic-rehearsal-20260806-01` theo cửa sổ PO đã duyệt
(`2026-08-06T03:00:00Z` – `2026-08-07T03:00:00Z`) — lưu ý cửa sổ đã bắt đầu, phần thời gian còn
lại sẽ ngắn hơn 24h tại thời điểm CA/PO thực sự sẵn sàng thực thi.

Dev không suy diễn quyền activation từ hồ sơ này.
