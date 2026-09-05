# Báo cáo review bản 1.0 dưới góc nhìn Dev và Project Manager

**Ngày review:** 05/09/2026. **Đối tượng:** repo cẩm nang tại commit `59fec79` (30 tệp Markdown). **Người review:** Claude Code, theo yêu cầu của chủ repo. **Không phải** phản biện của chuyên gia thứ hai; các kiểm tra tự động được mô tả đủ để tái lập.

## 1. Kết luận

Cẩm nang sạch về kỹ thuật tài liệu và trung thực về nguồn. Toàn bộ số đếm trong [báo cáo kiểm tra bản thảo](BAO-CAO-KIEM-TRA.md) được tái lập chính xác; 25/25 hash nguồn khớp; mọi số liệu, ngày tháng và thuật ngữ trích từ hồ sơ Alpha3s đều đối chiếu đúng. Phát hiện **một lỗi nội dung** (đã sửa trong bản 1.0.1) và **một vấn đề trạng thái**: hồ sơ Alpha3s đã đi qua mốc cắt của cẩm nang ngay trong ngày phát hành, nên phần trạng thái Gate B/Gate C cần bản cập nhật riêng.

## 2. Phương pháp và kết quả kiểm tra tự động

| Hạng mục | Cách kiểm | Kết quả |
|---|---|---:|
| Liên kết Markdown tương đối, 30 tệp | Duyệt mọi liên kết dạng tệp tương đối, kiểm tệp đích tồn tại | 0 đích thiếu |
| Liên kết ngoài (Phụ lục D) | `curl -I` 5 URL | 4 trả 200; ISO trả 403 do chặn bot, không phải hỏng |
| Hash nguồn S01–S25 | `sha256sum` từng tệp trong workspace so với `DAU-VAN-TAY-NGUON.md` | 25/25 khớp |
| Đơn vị `\S+`, chương + phụ lục | Node.js, UTF-8 | 26.466, khớp báo cáo |
| Đơn vị `\S+`, HANDBOOK | Node.js, UTF-8 | 29.372, khớp báo cáo |
| Code fence trong HANDBOOK | Đếm dòng bắt đầu bằng ba dấu backtick | 14 dấu, 7 khối, khớp |
| Bản ghép chứa đủ chương/phụ lục | So từng dòng không rỗng sau khi chuẩn hóa liên kết `../` | 0 dòng thiếu trên 22 tệp nguồn biên tập |
| Mã Sxx được trích | Quét `\bS\d{2}\b` trong chương/phụ lục | Chỉ S01–S25, không có mã lạ; S25 chỉ dùng ở chương 14 |
| Biểu mẫu A1–A14, bài B1–B8 được nhắc | Quét tham chiếu trong chương và mục lục | Mọi tham chiếu đều có đích |
| Kết thúc dòng | Đếm byte | Toàn bộ tệp dùng LF, không BOM |

## 3. Đối chiếu trích dẫn với hồ sơ gốc

Đã mở từng tệp nguồn và tìm đúng câu được trích. Tất cả các phát biểu dưới đây khớp nguồn:

- S02/S03: roadmap 2 vCPU/4 GB, báo cáo Giai đoạn I 4 vCPU/8 GB, ngày 22/07 và 24/07.
- S03: 12/12 issue Giai đoạn I đã đóng.
- S05: cổng đổi giá cần quyền quản lý giá; Telegram dual-poller đã loại bỏ.
- S06: chấp nhận development, không cấp merge vì repo auto-deploy khi push `main`.
- S07: Messenger chưa cutover; bare GET `/webhook` trả 403 là từ chối hợp lệ, không phải tín hiệu hỏng; Telegram double-poller 409.
- S08: hai policy retention chạy với candidates 0, deleted 0.
- S09: chuỗi 12 số, ngân hàng/giấy tờ/mã đơn; ngày 13/08.
- S10: bảy lớp đánh giá; S11: rubric và so sánh phiên bản; S12: bảng root cause có ASSEMBLY, GENERATION, UX, Tool.
- S13: collision một–nhiều là hard rule, kết quả `needs_staff_review`.
- S14: `approved_at: 2026-08-05`.
- S15: hard stop vì thiếu 3 principal thật; lệch mô hình grant theo role so với mô tả theo username; ngày 04/09.
- S16: transcript 49/49 PASS là evidence nộp, CA không tự chạy suite hay kiểm live.
- S17: ba loại finding BLOCKER NOW, FIX BEFORE HANDOVER, ADVISORY.
- S18: bốn tier DEV-INTERNAL, PRE-CUSTOMER, CUSTOMER-FACING, FINANCIAL.
- S19: 3.355 units, 10.560 aliases, gate 8/8, 2.404 legacy collisions, 0/0 temporary holders/grants.
- S20: ngưỡng `>= 0.95` auto khi hard rules pass, `0.80` đến dưới `0.95` customer confirmation, dưới `0.80` staff review.
- S21: hybrid retrieval có reranker; S22: bảng D5 cancel/expiry và retry không release lần hai.
- S23: chỉ đổi text trang signing guide, không thêm tuyên bố tự bảo đảm tuân thủ.
- S24: SUPERSEDED, dẫn sang M4-102A; S25: version 1.0.0, `draft_for_po_review`.
- Foundation (S01): version 2.0.0, cập nhật 20/07; "thành công không đo bằng số lượng tin nhắn hoặc số file Knowledge".
- Từ điển: CA là Chief Architect, đúng cách dùng trong CA-Docs.

## 4. Phát hiện

### 4.1. Lỗi nội dung, đã sửa trong 1.0.1

Chương 2 §2.2 viết "Các nguồn S01–S24" trong khi danh mục có 25 nguồn. Đã sửa thành S01–S25 ở `chuong/02-doc-hanh-trinh-alpha3s.md` và dòng tương ứng trong `HANDBOOK.md`.

### 4.2. Trạng thái Gate B/Gate C đã đi qua mốc cắt, chưa sửa

Cẩm nang ghi Gate B mới accepted for build/validation và "không có closure Gate B được dùng trong bản thảo". Tại thời điểm review, CA-Docs đã có:

| Tài liệu | Giờ tạo tệp 05/09 | Kết luận trong tài liệu |
|---|---|---|
| Review 177, Gate B completion v01 | 06:56 | CHANGES REQUIRED, 2 evidence gap |
| Closure 178, Gate B | 07:07 | CLOSED, đạt frozen DoD |
| Directive 179, Gate C | 07:12 | ACCEPTED FOR BUILD/VALIDATION |
| Review 180, Gate C submission v01 | 07:44 | CHANGES REQUIRED, 3 integration blocker |

HANDBOOK được ghép lúc 07:04. Review 177 có trước lúc ghép nhưng không nằm trong danh mục nguồn. Nội dung cẩm nang không sai tại thời điểm viết, nhưng người mở repo hôm nay nhận trạng thái cũ. Các chỗ cần cập nhật khi ra bản 1.1: README, lời mở đầu HANDBOOK, CHANGELOG, chương 2 (§2.2 và §2.5), §7.5, §12.5, mục S20 trong nguồn, §5 báo cáo kiểm tra. Cần thêm nguồn S26–S29 và hash tương ứng. Việc này là thay đổi nội dung, để chủ repo quyết định; báo cáo này không tự sửa.

### 4.3. Lời mở đầu HANDBOOK không có tệp nguồn

`HUONG-DAN-CAP-NHAT.md` quy định bản ghép đi từ "lời mở đầu; MUC-LUC; chương; phụ lục; nguồn", nhưng lời mở đầu chỉ tồn tại bên trong `HANDBOOK.md` và khác với README. Lần ghép sau phải chép tay từ bản cũ, trái nguyên tắc "không sửa riêng bản ghép". Đề xuất tách thành `LOI-MO-DAU.md` ở gốc repo.

### 4.4. Thiếu nguồn đóng M4

Bảng chặng ở chương 2 có dòng M4, nhưng danh mục nguồn dừng ở quyết định 05/08 (S14). Tệp `CA-Docs/PHASE1B-M4-FINAL-MILESTONE-CLOSURE-RECORD-101-VI.md` có sẵn và ghi trạng thái đóng. Thiếu nguồn này khiến timeline M4 không có điểm kết, trong khi sách nhấn mạnh đọc theo closure.

## 5. Góc nhìn Dev

- **Quyền thư mục:** repo do tài khoản sandbox Codex tạo; tài khoản Admin chạy `git` gặp lỗi dubious ownership, và `sed -i` không tạo được tệp tạm trong `chuong/`. Cách xử lý: `git config --global --add safe.directory E:/Alpha3s/ai-project-management-handbook` hoặc đổi owner thư mục.
- **Kết thúc dòng:** tệp dùng LF, nhưng git của máy đang bật `core.autocrlf=true` nên cảnh báo sẽ chuyển sang CRLF ở lần touch tiếp theo. Nên thêm `.gitattributes` với `* text=auto eol=lf` để tránh diff nhiễu.
- **Không có script kiểm tra:** báo cáo kiểm tra công bố số từ, liên kết, fence, hash nhưng repo không chứa script nào. Mọi số ở mục 2 phải viết lại bằng Node.js và bash để tái lập. Đề xuất thư mục `scripts/` gồm: ghép HANDBOOK, đếm đơn vị, kiểm liên kết, kiểm hash nguồn.
- **Không có `.gitignore`:** hiện chưa gây hại vì repo chỉ có Markdown, nhưng khi thêm script hoặc xuất PDF sẽ cần.
- Commit duy nhất ghi tác giả `Codex <codex@local>`, chưa có remote. Đúng như README mô tả; nếu công bố sau này cần chuẩn hóa author.

## 6. Góc nhìn Project Manager

**Điểm mạnh.** Cấu trúc 18 chương đồng nhất: năng lực sau chương, tình huống có mã nguồn, ví dụ giả định được dán nhãn, bài tập và câu mang vào cuộc họp. Ranh giới "hồ sơ nói đã" và "đã kiểm chứng" giữ nhất quán trong toàn bộ 18 chương; không suy ROI, không suy khách thật, không biến ngưỡng Alpha3s thành chuẩn chung. Bộ biểu mẫu A1–A14 và workbook B1–B8 dùng ngay được; từ điển có cột "câu hỏi của manager" thực dụng.

**Điểm yếu cho người đọc là PM.**

- Bảng chặng ở §2.2 không có cột ngày, dù cả sách nhấn mạnh đọc theo thứ tự sự kiện. Nên thêm tháng/ngày cho từng dòng.
- Toàn sách không có hình nào ngoài khối text ở §3.1. Hành trình câu hỏi tới hành động và ba vùng ngưỡng 0,80/0,95 nên có sơ đồ.
- Mật độ thuật ngữ tiếng Anh cao từ chương 3. Từ điển bù được, nhưng chương nên liên kết trực tiếp tới mục C khi dùng lần đầu.
- Workbook có B9 và B10 nhưng mục lục và báo cáo kiểm tra chỉ nhắc B1–B8. Nên ghi rõ B9–B10 là hướng dẫn tổ chức, không phải bài tập.
- Ước lượng 60–75 trang là quy đổi; chưa có bản PDF nào để kiểm, đúng như sách tự nhận. Nếu cần bản in, phải dàn trang và đếm lại.

## 7. Việc đề xuất theo thứ tự

1. Ra bản 1.1 cập nhật trạng thái Gate B đã đóng, Gate C đang build và bổ sung nguồn 101, 177–180 kèm hash.
2. Tách lời mở đầu thành tệp nguồn; thêm `.gitattributes`.
3. Thêm `scripts/` để tái lập toàn bộ kiểm tra trong báo cáo kiểm tra bản thảo.
4. Thêm cột ngày cho bảng §2.2 và một hai sơ đồ ở chương 3 và 12.
