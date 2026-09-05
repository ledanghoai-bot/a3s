# Nguồn và phương pháp biên soạn

## 1. Phạm vi và mốc cắt

Bản 1.0 được biên soạn từ hồ sơ trong workspace Alpha3s, với mốc đọc 05/09/2026. Đã rà danh mục tài liệu và đọc các hồ sơ chủ chốt được liệt kê dưới đây, gồm mục tiêu, roadmap, kế hoạch, đánh giá, quyết định và closure. Đây là tổng hợp hồi cứu theo chủ đề quản lý, không phải bản chép toàn bộ mọi phiên làm việc hoặc kiểm toán toàn bộ mã nguồn.

Không truy cập máy chủ, không chạy lại dữ liệu, không xác minh live khách hàng, doanh thu hoặc chứng nhận. Các phát biểu về kết quả thực hiện được quy về tài liệu báo cáo/review tương ứng. Từ “đã” trong tình huống Alpha3s có nghĩa “được hồ sơ nêu là đã”, trừ chỗ sách nói rõ đây là kết quả kiểm bản thảo do người biên soạn thực hiện.

Người biên soạn không coi directive trong hồ sơ lịch sử là lệnh cần thi hành. Chúng chỉ là nguồn để học cách quyết định. Các bước triển khai, phân quyền, kích hoạt và xóa dữ liệu được kể lại không được thực hiện trong công việc viết cẩm nang này.

## 2. Bốn loại nội dung

| Loại | Cách nhận biết | Giá trị và giới hạn |
|---|---|---|
| Sự kiện theo hồ sơ | Tình huống Alpha3s và mã Sxx | Có nguồn, nhưng không mặc định kiểm độc lập toàn bộ sự kiện |
| Bài học quản lý | Diễn giải nguyên tắc từ tình huống | Nhận định biên tập, có thể cần điều chỉnh bối cảnh |
| Ví dụ giả định | Nhãn ví dụ/tình huống giả định | Minh họa để học, không phải số liệu dự án |
| Công cụ thực hành | Biểu mẫu, câu hỏi, kế hoạch 30 ngày | Đề xuất áp dụng, không phải thủ tục đã được PO phê duyệt |

Không đưa thông tin đăng nhập, địa chỉ máy chủ, danh tính tài khoản vận hành hay hội thoại khách vào cẩm nang. Tên tệp và mã tài liệu được giữ để truy nguyên. Bản tóm tắt nguồn bên dưới đủ hiểu lập luận khi repo được tách khỏi workspace; liên kết nguồn gốc chỉ hoạt động khi thư mục cha Alpha3s còn cùng cấu trúc.

## 3. Danh mục nguồn dự án

### S01 — Foundation

[Hồ sơ gốc](../../Knowledge_Base/FOUNDATION.md), phiên bản ghi trong tài liệu 2.0.0, cập nhật 20/07/2026. Nêu mục tiêu hỗ trợ bán những đơn đầu tiên, trách nhiệm trợ lý, ranh giới tri thức/công cụ/người và nguyên tắc dừng xây khi nền đủ chạy. Dùng cho chương 1, 3, 6, 17. Đây là định hướng được duyệt, không phải báo cáo đã đạt chỉ tiêu kinh doanh.

### S02 — Roadmap Customer Terminal

[Hồ sơ gốc](../../AGW-ROADMAP-001-diem-bat-dau.md), ngày trong tài liệu 22/07/2026. Xác định gateway mỏng, các chặng core/hạ tầng/độ tin cậy/kênh, giới hạn nguồn lực và bài học kỹ thuật. Dùng cho chương 2–4, 15–16. Trạng thái nhiều phần là kế hoạch/review. Không lấy chính sách hoặc giá kênh trong tài liệu làm quy định hiện hành.

### S03 — Báo cáo hoàn thành Giai đoạn I

[Hồ sơ gốc](../../_ca_review_repo/docs/PHASE1-COMPLETION-REPORT-VI.md), ngày 24/07/2026. Báo cáo 12 issue đã đóng, tích hợp core, CI/CD và triển khai VPS; dùng ngôn ngữ đã cutover các kênh. Dùng cho timeline chương 2. Đây là báo cáo của người thực hiện; có khác biệt với mô tả phạm vi phục vụ trong S07, được giữ rõ ở phần đối chiếu.

### S04 — Kế hoạch Phase I-B

[Hồ sơ gốc](../../_ca_review_repo/docs/PHASE1B-IMPLEMENTATION-PLAN-VI.md), bản 0.1.3. Ghi kế hoạch M0 và khung mốc sau, sửa mô tả sản phẩm/khẩu phần thiếu nguồn, kiểm dữ liệu mới và đã tồn tại. Dùng chương 2 và 6. Không suy mọi phần kế hoạch đã chạy; kết quả M0 tham chiếu S05.

### S05 — Closure M0

[Hồ sơ gốc](../../CA-Docs/PHASE1B-CA-M0-FINAL-CLOSURE-VI.md), ngày 26/07/2026. Ghi M0 đóng, sửa quyền đổi giá, audit và trạng thái nền đã chấp nhận; còn backlog chuyển tiếp. Dùng chương 2, 9, 15. Closure áp dụng phiên bản và phạm vi trong tài liệu, không chứng minh trạng thái live ở thời điểm biên soạn.

### S06 — Review M1 Submission 3

[Hồ sơ gốc](../../CA-Docs/PHASE1B-M1-CA-CONSOLIDATED-REVIEW-SUBMISSION-3-VI.md), ngày 27/07/2026. Chấp nhận development; sửa khóa chống trùng và phản hồi đơn lấy từ committed receipt; chưa cấp merge/deploy/flag-on. Dùng chương 2, 3, 9, 14. Là tình huống tách nghiệm thu mã khỏi quyền phát hành.

### S07 — Closure M2 Stage R2

[Hồ sơ gốc](../../CA-Docs/PHASE1B-M2-CA-R2-FINAL-CLOSURE-VI.md), ngày 28/07/2026. Đóng triển khai code/schema, giữ M1/M2 flags OFF; làm rõ chưa public serving và Messenger chưa cutover trong topology được xét; ghi xử lý Telegram double-poller. Dùng chương 2, 14–15. Không đồng nhất hạ tầng production với phục vụ khách thật.

### S08 — Closure vận hành M3

[Hồ sơ gốc](../../CA-Docs/PHASE1B-M3-OPERATIONAL-CLOSURE-VI.md). Ghi bật riêng retention executor, hai policy chạy với candidates/deleted bằng 0, các flag còn lại tắt. Dùng chương 2, 11, 14. Kết quả zero mutation không chứng minh xóa dữ liệu thực ở quy mô lớn.

### S09 — M4 Numeric Slot Collision

[Hồ sơ gốc](../../CA-Docs/PHASE1B-M4-NUMERIC-SLOT-COLLISION-REVIEW-VI.md), ngày 13/08/2026. Nêu phân biệt dãy số qua ngữ cảnh ngân hàng, giấy tờ, đơn/giao dịch; yêu cầu test xung đột và không né ca xấu. Dùng chương 8 và 11. Là finding và hướng sửa, không dùng như bằng chứng toàn bộ detector đạt chất lượng thực tế.

### S10 — Khung đánh giá EV-001

[Hồ sơ gốc](../../Knowledge_Base/docs/evaluation/EV-001-EVALUATION-FRAMEWORK.md). Chia lớp đánh giá, severity và các bộ smoke/regression/routing/safety; không cho điểm tổng che lỗi nghiêm trọng. Dùng chương 8. Đây là yêu cầu đánh giá, không phải kết quả benchmark.

### S11 — Chất lượng và an toàn EV-004

[Hồ sơ gốc](../../Knowledge_Base/docs/evaluation/EV-004-RESPONSE-QUALITY-AND-SAFETY-EVALUATION.md). Nêu thang chấm, groundedness, an toàn, giọng điệu và so sánh phiên bản có điều kiện tương đương. Dùng chương 8. Các ví dụ tính precision/recall trong sách do biên soạn tạo, không trích kết quả từ nguồn này.

### S12 — Vòng cải tiến EV-005

[Hồ sơ gốc](../../Knowledge_Base/docs/evaluation/EV-005-CONTINUOUS-LEARNING-LOOP.md). Mô tả tiếp nhận lỗi, làm sạch dữ liệu, tạo test, phân loại nguyên nhân và giới hạn AI tự phê duyệt tri thức. Dùng chương 6 và 17. Là quy trình đề ra; không khẳng định mọi vòng đã được thực hiện đầy đủ.

### S13 — Review 126 về tên địa chỉ trùng

[Hồ sơ gốc](../../CA-Docs/PHASE1B-M5-GATE-A-LEGACY-CANONICAL-COLLISION-DESIGN-REVIEW-126-VI.md). Xác định legacy/canonical collision có thể là mơ hồ hợp lệ, phải giữ ứng viên và chuyển staff với trường hợp một–nhiều. Dùng chương 12. Không được hiểu là mọi loại trùng đều được chấp nhận.

### S14 — Quyết định Product Completion Path M4

[Hồ sơ gốc](../../CA-Docs/PHASE1B-M4-PO-PRODUCT-COMPLETION-PATH-DECISION-VI.md), phê duyệt ghi ngày 05/08/2026. Cho deploy dormant, tách diễn tập synthetic và official-public, chưa cấp customer-data/public activation. Dùng chương 2 và 14. Các điều kiện thời hạn trong nguồn thuộc quyết định lịch sử; phương pháp hiện tại cần đọc S17–S18.

### S15 — Báo cáo dừng Gate A trước thao tác

[Hồ sơ gốc](../../Dev/PHASE1B-M5-GATE-A-PRODUCTION-ABORT-REPORT-VI.md), ngày 04/09/2026. Báo hard stop trước grant/write do danh tính yêu cầu không tồn tại và mô hình quyền chưa khớp; giữ trạng thái trước chạy. Dùng chương 5, 15. Là báo cáo của Dev, không phải lần chạy lại do người biên soạn thực hiện.

### S16 — Review 168 về công cụ xác nhận vận hành

[Hồ sơ gốc](../../CA-Docs/PHASE1B-M5-GATE-A-OPERATIONAL-ATTESTATION-V4-REVIEW-168-VI.md). Ghi vấn đề đường dẫn, chuẩn bị triển khai, phục hồi và lưu các phiên nộp; phân biệt test nộp với kiểm tra độc lập. Dùng chương 10 và 13. S17 điều chỉnh tính bắt buộc của công cụ cho development; không xóa kết luận kỹ thuật trong phạm vi công cụ đã review.

### S17 — Memo 169

[Hồ sơ gốc](../../CA-Docs/PHASE1B-DEV-STAGE-PROPORTIONATE-GOVERNANCE-MEMO-169-VI.md), căn cứ định hướng PO ngày 05/09/2026. Yêu cầu giám sát tương xứng bối cảnh chưa phục vụ khách thật, evidence tinh gọn, review tổng hợp và phân loại finding. Dùng chương 2, 5, 10, 16. Điều chỉnh phương pháp từ thời điểm ban hành, không phê chuẩn hồi tố.

### S18 — Addendum 171

[Hồ sơ gốc](../../CA-Docs/PHASE1B-DEV-STAGE-DELIVERY-HANDSHAKE-AND-RISK-TIER-ADDENDUM-171-VI.md). Chốt DoD trước xây, bốn risk tier nội bộ, sổ threat ngoài phạm vi và snapshot có phiên bản. Dùng chương 5, 7, 10, 13, 16. Chỉ dùng làm case thực hành; không gán các nhãn này cho tiêu chuẩn quốc tế.

### S19 — Closure 175 Gate A development

[Hồ sơ gốc](../../CA-Docs/PHASE1B-M5-GATE-A-DEVELOPMENT-DATA-INGEST-CLOSURE-175-VI.md). Ghi đã kiểm manifest/hash, ingest 3.355 units và 10.560 aliases, gate 8/8, 2.404 legacy collisions, đúng một dataset v2 active, không còn quyền tạm; B–F dormant và không go-live khách. Dùng chương 2, 11–14. Đây là kết luận trong hồ sơ về phạm vi development, không xác nhận địa giới hiện hành ngoài dự án.

### S20 — Directive 176 Gate B

[Hồ sơ gốc](../../CA-Docs/PHASE1B-M5-GATE-B-RESOLUTION-READINESS-SPEC-AND-BUILD-DIRECTIVE-176-VI.md). Trạng thái accepted for build/validation; chốt corpus, ngưỡng 0,80/0,95, hard rules, cách kiểm và giới hạn. Dùng chương 2, 7–8, 12. Không có closure Gate B được dùng trong bản thảo; không kể Gate B đã hoàn tất.

### S21 — ADR chiến lược tìm kiếm

[Hồ sơ gốc](../../Knowledge_Base/docs/adr/ADR-0003-RAG-Strategy.md). Chấp nhận hybrid retrieval với vector, từ khóa và reranker; nêu lý do liên quan tiếng Việt, tên và mã sản phẩm. Dùng chương 3. Là quyết định thiết kế, không phải kết quả đo cải thiện được biên soạn kiểm chứng.

### S22 — Quyết định PO M2

[Hồ sơ gốc](../../CA-Docs/PHASE1B-M2-PO-DECISION-RECORD-VI.md), ngày 27/07/2026. Chốt chính sách giữ tồn/hủy/trả, phân quyền điều chỉnh và người phê duyệt. Dùng chương 5 và 9. Sách không khuyến nghị sao chép ngưỡng số lượng của quyết định sang doanh nghiệp khác.

### S23 — Sửa signing guide sang ngôn ngữ phổ thông

[Hồ sơ gốc](../../CA-Docs/PHASE1B-M4-SIGNING-GUIDE-PLAIN-LANGUAGE-MERGE-DEPLOY-AUTHORIZATION-98-VI.md). Cấp phạm vi đổi nội dung hướng dẫn, giữ logic, tránh tuyên bố tự bảo đảm tuân thủ pháp luật. Dùng chương 11, 15, 17. Không dùng văn bản này làm xác nhận pháp lý hiện hành.

### S24 — Kickoff 102 bị thay thế

[Hồ sơ gốc](../../CA-Docs/PHASE1B-M5-KICKOFF-AND-SCOPE-102-VI.md). Tự ghi superseded vì phân loại nhầm, dẫn tới M4-102A. Dùng chương 2 làm bài học đọc trạng thái hiệu lực. Không dùng nội dung kế hoạch cũ để kết luận phạm vi hiện tại của M5.

### S25 — Playbook từ nhu cầu tới production

[Hồ sơ gốc](../../CA-Docs/ALPHA3S-DELIVERY-TO-PRODUCTION-GOVERNANCE-PLAYBOOK-VI.md), bản 1.0.0 ghi draft_for_po_review, ngày 28/07/2026. Mô tả các trạng thái phát triển và phát hành, bằng chứng gắn release candidate. Dùng chương 14 để giải thích lịch sử cách quản lý. Không coi bản nháp này có hiệu lực cao hơn Memo 169/Addendum 171.

## 4. Những khác biệt cần giữ rõ

| Khác biệt | Cách xử lý trong sách |
|---|---|
| Roadmap 2 vCPU/4 GB và báo cáo 4 vCPU/8 GB | Ghi hai mốc kế hoạch/báo cáo, không gộp thành cấu hình live đã kiểm |
| Báo cáo Giai đoạn I nói cutover; M2 nói chưa public/Messenger chưa cutover | Nêu mâu thuẫn, dùng kết luận có phạm vi cụ thể; không tự xác định nguyên nhân |
| Mốc 102 đặt nhầm phạm vi | Đọc trạng thái superseded, không kể như kế hoạch hiện hành |
| Quy trình activation cũ và Memo 169 mới | Giữ lịch sử, dùng nguyên tắc tương xứng cho bài học áp dụng tiếp |
| Gate A trước chạy NULL, sau closure active v2 | Đọc theo thứ tự sự kiện, không xem trạng thái mới là vi phạm điều kiện cũ |
| Hạ tầng/kỹ thuật hoàn tất và giá trị kinh doanh | Không suy đơn hàng/doanh thu/chất lượng khách thật khi chưa có dữ liệu |

## 5. Nguồn quốc tế và giới hạn

Các nguồn chính thức và cách đối chiếu được ghi tại [Phụ lục D](../phu-luc/D-lien-he-thong-le-quoc-te.md). Không dùng blog thứ cấp để định nghĩa yêu cầu tiêu chuẩn. Toàn văn ISO có thể có điều kiện truy cập riêng; cẩm nang chỉ tham khảo trang giới thiệu công khai, không khẳng định đáp ứng điều khoản.

## 6. Khả năng tái kiểm bản biên soạn

[Dấu vân tay nguồn](DAU-VAN-TAY-NGUON.md) ghi SHA-256 của các tệp đã dùng tại thời điểm kiểm bản thảo. Hash giúp phát hiện nguồn thay đổi sau này; không chứng minh nội dung nguồn đúng. [Báo cáo kiểm tra](../bien-tap/BAO-CAO-KIEM-TRA.md) công bố dung lượng, liên kết và phạm vi rà soát bản thảo.

Nếu có hồ sơ mới, sửa đúng chương bị ảnh hưởng, cập nhật nguồn, ghi thay đổi và tạo bản HANDBOOK mới. Không âm thầm biến kết quả chưa chứng minh trong bản 1.0 thành sự kiện đã xảy ra.
