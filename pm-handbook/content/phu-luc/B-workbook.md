# Phụ lục B. Workbook: thực hành quyết định như một manager

Toàn bộ bài tập dưới đây là mô phỏng phục vụ học tập. Chúng lấy cảm hứng từ vấn đề quản lý của Alpha3s nhưng không phải biên bản sự kiện, số đo kinh doanh hay quyết định được cấp cho hệ thống thật. Hãy viết câu trả lời trước khi xem gợi ý.

## B1. Bot trả lời hay nhưng không giúp bán hàng

**Tình huống giả định:** sau hai tuần, đội báo đã có 500 hội thoại và trả lời tự động 90%. Nhân viên nói khách vẫn hỏi lại giá, đôi khi bot giải thích rất dài rồi mới trả lời. Lãnh đạo muốn mở thêm hai kênh vì “AI đã hoạt động tốt”. Chưa có thống kê đơn hợp lệ hoặc thời gian nhân viên sửa.

**Nhiệm vụ:** viết một bản phản hồi dưới 200 chữ cho lãnh đạo. Nêu điều có thể kết luận, điều chưa thể kết luận và một thử nghiệm vòng tới. Chọn tối đa bốn chỉ số để bổ sung.

**Gợi ý:** có thể nói hệ thống đã có lượt dùng theo báo cáo, nhưng chưa đủ căn cứ về giá trị bán hàng hay tiết kiệm. Cần xem tỷ lệ trả lời đúng giá từ nguồn hiện hành, công việc giải quyết đúng, mức hỏi lại và công sức hỗ trợ. Thử một hành trình hẹp trước khi mở kênh. Không tự kết luận dự án thất bại chỉ vì chưa có số đo; coi đây là lỗ hổng đo lường cần sửa.

**Cách chấm:** 1 điểm nếu phân biệt đầu ra và kết quả; 1 điểm nếu đề nghị baseline; 1 điểm nếu chọn đo chất lượng thay số lượng; 1 điểm nếu bước tiếp nhỏ và có thể thực hiện. Không cho điểm tối đa nếu đưa ra cam kết doanh thu không có dữ liệu.

## B2. Hai nguồn sản phẩm mâu thuẫn

**Tình huống giả định:** brochure cũ ghi một thành phần khác với trang sản phẩm đã duyệt tuần trước. FAQ và dữ liệu công cụ vẫn dùng bản cũ. Bot lấy nguồn khác nhau tùy câu hỏi. Người phát triển đề nghị thêm câu “hãy dùng thông tin mới nhất” vào prompt.

**Nhiệm vụ:** dùng mẫu A3 lập kế hoạch sửa. Nêu owner quyết định fact, phạm vi ảnh hưởng và cách chứng minh bot đã dùng nguồn đúng. Giải thích khi nào cần tạm ngừng câu trả lời liên quan.

**Gợi ý:** owner sản phẩm xác nhận nguồn có thẩm quyền và hiệu lực. Thu hồi hoặc đánh dấu bản cũ; cập nhật FAQ, dữ liệu công cụ và tài sản đã nhập; thêm ca kiểm cho cả cách hỏi từng gây lỗi. Prompt chỉ là một phần nếu cần. Nếu fact chưa được xác định hoặc lỗi có hậu quả nghiêm trọng, dùng phản hồi chưa xác nhận/chuyển người trong phạm vi đó.

**Cách chấm:** câu trả lời tốt có nguồn, owner, hiệu lực, nơi dùng và kiểm thử sau thay đổi. Câu trả lời chỉ “sửa prompt và thử lại” chưa quản lý được tài sản tri thức.

## B3. 99% test đạt nhưng có một đơn trùng

**Tình huống giả định:** bộ thử có 100 ca; 99 đạt, một ca mất kết nối tạo hai đơn. Đội đề nghị chấp nhận vì tỷ lệ chung cao. Chức năng dự kiến mở cho khách ngày mai. Chưa có cách nhận ra và xử lý đơn trùng tự động.

**Nhiệm vụ:** quyết định Go/No-Go cho phần tạo đơn, viết lý do và bằng chứng cần để xem lại. Nêu phần nào có thể tiếp tục nếu tách được phạm vi.

**Gợi ý:** lỗi tạo giao dịch trùng có hậu quả trực tiếp, không được bù bằng 99 ca tốt. Chưa mở tự động tạo đơn trong điều kiện này. Có thể tiếp tục phần tư vấn không ghi đơn nếu đã được đánh giá độc lập và trạng thái được giới hạn thật. Yêu cầu test gửi lại, phản hồi thất lạc, cùng yêu cầu và yêu cầu mới khác nhau, cộng kiểm trạng thái dữ liệu.

**Cách chấm:** 1 điểm cho phân loại hậu quả; 1 điểm cho tách phạm vi; 1 điểm cho bằng chứng chống trùng; 1 điểm cho cách xử lý giao dịch đã xảy ra nếu có. “Tắt toàn bộ dự án vô thời hạn” thường quá rộng nếu có phần độc lập vẫn hữu ích.

## B4. Điểm cao nhưng địa chỉ còn hai lựa chọn

**Tình huống giả định:** resolver trả điểm 0,98 cho tên phường, nhưng tên đó xuất hiện ở hai tỉnh và khách chưa cho tỉnh. Một thành viên muốn tự chọn vì đã vượt ngưỡng 0,95. Một thành viên khác muốn hỏi khách “xác nhận đúng không” mà không đưa lựa chọn cụ thể.

**Nhiệm vụ:** chọn đường xử lý, viết thông điệp cho khách và thông tin cần chuyển cho nhân viên nếu chưa giải quyết được. Nêu điều kiện nào có thể cho tự xử lý ở lần sau.

**Gợi ý:** áp quy tắc mơ hồ trước điểm. Cần thêm thông tin phân biệt, chẳng hạn tỉnh/thành phù hợp. Không hỏi xác nhận một kết quả mà khách không được nhìn thấy rõ. Nếu vẫn mơ hồ hoặc chính sách yêu cầu, chuyển staff với ứng viên và lý do. Tự xử lý chỉ khi dữ liệu đủ, quan hệ hợp lệ và mọi quy tắc đã chốt đều đạt.

**Cách chấm:** không suy 0,98 thành xác suất đúng 98% nếu chưa hiệu chuẩn. Câu trả lời cần bảo vệ khách đồng thời giảm công sức hỏi lại.

## B5. Quy trình bảo đảm đang trở thành dự án riêng

**Tình huống giả định:** một lần nhập dữ liệu giả nội bộ bị chặn vì thiếu chuỗi biên nhận mật mã. Đội đã xây ba phiên bản công cụ xác nhận, mỗi phiên bản lại phát sinh việc phục hồi riêng. Có backup, nhật ký và cách kiểm trạng thái trước–sau, chưa có khách thật hay giao dịch ngoài hệ thống trong phạm vi.

**Nhiệm vụ:** đề nghị điều chỉnh kiểm soát theo mẫu A7. Nêu kiểm soát giữ ngay, phần chuyển trước bàn giao, rủi ro còn lại và điều kiện xem lại. Không được coi “nội bộ” là lý do bỏ mọi kiểm tra.

**Gợi ý:** giữ đúng phiên bản dữ liệu, điều kiện chạy, kiểm kết quả, cách reset, phạm vi quyền tạm và thu hồi. Xem công cụ xác nhận phức tạp có cần cho mục tiêu hiện tại không. Nếu chưa, chuyển thành hạng mục bàn giao riêng có trigger khi có nhiều người vận hành hoặc tác động thật. Ghi rõ giới hạn xác nhận hiện tại.

**Cách chấm:** phương án tốt giảm chi phí mà vẫn bảo vệ tài sản hiện hữu. Phương án yếu hoặc giữ mọi thứ không giải thích, hoặc bỏ hết kiểm soát vì muốn nhanh.

## B6. Đã deploy nhưng chưa thể giới thiệu cho khách

**Tình huống giả định:** Dev báo “đã deploy thành công”. Trưởng kinh doanh soạn thông báo ra mắt. Thực tế cờ chức năng đang tắt, chỉ có dữ liệu giả và chưa có người nhận ca chuyển. Mã mới có thể chạy nội bộ.

**Nhiệm vụ:** viết lại báo cáo trạng thái và lập ba việc ưu tiên trước khi quyết định mở khách. Xác định ai cần nhận thông báo sửa cách hiểu.

**Gợi ý:** báo “phiên bản đã có trên môi trường, chức năng chưa bật cho khách; đã kiểm phần nội bộ được nêu; còn chất lượng trên phạm vi dùng thật, người hỗ trợ và quyết định activation”. Ưu tiên theo mức rủi ro cụ thể, không dùng một checklist vô hạn. Thông báo cho người dự kiến sử dụng kết quả, đặc biệt kinh doanh và vận hành.

**Cách chấm:** báo cáo cần môi trường, dữ liệu, người dùng và hành vi đang bật. Một câu “chưa production-ready” có thể đúng nhưng vẫn khó hiểu nếu không giải thích.

## B7. Tài liệu bàn giao mà người nhận không dùng được

**Tình huống giả định:** runbook dài 30 trang, đầy tên lệnh và mã trạng thái. Nhân viên đọc xong nói đã hiểu nhưng khi diễn tập không biết nên bấm tiếp hay dừng. Người viết liên tục hướng dẫn miệng. Lãnh đạo muốn ký bàn giao để chốt mốc.

**Nhiệm vụ:** thiết kế một bài kiểm bàn giao 30 phút và chọn ba thay đổi tài liệu có giá trị nhất. Phân biệt đã bàn giao tài liệu với đã chuyển trách nhiệm vận hành.

**Gợi ý:** thử một tác vụ thường ngày, một tình huống thiếu quyền và một tình huống kết quả sai. Người nhận tự dùng tài liệu. Bổ sung điều kiện bắt đầu, ảnh/trạng thái mong đợi khi phù hợp, điểm dừng và liên hệ. Giữ thuật ngữ ở phần tra cứu; hướng dẫn chính theo mục tiêu người thao tác.

**Cách chấm:** cần quan sát hành vi, không chỉ khảo sát “đã hiểu”. Chưa chuyển trách nhiệm nếu người nhận thiếu quyền hoặc chưa làm được các tình huống trong phạm vi.

## B8. Bài tập tổng hợp: quyết định vòng tiếp theo

**Tình huống giả định:** cửa hàng B có trợ lý tư vấn đã thử nội bộ. Tài liệu sản phẩm có owner, giá qua công cụ, 60 ca quan trọng đạt; chưa có mẫu khách đại diện. Một lỗi chuyển người khiến nhân viên thiếu tóm tắt. Hệ thống trên một máy chủ, đã thử khôi phục nhưng chưa đo thời gian. Kinh doanh muốn thêm kênh mới; kỹ thuật muốn đổi mô hình. Ngân sách chỉ đủ cho một nhóm việc chính trong hai tuần.

**Nhiệm vụ:** chuẩn bị một gói quyết định gồm đề bài vòng tới, ba lựa chọn, lựa chọn đề nghị, DoD, rủi ro, bằng chứng, owner và điều kiện dừng. Độ dài hai đến ba trang. Không giả định đã được phép dùng dữ liệu khách thật.

**Gợi ý:** có nhiều phương án hợp lý. Một phương án là hoàn thiện hành trình hiện tại và sẵn sàng thử có giới hạn: sửa handoff, đo khôi phục, chốt phạm vi dữ liệu và tiêu chí quan sát. Chưa đổi mô hình nếu chưa có bằng chứng lỗi nằm ở mô hình. Chưa thêm kênh nếu chưa có giá trị và vận hành đủ rõ. Nếu kinh doanh có bằng chứng mạnh cho kênh mới, có thể thử kênh đó ở phạm vi tư vấn nhỏ nhưng phải ghi đánh đổi.

**Cách chấm 20 điểm:** vấn đề và giá trị 3; lựa chọn/đánh đổi 3; nguồn và dữ liệu 3; DoD và bằng chứng 4; rủi ro/khôi phục 3; owner/giao tiếp 2; giới hạn và bước học tiếp 2. Trừ điểm nếu dùng số giả thành kết quả thật, để AI tự duyệt quyền hoặc mô tả “xong” không có phạm vi.

## B9. Cách tổ chức nhóm học

Nhóm ba người có thể luân phiên vai manager, người đề xuất và reviewer. Mỗi người đọc tình huống trong năm phút, đề xuất trong năm phút, phản biện trong mười phút và thống nhất bản quyết định trong mười phút. Người quan sát ghi những câu hỏi giúp làm rõ sự thật và những chỗ nhóm bắt đầu đoán.

Sau bài tập, đừng chỉ so ai chọn giống đáp án. Hãy hỏi giả định nào làm lựa chọn khác nhau, bằng chứng nào có thể thay đổi quyết định, và điểm nào đang áp quy trình nặng hơn hậu quả. Mục tiêu là học cách lập luận có trách nhiệm, không học thuộc nhãn GO/NO-GO.

## B10. Cam kết áp dụng sau khi đọc

Viết ba dòng: một thói quen sẽ bắt đầu, một thói quen sẽ dừng và một bằng chứng sẽ yêu cầu rõ hơn. Ví dụ: bắt đầu ghi nguồn fact; dừng báo tiến độ bằng số tệp; yêu cầu mọi kết luận chất lượng có mẫu và giới hạn. Sau hai tuần, chọn một quyết định thật để kiểm xem cam kết đã thay đổi công việc hay chỉ nằm trong ghi chú.
