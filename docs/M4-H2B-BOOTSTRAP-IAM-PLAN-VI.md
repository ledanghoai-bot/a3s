# M4 H2-B — Kế hoạch bootstrap IAM cho Infrastructure Apply Gate

> Trả lời **F-PR31-06** của `CA-Docs/PHASE1B-M4-H2B-PR31-BOOTSTRAP-TERRAFORM-PLAN-REVIEW-1-VI.md`.
> Authority cho các ràng buộc thời gian: `CA-Docs/PHASE1B-M4-H2B-F-PROV-06-PO-DECISION-RECORD-VI.md`
> mục 3 và 5.
>
> **Chưa được thực thi.** Đây là kế hoạch để CA review. Grant thật chỉ xảy ra khi PO mở
> Infrastructure Apply Gate, và do PO/operator tự chạy bằng danh tính của mình — Dev không nhận
> credential.

## 1. Vì sao tách thành hồ sơ riêng

Bản trước gộp quyền bootstrap vào phần mô tả chung với câu "expiry khoảng 48 giờ". CA bác đúng:
không có exact condition expression, không có timestamp, không nói ai grant ai revoke, không có
postcondition chứng minh đã thu hồi. Ba chỗ đó mới là chỗ hỏng được.

Điểm cần nhìn thẳng: ở giai đoạn này **một người kiêm cả bốn vai** (PO, custodian, operator,
người đọc audit). Không có người thứ hai để phát hiện một binding bị treo. Nên lớp bảo vệ thật
không phải "nhớ revoke", mà là **binding tự chết** — còn bước revoke tay là để chứng minh mình
không dựa vào nó.

## 2. Ma trận quyền bootstrap

Mỗi role phải được biện minh bằng **resource cụ thể** trong plan. Role nào không có resource tương
ứng thì bỏ (F-PROV-04).

| Role | Biện minh bằng resource trong `infra/gcp-kms/` | Vòng đời |
|---|---|---|
| `roles/serviceusage.serviceUsageAdmin` | `google_project_service.required` (8 API trong `local.required_services`) | tạm thời, có expiry |
| `roles/cloudkms.admin` | key ring, crypto key, 2 `google_kms_crypto_key_iam_member` | tạm thời, có expiry |
| `roles/iam.serviceAccountAdmin` | `google_service_account.signer` + `google_service_account_iam_member.wif_impersonate` | tạm thời, có expiry |
| `roles/iam.workloadIdentityPoolAdmin` | WIF pool + provider X.509 | tạm thời, có expiry |
| `roles/resourcemanager.projectIamAdmin` | `google_project_iam_audit_config` (KMS + allServices) | tạm thời, có expiry |
| `roles/logging.configWriter` | log sink + 6 log-based metric | tạm thời, có expiry |
| `roles/storage.admin` | bucket audit + 2 binding trên bucket | tạm thời, có expiry |
| `roles/monitoring.editor` | notification channel + 6 alert policy | tạm thời, có expiry |

**Cấm tuyệt đối:** `roles/owner`, `roles/editor` làm cơ chế bootstrap. Script sinh kế hoạch từ chối
chạy nếu hai role này lọt vào danh sách.

**Signer SA không có mặt trong bảng này** và không bao giờ có admin role — nó chỉ giữ
`roles/cloudkms.signer` + `roles/cloudkms.publicKeyViewer` ở cấp CryptoKey, thường trực.

## 3. Exact IAM Condition

Không gõ tay timestamp. Kế hoạch được **sinh ra** từ cửa sổ gate:

```bash
python scripts/m4_h2b_bootstrap_iam_plan.py --bat-dau <RFC3339> --ket-thuc <RFC3339>
```

Quy tắc script cưỡng chế (test ở `tests/test_m4_h2b_bootstrap_iam_plan.py`):

- `expiry = cuối cửa sổ gate + đúng 1 giờ cleanup`;
- `tổng vòng đời ≤ 48 giờ` — vượt thì **script thoát mã 2**, buộc thu hẹp cửa sổ chứ không kéo dài
  binding;
- condition là timestamp tuyệt đối: `request.time < timestamp("2026-08-21T07:00:00Z")`, có
  `title=m4-h2b-bootstrap` để lọc lại lúc kiểm postcondition.

## 4. Bốn bước bắt buộc, theo đúng thứ tự

1. **Chụp IAM trước** (`iam_before.json`) và **kiểm Owner/Editor**, kể cả quyền kế thừa. Nếu
   principal đã có Owner/Editor thì conditional Storage Admin **không còn ý nghĩa giới hạn** — khi
   đó CA phải ghi nhận bootstrap-owner exception hoặc chặn gate. Không được tuyên bố least privilege
   khi chưa chứng minh (PO Decision Record mục 3).
2. **Grant** 8 role, mỗi role kèm đúng condition ở trên.
3. **Revoke tay ngay sau khi apply + thu evidence xong.** Phải truyền lại đúng condition, nếu không
   `gcloud` sẽ không tìm thấy binding để gỡ.
4. **Postcondition:** đếm binding còn lại theo `condition.title=m4-h2b-bootstrap` — **phải bằng 0**.

## 5. Evidence phải nộp

- `iam_before.json` (trước grant);
- danh sách lệnh grant đã chạy + giờ UTC grant;
- exact condition expression đã dùng;
- giờ UTC revoke;
- `iam_after.json` (sau revoke);
- kết quả đếm postcondition = 0.

## 6. Safety-stop

- Hết cửa sổ trước khi apply xong → **dừng**, không tự kéo dài binding; cần PO amendment + CA gate mới.
- Postcondition đếm ra khác 0 → **chưa được coi là đóng gate**, phải gỡ tiếp và chụp lại.
- Cần một role ngoài 8 role trên → dừng, xin gate riêng; không tự thêm.
