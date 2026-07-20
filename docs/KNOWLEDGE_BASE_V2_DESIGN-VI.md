# Alpha3S — Thiết kế kỹ thuật Knowledge Base V2 (M1 Ingestion + M2 Retrieval)

> **Trạng thái: THIẾT KẾ, CHƯA CODE.** Chờ team Knowledge/PO xác nhận cách xử lý
> 10 file đang ở trạng thái `draft` (Sales + FAQ) trước khi triển khai thật.
> Tài liệu này để anh Hoài review/gửi lại team Knowledge nếu cần trước khi
> code — không phải tài liệu vận hành chính thức như `docs/*.md` khác.
>
> Phạm vi: **chỉ M1 (Repository/Ingestion) + M2 (Retrieval)** — chưa đụng tới
> Intent Router, Tool Layer, Prompt Assembly, Runtime Guardrails (M3-M6).

## Mục lục
- [Nguyên tắc thiết kế cốt lõi](#nguyên-tắc-thiết-kế-cốt-lõi)
- [3 phát hiện quan trọng từ depository thật](#3-phát-hiện-quan-trọng-từ-depository-thật)
- [Vị trí trong repo](#vị-trí-trong-repo)
- [Schema DB mới](#schema-db-mới)
- [M1 — Thiết kế Ingestion Pipeline](#m1--thiết-kế-ingestion-pipeline)
- [M2 — Thiết kế Retrieval Pipeline](#m2--thiết-kế-retrieval-pipeline)
- [Danh sách file sẽ tạo (khi code thật)](#danh-sách-file-sẽ-tạo-khi-code-thật)
- [Câu hỏi còn mở](#câu-hỏi-còn-mở)

---

## Nguyên tắc thiết kế cốt lõi

1. **Hoàn toàn tách biệt khỏi hệ thống production hiện tại.** Bảng mới
   (`kb_*`), script mới (`scripts/kb_ingest.py`), không đụng tới
   `knowledge_chunks`/`rag.py`/`orchestrator.py` đang chạy thật cho bot. Đây
   là sandbox thử nghiệm — chỉ khi anh quyết định "go" mới tính chuyện tích
   hợp vào runtime thật (M3+, ngoài phạm vi thiết kế này).
2. **Tuân thủ đúng `INGESTION_GUIDE.md`/`REFERENCE_IMPLEMENTATION.md`** —
   validation, Knowledge Unit builder, index versioning + atomic switch đều
   theo đúng pseudocode team Knowledge đã duyệt, không tự sáng tác kiến trúc
   khác.
3. **Dữ liệu thật rất "bẩn" — parser phải chịu được**, không giả định file
   nào cũng đúng chuẩn (xem phần phát hiện bên dưới).

---

## 3 phát hiện quan trọng từ depository thật

### 1. Trạng thái draft/approved (đang chờ team Knowledge xác nhận)
Xem tóm tắt đã gửi trước đó — 10/23 file Skill (toàn bộ Sales + FAQ) đang
`status: draft` trong file thật, dù `depository-structure.md` ghi "approved".
**Thiết kế đã tính đến cả 2 khả năng** (xem cờ `--include-draft` ở mục M1).

### 2. Không đồng nhất định dạng front matter (4 kiểu, phải hỗ trợ hết)
| Kiểu | Ví dụ | File gặp |
|---|---|---|
| YAML chuẩn | `status: draft` (trong khối `---`) | SAL, CON, FAQ, PBK |
| Text 1 dòng | `Status: Approved Version: 1.0.0` | BRAND-001, CS-001 |
| Bold 1 dòng | `**Status:** Approved & Locked **Version:** 1.0.0` | PRD-003 |
| Bold nhiều dòng, có `\` cuối dòng | `**Status:** Draft for Review\` | PRD-004 |

### 3. Cấu trúc thư mục lệch `depository-structure.md`
- `skill/` (số ít, thực tế) vs `skills/` (số nhiều, spec)
- FAQ nằm ở `docs/faq/` (thực tế) vs `skills/faq/` (spec)
- `SKL-CS-002` (Need Discovery) — **không tồn tại file nào**, không phải draft

**Quyết định thiết kế:** khi copy vào repo alpha3s, mình sẽ **chuẩn hóa lại
đúng theo spec** (`skills/` số nhiều, FAQ vào `skills/faq/`) — vì đây là bản
copy dùng để ingest, không phải bản gốc của team Knowledge, nên sửa cho khớp
tài liệu đã duyệt là hợp lý. Không tự "chế" nội dung cho `SKL-CS-002` còn
thiếu — bỏ trống, ghi nhận trong rejected-report là "not found".

---

## Vị trí trong repo

```
alpha3s/
├── data/knowledge/          # KHÔNG ĐỔI — vẫn dùng cho bot production hiện tại
│
└── knowledge-base/          # MỚI — bản copy đã chuẩn hóa từ depository team Knowledge
    ├── skills/
    │   ├── brand/SKL-BRAND-001.md
    │   ├── customer_service/SKL-CS-001.md, SKL-CS-003.md
    │   ├── product/SKL-PRD-001..004.md
    │   ├── sales/SKL-SAL-001..005.md
    │   ├── conversation/SKL-CON-001..003.md
    │   └── faq/SKL-FAQ-001..005.md      # chuẩn hóa vị trí (thay vì docs/faq/)
    ├── playbooks/PBK-*.md
    └── taxonomy.yaml
```

---

## Schema DB mới

Migration mới (`migrations/011_knowledge_base_v2.sql`), **hoàn toàn cộng
thêm**, không sửa bảng nào đang có.

```sql
-- Nguon that cho tung file Skill/Playbook da ingest
CREATE TABLE kb_assets (
  id TEXT PRIMARY KEY,               -- vd 'SKL-FAQ-003' (lay tu front matter, KHONG tu sinh)
  title TEXT,
  domain TEXT NOT NULL,              -- brand/product/sales/conversation/faq/playbook (theo taxonomy.yaml)
  asset_type TEXT NOT NULL,          -- brand_skill/faq_skill/playbook/... (theo prefix trong taxonomy.yaml)
  status TEXT NOT NULL,              -- draft/review/approved/locked/superseded/archived
  version TEXT,
  priority TEXT,                     -- P1-P4, dung de boost retrieval
  source_path TEXT NOT NULL,
  language TEXT NOT NULL DEFAULT 'vi',
  raw_frontmatter JSONB,             -- luu nguyen front matter da parse (du cac field khac chua dung ngay)
  content_hash TEXT NOT NULL,        -- sha256 toan bo file - phat hien file doi ma khong ingest lai
  ingested_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Knowledge Unit - don vi chunk theo heading (## / ###)
CREATE TABLE kb_units (
  id TEXT PRIMARY KEY,               -- vd 'KU-FAQ-003-005', on dinh qua cac lan ingest lai
  asset_id TEXT NOT NULL REFERENCES kb_assets(id) ON DELETE CASCADE,
  heading TEXT,
  content TEXT NOT NULL,             -- giu ca parent title + section heading trong content
  content_hash TEXT NOT NULL,
  domain TEXT NOT NULL,
  status TEXT NOT NULL,              -- ke thua tu asset luc ingest
  priority TEXT,
  language TEXT NOT NULL DEFAULT 'vi',
  embedding vector(384),
  search_tsv TSVECTOR,               -- cho lexical search (Postgres full-text, xem M2)
  index_version INTEGER NOT NULL,    -- ho tro build song song + atomic switch
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX kb_units_embedding_idx ON kb_units USING hnsw (embedding vector_cosine_ops);
CREATE INDEX kb_units_tsv_idx ON kb_units USING GIN (search_tsv);
CREATE INDEX kb_units_asset_id_idx ON kb_units(asset_id);
CREATE INDEX kb_units_index_version_idx ON kb_units(index_version);

-- 1 dong / lan chay ingest - bao cao + de quyet dinh atomic switch
CREATE TABLE kb_ingestion_reports (
  id BIGSERIAL PRIMARY KEY,
  index_version INTEGER NOT NULL,
  run_at TIMESTAMPTZ DEFAULT now(),
  include_draft BOOLEAN NOT NULL,    -- co bat co --include-draft khong (xem M1)
  accepted_count INTEGER NOT NULL,
  rejected_count INTEGER NOT NULL,
  rejected_files JSONB NOT NULL      -- [{file, reason}, ...]
);

-- 1 dong duy nhat: index_version nao dang "active" cho retrieval that
CREATE TABLE kb_config (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
-- vd: ('active_index_version', '1')
```

**Atomic switch hoạt động thế nào:** mỗi lần chạy `kb_ingest.py` tạo 1
`index_version` MỚI (số tăng dần), ghi toàn bộ KU với version đó — KHÔNG xóa
version cũ. Sau khi chạy xong + smoke test pass, mới `UPDATE kb_config SET
value = '<version_mới>' WHERE key = 'active_index_version'`. Retrieval
(M2) LUÔN filter `WHERE index_version = (SELECT value FROM kb_config WHERE
key='active_index_version')`. Muốn rollback → đổi `kb_config` về version cũ,
không cần ingest lại.

---

## M1 — Thiết kế Ingestion Pipeline

Theo đúng thứ tự pseudocode trong `REFERENCE_IMPLEMENTATION.md`:

```
Discover files (knowledge-base/skills/**/*.md, knowledge-base/playbooks/*.md)
  → Parse front matter (KnowledgeLoader — chiu duoc ca 4 dinh dang)
  → Validate schema/status (AssetValidator)
  → Classify asset type (tra cuu prefix trong taxonomy.yaml)
  → Split by heading (KnowledgeUnitBuilder)
  → Generate stable KU ID + content_hash
  → Deduplicate (bo qua KU trung content_hash trong cung 1 asset)
  → Embed (embed_async, tai su dung tu app/services/embedder.py)
  → Ghi vao kb_units voi index_version MOI
  → Chay smoke retrieval (vai cau hoi P1 co dinh)
  → In bao cao (accepted/rejected) + ghi kb_ingestion_reports
  → (Thu cong) doi kb_config active_index_version neu smoke test pass
```

### Parser front matter (chịu 4 định dạng)
Thứ tự thử, dừng ở kiểu đầu tiên khớp:
1. Nếu file bắt đầu bằng `---\n` → parse YAML chuẩn.
2. Nếu không → tìm dòng khớp regex linh hoạt trong 15 dòng đầu:
   `r"\*?\*?Status:?\*?\*?\s*([A-Za-z& ]+?)\s*\*?\*?Version:?\*?\*?\s*([\d.]+)"`
   (chấp nhận có/không có `**`, có/không dấu `\` cuối dòng, "Approved & Locked"
   vẫn khớp nhóm 1, chuẩn hóa lowercase rồi map: chứa "approved" → `approved`,
   chứa "draft" → `draft`).
3. Title/ID lấy từ dòng `# SKL-XXX --- Tên` (regex `^#\s+([A-Z]+-[A-Z]+-\d+)\s*-+\s*(.+)$`)
   nếu không có trong YAML.
4. `domain`/`asset_type` suy ra từ **prefix của ID** tra trong `taxonomy.yaml`
   (không cần file tự khai domain nếu ID đã đủ xác định, dùng làm fallback).

### Validation (block ingestion khi):
- Thiếu `id` (không parse được cả 2 cách trên) → reject, lý do `"missing_id"`.
- `id` trùng trong cùng 1 lần chạy → reject file sau, lý do `"duplicate_id"`.
- `status` không phải `approved`/`locked` **VÀ không bật `--include-draft`**
  → reject, lý do `"not_approved (status=draft)"`.
- File không phải UTF-8 → reject, lý do `"invalid_encoding"`.
- (Dependency check — có `dependencies:` trong front matter nhưng ID đó
  không tồn tại trong batch đang ingest → reject, lý do `"missing_dependency"`.
  Về sau nếu dependency là asset production đã ingest trước đó thì không tính
  là thiếu — cần bảng tra cứu asset đã ingest, không chỉ trong batch hiện tại.)

### Cờ `--include-draft` (giải quyết vấn đề #1 đang chờ PO)
```bash
python scripts/kb_ingest.py                    # mac dinh: CHI approved/locked
python scripts/kb_ingest.py --include-draft     # localhost test: cho phep ca draft
```
Khi bật `--include-draft`, mọi KU tạo ra từ asset draft vẫn lưu đúng
`status='draft'` trong `kb_units` (không "tẩy trắng" thành approved) — để
M2 (retrieval) có thể tự quyết định có lọc draft ra hay không tùy ngữ cảnh
gọi (xem M2).

### Knowledge Unit builder
- Chunk theo `##` (heading cấp 1 trong nội dung, sau phần front matter) —
  không cắt theo `###` mặc định (tránh chunk quá nhỏ mất ngữ cảnh), trừ khi
  section `##` quá dài (>~800 từ) thì mới tách tiếp theo `###` con.
- Mỗi KU giữ nguyên `# <Tên asset>` (title cha) + `## <heading>` ở đầu
  content — đúng yêu cầu "giữ parent title và section heading".
- KU ID: `KU-<phần-số-của-asset-id>-<3-chữ-số-tăng-dần>`, vd asset
  `SKL-FAQ-003` → `KU-FAQ-003-001`, `KU-FAQ-003-002`... — khớp đúng ví dụ
  `KU-FAQ-003-005` trong `INGESTION_GUIDE.md`.
- **Ổn định qua các lần ingest lại:** nếu heading giữ nguyên vị trí thứ tự
  trong file, giữ nguyên KU ID cũ, chỉ tăng `content_hash`/version — không
  tự sinh ID mới cho content không đổi (đúng yêu cầu "Stable IDs").

---

## M2 — Thiết kế Retrieval Pipeline

Theo đúng `RAG_PIPELINE.md` + `ADR-0003-RAG-Strategy.md`:

```
Query
  → Chuẩn hóa (trim, lowercase cho phần lexical)
  → Vector search (pgvector, top-20) SONG SONG Lexical search (Postgres FTS, top-20)
  → Merge bằng Reciprocal Rank Fusion (RRF)
  → Áp dụng filter (status, domain, language, index_version=active)
  → Boost theo priority (P1 > P2 > P3 > P4) + canonical-source priority
  → Dedup theo content_hash
  → Trả về top-K kèm provenance
```

### Vector search
Y hệt cơ chế `rag.py` hiện tại (`ORDER BY embedding <=> query_vec`), chỉ đổi
bảng nguồn thành `kb_units` + filter `index_version`.

### Lexical/BM25-like search
Dùng **Postgres full-text search built-in** (`tsvector`/`tsquery`), KHÔNG
cần thêm hạ tầng ngoài (Elasticsearch...) — phù hợp quy mô hiện tại:
```sql
SELECT id, ts_rank_cd(search_tsv, query) AS rank
FROM kb_units, plainto_tsquery('simple', $1) query
WHERE search_tsv @@ query AND index_version = $2
ORDER BY rank DESC LIMIT 20;
```
**Lưu ý hạn chế đã biết:** dùng config `'simple'` (không phải config tiếng
Việt chuyên dụng) vì Postgres không có dictionary tiếng Việt built-in tốt —
`'simple'` chỉ tokenize thô, không stem, nhưng đủ để bắt chính xác SKU/tên
riêng/từ khóa (đúng mục đích ADR-0003 nêu — lexical mạnh ở chỗ ID/SKU/tên
riêng, không cần hiểu ngữ nghĩa sâu). Có thể nâng cấp sau nếu cần.

### Merge — Reciprocal Rank Fusion (RRF)
Thay vì 1 model rerank ML riêng (ngoài phạm vi M2, cần thêm hạ tầng), dùng
công thức RRF chuẩn, đơn giản, không cần chuẩn hóa điểm số giữa 2 loại tìm
kiếm khác nhau:
```
score(unit) = Σ 1 / (k + rank_trong_moi_danh_sach), k = 60 (hang so pho bien)
```
Unit nào xuất hiện ở cả 2 danh sách (vector + lexical) sẽ có điểm cao hơn
hẳn unit chỉ xuất hiện ở 1 danh sách — đúng tinh thần "reranker" mà
`RAG_PIPELINE.md` mô tả, dù chưa phải model ML thật (**ghi nhận là giới hạn
đã biết, có thể nâng cấp lên cross-encoder reranker thật ở giai đoạn sau**).

### Canonical-source priority / boost
Cộng thêm điểm nhỏ theo tầng kiến trúc (`depository-structure.md` mục
"Knowledge Architecture"): Brand > Product > Sales > Conversation > FAQ, và
theo field `priority` (P1 boost nhiều nhất). Danh sách domain + thứ tự lấy
thẳng từ `taxonomy.yaml` (đã có sẵn `domains.active`).

### Provenance
Mỗi kết quả trả về kèm: `ku_id, asset_id, source_file, heading, status,
version, score` — đúng yêu cầu *"Mọi response lưu provenance IDs"*.

### Hàm chính (dự kiến)
```python
async def search_kb(
    query: str,
    top_k: int = 5,
    allowed_domains: list[str] | None = None,
    include_draft: bool = False,
) -> list[dict]:
    """Tra ve KU lien quan nhat kem provenance day du."""
```

---

## Danh sách file sẽ tạo (khi code thật)

| File | Vai trò |
|---|---|
| `migrations/011_knowledge_base_v2.sql` | 4 bảng mới `kb_*` |
| `knowledge-base/**/*.md` | Bản copy đã chuẩn hóa cấu trúc từ depository |
| `app/services/kb_ingest/loader.py` | Parse front matter (4 định dạng) |
| `app/services/kb_ingest/validator.py` | Validation rules |
| `app/services/kb_ingest/unit_builder.py` | Chunk theo heading, sinh KU ID/hash |
| `scripts/kb_ingest.py` | CLI chạy toàn bộ pipeline M1, in báo cáo |
| `app/services/kb_retrieval.py` | `search_kb()` — hybrid retrieval M2 |
| `scripts/kb_search_test.py` | CLI test nhanh 1 câu hỏi, xem kết quả + provenance (không qua bot) |
| `docs/KNOWLEDGE_BASE_V2-VI.md` | Tài liệu vận hành chính thức (viết SAU khi code xong, giống các `docs/*.md` khác) |

---

## Câu hỏi còn mở

1. **[ĐANG CHỜ]** Team Knowledge/PO xác nhận: 10 file draft (Sales+FAQ) nên
   sửa status thật, hay đúng là chưa duyệt thật (tracker `depository-structure.md`
   sai)?
2. Baseline tests trong `RAG_PIPELINE.md` (Brand definition, Freeze-dried
   definition, Hot/cold brewing, Caffeine calculation, 100% Robusta
   correction, Price → Tool, Complaint → Human) — dùng làm smoke test sau
   M1 ingest, nhưng câu hỏi mẫu cụ thể + đáp án đúng mong đợi chưa có — cần
   team Knowledge cung cấp hoặc tự soạn dựa trên nội dung Brand Truth.
3. `dependencies:` trong front matter FAQ (vd `SKL-FAQ-003`) tham chiếu tới
   Skill nào — cần đọc kỹ nội dung `dependencies:` thật của từng file khi
   code (chưa liệt kê chi tiết trong thiết kế này).
