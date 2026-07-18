# Alpha3S — Tài liệu Dashboard (Next.js)

> Tham chiếu đầy đủ dashboard quản trị (`dashboard/`) — dùng khi deploy, đào
> tạo nhân viên mới, hoặc phát triển tiếp. Giống 1 file `/help` cho dashboard.
> Cập nhật lần cuối: 17/7 (sau Bat 4 — Auth thật, đóng hẳn issue #8).

## Mục lục nhanh
- [Tổng quan](#tổng-quan)
- [Đăng nhập](#đăng-nhập)
- [Trang /conversations (trang chính)](#trang-conversations-trang-chính)
- [Trang /orders](#trang-orders)
- [Trang /orders/new](#trang-ordersnew)
- [Trang /products](#trang-products)
- [Trang /faq](#trang-faq)
- [Trang /metrics](#trang-metrics)
- [Trang /staff](#trang-staff)
- [Component dùng chung: OrderForm](#component-dùng-chung-orderform)
- [Cấu trúc thư mục](#cấu-trúc-thư-mục)
- [API backend mà dashboard gọi tới](#api-backend-mà-dashboard-gọi-tới)
- [Biến môi trường](#biến-môi-trường)
- [Cách chạy / deploy](#cách-chạy--deploy)
- [Giới hạn đã biết](#giới-hạn-đã-biết)
- [Việc chưa làm (ngoài phạm vi hiện tại)](#việc-chưa-làm-ngoài-phạm-vi-hiện-tại)

---

## Tổng quan

Dashboard là ứng dụng **Next.js App Router** riêng biệt (service `dashboard`
trong `docker-compose.yml`, cổng **3000**), gọi tới backend FastAPI qua REST
JSON (`NEXT_PUBLIC_API_URL`, mặc định `http://localhost:8000`).

**Mục đích:** cho nhân viên vận hành fanpage hằng ngày mà không cần vào thẳng
database — xem hội thoại, tiếp quản/bàn giao bot, quản lý ghi chú/phê duyệt
giá đặc biệt, tạo và theo dõi đơn hàng.

**Xác thực:** đăng nhập thật theo từng nhân viên (username/password + session
token) từ Bat 4 (17/7) — thay thế hoàn toàn token tĩnh `ADMIN_API_TOKEN` dùng
chung trước đây. Chưa có phân quyền theo role — xem mục "Giới hạn đã biết".

---

## Đăng nhập

**Trang:** `/login`

Từ Bat 4 (17/7) — đăng nhập bằng **username/password thật** (không còn dán
token tĩnh):
- Gọi `POST /dashboard/auth/login` với `{username, password}` → nhận về
  **session token** (chuỗi ngẫu nhiên, TTL 7 ngày, lưu trong bảng `staff_sessions`).
- Token lưu trong `localStorage` (key `staff_token`, đổi từ `admin_token` cũ).
- Mọi request kèm header chuẩn `Authorization: Bearer <token>` (thay
  `X-Admin-Token` trước đây).
- Nhận `401` → tự xóa token + điều hướng về `/login`.
- **Đăng xuất thật** đã có (nút trên nav, `NavUser.js`) — gọi
  `POST /dashboard/auth/logout`, xóa đúng session đó khỏi DB (không ảnh
  hưởng session khác nếu đăng nhập trên nhiều thiết bị).

**Tạo tài khoản đầu tiên (bắt buộc, chỉ 1 lần):** chưa ai đăng nhập được để
tự tạo tài khoản qua `/staff` (gà và trứng), nên dùng script:
```bash
docker compose exec api python scripts/create_staff_user.py <username> <password> "<ten>"
```
Từ tài khoản thứ 2 trở đi, tạo thẳng qua trang `/staff`.

---

## Trang /conversations (trang chính)

Danh sách toàn bộ hội thoại, **tự động refresh mỗi 5 giây** (không cần F5 tay)
— tạm dừng refresh khi đang có thao tác đang xử lý (tránh giật UI).

### Cột trong bảng
| Cột | Nội dung |
|---|---|
| **Khách** | Tên (hoặc "chưa có tên") + nút **"▼ Mở rộng chat"** + SĐT/PSID bên dưới |
| **Status** | `/n(N)` = số ghi chú **chưa xử lý**, `/a(N)` = số phê duyệt `/approve` **còn hiệu lực**. Số in đậm, màu xám khi N=0, cam khi N>0 |
| **Tin nhắn gần nhất** | Preview 1 dòng, cắt bớt nếu dài |
| **Lúc** | Thời gian tin nhắn gần nhất |
| **Trạng thái** | Badge "Bot đang trả lời" / "Chờ nhân viên" (phản ánh `conversations.bot_paused`) |
| *(cột cuối, không tên)* | Nút **"Tiếp quản"** (pause) hoặc **"Resume bot"** |

### Nút "Tiếp quản" / "Resume bot"
- **Tiếp quản** (bot → paused): gọi `POST /dashboard/conversations/{psid}/pause`.
  Nhân viên tự set, khác với bot tự escalate.
- **Resume bot** (paused → bot): gọi `POST /dashboard/conversations/{psid}/resume`.
  Trước khi resume, **hiện popup hỏi ghi chú tuỳ chọn** — nếu điền, ghi chú
  này được lưu vào lịch sử (`role='agent'`) VÀ bơm ngược vào context bot ngay
  lượt chat kế tiếp (tránh bot "quên" thoả thuận vừa chốt lúc paused).

### Nút "▼ Mở rộng chat"
Mở 1 dòng bên dưới, hiển thị:

1. **Lịch sử chat đầy đủ** — dạng bubble, phân biệt Khách (trái) / Bot & Nhân
   viên (phải, màu khác nhau theo `role`).
2. **📝 Ghi chú (tất cả)** — liệt kê **toàn bộ** note (`role='agent'` trong
   `messages`), không chỉ note chưa xử lý:
   - Note **chưa xử lý**: nền vàng, có nút **"✓ Đã xử lý"** (bấm là lưu ngay,
     **không** cần xác nhận).
   - Note **đã xử lý**: nền xám, mờ đi, chỉ còn nhãn tĩnh "✓ Đã xử lý" —
     **không biến mất khỏi danh sách**, chỉ đổi trạng thái hiển thị.
3. **✅ Phê duyệt (/approve) (tất cả)** — tương tự, liệt kê toàn bộ:
   - **Active**: nền vàng, 2 nút **"✓ Đã tạo đơn"** (bắt buộc popup xác nhận
     trước khi lưu) và **"✗ Từ chối"** (bắt buộc popup xin lý do, không được
     để trống).
   - **Used** (đã tạo đơn): nền xám, nhãn tĩnh "✓ Đã tạo đơn".
   - **Rejected** (đã từ chối): nền xám, nhãn tĩnh "✗ Đã từ chối" kèm hiện lý
     do đã nhập.
4. Nút **"🧾 Tạo đơn (tự điền từ /approve, /note)"** — điều hướng sang
   `/orders/new?psid=<psid>` (xem phần dưới), **không** tạo đơn ngay tại chỗ.

---

## Trang /orders

Danh sách đơn hàng thật (bảng `orders`), có nút **"+ Tạo đơn thủ công"** góc
trên phải (điều hướng sang `/orders/new` **không kèm** `psid`).

Mỗi dòng có dropdown đổi trạng thái đơn — gọi `PATCH /dashboard/orders/{id}/status`.
Backend validate thứ tự chuyển hợp lệ: `new → confirmed → shipped → done`
(không lùi được), `cancelled` được phép từ mọi bước **trừ** `done`. Chọn sai
thứ tự sẽ bị backend từ chối kèm thông báo lỗi.

---

## Trang /orders/new

Trang tạo đơn thủ công, đóng **2 vai trò** tuỳ có `?psid=` trên URL hay không:

| Truy cập | Có `psid`? | Hành vi |
|---|---|---|
| Từ nút "🧾 Tạo đơn" trong `/conversations` | Có (`?psid=...`) | Tự động gọi `order_draft` để **điền sẵn** số lượng/đơn giá từ `/approve` gần nhất + tên/SĐT/địa chỉ nếu khách đã từng đặt đơn. Hiện **cả 2 nút** "🤖 Gọi bot tạo đơn" và "👤 NV tạo đơn". |
| Từ nút "+ Tạo đơn thủ công" trong `/orders` | Không | Form trống hoàn toàn. Chỉ hiện nút **"👤 NV tạo đơn"** (không có "gọi bot" vì không có hội thoại nào để bot đọc ngữ cảnh). |

**Lưu ý bảo mật:** URL chỉ mang theo `psid` (không nhạy cảm) — tên/SĐT/địa
chỉ **không bao giờ** đưa vào query string, luôn fetch lại qua API.

### 2 nút submit khác nhau
- **🤖 Gọi bot tạo đơn** — gọi `POST /dashboard/conversations/{psid}/create_order`,
  dùng **đúng logic AI tool đang dùng** (`app/services/tools.py:create_order`)
  — vẫn kiểm tra đầy đủ bậc giá chuẩn / `MAX_AUTO_QUANTITY` / `price_overrides`
  khớp chính xác số lượng. Có thể bị từ chối nếu không có phê duyệt hợp lệ.
- **👤 NV tạo đơn** — gọi `create_order_manual`, **bỏ qua toàn bộ** validate
  trên, staff tự nhập đơn giá và tự chịu trách nhiệm. Chỉ còn kiểm tra tồn
  kho thật (không bán vượt số lượng đang có).

---

## Trang /products

CRUD sản phẩm đầy đủ (17/7, Bat 2) — danh sách SKU + bậc giá, mỗi dòng có 3 nút:
**Sửa**, **Bậc giá**, **Xoá**.

- **Thêm/Sửa** — form mở ngay trong bảng (không chuyển trang). `sku`
  **không sửa được** sau khi tạo (immutable, xem `docs/DATABASE-VI.md`).
  Trường **Mô tả** tự động dùng cho RAG (xem bên dưới) — UI có gợi ý nên
  viết cụ thể (kích thước, đóng gói, điểm khác biệt) để bot trả lời đúng hơn.
- **Bậc giá** — editor riêng, thay **TOÀN BỘ** danh sách bậc mỗi lần lưu (không
  PATCH từng dòng) — gọi `PUT /dashboard/products/{id}/tiers`.
- **Xoá** — bị **từ chối** nếu sản phẩm đã có đơn hàng/bậc giá liên quan (khóa
  ngoại chặn đúng thiết kế, không phải bug).

⚠️ **Quan trọng — sản phẩm tạo TRƯỚC khi có tính năng RAG tự đồng bộ (trước
migration 009) sẽ KHÔNG có sẵn knowledge_chunk** — cần vào sửa rồi lưu lại
(không cần đổi nội dung gì) để trigger tạo chunk cho lần đầu.

---

## Trang /faq

CRUD FAQ (17/7, Bat 2) — từng cặp câu hỏi/trả lời, **tự động đồng bộ vào RAG
ngay khi lưu** (không cần chạy `scripts/ingest.py`).

- **Thêm/Sửa** — form 2 ô (Câu hỏi, Câu trả lời). Lưu sẽ mất vài giây vì phải
  tính embedding (model chạy local, CPU-bound) — UI hiển "Đang lưu (tính
  embedding)..." trong lúc chờ.
- **Xoá** — xóa luôn cả `knowledge_chunk` tương ứng qua `ON DELETE CASCADE`,
  không cần bước dọn thêm.
- Nội dung tĩnh gốc (`data/knowledge/*.md`) **không bị ảnh hưởng gì** — 2
  nguồn cùng tồn tại song song trong `knowledge_chunks` (phân biệt qua cột `source`).

---

## Trang /metrics

Metrics/Analytics (17/7, Bat 3) — **không thêm bảng DB mới nào**, tận dụng hoàn
toàn dữ liệu sẵn có. 3 khối nội dung:

1. **3 thẻ tổng quan** — tổng số khách đã chat, số khách đã có đơn, tỷ lệ
   chat → đơn (%). Tỷ lệ tính tổng thể từ trước tới giờ, **chưa tách theo
   thời gian** (đơn giản hóa có chủ đích cho v1).
2. **Tin nhắn/ngày** (14 ngày gần nhất) — bar chart tự vẽ bằng CSS (không
   thêm thư viện chart ngoài, tránh phải cài gói npm mới trong container dev
   mode), tách màu theo `role` (khách/bot/nhân viên).
3. **Top câu hỏi bot không trả lời được** — dò tin nhắn bot khớp câu fallback
   cố định ("chưa có thông tin xác nhận..."), ghép với câu hỏi khách ngay trước
   đó, gom nhóm theo tần suất. **Không NLP/fuzzy** — câu hỏi khác chữ dù cùng
   ý sẽ bị đếm riêng.

Backend: `app/services/metrics.py` (3 hàm, không transaction, chỉ SELECT).

---

## Trang /staff

Quản lý tài khoản nhân viên (17/7, Bat 4) — liệt kê, thêm mới, vô hiệu
hóa/kích hoạt lại.

- **Thêm nhân viên** — username + password (tối thiểu 6 ký tự) + tên hiển
  thị (tuỳ chọn). Mật khẩu hash bằng PBKDF2 (xem `docs/BACKEND_API-VI.md`).
- **Vô hiệu hóa** — không xóa tài khoản (giữ lịch sử), chỉ đặt `is_active=FALSE`
  — mọi session hiện có của staff đó bị từ chối ngay từ lần gọi API kế tiếp.

⚠️ **Chưa có phân quyền theo role** — bất kỳ staff nào đang đăng nhập đều vào
được trang này và quản lý được tài khoản khác (kể cả tự vô hiệu hóa chính mình).
Phù hợp quy mô đội nhỏ hiện tại.

---

## Component dùng chung: OrderForm

File: `dashboard/app/components/OrderForm.js`

Nhận prop `psid` (mặc định `null`):
- `psid` truyền vào → tự fetch `order_draft`, tự điền form, hiện cả 2 nút.
- `psid = null` → form trống, chỉ hiện nút "NV tạo đơn", gọi `POST /dashboard/orders/manual`
  (đơn độc lập, tự sinh `psid` dạng `manual:<uuid>`).

Dùng lại y hệt ở cả `/orders/new` (2 trường hợp trên) — không có bản sao code.

---

## Cấu trúc thư mục

```
dashboard/
├── app/
│   ├── layout.js              # Layout gốc: nav (Hội thoại / Đơn hàng / Sản phẩm / FAQ / Metrics)
│   ├── page.js                 # Redirect -> /conversations
│   ├── globals.css
│   ├── login/page.js
│   ├── conversations/
│   │   ├── page.js              # Trang chính (mô tả ở trên)
│   │   └── [psid]/page.js       # ⚠️ Còn trong code nhưng KHÔNG còn link tới
│   │                             #    từ UI (nút "Mở cửa sổ riêng" đã bị bỏ
│   │                             #    theo yêu cầu 16/7) — dead code, có thể
│   │                             #    xoá hoặc tái sử dụng sau này.
│   ├── orders/
│   │   ├── page.js
│   │   └── new/page.js
│   ├── products/page.js         # CRUD sản phẩm (Bat 2, 17/7)
│   ├── faq/page.js              # CRUD FAQ (Bat 2, 17/7)
│   ├── metrics/page.js          # Metrics/Analytics (Bat 3, 17/7)
│   ├── staff/page.js            # Quan ly tai khoan nhan vien (Bat 4, 17/7)
│   └── components/
│       ├── OrderForm.js
│       └── NavUser.js             # Ten + nut Dang xuat tren nav (Bat 4, 17/7)
├── lib/
│   ├── api.js                  # apiFetch() - tự đính kèm token, xử lý 401
│   └── useAuthGuard.js         # Hook check token, điều hướng /login nếu thiếu
├── Dockerfile
├── package.json
└── next.config.mjs
```

---

## API backend mà dashboard gọi tới

Tất cả endpoint dưới `/dashboard/*`, yêu cầu header `Authorization: Bearer
<token>` (trừ `POST /dashboard/auth/login` không cần, vì chưa có token lúc đó).

| Method | Path | Dùng ở |
|---|---|---|
| POST | `/dashboard/auth/login` | Đăng nhập — KHÔNG cần token |
| POST | `/dashboard/auth/logout` | Nút "Đăng xuất" |
| GET | `/dashboard/auth/me` | Hiển thị tên staff trên nav |
| GET | `/dashboard/auth/staff` | Trang `/staff` — danh sách |
| POST | `/dashboard/auth/staff` | Trang `/staff` — thêm nhân viên |
| PATCH | `/dashboard/auth/staff/{id}` | Trang `/staff` — vô hiệu hóa/kích hoạt lại |
| GET | `/dashboard/ping` | Legacy, giữ tương thích ngược |
| GET | `/dashboard/conversations` | `/conversations` — danh sách + `/n(N)` `/a(N)` |
| GET | `/dashboard/conversations/{psid}/messages` | Khung chat mở rộng |
| GET | `/dashboard/conversations/{psid}/order_draft` | Khung note/approve mở rộng + tự điền `OrderForm` |
| POST | `/dashboard/conversations/{psid}/pause` | Nút "Tiếp quản" |
| POST | `/dashboard/conversations/{psid}/resume` | Nút "Resume bot" |
| POST | `/dashboard/notes/{message_id}/mark-handled` | Nút "✓ Đã xử lý" (note) |
| POST | `/dashboard/overrides/{override_id}/mark-used` | Nút "✓ Đã tạo đơn" (approve) |
| POST | `/dashboard/overrides/{override_id}/reject` | Nút "✗ Từ chối" (approve) |
| GET | `/dashboard/products` | Dropdown chọn SKU trong `OrderForm` |
| GET | `/dashboard/products/full` | Trang `/products` — danh sách đầy đủ kèm bậc giá |
| POST | `/dashboard/products` | Thêm sản phẩm mới |
| PATCH | `/dashboard/products/{id}` | Sửa sản phẩm (không gồm `sku`) |
| DELETE | `/dashboard/products/{id}` | Xoá sản phẩm |
| PUT | `/dashboard/products/{id}/tiers` | Thay toàn bộ bậc giá |
| GET | `/dashboard/faq` | Trang `/faq` — danh sách |
| POST | `/dashboard/faq` | Thêm FAQ |
| PATCH | `/dashboard/faq/{id}` | Sửa FAQ |
| DELETE | `/dashboard/faq/{id}` | Xoá FAQ |
| GET | `/dashboard/metrics/messages-per-day?days=14` | Trang `/metrics` — bar chart tin nhắn/ngày |
| GET | `/dashboard/metrics/conversion-rate` | Trang `/metrics` — 3 thẻ tổng quan |
| GET | `/dashboard/metrics/unanswered-questions?limit=15` | Trang `/metrics` — bảng top câu hỏi |
| POST | `/dashboard/conversations/{psid}/create_order` | Nút "🤖 Gọi bot tạo đơn" |
| POST | `/dashboard/conversations/{psid}/create_order_manual` | Nút "👤 NV tạo đơn" (gắn hội thoại) |
| POST | `/dashboard/orders/manual` | Nút "👤 NV tạo đơn" (độc lập, `/orders/new` không psid) |
| GET | `/dashboard/orders` | `/orders` — danh sách đơn |
| PATCH | `/dashboard/orders/{order_id}/status` | Dropdown đổi trạng thái đơn |

---

## Biến môi trường

| Biến | Nơi dùng | Mặc định |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `dashboard/lib/api.js` | `http://localhost:8000` |
| `ADMIN_API_TOKEN` | ⚠️ **Không còn được dùng từ Bat 4** — vẫn còn trong `config.py`/`.env` để tương thích ngược, không gây lỗi nếu còn set nhưng không còn tác dụng xác thực | — |
| `DASHBOARD_CORS_ORIGINS` | Backend — origin được phép gọi API | `http://localhost:3000` |

---

## Cách chạy / deploy

Service `dashboard` trong `docker-compose.yml` chạy **dev mode hot-reload**
(`npm run dev`, bind-mount `./dashboard:/app`):

```bash
docker compose up -d --build dashboard   # lần đầu, hoặc sau khi doi command/volume
docker compose up -d dashboard            # cac lan sau (theo ly thuyet la du)
```

⚠️ **Xem mục "Giới hạn đã biết" bên dưới** — thực tế vẫn cần `--build` sau mỗi
lần sửa code, chưa hot-reload hoàn hảo như kỳ vọng.

**Khi deploy production thật (#9, chưa làm):** nên đổi lại sang production
build (`npm run build && npm start`) thay vì dev mode, vì dev mode chậm hơn và
không tối ưu — dev mode hiện dùng tạm để tiện sửa code nhanh trong giai đoạn
phát triển.

---

## Giới hạn đã biết

1. **Vẫn cần `docker compose up -d --build dashboard`** sau mỗi lần sửa code
   dashboard, dù đã chuyển sang dev mode hot-reload — không tự nhận code mới
   hoàn toàn như kỳ vọng ban đầu. Đã ghi nhận trong `ISSUES-VI.md`, quyết định
   **không đào sâu fix** (16/7).
2. **Chưa phân quyền theo role** — bất kỳ staff nào đăng nhập đều quản lý được
   tài khoản nhân viên khác (Bat 4, 17/7) — đủ dùng cho quy mô đội nhỏ.
3. **Chưa có audit trail** — không ghi lại AI nhân viên nào thực hiện hành động
   gì (vd ai tạo đơn, ai đánh dấu note đã xử lý) — có biết AI đang đăng nhập
   qua session, nhưng chưa lưu vào dữ liệu nghiệp vụ.
4. **Chưa có đổi mật khẩu/quên mật khẩu** — cần sysadmin can thiệp trực tiếp
   DB (`UPDATE staff_users ...`) nếu quên.
5. Trang `/conversations/[psid]` (popup cửa sổ riêng) **còn trong code
   nhưng không còn nút nào dẫn tới** — an toàn để xoá nếu muốn dọn code sau này.

---

## Việc chưa làm (ngoài phạm vi hiện tại)

Issue #8 **đã xong toàn bộ checklist gốc** (CRUD Bat 2, Metrics Bat 3, Auth Bat 4
— 17/7). Các hướng mở rộng tiềm năng (ngoài phạm vi #8 gốc, chưa có kế hoạch):
- Phân quyền theo role (vd chỉ "admin" mới quản lý được tài khoản)
- Audit trail chi tiết (ai làm gì, lúc nào)
- Đổi mật khẩu/quên mật khẩu qua UI

Xem chi tiết đầy đủ lịch sử phát triển + quyết định kỹ thuật trong
`ISSUES-VI.md` (hoặc `ISSUES-EN.md`) mục **#8**.
