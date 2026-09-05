# Phụ lục C. Từ điển thuật ngữ cho manager

Các giải thích dưới đây theo nghĩa sử dụng trong cẩm nang. Thuật ngữ có thể được định nghĩa chặt hơn trong một tiêu chuẩn hoặc tổ chức. Khi ký yêu cầu hay quyết định, nhóm cần thống nhất nghĩa đang dùng.

## C1. Sản phẩm và quản lý công việc

| Thuật ngữ | Hiểu bằng tiếng phổ thông | Câu hỏi của manager |
|---|---|---|
| AI — Artificial Intelligence | Công nghệ thực hiện những nhiệm vụ thường cần năng lực nhận biết, suy luận hoặc tạo nội dung | AI giúp phần việc nào? |
| Generative AI | AI tạo nội dung mới như văn bản | Ai kiểm sự thật và hành động? |
| PO — Product Owner | Người chịu trách nhiệm tối đa hóa giá trị sản phẩm trong Scrum; ở dự án cần làm rõ quyền thực tế | Ai quyết phạm vi và giá trị? |
| Manager | Người quản lý mục tiêu, nguồn lực, trách nhiệm hoặc vận hành theo vai trò được giao | Quyền quyết của tôi tới đâu? |
| CA — Chief Architect | Vai trò kiến trúc/phản biện trong hồ sơ Alpha3s | Đây là tư vấn hay quyết định có thẩm quyền? |
| Dev — Developer | Người/đội triển khai phần mềm | Ai xác nhận khả thi và kết quả? |
| Stakeholder | Bên có liên quan hoặc chịu ảnh hưởng | Ai đang thiếu tiếng nói? |
| Use case | Tình huống sử dụng có người dùng và mục đích | Ai hoàn thành việc gì? |
| Scope | Phạm vi công việc và tác động | Dữ liệu, người dùng, hành vi nào thuộc phạm vi? |
| MVP | Phiên bản tối thiểu để kiểm giả thuyết giá trị trong phạm vi đã chọn | Tối thiểu nhưng có dùng được không? |
| Output / outcome / impact | Đầu ra / kết quả sử dụng / tác động rộng hơn | Báo cáo đang chứng minh lớp nào? |
| Backlog | Danh sách công việc được sắp thứ tự | Vì sao việc này đứng trước? |
| Roadmap | Định hướng các chặng và kết quả dự kiến | Phụ thuộc và điều kiện đổi hướng là gì? |
| Vertical slice | Phần nhỏ đi trọn một hành trình | Có thể kiểm từ đầu tới cuối không? |
| Dependency | Điều kiện cần từ việc khác hoặc bên ngoài | Ai cung cấp, khi nào cần? |
| Acceptance criteria | Tiêu chí chấp nhận một hành vi/hạng mục | Kiểm bằng tình huống nào? |
| DoD — Definition of Done | Định nghĩa trạng thái hoàn thành theo yêu cầu chất lượng | Khi nào được đóng việc? |
| Baseline | Trạng thái tham chiếu ở một mốc rõ | So với bản nào, ngày nào? |
| ADR | Bản ghi quyết định kiến trúc và lý do | Đánh đổi nào đã được chấp nhận? |
| RACI | Bảng người làm, người chịu trách nhiệm, người tham vấn, người nhận tin | Có owner thật chưa? |
| Retrospective | Nhìn lại để cải tiến cách làm | Vòng sau thay đổi hành vi nào? |

## C2. Cách hệ thống AI hoạt động

| Thuật ngữ | Hiểu bằng tiếng phổ thông | Câu hỏi của manager |
|---|---|---|
| LLM — Large Language Model | Mô hình ngôn ngữ lớn tạo/hiểu văn bản theo ngữ cảnh | Dữ liệu nào được đưa vào? |
| Prompt | Chỉ dẫn và nội dung đưa cho mô hình | Đã kiểm hành vi hay mới sửa câu lệnh? |
| Context | Thông tin có mặt khi mô hình xử lý | Có thiếu hoặc xung đột nguồn không? |
| Token | Đơn vị mô hình dùng để xử lý văn bản | Chi phí trên công việc đúng là bao nhiêu? |
| RAG | Tìm tài liệu liên quan để hỗ trợ mô hình trả lời | Lấy đúng nguồn được duyệt chưa? |
| Retrieval | Tìm thông tin phù hợp | Có nguồn nhưng tìm không ra không? |
| Embedding | Cách biểu diễn dữ liệu bằng các con số phục vụ so sánh ý nghĩa | Chi phí tài nguyên và chất lượng đã đo chưa? |
| Hybrid search | Kết hợp tìm theo từ khóa và ý nghĩa | Có cải thiện các ca cần thiết không? |
| Reranking | Sắp lại kết quả tìm để chọn phần phù hợp hơn | Cải thiện có đáng chi phí không? |
| NLU | Hiểu ý định và thông tin trong ngôn ngữ | Có kiểm tiếng Việt và cách nói thật không? |
| Intent / entity | Ý định / đối tượng hoặc thông tin nhận ra trong câu | Đã hiểu đúng việc khách muốn chưa? |
| Tool calling | Gọi chức năng đọc hoặc thay đổi dữ liệu | Ai kiểm quyền và điều kiện thực thi? |
| Orchestration | Điều phối các bước và công cụ | Lỗi giữa chừng được xử lý ra sao? |
| Hallucination | Nội dung sai/không có căn cứ nhưng được tạo như có thật | Nguồn và cơ chế ngăn hậu quả đâu? |
| Groundedness | Mức câu trả lời có căn cứ trong nguồn được cung cấp | Có phát biểu vượt nguồn không? |
| Guardrail | Cơ chế giới hạn hành vi hoặc chặn rủi ro | Bảo vệ điều gì và đã thử lỗi chưa? |
| Human-in-the-loop | Con người tham gia vào một điểm xử lý/quyết định | Có đủ thông tin và thời gian để kiểm không? |
| Handoff | Chuyển công việc cho người | Ai nhận và khách phải chờ thế nào? |
| Fallback | Cách xử lý thay thế khi đường chính không dùng được | Người dùng có biết bước tiếp không? |
| Latency | Độ trễ | Đo từ góc nhìn khách hay một thành phần? |

## C3. Dữ liệu, chất lượng và rủi ro

| Thuật ngữ | Hiểu bằng tiếng phổ thông | Câu hỏi của manager |
|---|---|---|
| Canonical / alias / legacy | Tên chuẩn / tên khác / cách gọi hoặc dữ liệu cũ | Có làm mất ứng viên hợp lệ không? |
| Provenance | Nguồn gốc có thể truy lại | Ai cung cấp, biến đổi thế nào? |
| Ground truth | Đáp án/hành vi tham chiếu đã xác định | Ai xác nhận nó đúng? |
| Synthetic data | Dữ liệu tạo riêng để thử | Có đủ ca khó và giới hạn đại diện không? |
| Precision | Tỷ lệ đúng trong các trường hợp đã đánh dấu | Có bao nhiêu nhận nhầm? |
| Recall | Tỷ lệ bắt được trong các trường hợp cần bắt | Có bao nhiêu bỏ sót? |
| False positive / false negative | Báo có nhầm / bỏ sót trường hợp có | Loại sai nào gây hậu quả lớn hơn? |
| Confidence score | Điểm tin cậy theo cơ chế hệ thống | Đã hiệu chuẩn hay chỉ là điểm nội bộ? |
| Calibration | Hiệu chuẩn quan hệ giữa điểm và mức đúng quan sát | Điểm có đáng dùng cho tự động không? |
| Hard rule | Quy tắc cứng không được bỏ qua vì điểm cao | Điều nào luôn chặn tự chọn? |
| Regression test | Kiểm lỗi cũ và hành vi đã ổn không tái hỏng | Lỗi vừa sửa đã thành test chưa? |
| Smoke test | Bộ kiểm nhanh các chức năng thiết yếu | Ca quan trọng có đang chạy được? |
| UAT | Kiểm chấp nhận với góc nhìn người dùng/nghiệp vụ | Có hoàn thành việc thực tế không? |
| E2E | Kiểm hành trình từ đầu đến cuối | Kết quả có tới đúng người không? |
| Threat model | Mô tả tài sản, cách có thể bị hại và kiểm soát | Rủi ro nào hiện hữu trong phạm vi? |
| Residual risk | Rủi ro còn sau kiểm soát | Ai chấp nhận, khi nào xem lại? |
| Risk tier | Nhóm mức rủi ro để chọn kiểm soát | Phân theo tác động hay tên môi trường? |
| PII | Thông tin nhận diện/liên quan cá nhân theo phạm vi định nghĩa | Có cần thu, truyền và giữ không? |
| Retention | Quy tắc thời hạn lưu giữ | Khi nào hết cần và xóa thế nào? |
| RBAC | Phân quyền theo vai trò | Người đó thực sự có quyền gì? |
| SoD | Phân tách nhiệm vụ | Có độc lập thật hay chỉ hai tài khoản? |
| Fail-closed | Khi thiếu điều kiện, chặn hành động được bảo vệ | Có đường xử lý tiếp an toàn không? |

## C4. Phát hành và vận hành

| Thuật ngữ | Hiểu bằng tiếng phổ thông | Câu hỏi của manager |
|---|---|---|
| Repository / repo | Kho quản lý tệp và lịch sử thay đổi | Nguồn hiện hành nằm đâu? |
| Commit / hash | Mốc thay đổi / dấu vân tay nội dung | Có đúng bản đã kiểm không? |
| Manifest / snapshot | Danh sách thành phần / bản giữ tại một mốc | Gói đủ và còn truy lại được không? |
| CI/CD | Tự động kiểm, tích hợp và đưa thay đổi tới môi trường theo thiết kế | Merge có làm deploy ngay không? |
| Migration | Chuyển đổi cấu trúc hoặc dữ liệu có kiểm soát | Dữ liệu cũ được bảo toàn thế nào? |
| Merge / deploy | Hợp nhất mã / đưa phiên bản tới nơi chạy | Hành động nào được quyết định? |
| Release candidate | Bản dự kiến phát hành để kiểm | Evidence có gắn đúng bản không? |
| Feature flag / dormant | Công tắc chức năng / trạng thái chưa hoạt động | Giá trị thực tế sau deploy là gì? |
| Canary / shadow | Mở thử nhóm nhỏ / chạy quan sát không quyết định đường chính | Giới hạn tác động và điều kiện mở rộng? |
| Idempotency | Gửi lại cùng yêu cầu không lặp tác dụng | Retry có tạo thêm đơn/phí không? |
| Outbox | Cơ chế lưu việc gửi cùng trạng thái nghiệp vụ để giao sau | Kết quả có bị mất khi lỗi gửi không? |
| Audit trail | Dấu vết ai làm gì và kết quả | Có đủ điều tra mà không lộ dữ liệu thừa? |
| Invariant | Điều phải luôn đúng | Trước–sau có giữ điều đó không? |
| Preflight / postflight | Kiểm trước / kiểm sau thao tác | Điều kiện và trạng thái cuối đã xác nhận? |
| Rollback / compensation | Quay lại / hành động bù hậu quả | Phần đã ra ngoài hệ thống xử lý thế nào? |
| Backup / restore | Sao lưu / khôi phục để dùng lại | Đã thử phục hồi chưa? |
| RPO / RTO | Mục tiêu mức mất dữ liệu / thời gian khôi phục | Đã đo so với nhu cầu kinh doanh chưa? |
| Runbook | Hướng dẫn thao tác và xử lý lỗi | Người nhận tự dùng được không? |
| TCO / ROI | Tổng chi phí sở hữu / tỷ suất lợi ích đầu tư | Có tính công sức sửa và hỗ trợ không? |
| Observability | Khả năng hiểu tình trạng qua số đo, log và dấu vết | Khi lỗi, có biết hỏng ở bước nào? |
| Drift | Sự lệch dần của trạng thái, dữ liệu hoặc hành vi | Baseline nào không còn đúng? |

## C5. Cách dùng thuật ngữ trong giao tiếp

Khi gặp thuật ngữ mới, hãy đặt nghĩa phổ thông trước, từ gốc trong ngoặc sau và một ví dụ hành động. Ví dụ: “Nếu gửi lại cùng yêu cầu, hệ thống không tạo đơn thứ hai; đó là tính idempotency.” Người đọc hiểu điều cần quản lý trước khi học tên gọi.

Không dùng thuật ngữ để làm kết luận có vẻ mạnh hơn. “Đã có audit” không có nghĩa đã tuân thủ mọi yêu cầu; “confidence cao” không có nghĩa chắc đúng; “production complete” không có nghĩa đã có khách thật. Viết thêm phạm vi và căn cứ thường có giá trị hơn thêm chữ chuyên môn.
