# Đánh giá độc lập: KB V2 + Lớp NLU trên ngân sách VPS 4GB

> **Tính chất tài liệu:** phân tích kỹ thuật ĐỘC LẬP, chỉ dựa trên (1) số đo thực tế
> ngày 23/7/2026 trên máy dev (i7-3720QM, Docker Desktop/WSL2) và (2) đọc trực tiếp
> code trong repo. KHÔNG kế thừa kết luận từ các tài liệu định hướng của CA
> (AGW-ARCH/IMPL/REVIEW) — các con số budget chỉ lấy đúng 1 tham số đầu vào:
> VPS mục tiêu 2 vCPU / 4 GB RAM / 60 GB disk.
>
> Người lập: Claude Code (dev session 23/7). Người quyết định: anh Hoài (PO).

---

## 1. Hệ thống thực tế đang có gì (theo code, không theo tài liệu)

Hai hệ con độc lập, cùng nạp vào **worker** khi xử lý tin nhắn:

| Hệ | Model embedding | Kích thước tham số | Vai trò thật trong luồng trả lời |
|---|---|---|---|
| **KB V2** (#11) | `paraphrase-multilingual-MiniLM-L12-v2` (384 chiều) | 118M | Tìm nội dung thật (24 asset / 364 Knowledge Unit) bơm vào system prompt — **nguồn tri thức trả lời khách** |
| **NLU** (#12) | `paraphrase-multilingual-mpnet-base-v2` (768 chiều) | 278M | Đoán intent để bơm **1 câu gợi ý** vào system prompt — LLM vẫn toàn quyền quyết định |

Điểm mấu chốt về VAI TRÒ (ảnh hưởng trực tiếp tới đánh giá "bỏ được không"):
- KB V2 tạo ra **nội dung** — bỏ là bot mất tri thức thương hiệu/sản phẩm.
- NLU chỉ tạo ra **gợi ý tham khảo** ("không bắt buộc" — nguyên văn trong prompt của
  `orchestrator.py`). Toàn bộ đường NLU bọc try/except, lỗi thì bot vẫn trả lời.
  → NLU là lớp **tăng chất lượng có điều kiện**, không phải lớp sống còn.

NLU thực chất gồm 3 tầng với chi phí RAM rất khác nhau:

| Tầng NLU | Cần model? | RAM | Độ chính xác đã đo (150 held-out) |
|---|---|---|---|
| Pattern Router (exact + token overlap) | Không | ~vài MB | **94,6%** trong phạm vi phủ 40,0% số câu |
| High-precision rules (25 RTE) + Entity Extraction | Không | ~không đáng kể | nằm trong số Pattern ở trên |
| Semantic Router (mpnet, fallback) | **CÓ — chính là cục 1,1 GB** | xem §2 | **71,3%** trên 60% số câu còn lại |

Tổng pipeline: 80,7% đúng / 14,7% sai / 4,7% clarify.

---

## 2. Số đo tài nguyên thực tế (23/7, máy dev)

### 2.1. RAM của model embedding (VmHWM — peak, mỗi kịch bản 1 process riêng)

| Kịch bản | Peak |
|---|---|
| Python interpreter trần | 12 MB |
| Chỉ MiniLM (KB), sau khi encode thật | **1.126 MB** |
| Chỉ mpnet (NLU), sau khi encode thật | **1.132 MB** |
| Cả 2 model trong 1 process | **1.532 MB** |

Nhận xét kỹ thuật quan trọng:
- Phần lớn chi phí là **runtime PyTorch + sentence-transformers dùng chung** (~600-700
  MB), không phải trọng số model. Bằng chứng: model thứ 2 nạp vào cùng process chỉ tốn
  **+400 MB**, trong khi đứng riêng tốn 1.132 MB.
- Hệ quả kiến trúc: **gộp 2 model vào 1 process rẻ hơn hẳn 2 process riêng**
  (1,53 GB so với 2,26 GB). Và ngược lại: mỗi process "lỡ" import torch là trả trước
  ~300 MB dù chưa load model nào.

### 2.2. Độ trễ encode mỗi tin nhắn (đã warm-up, trung bình 10 lần)

| Model | ms/câu |
|---|---|
| MiniLM (KB) | **65 ms** |
| mpnet (NLU) | **177 ms** |

→ Trên 2 vCPU, encode KHÔNG phải điểm nghẽn độ trễ (lượt gọi LLM DeepSeek tính bằng
giây). CPU chỉ thành vấn đề lúc **build semantic index khi khởi động** (batch 380
utterance, hàng chục giây) — xảy ra 1 lần/lần restart worker, chấp nhận được.

### 2.3. Tài nguyên từng database (đo thật)

**PostgreSQL** (container `db`: 75 MB RAM khi gần idle):

| Bảng | Tổng dung lượng | Trong đó index | Ghi chú |
|---|---|---|---|
| `kb_units` (364 dòng, vector 384d) | **2,1 MB** | 1,1 MB | Toàn bộ "vector database" của KB V2 |
| `kb_assets` (24 dòng) | 72 kB | — | |
| `knowledge_chunks` (RAG cũ #4) | 48 kB | — | trống trên máy mới |
| Tất cả bảng còn lại cộng lại | < 0,5 MB | — | orders/messages/customers... mới trống |

Kết luận cho Postgres: **dữ liệu nhỏ tới mức không có ý nghĩa về RAM**. RAM Postgres
do CẤU HÌNH quyết định (`shared_buffers`, số connection), không do dữ liệu. Vector
364 dòng × 384 chiều dùng brute-force scan cũng chỉ ~0,5 MB đọc mỗi query — không cần
bàn tới IVF/HNSW index ở quy mô này. Dự phóng: kể cả KB tăng ×100 (36.400 unit) thì
bảng vector mới ~210 MB — vẫn trong tầm 4GB.

**Redis** (container `redis`: **10 MB**): giữ queue arq + context NLU (TTL) + cache
intent (TTL 1h). Toàn bộ đều là key nhỏ có TTL → tăng trưởng bị chặn. Chỉ cần đặt
`maxmemory 128mb` + policy `allkeys-lru` là đóng hoàn toàn rủi ro.

**"Vector DB" riêng: KHÔNG có** — pgvector nằm trong Postgres, không thêm service.
Semantic index NLU (380 utterance × 768d) sống trong RAM worker: **~1,2 MB** — không
đáng kể; cục nặng là MODEL tạo ra nó, không phải index.

### 2.4. RAM container thực tế đang chạy (docker stats, dev mode)

| Container | RAM đo được | Diễn giải cho production |
|---|---|---|
| worker | 350 MB (CHƯA load model — lazy) | → **~1,85-1,9 GB** sau tin nhắn đầu tiên (350 + 1.532) |
| api | 1,7 GB (nhiễu: chứa page cache model do các lệnh test exec vào đây) | → ~300 MB nếu KHÔNG embed; **~1,4 GB nếu có** (xem §3) |
| telegram_customer_bot | 371 MB ⚠️ | nghi import chuỗi module kéo theo torch — đáng rà lại, tiết kiệm được ~300 MB |
| telegram_bot | 38 MB | listener "sạch" — chứng minh bot polling chỉ cần ~40 MB |
| dashboard (next dev) | 132 MB | production build ước ~150-250 MB |
| db | 75 MB | với `shared_buffers=256MB` + connections → ~350 MB |
| redis | 10 MB | chặn trần 128 MB |

---

## 3. Trả lời câu hỏi chính: 4 GB có khả thi không?

### Rủi ro số 1 phát hiện từ code (độc lập với mọi tài liệu)

`app/services/products.py` và `app/services/knowledge_entries.py` (route dashboard
trong **api**) đều import `embed_async` → thao tác sửa KB/sản phẩm trên dashboard sẽ
làm **api nạp MiniLM lần thứ hai** (~+1,1 GB ngoài worker). Tương tự,
`telegram_customer_bot` đang chiếm 371 MB kiểu "trả trước torch".

### Ba kịch bản trên VPS 4 GB (ước tính từ số đo, production build)

| Thành phần | KB1: để nguyên như code hiện tại | KB2: ép embedding chỉ ở worker | KB3: KB2 + trim import listener |
|---|---|---|---|
| worker (2 model) | 1,90 GB | 1,90 GB | 1,90 GB |
| api | 1,40 GB (embed khi dùng dashboard) | 0,30 GB | 0,30 GB |
| 2 bot Telegram | 0,41 GB | 0,41 GB | 0,10 GB |
| Postgres | 0,35 GB | 0,35 GB | 0,35 GB |
| Redis (capped) | 0,13 GB | 0,13 GB | 0,13 GB |
| dashboard (prod) | 0,20 GB | 0,20 GB | 0,20 GB |
| OS + Docker + proxy | 0,45 GB | 0,45 GB | 0,45 GB |
| **Tổng** | **~4,8 GB — TRÀN** | **~3,7 GB** | **~3,4 GB** |

### Kết luận khả thi

- **4 GB khả thi CÓ ĐIỀU KIỆN** — không phải "khả thi thoải mái":
  1. BẮT BUỘC ép embedding chỉ sống trong worker (sửa 2 đường dashboard đi qua
     queue) — nếu không, tràn ngay khi nhân viên sửa KB lúc bot đang bận (KB1).
  2. Nên trim import ở `telegram_customer_bot` (+0,3 GB không công).
  3. Swap 2-4 GB là lưới an toàn, không phải chỗ chạy thường trực.
- Biên an toàn sau khi làm đủ: **~0,6 GB (KB3)** — mỏng. Mọi thứ phát sinh
  (spike build index lúc restart, backup chạy đêm, upgrade image) đều gặm vào biên này.
- Đây là hệ **chạy được nhưng không có chỗ thở** — vận hành phải kỷ luật (alert RAM,
  restart có trật tự, không thêm service mới).

---

## 4. Phương án 1 (PO đề xuất): tăng RAM lên 6 GB

**Tác động:** tổng nhu cầu xấu nhất (KB1 ~4,8 GB) < 6 GB → kể cả kịch bản "quên
guardrail, dashboard embed trong api" cũng KHÔNG chết. Biên an toàn kịch bản đúng
(KB3 ~3,4 GB) lên **~2,6 GB** — hệ có chỗ thở thật sự.

| Tiêu chí | Đánh giá |
|---|---|
| Kỹ thuật | Khả thi tuyệt đối — không đổi 1 dòng code, không đo lại accuracy |
| Chi phí | VPS 4→6/8 GB thường chênh ~50-100% giá thuê (~vài trăm nghìn ₫/tháng). Lưu ý: nhiều nhà cung cấp không có bậc 6 GB — lựa chọn thực tế hay là **8 GB** |
| Thời gian | 0 ngày công dev |
| Rủi ro | Gần như 0. Rủi ro duy nhất là "RAM che lỗi kiến trúc": double-load model vẫn là lãng phí, chỉ là không còn gây chết |
| Cái KHÔNG giải quyết được | CPU 2 vCPU (không đổi — nhưng §2.2 cho thấy encode không phải nghẽn); thói quen để process nào cũng import torch |

**Kết luận PA1: khả thi cao nhất, đổi tiền lấy độ an toàn + tiến độ.** Nếu chọn PA1
vẫn NÊN làm mục 3.1 (ép 1 process) như một việc vệ sinh kiến trúc, làm sau, không gấp.

---

## 5. Phương án 2 (PO đề xuất): thiết kế lại KB+NLU, hoặc bỏ NLU

Đánh giá từng biến thể — có số liệu đi kèm:

### 5a. Bỏ RIÊNG Semantic Router (giữ Pattern + Rules + Entity) — "bỏ NLU đúng chỗ"
- Tiết kiệm: mpnet ra khỏi worker → worker còn ~1,4-1,5 GB → tổng KB3 còn **~3,0 GB**
  → biên an toàn ~1 GB trên 4 GB. Đây là cục RAM lớn duy nhất bỏ được mà không đụng KB.
- Mất gì: 60% số câu không còn hint intent (LLM tự xử như trước #12 — bot VẪN chạy).
  Phần mất là lớp có độ chính xác **thấp nhất** hệ thống (71,3%). Phần GIỮ LẠI
  (Pattern+Rules+Entity, 94,6% trong phạm vi phủ 40%) gần như **miễn phí RAM**.
- Cần lưu ý: giá trị thật của semantic hint đối với CHẤT LƯỢNG TRẢ LỜI CUỐI chưa từng
  được A/B test — con số 71,3% là accuracy phân loại, không phải mức đóng góp vào trải
  nghiệm khách. Quyết định bỏ sẽ dựa trên suy luận, không phải đo lường trực tiếp.
- Công: ~0,5-1 ngày (flag tắt semantic + chạy lại 150 test + cập nhật tài liệu).

### 5b. Dùng chung MiniLM cho cả NLU (1 model cho cả 2 hệ)
- **LOẠI bằng số liệu có sẵn:** đã đo 18/7 — semantic router chạy MiniLM chỉ đạt
  **38,3%** trên 60 held-out (lý do đổi sang mpnet ngay từ đầu). Tiết kiệm 400 MB để
  nhận bộ phân loại tệ hơn tung đồng xu là giao dịch lỗ.

### 5c. Thay Semantic Router bằng chính LLM (DeepSeek classify intent trong prompt)
- RAM = 0 (không model thứ 2), latency +0 nếu gộp vào lượt gọi LLM sẵn có, chi phí
  token không đáng kể với đơn giá DeepSeek.
- Bản chất: đây là "5a nhưng bù đắp phần mất bằng prompt tốt hơn" — LLM tự phân loại
  intent của nó, chất lượng phụ thuộc DeepSeek (không kiểm soát/đo được bằng bộ 150
  test một cách tách bạch như hiện nay).
- Công: ~1 ngày (prompt engineering + đánh giá tay).

### 5d. Quantize/ONNX int8 cho mpnet (giữ nguyên kiến trúc NLU)
- mpnet int8 ước ~300-400 MB thay vì ~1,1 GB → 2 model + runtime còn **~0,9-1,1 GB**
  → tổng KB3 còn ~2,9-3,1 GB trên 4 GB. Giữ nguyên TOÀN BỘ giá trị NLU hiện có.
- Rủi ro: accuracy thường giảm nhẹ (1-2 điểm) — PHẢI chạy lại bộ 150 test để xác nhận;
  thêm phụ thuộc (optimum/onnxruntime); công ~1-2 ngày.

### 5e. Hosted embedding API (đẩy encode ra ngoài)
- RAM ~0 nhưng đổi lấy: phụ thuộc mạng cho MỌI tin nhắn, thêm ~100-300 ms/call, thêm
  chi phí thường xuyên, và mất ưu điểm hiện tại "embedding local không cần API key".
  Với hệ chỉ thiếu RAM chứ không thiếu CPU, đây là đánh đổi kém hấp dẫn nhất.

### Riêng phần KB: có "thiết kế lại" được không?
Không nên. KB V2 là nơi chứa giá trị thật (nội dung trả lời khách), MiniLM 65 ms/câu,
dữ liệu 2,1 MB, và phương án thay thế (full-text search thuần) kém với tiếng Việt
(không tách từ, đồng âm khi bỏ dấu — đúng lớp bug dự án đã gặp nhiều lần). Chi phí
RAM của KB (~1,1 GB đứng riêng, +400 MB khi ghép process) là **chi phí lõi đáng trả**.

---

## 6. Tổng hợp & khuyến nghị

| Phương án | Tổng RAM ước (kịch bản đúng) | Biên trên 4GB | Công dev | Mất mát chức năng | Khả thi |
|---|---|---|---|---|---|
| Giữ nguyên + guardrail 1-process (baseline §3) | ~3,4 GB | ~0,6 GB — mỏng | 1-2 ngày | Không | ✅ có điều kiện |
| **PA1: RAM 6 GB (hoặc 8 GB)** | ~3,4 GB / 6 GB | **~2,6 GB** | 0 | Không | ✅✅ cao nhất |
| PA2-5a: bỏ semantic router | ~3,0 GB | ~1,0 GB | 0,5-1 ngày | Hint cho 60% câu (lớp 71,3%) | ✅ cao |
| PA2-5d: quantize mpnet | ~3,0 GB | ~1,0 GB | 1-2 ngày | Có thể -1-2 điểm accuracy | ✅ cao |
| PA2-5b: chung MiniLM | ~3,0 GB | ~1,0 GB | 0,5 ngày | Semantic sập còn 38,3% | ❌ loại |
| PA2-5e: hosted API | ~2,3 GB | ~1,7 GB | 1-2 ngày | Phụ thuộc mạng/chi phí/latency | ⚠️ thấp |

**Khuyến nghị của người lập (để PO quyết):**
1. Dù chọn phương án nào, làm **guardrail 1-process** (sửa 2 đường embed của dashboard
   đi qua worker + trim import telegram_customer_bot) — đây là lỗi kiến trúc cần sửa,
   không phải tối ưu tùy chọn.
2. Nếu ngân sách chịu được: **PA1** — rẻ so với ngày công dev, mở biên an toàn cho cả
   Chặng C-E (terminal, web, Zalo đều sẽ ăn thêm RAM trên cùng VPS — điều mà bảng §3
   CHƯA tính).
3. Nếu phải giữ 4 GB: **PA2-5d (quantize)** trước — giữ nguyên chức năng; **PA2-5a**
   (bỏ semantic) là nút thoát hiểm đơn giản nếu 5d trục trặc. KHÔNG "bỏ NLU" toàn bộ —
   Pattern+Rules+Entity gần như miễn phí RAM và là phần chính xác nhất hệ thống.
4. Con số quan trọng nhất cần đo TIẾP trên VPS thật (HOST-003): lặp lại đúng script
   `scripts/measure_embedding_rss.py` + `docker stats` sau khi deploy — số dev machine
   chỉ là ước lượng tốt, không phải cam kết.
