# M4 H2 — Threat model và runbook cho ký bất đối xứng qua KMS

> Đáp deliverable 4 của `PHASE1B-M4-H2-KMS-SANDBOX-ADAPTER-PREPARATION-DIRECTIVE-VI`.
> Phạm vi: **sandbox**. Giai đoạn managed cloud KMS cần PO decision riêng (xem
> `M4-H2-KMS-MIGRATION-PLAN-VI.md`).

## 1. Vấn đề gốc

HMAC hiện tại ký transcript bằng khóa **đối xứng** nằm trong DB. Nên bên **kiểm** chữ ký và bên
**làm giả được** chữ ký là một. Ed25519 tách hai vai đó: ký bằng khóa riêng mà DB không có, verify
bằng khóa công khai mà ai cũng lấy được.

## 2. Threat model

| Kẻ đe dọa | Làm được gì | Có giả mạo được chữ ký không |
|---|---|---|
| DBA / người có quyền DB | đọc, sửa, xóa mọi bảng; tắt trigger bất biến | **Không** — khóa riêng chưa bao giờ nằm trong DB |
| Người giữ backup DB | khôi phục toàn bộ nội dung DB | **Không** — backup không chứa khóa ký |
| Người đọc được `.env` / file secret của app | lấy khóa HMAC, khóa AEAD | **Không** — khóa Ed25519 không nằm trong file nào của app |
| Người chiếm được tiến trình `m4-signer` | gọi `sign` tùy ý trong lúc token còn hạn | **Có, trong cửa sổ đó** — nhưng không lấy được khóa ra khỏi backend |
| Người chiếm được root máy chạy KMS, KMS đang mở | như trên | **Có** |
| Người chiếm được root máy chạy KMS, KMS **đã seal** | không gọi được thao tác mật mã nào | **Không** |
| Người có quyền admin của KMS | quản trị khóa, rotate, vô hiệu | **Không export được** — khóa tạo với `exportable=false`; đã đo: root token cũng bị từ chối |

**Điều KHÔNG được suy ra:** tài liệu này không tuyên bố chống được kẻ có root trên máy đang chạy
KMS ở trạng thái mở. Đó là lý do PO chốt giai đoạn 2 dùng managed cloud KMS, và là lý do mục 5 đề
xuất giữ backend ở trạng thái seal ngoài cửa sổ ceremony.

## 3. Luồng danh tính — ai được gọi gì

```
người vận hành ──(admin API riêng)──> KMS: tạo/rotate/vô hiệu khóa
                                        │
m4-signer (UID 5001) ──token policy hẹp─┘ CHỈ: sign + đọc public key
      │ Ed25519 signature
      ▼
collector (UID 5002) ──> m4_stage0p_record_transcript_signature (migration 044)
                              │ chỉ PUBLIC material vào DB
                              ▼
                  verifier ngoài DB — không cần bí mật nào
```

Ba ranh giới, không được nhập lại:

1. **Signer không có quyền admin.** Policy chỉ cho `sign` và đọc public key. Không có export —
   `KmsTransport` không có phương thức đó, và provider cũng từ chối (hai lớp độc lập).
2. **Collector không nói chuyện với KMS.** Nó chỉ nhận kết quả qua Unix socket từ signer.
3. **Verifier không giữ bí mật nào.** Chạy được bởi bất kỳ ai, kể cả người không tin Dev lẫn DB.

## 4. Registry public key

- Bảng `m4_stage0p_transcript_public_keys` (migration 044) chỉ chứa **public** material, bất biến,
  tra theo `(key_id, key_version)`.
- Công bố bằng `scripts/m4_publish_transcript_public_key.py` — đọc public key từ backend rồi INSERT.
  Idempotent; nếu registry đã có hàng khác giá trị thì **dừng và báo**, không ghi đè (bảng bất biến).
- `m4_stage0p_record_transcript_signature` từ chối ghi nếu `(key_id, key_version)` chưa có trong
  registry hoặc đã `retired_at`. Nên **thứ tự bắt buộc**: công bố public key **trước**, ký sau.

## 5. Vận hành theo cửa sổ ceremony

Capture của M4 là hoạt động **theo đợt**, không thường trực. Khuyến nghị:

| Bước | Thao tác |
|---|---|
| Trước ceremony | unseal/kích hoạt backend; `--kiem-tra` xác nhận public key đã có trong registry |
| Trong ceremony | signer chạy với token TTL ngắn, policy hẹp |
| Sau ceremony | thu hồi token; seal/khóa lại backend; ghi vào checklist cleanup |
| Kiểm định kỳ | chạy verifier ngoài DB trên các batch đã capture |

Đưa "backend đã seal/không truy cập được" vào **cùng checklist dormant** với `capture_enabled=false`
— nếu không, trạng thái mở sẽ trôi qua nhiều tuần mà không ai để ý.

## 6. Timeout và retry

- Transport dùng timeout ngắn (mặc định 5s). Backend treo phải thành "không ký được" **nhanh**, vì
  fenced unit đang giữ lock DB; chờ lâu không cho kết quả tốt hơn.
- **Không retry trong transport.** Fenced unit thất bại là kết quả đúng: candidate không chuyển
  sang `committed` và sẽ được thử lại ở lần chạy collector sau, qua đúng đường có kiểm soát.
- Không có đường lui sang backend khác. Provider lỗi ⇒ không ký ⇒ không có sample. Đây là thiết kế,
  không phải thiếu sót.

## 7. Mô hình sự kiện audit

| Nguồn | Ghi gì |
|---|---|
| KMS | mọi lời gọi `sign` (audit device của backend) — ai gọi, khóa nào, lúc nào |
| Signer | `m4_signing_request_rejected` kèm `error_type`; **không bao giờ** nội dung được ký |
| DB | hàng chữ ký bất biến, `created_at`, `(key_id, key_version)` |
| Verifier | báo cáo đạt/hỏng theo từng `key_id@key_version` |

Đối chiếu chéo được: số lần `sign` ở KMS phải khớp số hàng chữ ký sinh ra trong cùng cửa sổ. Lệch
là dấu hiệu phải điều tra.

## 8. Rotation / vô hiệu / khôi phục

**Rotation.** Tạo phiên bản mới ở backend → **công bố public key mới vào registry** → đổi
`M4_KMS_KEY_VERSION` của signer. Chữ ký cũ vẫn verify được vì registry giữ mọi phiên bản. Đã đo ở
[S5] của `m4_h2_kms_e2e_sandbox.py`.

**Vô hiệu.** Đánh `retired_at` trong registry: chữ ký tạo **sau** mốc đó bị coi là không hợp lệ,
chữ ký tạo **trước** vẫn hợp lệ. Vô hiệu ở phía provider thì signer không ký được nữa — fenced unit
thất bại, không có sample nào thiếu bằng chứng.

**Mất backend.** Khóa cấm export nên **không khôi phục được khóa đó**. Nhưng:

- **chữ ký cũ vẫn verify được** — public key nằm trong DB registry, verifier không cần backend;
- chỉ mất khả năng **ký tiếp** ⇒ đường xử lý là tạo khóa mới, công bố phiên bản mới, `retired_at`
  cho khóa cũ.

Nói cách khác: mất backend làm gián đoạn việc **tạo** bằng chứng mới, không làm mất giá trị bằng
chứng **đã có**.

## 9. Những gì đã đo, không phải giả định

| Khẳng định | Đo ở đâu |
|---|---|
| Ed25519 được hỗ trợ, `exportable=false` là mặc định | `evidence-h2-kms-v0/00_v0_khao_sat.log` |
| Root token **không** export được khóa | cùng file, mục [5d] |
| Chữ ký của backend verify được bằng `verify_signature` của dự án | cùng file, mục [3] |
| Unavailable / unauthorized / khóa vô hiệu đều không commit sample, **đúng lý do** | `01_kms_e2e.log` [S2][S3][S4] |
| Rotation giữ verify được chữ ký lịch sử | cùng file, [S5] |
