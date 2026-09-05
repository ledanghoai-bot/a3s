# Dẫn dắt dự án AI

## Cẩm nang thực hành cho PO và Manager từ Alpha3s

**Phiên bản 1.0 · Tiếng Việt · Mốc đọc hồ sơ: 05/09/2026**

Một dự án AI không kết thúc khi bot trả lời trôi chảy. Người quản lý còn phải biết câu trả lời dựa vào đâu, hành động nào được phép tự động, ai chịu trách nhiệm khi sai, và bằng chứng nào đủ để đi tiếp. Cuốn sách này giúp bạn thực hành những quyết định ấy qua hành trình Alpha3s, một dự án trợ lý bán hàng và chăm sóc khách hàng cho 3S Coffee.

Độc giả chính là Product Owner (người chịu trách nhiệm giá trị sản phẩm), quản lý dự án, quản lý kinh doanh và người phụ trách đưa AI vào một đội ngũ nhỏ. Bạn không cần biết lập trình. Các đoạn nói về kỹ thuật đều nhằm giúp bạn đặt câu hỏi, đánh giá lựa chọn hoặc ra quyết định.

### Bắt đầu đọc

- [Đọc toàn bộ cẩm nang](HANDBOOK.md): bản liền mạch được ghép từ các chương và phụ lục.
- [Mục lục và lộ trình học](MUC-LUC.md): chọn chương theo vấn đề đang gặp.
- [Bộ biểu mẫu sử dụng ngay](phu-luc/A-bo-bieu-mau.md).
- [Bài tập tổng hợp và gợi ý đánh giá](phu-luc/B-workbook.md).
- [Từ điển thuật ngữ](phu-luc/C-thuat-ngu.md).
- [Nguồn và giới hạn diễn giải](nguon/NGUON-VA-PHUONG-PHAP.md).
- [Báo cáo kiểm tra bản thảo](bien-tap/BAO-CAO-KIEM-TRA.md).

### Bạn sẽ học được gì?

Sau khi đọc và làm bài tập, bạn có thể viết một đề bài AI theo kết quả kinh doanh; phân biệt việc AI đề xuất với việc hệ thống thực thi; tổ chức nguồn tri thức và bộ kiểm thử; quyết định mức kiểm soát theo rủi ro; nghiệm thu bằng bằng chứng; và đưa sản phẩm vào vận hành với người chịu trách nhiệm rõ ràng.

Cuốn sách kể lại các chặng chính có hồ sơ trong workspace: nền tảng tri thức, chatbot và hạ tầng ban đầu; lựa chọn Customer Terminal; các mốc Phase I-B M0–M4; dữ liệu địa chỉ M5; và bước điều chỉnh cơ chế quản lý ở Memo 169/Addendum 171. Đích gần nhất được hồ sơ xác nhận là Gate A development đã đóng; Gate B được chấp nhận để xây dựng/kiểm thử. Đây không phải câu chuyện mặc định đã ra mắt thương mại thành công.

### Quy ước đọc

**Tình huống Alpha3s** là diễn giải từ hồ sơ được dẫn bằng mã nguồn S01, S02… **Bài học quản lý** là nhận định biên tập từ các tình huống đó. **Ví dụ giả định** và **bài tập** được tạo phục vụ học tập; số liệu của chúng không phải kết quả của Alpha3s. Các mức ngưỡng của dự án là quyết định trong bối cảnh cụ thể, không phải chuẩn chung cho ngành.

Markdown không có số trang cố định. Dung lượng quy đổi và giả định dàn trang được công bố trong báo cáo kiểm tra; không dùng dòng ngắt trang để tạo cảm giác đủ độ dài. Bản theo chương là nguồn biên tập, bản HANDBOOK được ghép lại để đọc, tìm kiếm hoặc xuất bản sau này.

### Repo và phạm vi sử dụng

Đây là một Git repository cục bộ riêng, đặt bên trong workspace Alpha3s. Chưa gắn remote và chưa công bố lên Internet. Toàn bộ nội dung học nằm trong repo này; liên kết tới hồ sơ gốc ở repo cha chỉ phục vụ kiểm chứng bổ sung. Không sao chép khóa, thông tin đăng nhập, địa chỉ máy chủ hoặc dữ liệu khách hàng vào cẩm nang.

Muốn áp dụng cho dự án khác, hãy sao chép biểu mẫu, thay bối cảnh, xác minh nguồn và chốt người quyết định. Không sao chép nguyên tên tài khoản, ngưỡng điểm, cửa sổ triển khai hay mô hình phê duyệt của Alpha3s.
