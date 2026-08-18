# M4 H2-B — Nguồn tin cậy cho Workload Identity Federation: bảng lựa chọn để PO quyết

> Đáp F-H2B-01 mục 5 (`PHASE1B-M4-H2B-GOOGLE-KMS-SUBSTANTIVE-REVIEW-1-VI`): CA yêu cầu Dev **không
> tự chọn** issuer, mà nộp bảng trade-off trước. Tài liệu này **không** chọn hộ.

## 1. Vấn đề cần quyết

Workload Identity Federation **không tự tạo danh tính**. Nó đổi một credential có sẵn từ một IdP
bên ngoài lấy short-lived Google token. Nhưng VPS Alpha3S là **một VM thường** — không phải GCE,
không phải GKE, không có metadata identity, không có ambient credential nào.

Nên câu hỏi thật không phải "cấu hình WIF thế nào", mà: **cái gì trên VPS đủ tư cách chứng minh
'tôi là signer của Alpha3S'?**

Đây cũng là lý do bản trước của Dev sai: nó đọc thẳng một access token từ biến môi trường — tiện,
nhưng đó là *tiêm token*, không phải danh tính, và nó lặng lẽ tạo ra một đường vận hành mà PO chưa
duyệt. CA bác đúng.

## 2. Bốn phương án

| | A. WIF + X.509 | B. WIF + OIDC tự dựng | C. Ký từ CI (GitHub OIDC) | D. Chuyển signer sang GCE |
|---|---|---|---|---|
| Cái gì chứng minh danh tính | chứng chỉ client + khóa riêng trên VPS | JWT ngắn hạn do một IdP của mình phát | OIDC token GitHub phát cho workflow | metadata identity của GCE |
| Bí mật nằm trên VPS | **có** — khóa riêng của chứng chỉ | **có** — khóa ký của IdP (nếu IdP chạy cùng VPS) | **không** | **không** |
| Hạ tầng phải thêm | CA nội bộ + quy trình cấp/thu hồi chứng chỉ | một IdP (dựng, vá, canh) | không | một VM GCE + chuyển kiến trúc capture |
| Thu hồi | thu hồi chứng chỉ / sửa attribute condition | thu hồi khóa IdP | sửa attribute condition | xóa/gỡ quyền VM |
| Hợp với ceremony theo đợt | tốt | tốt | **kém** — capture chạy trên VPS, không phải trong CI | tốt |
| Chi phí vận hành | trung bình | **cao** | thấp | trung bình + tiền VM |
| Rủi ro chính | khóa chứng chỉ bị lộ ⇒ mạo danh signer trong thời hạn chứng chỉ | IdP thành điểm yếu mới; tự dựng auth dễ sai | **không khả thi với kiến trúc hiện tại** | phải đưa dữ liệu capture lên GCE — đụng ranh giới dữ liệu khách |

## 3. Nhận xét thẳng

- **C không khả thi** với kiến trúc hiện tại: signer chạy trên VPS lúc ceremony, không phải trong
  GitHub Actions. Đưa nó vào CI nghĩa là đưa đường capture dữ liệu khách vào CI — Dev không đề xuất.
- **B đắt và tự chuốc rủi ro**: dựng một IdP để phục vụ đúng một client là thêm một hệ thống phải vá
  và canh; nếu IdP chạy cùng VPS thì tính tách bạch cũng không hơn A.
- **D sạch nhất về danh tính** nhưng kéo theo câu hỏi lớn hơn nhiều: dữ liệu khách có được rời VPS
  sang GCE không. Đó là quyết định về **ranh giới dữ liệu**, không phải về xác thực — cần PO/CA
  riêng, và nên tránh gộp vào việc này.
- **A là phương án ít lệ thuộc nhất** với kiến trúc đang có. Đổi lại, vẫn có **một bí mật trên VPS**
  — nhưng khác về bản chất so với khóa ký: nó chỉ cho phép *mạo danh trong thời hạn ngắn*, có thể
  thu hồi ngay, và **không** lấy được khóa ký ra khỏi Google KMS. Tức kịch bản xấu nhất là "kẻ tấn
  công ký được trong cửa sổ chưa thu hồi", không phải "mất khóa vĩnh viễn".

Nếu PO chọn A, Dev đề nghị kèm: chứng chỉ **thời hạn ngắn**, quy trình xoay định kỳ, và giữ nguyên
mô hình ceremony (credential chỉ hiện diện trong cửa sổ ceremony, thu hồi sau khi xong).

## 3b. QUYẾT ĐỊNH CỦA PO (18/8/2026)

**PO chọn phương án A — WIF + X.509.**

Hệ quả trực tiếp, ghi lại để không phải suy diễn về sau:

- danh tính của signer là **một chứng chỉ client**; VPS giữ khóa riêng của chứng chỉ đó;
- Google WIF provider phải là loại **X.509** (trust store chứa trust anchor của CA nội bộ), không
  phải OIDC;
- thứ nằm trên VPS là **credential để mạo danh trong thời hạn ngắn**, không phải khóa ký. Khóa ký
  vẫn ở Google KMS và không export được — kịch bản xấu nhất là "ký được cho tới khi thu hồi", không
  phải "mất khóa vĩnh viễn";
- **thu hồi** là năng lực bắt buộc, không phải tùy chọn: phải làm được ngay mà không cần chạm khóa
  ký.

## 4. Việc Dev cần PO trả lời

1. ~~Chọn A, B, C hay D.~~ → **đã chốt: A (WIF + X.509)**, 18/8/2026.
2. **CÒN MỞ** — ai vận hành CA nội bộ, thời hạn chứng chỉ, quy trình thu hồi.
3. **CÒN MỞ** — credential có được phép nằm trên VPS **ngoài** cửa sổ ceremony không, hay phải nạp
   lúc ceremony rồi gỡ.

Hai câu còn mở **không chặn phần code** (adapter chỉ gọi `load_credentials_from_file`, không cần
biết hình dạng credential), nhưng **chặn runbook vận hành** và **chặn Provisioning Gate** — vì
chúng quyết định vòng đời chứng chỉ và ai chịu trách nhiệm.

## 5. Trạng thái code trong lúc chờ

`_token_provider_google()` **fail-closed**: thiếu `M4_GOOGLE_CREDENTIAL_CONFIG` thì ném
`SigningBackendMisconfigured` kèm trỏ về tài liệu này. Đường `M4_GOOGLE_ACCESS_TOKEN` đã **bị gỡ
hẳn**. Khi PO chốt, phần phải viết chỉ là *credential configuration* của external-account — logic
ký, DB, verifier và E2E không đổi một dòng.
