# M4 H2-B — Google Cloud KMS: thiết kế IAM, kế hoạch provisioning, audit/rotation/runbook

> Đáp deliverable 3, 4, 5 của `PHASE1B-M4-H2B-GOOGLE-CLOUD-KMS-PREPARATION-DIRECTIVE-VI`.
> **Chưa thực thi gì.** Không có resource nào được tạo. Mọi định danh dưới đây là **đề xuất**, cần
> PO chốt trước khi `terraform plan`.

## 1. Giới hạn phải đọc trước

Hai điều Dev **không** kiểm chứng được ở bước chuẩn bị này, khai báo thẳng để CA không phải đoán:

1. **Chưa gọi API Google KMS thật lần nào.** Directive cấm dùng credential thật, nên hình dạng
   request/response (`asymmetricSign` nhận `data`, `publicKey` trả `pem` + `algorithm`, tên trường
   `signature`/`name`) được viết theo tài liệu Google, **chưa đối chiếu với API thật**. Bước
   provisioning **phải** có một phép gọi thật trên khóa thử để xác nhận trước khi tin.
2. **Chưa chạy `terraform validate/plan`** — máy làm việc không có `terraform` lẫn `gcloud`. Thay
   vào đó có `scripts/m4_h2b_kiem_provisioning_plan.py`: kiểm **tĩnh** 24 bất biến an toàn, chạy
   được trong CI không cần cloud, và tiếp tục gác khi ai đó sửa Terraform sau này.

Thứ **đã** đo được: chuyển PEM → raw 32 byte và verify chữ ký Ed25519 bằng chính `verify_signature`
của dự án (test `test_public_key_doi_PEM_sang_raw_32_byte`, `test_ky_gui_raw_bytes_...`).

## 2. Thiết kế danh tính (deliverable 3)

### Giá trị đề xuất — PO chốt

| Hạng mục | Đề xuất | Lý do |
|---|---|---|
| Project | `a3s-m4-signing` (project **riêng**, không dùng chung) | tách blast radius; IAM của project khác không với tới khóa |
| Location | `asia-southeast1` | gần VPS (VN) → độ trễ thấp; fenced unit có deadline |
| Key ring | `m4-transcript` | |
| Key | `transcript-ed25519` | |
| Signer SA | `m4-signer@a3s-m4-signing.iam.gserviceaccount.com` | |
| WIF pool / provider | `alpha3s-vps` / `vps-oidc` | |

`key_id` ghi vào registry là **resource path đầy đủ**
(`projects/…/cryptoKeys/transcript-ed25519`), không phải tên ngắn — để một hàng chữ ký tự mô tả
được nó thuộc project/keyring nào. Người verify sau này có thể là người **không còn quyền truy cập
hệ thống**; path đầy đủ khiến họ không phải đoán.

### Phân tách quyền

| Vai | Được làm | **Không** được làm |
|---|---|---|
| Signer SA | `roles/cloudkms.signer` + `roles/cloudkms.publicKeyViewer`, gán ở **cấp CryptoKey** | tạo/rotate/disable/destroy khóa, sửa IAM, đọc khóa khác |
| KMS admin (người) | quản trị khóa, rotate | ký thay signer |
| IAM admin (người) | quản trị binding | quản trị khóa |

Gán ở **cấp CryptoKey** chứ không cấp project là có chủ ý: `roles/cloudkms.signer` ở cấp project sẽ
cho signer ký bằng **mọi** khóa sau này của project.

### Xác thực: Workload Identity Federation, không JSON key

PO decision cấm service-account JSON key lâu dài. WIF provider có `attribute_condition` khóa đúng
**một** subject; thiếu điều kiện đó thì bất kỳ identity nào của issuer cũng mạo danh được signer.

Trong code, `GoogleKmsTransport` nhận `token_provider` — chỗ cắm WIF. Dev **cố ý chưa** hiện thực
đường WIF: không có credential để chạy thử, và viết một đường xác thực không thể kiểm thử là cách
chắc chắn nhất để nó sai âm thầm.

## 3. Kế hoạch provisioning (deliverable 4) — chưa thực thi

`infra/gcp-kms/` (Terraform): bật API, key ring, khóa `ASYMMETRIC_SIGN`/`EC_SIGN_ED25519`/`SOFTWARE`,
signer SA, hai IAM binding cấp khóa, WIF pool + provider có điều kiện, audit config, log sink.

### Bất biến được kiểm tự động (24 mục)

| Nhóm | Ví dụ |
|---|---|
| Mật mã | purpose `ASYMMETRIC_SIGN`, thuật toán `EC_SIGN_ED25519`, `SOFTWARE`, không dùng cho mã hóa |
| Credential | **không** `google_service_account_key`; có WIF; provider có `attribute_condition` |
| Quyền tối thiểu | binding ở cấp CryptoKey; **không** `google_project_iam_member`; chỉ 2 role; không admin/owner/editor |
| Chống mất bằng chứng | `prevent_destroy` trên key ring + khóa; **không** `rotation_period` tự động |
| Audit | `DATA_READ` + `DATA_WRITE` + log sink |
| Vệ sinh | không hard-code project id, không token/khóa trong cấu hình |

Hai bất biến đáng giải thích:

- **Không rotation tự động.** Rotation của M4 phải kèm bước **công bố public key mới vào registry
  trước** khi signer đổi phiên bản. Rotation tự động sẽ tạo phiên bản mà registry chưa biết, và
  migration 044 sẽ từ chối ghi ⇒ fenced unit thất bại. An toàn, nhưng là gãy vận hành không cần có.
- **`prevent_destroy`.** Hủy phiên bản khóa làm **mọi chữ ký lịch sử không verify được nữa**. Chỉ
  được hủy khi retention/nghĩa vụ pháp lý đã hết — cần quyết định riêng, không nằm trong Terraform.

### Rollback / break-glass

| Tình huống | Xử lý | Ảnh hưởng chữ ký cũ |
|---|---|---|
| Sai cấu hình IAM | gỡ binding, gán lại | không |
| Nghi lộ credential | vô hiệu subject trong WIF condition; signer mất quyền ngay | không |
| Nghi lộ khóa | `disable` phiên bản → tạo phiên bản mới → công bố public key mới → đổi signer | **vẫn verify được** (registry giữ public key cũ) |
| Cần dừng gấp toàn bộ | bỏ `M4_SIGNING_BACKEND` ⇒ signer **không khởi động** ⇒ capture dừng, không sample thiếu bằng chứng | không |

Đường dừng gấp cuối cùng **không cần chạm Google Cloud** — đó là tính chất tốt: sự cố phía cloud
không khóa tay người vận hành.

## 4. Audit / rotation / runbook (deliverable 5)

**Audit.** `DATA_WRITE` ghi mọi lần ký, `DATA_READ` ghi mọi lần đọc public key, sink giữ lại log.
Đối chiếu chéo được: số lần `asymmetricSign` trong một cửa sổ phải khớp số hàng chữ ký sinh ra ở DB.
Lệch là dấu hiệu phải điều tra. Cảnh báo đề xuất: ký ngoài cửa sổ ceremony, đổi IAM trên key ring,
thay đổi trạng thái khóa, tỉ lệ `PERMISSION_DENIED` tăng đột biến.

**Trình tự rotation — thứ tự bắt buộc:**

1. tạo phiên bản mới (KMS admin);
2. **công bố public key mới vào registry** (`scripts/m4_publish_transcript_public_key.py`);
3. preflight: `--kiem-tra` xác nhận registry đã có, ký thử trên sandbox;
4. đổi `M4_KMS_KEY_VERSION` của signer;
5. **giữ** public key/phiên bản cũ. Không destroy khi còn nghĩa vụ verify.

Đảo bước 1–2 sẽ làm mọi capture thất bại cho tới khi registry được cập nhật.

**Sự cố và mã lỗi tương ứng** (chi tiết provider chỉ có ở Cloud Audit Logs, **không** đi qua giao
thức collector — xem F-H2-KMS-02):

| Hiện tượng | Mã | Việc cần làm |
|---|---|---|
| KMS lỗi/timeout | `backend_unavailable` | kiểm mạng/độ trễ; capture tự thử lại lần chạy sau |
| Sai quyền/credential/federation hỏng | `backend_denied` | kiểm IAM binding, WIF condition, hạn credential |
| Khóa bị disable/destroy | `backend_key_disabled` | kiểm trạng thái phiên bản; nếu cố ý thì làm trình tự rotation |
| Cấu hình sai (vd backend sandbox ở production) | `backend_misconfigured` | sửa cấu hình triển khai |

Mọi mã trên đều dẫn tới **không commit sample** — không có đường nào tạo ra sample thiếu bằng chứng.

## 5. Việc bắt buộc ở Provisioning Gate

1. Gọi **thật** một lần trên khóa thử để xác nhận hình dạng request/response (mục 1.1).
2. Chạy `terraform validate` + `plan` (mục 1.2), nộp plan output.
3. Chứng minh signer **không** export được khóa và **không** quản trị được khóa.
4. Công bố public key vào registry rồi verify một chữ ký thật bằng verifier ngoài DB.
