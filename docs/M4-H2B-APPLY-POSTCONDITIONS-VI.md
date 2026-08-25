# M4 H2-B — Postcondition bắt buộc của Infrastructure Apply Gate

> Trả lời **F-PR31-08B** của `CA-Docs/PHASE1B-M4-H2B-PR31-BOOTSTRAP-TERRAFORM-PLAN-REVIEW-1-VI.md`
> và mục 2 "Bootstrap controls bắt buộc" của
> `CA-Docs/PHASE1B-M4-H2B-AUDIT-BUCKET-RETENTION-PO-DECISION-VI.md`.
>
> **Chưa được thực thi.** Đây là danh sách điều kiện phải chứng minh **sau khi** apply, để CA đóng
> được gate. Không mục nào trong đây tự cấp quyền apply.

## 0. Nguyên tắc

`terraform apply` chạy xong **không** có nghĩa là gate đạt. Terraform chỉ chứng minh nó đã gọi API
thành công; nó không chứng minh **đường báo động có người nhận**, **log có thật sự chảy vào bucket**,
hay **retention đang có hiệu lực**. Ba thứ đó phải được đo sau khi apply.

Mỗi mục dưới đây phải có: **lệnh đã chạy**, **output thô**, **giờ UTC**. Thiếu một mục = gate chưa đạt.

## 1. Email notification channel — phải chứng minh ĐÃ XÁC MINH và ĐÃ NHẬN

Đây là mục CA nêu đích danh: kênh email tồn tại trong Terraform state **không đủ**.

| # | Phải chứng minh | Cách lấy bằng chứng |
|---|---|---|
| 1.1 | Channel tồn tại đúng địa chỉ authoritative | `gcloud alpha monitoring channels list --format=json` — kiểm `type=email`, `labels.email_address` |
| 1.2 | **Verification status không phải `UNVERIFIED`** | cùng output trên, trường `verificationStatus`. Sửa theo CA Review 37/39 và Monitoring API reference: channel **email** không có workflow xác minh — trường thường **vắng mặt** (= `VERIFICATION_STATUS_UNSPECIFIED`) và channel vẫn gửi thư bình thường. Chỉ giá trị `UNVERIFIED` mới là non-functioning và chặn gate. Acceptance cuối cùng là **email test nhận được thật** (§1.3), không phải giá trị trường này |
| 1.3 | **Controlled test alert được nhận thật** | xem §1.4 |
| 1.4 | Ảnh chụp/redact của email alert nhận được | ghi giờ UTC nhận, tiêu đề alert, policy name; **che** nội dung nhạy cảm |

**Kịch bản test có kiểm soát** (chạy trong cửa sổ apply, ghi rõ vào evidence là test):

1. ghi giờ UTC bắt đầu test;
2. tạo **một** sự kiện thuộc phạm vi một metric đã khai — test chuẩn (đã chạy thật và PASS
   25/8/2026, CA Review 39): đúng **một** lệnh describe read-only WIF provider `vps-x509` trong
   pool `alpha3s-prod-vps` — audit event `GetWorkloadIdentityPoolProvider` match filter
   `m4-identity-config-changes`. **KHÔNG dùng `GetPublicKey`** (CA Review 36: filter
   `sign_operations` chỉ bắt `AsymmetricSign` nên GetPublicKey không match metric nào — test sẽ
   câm); **không** dùng thao tác ký thật để test;
3. chờ alignment/evaluation/notification latency (align 300s; độ trễ đo thật 25/8: ~3m41s;
   trần chờ hợp lý 15 phút). **Không có notification rate-limit**: metric-threshold policy không
   hỗ trợ cấu hình đó (F-APPLY-04A) — không được mô tả hay trông đợi throttle ở tầng policy;
4. xác nhận email đến hộp `3scoffee.cs@gmail.com`;
5. ghi giờ UTC nhận, độ trễ, và **đóng** incident.

Nếu không nhận được email: **safety-stop**, coi là gate failure, không đi tiếp sang Synthetic KMS
Integration. Telegram **không** thay thế được mục này và **không** chặn gate (Decision Record mục 2).

## 2. Audit bucket retention — unlocked nhưng phải chứng minh đúng

PO chốt `unlocked` trong bootstrap, nên bằng chứng phải ghi **chính xác trạng thái đó**, không nói
chung chung:

| # | Phải chứng minh | Giá trị kỳ vọng |
|---|---|---|
| 2.1 | Retention period | `34560000` giây (400 ngày) |
| 2.2 | `isLocked` | **`false`** — ghi tường minh, không để trống |
| 2.3 | `effectiveTime` | có, ghi lại |
| 2.4 | **metageneration** của bucket | ghi lại — đây là mốc để gate lock sau này tham chiếu |
| 2.5 | `uniformBucketLevelAccess` | `true` |
| 2.6 | `publicAccessPrevention` | `enforced` |

```bash
gcloud storage buckets describe gs://a3s-prod-kms-audit --format=json
```

## 3. Sink writer — chứng minh log CHẢY được, không chỉ cấu hình đúng

Một sink trỏ tới bucket không có quyền ghi vẫn "tạo thành công" và vẫn im lặng. Phải chứng minh:

| # | Phải chứng minh |
|---|---|
| 3.1 | `writer_identity` của sink đúng là principal đang giữ `roles/storage.objectCreator` trên bucket |
| 3.2 | Trên bucket **không** có binding rộng hơn cho writer identity (không `objectAdmin`, không `storage.admin`) |
| 3.3 | **Có object thật** xuất hiện trong bucket sau khi phát sinh audit log — liệt kê prefix và giờ UTC |
| 3.4 | Audit reader (`user:3scoffee.cs@gmail.com`) **khác** writer identity và **khác** signer SA |

## 4. IAM bootstrap — chứng minh đã thu hồi

Theo `docs/M4-H2B-BOOTSTRAP-IAM-PLAN-VI.md` và PO Decision Record F-PROV-06 mục 5:

| # | Phải chứng minh |
|---|---|
| 4.1 | `iam_before.json` (trước grant) |
| 4.2 | exact condition expression đã dùng + giờ UTC grant |
| 4.3 | giờ UTC revoke |
| 4.4 | `iam_after.json` |
| 4.5 | **đếm binding còn lại theo `condition.title=m4-h2b-bootstrap` = 0** |
| 4.6 | effective IAM sau revoke: principal **không** còn Owner/Editor bất ngờ |

## 5. Drift check định kỳ (hệ quả của việc chưa lock)

Vì retention đang unlocked, phải có đường phát hiện nếu ai đó giảm/gỡ nó **giữa các lần review**:

- alert `m4-audit-destination-changes` (đã có trong Terraform) bao thay đổi sink/bucket;
- thêm một lần chạy `gcloud storage buckets describe` **định kỳ** đối chiếu lại §2 — kết quả lưu
  cùng evidence của kỳ đó;
- lệch bất kỳ giá trị nào ở §2 ⇒ **safety-stop**, coi là gate failure, không tiếp tục
  integration/activation.

## 6. Điều kiện đóng gate

Gate Infrastructure Apply **chỉ** được đề nghị đóng khi cả §1–§5 đều có bằng chứng thô kèm giờ UTC.
Riêng §1.2 và §1.3 (channel không `UNVERIFIED` + nhận được alert thật) là **điều kiện cứng** — CA nêu đích danh,
và nó là thứ duy nhất chứng minh đường báo động không phải đường câm.

Sau khi CA đóng gate này **và** Synthetic KMS Integration, mới xét tới
**Irreversible Bucket Retention Lock Gate** cho exact bucket + exact metageneration ở §2.4.
