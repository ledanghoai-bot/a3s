# Đề xuất cải thiện dữ liệu NLU — sau khi test Semantic Router (Bat C)

> Gửi từ team Dev sau khi test `datasets/nlu/` với model embedding
> `paraphrase-multilingual-mpnet-base-v2` trên 60 câu held-out
> (`intent-routing-tests.yaml`). Đây là góp ý về **nội dung/số lượng dữ
> liệu**, không phải lỗi kỹ thuật.

## 1. Đề xuất ngưỡng `low_confidence_threshold`

Đã thử 7 mức ngưỡng (0.60 → 0.90), đo tỷ lệ Đúng/Sai/Clarify trên 60 test:

| Ngưỡng | Đúng | Sai | Clarify | Tỷ lệ sai trong lúc "dám đoán" |
|---|---|---|---|---|
| 0.60 | 58.3% | 36.7% | 5.0% | 38.6% |
| 0.65 (default hiện tại) | 55.0% | 31.7% | 13.3% | 36.5% |
| 0.70 | 50.0% | 26.7% | 23.3% | 34.8% |
| 0.75 | 41.7% | 21.7% | 36.7% | 34.2% |
| 0.80 | 26.7% | 13.3% | 60.0% | 33.3% |
| **0.85** | **20.0%** | **6.7%** | 73.3% | **25.0%** |
| 0.90 | 16.7% | 6.7% | 76.7% | 28.6% |

**Nhận xét:** từ 0.60→0.80, tỷ lệ sai-khi-dám-đoán gần như không đổi
(~33-38%) — tăng ngưỡng trong khoảng này chỉ đẩy đều cả case đúng lẫn sai
sang hỏi lại (clarify), không thực sự lọc được case sai. Chỉ tới **0.85**
mới có bước nhảy rõ rệt.

**Đề xuất:** cập nhật `defaults.low_confidence_threshold` trong
`intent-catalog.yaml` từ `0.65` lên **`0.85`**. Lý do ưu tiên: với 1 bot
CSKH, trả lời sai mà tự tin nguy hiểm hơn nhiều so với hỏi lại 1 câu ngắn.

## 2. Các cặp intent hay bị nhầm lẫn — cần thêm utterance phân biệt rõ hơn

Không chỉ cần **thêm số lượng** utterance, mà cần thêm utterance **nhấn
mạnh điểm khác biệt** giữa các intent trong cùng 1 cụm dễ nhầm dưới đây
(liệt kê theo từng nhóm ngữ nghĩa gần nhau):

### Nhóm A — Logistics sau mua hàng (nhầm lẫn nhiều nhất)
`ask_payment`, `ask_cod`, `ask_shipping_fee`, `ask_tracking`,
`ask_order_status`, `ask_shipping_availability`, `ask_delivery_time`

Ví dụ case sai thật:
- "bên mình thu tiền qua kênh nào" → nhầm `ask_cod` (đúng: `ask_payment`)
- "tôi muốn trả bằng chuyển khoản" → nhầm `ask_cod` (đúng: `ask_payment`)
- "không trả trước có được không" → nhầm `request_return` (đúng: `ask_cod`)
- "ước tính phần vận chuyển giúp tôi" → nhầm `ask_tracking` (đúng: `ask_shipping_fee`)
- "shop đã bàn giao đơn của mình chưa" → nhầm `ask_shipping_availability` (đúng: `ask_order_status`)

**Đề xuất:** cân nhắc bổ sung entity-aware rule (dùng `order_id` — nếu
khách nhắc mã đơn cụ thể → ưu tiên `ask_order_status`/`ask_tracking`;
`payment_method` — nếu nhắc "chuyển khoản"/"tiền mặt" → ưu tiên
`ask_payment`) thay vì chỉ dựa thuần vào độ tương đồng ngữ nghĩa, vì
nhóm này có từ vựng chung rất nhiều (đơn hàng, giao, tiền, nhận...).

### Nhóm B — Chi tiết sản phẩm
`ask_product`, `ask_ingredients`, `ask_freeze_dried`, `ask_taste`, `compare_coffee`

Ví dụ case sai thật:
- "dịch cà phê biến thành tinh thể kiểu gì" → nhầm `ask_ingredients` (đúng: `ask_freeze_dried`)
- "có công bố blend hạt không" → nhầm `purchase_product` (đúng: `ask_ingredients`)
- "hậu vị có lưu lâu không" → nhầm `ask_delivery_time` (từ "lưu" trùng nghĩa "delivery"?) (đúng: `ask_taste`)
- "người quen uống máy có hợp không" → nhầm `ask_taste` (đúng: `compare_coffee`)

### Nhóm C — Khiếu nại/đổi trả
`complaint`, `request_return`, `request_refund`

Ví dụ case sai thật:
- "tôi cần phản ánh chính thức" → nhầm `request_consultation` (đúng: `complaint`)
- "hướng dẫn đổi hũ bị hỏng" → nhầm `complaint` (đúng: `request_return`)

### Nhóm D — `greeting` bị match nhầm với câu có nội dung cụ thể
- "mặt hàng chính của shop là gì" → nhầm `greeting` (đúng: `ask_product`)
- "shop đã bàn giao đơn của mình chưa" → nhầm `greeting` (đúng: `ask_order_status`)

**Nghi vấn:** utterance mẫu của `greeting` có thể đang quá ngắn/chung
chung, khiến vector trung bình của cụm `greeting` "kéo" các câu không
liên quan lại gần. Đề xuất rà soát lại có utterance `greeting` nào quá
mơ hồ (không rõ ràng là lời chào) hay không.

## 3. Kế hoạch tiếp theo

Sau khi team Knowledge cân nhắc bổ sung/điều chỉnh utterance theo các
nhóm trên (không bắt buộc theo đúng câu chữ đề xuất, chỉ cần đúng tinh
thần "làm rõ ranh giới"), gửi lại `datasets.zip` bản cập nhật — team Dev
sẽ chạy lại đúng bộ test held-out này (`--sweep` + `--eval`) để đo mức
cải thiện thực tế trước khi quyết định bước tiếp theo (Bat D).

## Bổ sung (18/7) — 2 góp ý từ `routing-rules.yaml`

Sau khi tích hợp `routing-rules.yaml` (25 rule ưu tiên cao), phát hiện thêm
2 điểm mơ hồ trong chính bộ rule (không phải lỗi kỹ thuật):

1. **Thiếu rule cho `b2b_inquiry`** — câu “doanh nghiệp tôi cần báo giá
   định kỳ” bị khớp nhầm `ask_price` qua cụm “báo giá” (RTE-019), vì
   trong 25 rule hiện tại **không có rule nào dành riêng cho
   `b2b_inquiry`**. Đề xuất thêm 1 rule ưu tiên cao hơn RTE-019, ví dụ
   khớp các cụm như “đại lý”, “doanh nghiệp”, “số lượng lớn”, “nhập
   sỉ”.
2. **Từ “giống” đa nghĩa** — RTE-013 (`compare_coffee`) dùng “giống” với
   nghĩa “tương tự”, nhưng trong tiếng Việt “giống” còn có nghĩa “chủng
   loại/giống cà phê” (thuộc `ask_ingredients`) — ví dụ “giống nào” bị
   khớp nhầm thành `compare_coffee`. Đề xuất: thu hẹp cụm trong
   RTE-013 thành “giống như” (rõ nghĩa so sánh hơn “giống” đứng riêng).

**Lưu ý thêm:** đã tự phát hiện và sửa 1 bug kỹ thuật nghiêm trọng phía
Dev (không cần team Knowledge xử lý) — cả “chưa” (not yet) và “chua”
(vị chua, trong RTE-012) đều bị quy về cùng 1 chuỗi sau khi hệ thống
bỏ dấu để so khớp, gây khớp nhầm hàng loạt. Đã sửa bằng cách giữ
nguyên dấu tiếng Việt khi so khớp các rule phía Dev — không cần team
Knowledge thay đổi gì.

## Bổ sung lần 2 (18/7) — vấn đề phủ định (negation)

Sau khi sửa bug trên, chạy lại thì Pattern Router chỉ còn **đúng 3/150
sai** (từ 25/150) — 2 case cũ (b2b_inquiry, “giống”) + 1 case mới:

**Câu:** “không đổi hàng, vui lòng hoàn khoản thanh toán”
**Kết quả:** khớp nhầm `request_return` (đúng ra phải là `request_refund`)
**Nguyên nhân:** RTE-016 (`request_return`) khớp qua cụm “đổi hàng” xuất
hiện trong câu — nhưng rule lại **không nhận ra từ “không” đứng ngay
trước đang phủ định** ý đó (khách **TỨC LÀ KHÔNG MUỐN** đổi hàng, muốn
hoàn tiền thay vì đổi). Đây là giới hạn thật của cách khớp theo cụm từ
đơn giản (không hiểu ngữ cảnh phủ định).

**Đề xuất:** cân nhắc thêm cơ chế “nếu có từ phủ định (không/chẳng/chưa)
đứng ngay trước cụm khớp → giảm ưu tiên hoặc bỏ qua rule đó”, hoặc đơn
giản hơn: với các cặp đối lập như `request_return`/`request_refund`, khi
cả 2 có thể cùng xuất hiện từ khóa trong 1 câu, nên ưu tiên tìm cụm đặc
trưng hơn cho `request_refund` (như “thanh toán”/“số tiền” đi kèm “hoàn”)
để giảm nhầm lẫn.

**Tổng hợp kết quả sau toàn bộ fix (Pattern Router riêng):**
- Trước: 32.7% tự phủ, 25/150 sai (bị nhiễu bởi bug đồng âm)
- Sau: 35.3% tự phủ, **chỉ 3/150 sai**, cả 3 đều là mơ hồ ngữ nghĩa thật
  của rule (không phải bug), đã ghi nhận đầy đủ ở trên.
