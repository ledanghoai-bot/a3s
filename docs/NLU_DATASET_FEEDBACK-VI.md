# Góp ý dữ liệu NLU (`datasets/nlu/`) — sau khi build & test thật

> Gửi từ team Dev sau khi tích hợp `datasets.zip` vào code (Bat A — Loader +
> Validator + Normalization engine). Đây là góp ý về **dữ liệu**, không phải
> lỗi kỹ thuật — code phía Dev đã chạy đúng, chỉ là 1 vài rule trong
> `normalization.yaml` chưa phủ hết các biến thể test đã đề ra.

## Tóm tắt kết quả test

- **Validation cấu trúc dữ liệu: 0 lỗi** — không có ID trùng, không có
  utterance tham chiếu intent không tồn tại, không có train/test leakage.
  Bộ dữ liệu 30 intent / 300 utterance / 100 normalization rule đều sạch.
- **Test normalization: 36/40 PASS** (`datasets/tests/normalization-tests.yaml`).
  4 case fail dưới đây đều là do **thiếu rule**, không phải lỗi engine xử lý.

## 4 case cần bổ sung rule

### 1. `NLU-NRM-T015` — thiếu biến thể không dấu
- **Input:** `"chot don nha"`
- **Kỳ vọng:** `"xác nhận đặt hàng"`
- **Rule hiện có:** `NRM-050: "chốt đơn nha" → "xác nhận đặt hàng"` (match: phrase) — **viết có dấu**
- **Vấn đề:** khách gõ không dấu (`"chot don nha"`) không khớp được với rule viết có dấu.
- **Đề xuất:** thêm 1 rule biến thể không dấu, ví dụ:
  ```yaml
  - {id: NRM-XXX, source: "chot don nha", target: "xác nhận đặt hàng", match: phrase}
  ```

### 2. `NLU-NRM-T024` — thiếu rule cho cách viết tắt "dh"
- **Input:** `"dh toi dau"`
- **Kỳ vọng:** `"đơn hàng tới đâu"`
- **Rule hiện có:** `NRM-079: "don toi dau" → "đơn hàng tới đâu"` (chỉ khớp `"don"`, không khớp `"dh"`)
- **Vấn đề:** đã có rule token `"dh" → "đơn hàng"` riêng, nên khi khách gõ
  `"dh toi dau"`, phần `"dh"` bị đổi thành `"đơn hàng"` trước, còn lại
  `"toi dau"` thì **không có rule nào** xử lý tiếp (rule `NRM-079` chỉ nhận
  diện đúng chuỗi `"don toi dau"`, không phải `"toi dau"` đứng riêng).
- **Đề xuất:** thêm 1 rule độc lập cho cụm `"toi dau"`, ví dụ:
  ```yaml
  - {id: NRM-XXX, source: "toi dau", target: "tới đâu", match: phrase}
  ```

### 3. `NLU-NRM-T035` — thiếu rule "ad" đứng một mình
- **Input:** `"thanks ad"`
- **Kỳ vọng:** `"cảm ơn admin"`
- **Rule hiện có:** chỉ có `"ad oi" → "admin ơi"` (bắt buộc phải có "oi" theo sau)
- **Vấn đề:** chưa có rule cho `"ad"` đứng một mình (không kèm "oi").
- **Đề xuất:** thêm 1 rule token riêng:
  ```yaml
  - {id: NRM-XXX, source: "ad", target: "admin", match: token}
  ```
  (cân nhắc: `"ad"` khá ngắn, nên kiểm tra kỹ có gây nhiễu với từ khác không
  trước khi thêm dạng token toàn cục.)

### 4. `NLU-NRM-T037` — tên thương hiệu bị normalize nhầm
- **Input:** `"3S Coffee"`
- **Kỳ vọng:** giữ nguyên `"3S Coffee"` (không đổi)
- **Rule hiện có:** `"coffee" → "cà phê"` (match: token, áp dụng toàn cục,
  không phân biệt hoa/thường)
- **Vấn đề:** rule này đúng cho câu thường ("mình muốn uống coffee"), nhưng
  vô tình áp cả vào tên thương hiệu viết hoa `"3S Coffee"`, biến thành
  `"3S cà phê"` — sai vì đây là danh xưng riêng, không nên bị dịch/thay thế.
- **Đề xuất (cần team Knowledge quyết định hướng xử lý, ngoài phạm vi engine
  hiện tại):**
  - Phương án A: thêm khái niệm "cụm từ được bảo vệ" (protected phrases) —
    ví dụ `"3S Coffee"` luôn được match và giữ nguyên **trước khi** các rule
    token khác chạy.
  - Phương án B: đổi rule `"coffee" → "cà phê"` thành phân biệt hoa/thường
    (chỉ áp dụng khi viết thường `"coffee"`, không áp dụng khi viết hoa
    `"Coffee"` — dù cách này không tổng quát 100%, vì khách có thể viết hoa
    ngẫu nhiên đầu câu).
  - Phương án C: chấp nhận giới hạn này ở giai đoạn MVP (không ảnh hưởng lớn
    vì ngữ cảnh câu vẫn đủ để hiểu đúng ý).

## Ghi chú thêm (không cần hành động, chỉ để rõ phạm vi)

Quy tắc "train/test leakage" trong `README.md` chỉ nên áp dụng cho
`intent-routing-tests.yaml` (test phân loại intent) — **không áp dụng** cho
`normalization-tests.yaml`, vì bản chất 2 file khác nhau: file sau test đúng
hàm chuẩn hóa câu, và việc trùng câu với utterance mẫu (cả 2 cùng lấy nguồn
từ cách viết thông tục thực tế) là **bình thường**, không phải lỗi rò rỉ dữ
liệu train/test thật sự.
