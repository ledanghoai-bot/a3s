# Hướng dẫn cập nhật cẩm nang

## Nguồn biên tập

Tệp trong `chuong/`, `phu-luc/`, `MUC-LUC.md` và `nguon/NGUON-VA-PHUONG-PHAP.md` là nguồn biên tập. `HANDBOOK.md` là bản ghép. Không sửa riêng bản ghép rồi để các chương lệch nhau.

## Nguyên tắc

1. Độc giả là manager. Mỗi chi tiết kỹ thuật phải giúp hiểu hậu quả, đặt câu hỏi hoặc quyết định.
2. Tình huống Alpha3s phải có mã nguồn; giữ phạm vi và trạng thái của tài liệu.
3. Số minh họa phải ghi giả định. Không tạo số kinh doanh để lấp khoảng trống hồ sơ.
4. Thuật ngữ mới được giải thích bằng tiếng phổ thông ngay khi dùng có ý nghĩa quan trọng.
5. Quy tắc lịch sử không mặc định còn áp dụng. Ghi phần bị thay và điều kiện hiện hành.
6. Không đưa bí mật vận hành hoặc dữ liệu khách vào nội dung học.
7. Khi nguồn quốc tế thay đổi, ghi phiên bản và ngày tra cứu; không tự tuyên bố chứng nhận.

## Quy trình tạo lại bản liền mạch

Ghép theo thứ tự: lời mở đầu; MUC-LUC; chương 01–18; phụ lục A–D; nguồn và phương pháp. Đổi liên kết tương đối từ thư mục con về gốc repo trong bản ghép. Giữ bản theo chương để dễ cập nhật và review.

Sau ghép, đếm dung lượng trên các chương và phụ lục đúng một lần, không cộng thêm bản HANDBOOK. Kiểm liên kết Markdown tới tệp, mã nguồn Sxx, cấu trúc chương và các phát biểu trạng thái. Ghi kết quả vào báo cáo kiểm tra; cập nhật CHANGELOG.

Markdown không quy định trang giấy. Khi xuất PDF về sau, chọn khổ, font và khoảng cách phù hợp rồi kiểm số trang thực; không cam kết số trang tuyệt đối chỉ từ số từ.
