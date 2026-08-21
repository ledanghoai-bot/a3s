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

3. **Schema Terraform của WIF provider X.509 chưa đối chiếu.** Tên khối/trường (`x509`,
   `trust_store`, `trust_anchors`, `pem_certificate`) viết theo tài liệu; `terraform validate` ở
   Provisioning Gate phải xác nhận và sửa nếu lệch. Đã ghi cảnh báo ngay trong `main.tf`.

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

## 2b. Nguồn tin cậy: WIF + X.509

> Authority: `CA-Docs/PHASE1B-M4-H2B-WIF-X509-TRUST-SOURCE-PO-DECISION-VI.md`

PO chọn phương án A. Danh tính của signer là **một chứng chỉ client** do CA nội bộ cấp; VPS giữ khóa
riêng của chứng chỉ đó. Google WIF provider là loại **X.509** với trust store chứa trust anchor của
CA nội bộ.

### Ranh giới phải giữ

| | |
|---|---|
| Thứ nằm trên VPS | khóa riêng của **chứng chỉ** — credential để mạo danh, **không** phải khóa ký |
| Khóa ký | ở Google KMS, `exportable` không tồn tại như một khả năng, kể cả admin |
| Kịch bản xấu nhất | kẻ tấn công ký được **cho tới khi thu hồi** — không phải "mất khóa vĩnh viễn" |
| Năng lực bắt buộc | **thu hồi ngay** mà không cần chạm khóa ký |

### Ba đường thu hồi, từ nhanh tới chậm

1. **Sửa `attribute_condition`** của WIF provider — chặn ngay một CN cụ thể, hiệu lực tức thì, không
   cần CA nội bộ tham gia. Đây là đường nhanh nhất và nên là phản xạ đầu tiên.
2. **Thu hồi chứng chỉ** ở CA nội bộ — đúng quy trình PKI, cần CA vận hành được.
3. **Gỡ `roles/iam.workloadIdentityUser`** khỏi signer SA — chặn toàn bộ đường federation.

Cả ba đều **không** đụng tới khóa ký, nên chữ ký lịch sử vẫn verify được sau khi thu hồi.

### Quyết định của PO

> **Nguồn authority:** `CA-Docs/PHASE1B-M4-H2B-WIF-X509-TRUST-SOURCE-PO-DECISION-VI.md` — APPROVED 2026-08-18T11:10:00Z.

| Hạng mục | Quyết định |
|---|---|
| Nguồn tin cậy | WIF với **X.509 client certificate** |
| Offline Certificate Authority | owner/custodian là **PO** hoặc human Security-KMS Administrator được PO ủy quyền bằng văn bản. **Dev không giữ** khóa riêng của Offline CA |
| Khóa riêng Offline CA | không lên VPS, Google Cloud, repository, CI hay máy Dev. Chỉ **public trust anchor** đi vào Terraform/WIF |
| TTL chứng chỉ client | **tối đa 24 giờ**, và không vượt cửa sổ được duyệt cộng một giờ |
| Mỗi ceremony | serial mới + **khóa riêng client mới** |
| Khóa riêng client | **sinh trong tmpfs hạn chế TRÊN VPS, không rời VPS** |
| Ra/vào | VPS chỉ gửi **CSR**; custodian chỉ trả **certificate/chain** |

**Lưu ý thuật ngữ:** trong dự án này "CA" là vai **reviewer/governance**. Bên cấp chứng chỉ phải
luôn gọi đầy đủ là **Offline Certificate Authority**, và nó **không phải** CA reviewer.

### Quy trình chứng chỉ theo ceremony

| Bước | Việc | Ai |
|---|---|---|
| 1 | tạo tmpfs hạn chế trên VPS (chỉ UID signer đọc được), **sinh khóa riêng client tại đó** | vận hành |
| 2 | tạo **CSR** với CN = đúng giá trị `wif_allowed_subject`; **chỉ CSR** rời VPS | vận hành |
| 3 | ký CSR trên máy offline, TTL ≤ 24h và ≤ cửa sổ duyệt + 1h; trả về certificate/chain | custodian Offline CA |
| 4 | mount certificate/chain + external-account config cho signer **trong** ceremony | vận hành |
| 5 | chạy ceremony | runbook M4 |
| 6 | **cleanup**: xóa certificate, khóa riêng client, subject-token artifact và credential config khỏi tmpfs/mount; stop signer; xóa socket; revoke runtime approval | **bắt buộc** |
| 7 | xác nhận dormant bằng kiểm read-only (danh sách dưới) | Dev/vận hành |

Khóa riêng **không bao giờ đi qua đường truyền nào** — đây là điểm bản chính thức chặt hơn đề xuất
ban đầu của Dev (vốn định sinh khóa trên máy PO rồi chuyển lên VPS).

**Bước 6 nằm trong CÙNG checklist cleanup** với `capture_enabled=false` và thu hồi approval. Tách ra
là sớm muộn bị quên — `signing.sock` sót lại từ Amendment 16 đã cho thấy điều đó xảy ra thật.

### Bất biến dormant, kiểm được read-only

Giữa các ceremony phải chứng minh được:

- không có khóa riêng client / certificate / chain;
- không có WIF credential configuration nào được mount;
- không có subject-token artifact, và không có `M4_GOOGLE_ACCESS_TOKEN`;
- không có signer/init process hay socket;
- capture OFF và không approval còn hiệu lực.

**Public trust anchor không phải secret** và được phép tồn tại.

### Thu hồi — nhiều lớp

| Lớp | Việc | Tốc độ |
|---|---|---|
| 1 | stop signer + xóa runtime credential khỏi tmpfs/mount | tức thì, không cần ai cấp quyền |
| 2 | disable/gỡ WIF provider hoặc impersonation binding | nhanh, không cần Offline CA |
| 3 | gỡ signer role khi cần | nhanh |
| 4 | chứng chỉ hết hạn ngắn (≤ 24h) | tự động |

**Không** dựa vào CRL/OCSP cho tới khi có bằng chứng Google WIF thực thi cơ chế đó — Dev chưa kiểm
chứng được điều này và không được giả định.

**Không** destroy Google KMS signing key/version chỉ để thu hồi workload identity: vấn đề nằm ở
danh tính chứ không ở khóa, và destroy còn cắt mất mắt xích đối chiếu public key trong
registry ngược về nguồn KMS (xem §2, mục `prevent_destroy`).

## 3. Kế hoạch provisioning (deliverable 4) — chưa thực thi

`infra/gcp-kms/` (Terraform): bật API, key ring, khóa `ASYMMETRIC_SIGN`/`EC_SIGN_ED25519`/`SOFTWARE`,
signer SA, hai IAM binding cấp khóa, WIF pool + provider có điều kiện, audit config, log sink, ba
log-based metric + ba alert policy nối vào một notification channel email (§4).

### Bất biến được kiểm tự động (42 mục)

| Nhóm | Ví dụ |
|---|---|
| Mật mã | purpose `ASYMMETRIC_SIGN`, thuật toán `EC_SIGN_ED25519`, `SOFTWARE`, không dùng cho mã hóa |
| Credential | **không** `google_service_account_key`; có WIF; provider có `attribute_condition` |
| Quyền tối thiểu | binding ở cấp CryptoKey; **không** `google_project_iam_member`; chỉ 2 role; không admin/owner/editor |
| Chống mất bằng chứng | `prevent_destroy` trên key ring + khóa; **không** `rotation_period` tự động |
| Audit | `DATA_READ` + `DATA_WRITE` + log sink |
| Cảnh báo | đủ 3 alert policy; **mọi** policy đều nối vào notification channel; hộp thư là biến; không webhook channel (tránh giữ bot token) |
| Vệ sinh | không hard-code project id, không token/khóa trong cấu hình |

Hai bất biến đáng giải thích:

- **Không rotation tự động.** Rotation của M4 phải kèm bước **công bố public key mới vào registry
  trước** khi signer đổi phiên bản. Rotation tự động sẽ tạo phiên bản mà registry chưa biết, và
  migration 044 sẽ từ chối ghi ⇒ fenced unit thất bại. An toàn, nhưng là gãy vận hành không cần có.
- **`prevent_destroy`.** Cần nói chính xác cái gì mất khi hủy phiên bản khóa. Verifier
  (`scripts/m4_stage0p_verify_transcripts.py`) đọc public key từ registry DB
  (`m4_stage0p_transcript_public_keys`), **không** gọi Google, nên chữ ký lịch sử **vẫn verify
  được** sau khi phiên bản khóa bị hủy ở Google. Cái thật sự mất là (a) khả năng **ký tiếp** bằng
  phiên bản đó và (b) **mắt xích đối chiếu** public key trong registry ngược về nguồn KMS — không
  còn cách chứng minh độc lập rằng public key đang nằm trong DB đúng là của khóa Google đã ký.
  `prevent_destroy` giữ mắt xích đó lại; hủy hay vô hiệu là quyết định riêng của PO, không nằm
  trong Terraform.

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
Lệch là dấu hiệu phải điều tra.

**Cảnh báo — PO chốt 20/8/2026** (Dev ghi lại ở `Dev/PHASE1B-M4-H2B-PROVISIONING-F-PROV-06-PO-ANSWERS-VI.md`;
chờ PO Decision Record chính thức nếu CA đòi). Ba alert policy đã nằm trong Terraform, tất cả
nối vào **một notification channel email**:

| Alert | Nguồn | Vì sao |
|---|---|---|
| Có thao tác ký | metric `m4-transcript-sign-operations` | production dormant ⇒ ngoài ceremony thì số lần ký đúng phải là 0; gom theo cửa sổ 300s + `notification_rate_limit` ⇒ **một ceremony ≈ một email**, không phải 260 |
| Đổi IAM trên key ring/khóa | metric `m4-transcript-key-iam-changes` | đổi quyền là bước bắt buộc của mọi đường lạm dụng — phải phát ra tiếng kể cả khi người đổi là chính chủ |
| Đổi trạng thái khóa/phiên bản | metric `m4-transcript-key-state-changes` | destroy phiên bản làm mất mắt xích đối chiếu registry ↔ nguồn KMS (xem §2 `prevent_destroy`) |

**Email, không phải Telegram, là đường chính** — Telegram webhook đi qua VPS nên sẽ chết đúng lúc
cần nhất. PO muốn nhận **cả hai**; phần Telegram làm **ngoài** Google Cloud (forward từ hộp thư
nhận alert), vì Cloud Monitoring không có kênh Telegram và làm bằng webhook thì phải giữ bot token
trong cấu hình — phá bất biến "không token/khóa trong cấu hình".

**Chưa làm, khai rõ:** alert "tỉ lệ `PERMISSION_DENIED` tăng đột biến" (đề xuất ban đầu) chưa có
metric riêng. Nó chỉ có ý nghĩa khi đã có nền lưu lượng thật, mà production đang dormant.

**Trình tự rotation — thứ tự bắt buộc:**

1. tạo phiên bản mới (KMS admin);
2. **công bố public key mới vào registry** (`scripts/m4_publish_transcript_public_key.py`);
3. preflight: `--kiem-tra` xác nhận registry đã có, ký thử trên sandbox;
4. đổi `M4_KMS_KEY_VERSION` của signer;
5. **giữ** public key cũ trong registry (verify dựa vào đây) **và** giữ phiên bản khóa cũ ở KMS
   để còn đối chiếu được registry với nguồn.

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
