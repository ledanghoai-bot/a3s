# Alpha3S — Tài liệu Dashboard (Next.js)

> Tham chiếu đầy đủ dashboard quản trị (`dashboard/`) — dùng khi deploy, đào
> tạo nhân viên mới, hoặc phát triển tiếp. Giống 1 file `/help` cho dashboard.
> Cập nhật lần cuối: 16/7 (sau nâng cấp UX lần 5 — note/approve theo từng item).

## Mục lục nhanh
- [Tổng quan](#tổng-quan)
- [Đăng nhập](#đăng-nhập)
- [Trang /conversations (trang chính)](#trang-conversations-trang-chính)
- [Trang /orders](#trang-orders)
- [Trang /orders/new](#trang-ordersnew)
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

**Xác thực:** token tĩnh đơn giản (`ADMIN_API_TOKEN`, lấy từ `.env` của backend) —
**chưa có** hệ thống đăng nhập/JWT thật, đủ dùng cho quy mô hiện tại, cần nâng cấp
khi có nhiều nhân viên dùng song song.

---

## Đăng nhập

**Trang:** `/login`

- Nhập `ADMIN_API_TOKEN` (lấy từ file `.env` của backend, biến `ADMIN_API_TOKEN`).
- Token lưu trong `localStorage` trình duyệt (key `admin_token`) — **không hết
  hạn tự động**, chỉ mất khi xoá cache trình duyệt hoặc bấm đăng xuất (hiện
  **chưa có nút đăng xuất** trên UI — xoá tay qua DevTools nếu cần đổi token).
- Xác thực bằng cách gọi `GET /dashboard/ping` — sai token thì báo lỗi ngay,
  không lưu token sai vào localStorage.
- Mọi request khác nếu nhận `401` sẽ tự xoá token + điều hướng về `/login`.

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
│   ├── layout.js              # Layout gốc: nav (Hội thoại / Đơn hàng)
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
│   └── components/
│       └── OrderForm.js
├── lib/
│   ├── api.js                  # apiFetch() - tự đính kèm token, xử lý 401
│   └── useAuthGuard.js         # Hook check token, điều hướng /login nếu thiếu
├── Dockerfile
├── package.json
└── next.config.mjs
```

---

## API backend mà dashboard gọi tới

Tất cả endpoint dưới `/dashboard/*`, yêu cầu header `X-Admin-Token` (trừ
`ping` cũng yêu cầu nhưng dùng để validate token lúc login).

| Method | Path | Dùng ở |
|---|---|---|
| GET | `/dashboard/ping` | Login — validate token |
| GET | `/dashboard/conversations` | `/conversations` — danh sách + `/n(N)` `/a(N)` |
| GET | `/dashboard/conversations/{psid}/messages` | Khung chat mở rộng |
| GET | `/dashboard/conversations/{psid}/order_draft` | Khung note/approve mở rộng + tự điền `OrderForm` |
| POST | `/dashboard/conversations/{psid}/pause` | Nút "Tiếp quản" |
| POST | `/dashboard/conversations/{psid}/resume` | Nút "Resume bot" |
| POST | `/dashboard/notes/{message_id}/mark-handled` | Nút "✓ Đã xử lý" (note) |
| POST | `/dashboard/overrides/{override_id}/mark-used` | Nút "✓ Đã tạo đơn" (approve) |
| POST | `/dashboard/overrides/{override_id}/reject` | Nút "✗ Từ chối" (approve) |
| GET | `/dashboard/products` | Dropdown chọn SKU trong `OrderForm` |
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
| `ADMIN_API_TOKEN` | Backend (`.env` gốc, **không phải** của dashboard) — dùng để đăng nhập | `change-me` (đổi khi deploy thật) |
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
   hoàn toàn như kỳ vọng ban đầu. Đã ghi nhận trong `ISSUES.md`, quyết định
   **không đào sâu fix** (16/7).
2. **Chưa có đăng xuất** trên UI — đổi token phải xoá tay qua DevTools
   (`localStorage.removeItem('admin_token')`) hoặc xoá cache trình duyệt.
3. **1 token dùng chung cho mọi nhân viên** — không phân biệt ai đang thao
   tác, không có audit "ai bấm nút gì". Đủ dùng cho quy mô hiện tại.
4. Trang `/conversations/[psid]` (popup cửa sổ riêng) **còn trong code
   nhưng không còn nút nào dẫn tới** — an toàn để xoá nếu muốn dọn code sau này.

---

## Việc chưa làm (ngoài phạm vi hiện tại)

Theo đúng phạm vi issue #8 gốc, các mục sau **chưa xây**:
- CRUD sản phẩm/FAQ (tự động re-ingest RAG khi sửa nội dung)
- Metrics/analytics (tin nhắn/ngày, tỷ lệ hội thoại → đơn, top câu hỏi bot
  không trả lời được)
- Auth thật (đăng nhập theo từng nhân viên, JWT/session)

Xem chi tiết đầy đủ lịch sử phát triển + quyết định kỹ thuật trong `ISSUES.md`
mục **#8**.
