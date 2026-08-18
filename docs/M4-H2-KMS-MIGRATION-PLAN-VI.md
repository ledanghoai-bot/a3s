# M4 H2 — Kế hoạch chuyển từ adapter sandbox sang managed cloud KMS

> Đáp deliverable 5 của `PHASE1B-M4-H2-KMS-SANDBOX-ADAPTER-PREPARATION-DIRECTIVE-VI`, theo lộ trình
> hai giai đoạn tại `PHASE1B-M4-H2-KMS-DELIVERY-PATH-PO-DECISION-VI`.

## 1. Ràng buộc bất di bất dịch

Chuyển provider **không được** đổi bất kỳ thứ nào sau đây:

| Không được đổi | Vì sao |
|---|---|
| Định dạng transcript (chuỗi byte được ký) | HMAC và Ed25519 ký **cùng** chuỗi byte; đổi là làm hỏng cả hai thẻ |
| Thuật toán `Ed25519`, chữ ký 64 byte, public key 32 byte | ràng buộc cứng ở migration 044 (`CHECK`), `KmsSigningBackend`, và verifier |
| Schema `m4_stage0p_transcript_public_keys` / `_signatures` | 044 đã deploy production, checksum đã vào ledger |
| Ngữ nghĩa `(key_id, key_version)` | verifier tra registry bằng cặp này để verify chữ ký lịch sử |
| Bất biến dormant của H2-A-2 | signer/init absent, capture OFF, counters = 0 |

Nói cách khác: **chỉ lớp transport được thay.** Contract, DB, verifier, E2E giữ nguyên.

## 2. Điểm thay đổi duy nhất

```
app/services/pii/
  signing_backend.py        <- KHÔNG đổi (KmsSigningBackend, fail-closed, kiểm 64/32 byte)
  kms_transport.py          <- thêm ĐÚNG MỘT nhánh cho provider mới
  kms_transport_vault.py    <- giữ, chỉ dùng cho sandbox
  kms_transport_<provider>.py  <- MỚI: hiện thực sign() + public_key()
```

Signer, collector, migration, verifier, script công bố public key: **không đổi dòng nào**.

## 3. Điều kiện tiên quyết trước khi bắt đầu

PO decision riêng phải chốt: provider; account/project/region; key namespace/alias Ed25519; key
owner; KMS administrator; signer principal; chính sách rotation/revoke/audit/recovery. Trước khi có
văn bản đó: **không** provision, **không** viết adapter production, **không** deploy.

Việc kỹ thuật cần xác minh **trước** khi chốt provider — thứ tự này quan trọng:

1. **Provider có ký Ed25519 không.** Nếu không, hoặc đổi provider, hoặc phải sửa `CHECK` của
   migration 044 + verifier + backend — tức một vòng migration và review nữa. Đây là câu hỏi đắt
   nhất, phải trả lời đầu tiên.
2. Có tạo được khóa **cấm export** không, và provider có từ chối export **kể cả với admin** không.
3. Định dạng chữ ký/public key trả về (raw hay DER/PEM, base64 hay hex) — Vault trả
   `vault:v<n>:<base64>`; provider khác gần như chắc chắn khác.
4. Có định danh phiên bản khóa ổn định để ánh xạ vào `key_version` không.
5. Cơ chế danh tính cho signer (service account / workload identity / static credential) và cách
   cấp credential đó vào tiến trình mà **không** ghi ra file plaintext lâu dài.

## 4. Các bước

| Bước | Nội dung | Cổng |
|---|---|---|
| M1 | PO decision chốt provider + authority | PO |
| M2 | Khảo sát 5 câu ở mục 3 trên **tài khoản thử**, không phải production | báo cáo, không gate |
| M3 | Viết `kms_transport_<provider>.py` + nhánh trong factory + unit test | — |
| M4 | Chạy lại **nguyên xi** `scripts/m4_h2_kms_e2e_sandbox.py` với provider mới: 5 kịch bản phải cho cùng kết luận | CA substantive review |
| M5 | Provision khóa production (cấm export), chứng minh admin cũng không export được | PO gate riêng |
| M6 | Công bố public key production vào registry bằng `m4_publish_transcript_public_key.py` | evidence |
| M7 | Deploy dormant: signer vẫn không chạy, capture vẫn OFF | PO gate + CA closure |
| M8 | Rehearsal ký thật, rồi capture | các gate riêng |

Bước M4 là mấu chốt: nếu kịch bản E2E phải **sửa** để chạy với provider mới, đó là dấu hiệu contract
đã bị rò rỉ chi tiết nhà cung cấp — phải sửa adapter, không phải sửa kịch bản.

## 5. Ánh xạ ba chế độ hỏng sang provider khác

Kịch bản E2E kiểm **hành vi**, không kiểm mã lỗi của Vault. Adapter mới chỉ cần ánh xạ đúng:

| Tình huống | Phải nâng thành |
|---|---|
| không gọi được backend (mạng, timeout, 5xx) | `SigningBackendUnavailable` |
| bị từ chối quyền / sai credential | `SigningBackendDenied` |
| khóa/phiên bản không tồn tại hoặc bị vô hiệu | `SigningBackendDenied` (hoặc `Unavailable` nếu provider trả 5xx) |
| phản hồi dị dạng, sai độ dài | `SigningBackendUnavailable` |

Cả hai lớp đều là `SigningBackendError` ⇒ fenced unit thất bại ⇒ không commit sample. Phân biệt chỉ
để người vận hành đọc log biết nên sửa hạ tầng hay sửa cấu hình — nên adapter mới **phải** đính kèm
thông điệp gốc của provider (đã cắt ngắn, không chứa nội dung được ký).

## 5b. Hai ràng buộc adapter mới BẮT BUỘC giữ

1. **Guard môi trường.** Nếu provider mới cũng là sandbox-only, hàm khởi tạo của nó phải gọi
   `assert_khong_phai_production(app_env, "<tên>")`. Nếu là provider production thì **không** thêm
   guard đó, nhưng cũng **không** được sửa/nới guard của backend sandbox — mỗi provider là một
   nhánh explicit riêng trong factory, không bao giờ là fallback của nhau.
2. **Chỉ phát mã lỗi an toàn.** Adapter tự phân loại lỗi provider thành
   `backend_unavailable` / `backend_denied` / `backend_key_disabled` / `backend_misconfigured`
   (bảng ở `M4-H2-KMS-THREAT-MODEL-VA-RUNBOOK-VI.md` §5b) và **không** đưa text của provider vào
   thông điệp ngoại lệ hay log. Kịch bản E2E khẳng định trên mã, nên adapter nào ánh xạ đúng thì
   chạy được ngay mà không phải sửa kịch bản.

## 6. Chuyển khóa: không migrate khóa, chỉ rotate

Khóa sandbox **không bao giờ** được mang sang production (PO decision, mục Ràng buộc). Đường đi
đúng là coi khóa production như một **phiên bản mới**:

1. tạo khóa mới ở provider production;
2. công bố public key vào registry (`key_id` mới hoặc phiên bản mới);
3. trỏ signer sang đó;
4. đánh `retired_at` cho khóa sandbox nếu nó từng xuất hiện trong registry của môi trường đó.

Chữ ký sandbox cũ (nếu có, trong DB rác) không cần và không được mang sang.

## 7. Rủi ro đã lường

| Rủi ro | Xử lý |
|---|---|
| Provider không hỗ trợ Ed25519 | trả lời **trước** khi chốt (mục 3.1); nếu buộc đổi thuật toán thì phải có migration + CA review riêng, không làm lén trong PR adapter |
| Credential của signer hết hạn giữa ceremony | fail-closed, không có sample sai; runbook đưa việc kiểm hạn credential vào preflight |
| Độ trễ mạng ra cloud cao hơn Vault nội bộ | timeout ngắn + không retry; nếu chậm quá thì fenced unit thất bại và thử lại lần chạy sau — không nới timeout để "cho qua" |
| Adapter mới rò rỉ chi tiết provider ra contract | dấu hiệu nhận biết: kịch bản E2E phải sửa mới chạy được (xem M4) |
| Chi phí/khóa chặt nhà cung cấp | `key_id`/`key_version` là chuỗi tự do, verifier chỉ cần public key — đổi provider lần nữa vẫn là thay một file transport |
