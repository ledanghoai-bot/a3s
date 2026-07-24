# Alpha3S — Hướng dẫn xin duyệt Meta App Review (cổng Messenger)

> **Ngày soạn:** 24/07/2026 · **Người soạn:** Claude Code (theo yêu cầu anh Hoài)
> **Mục đích:** Cẩm nang thực thi để đưa app Messenger của Alpha3S từ **chế độ phát triển**
> (chỉ role test nhắn được) sang **mở cho khách thật**, qua quy trình **Meta App Review**.
> Đây là hạng mục còn treo cuối cùng của **#9** (xem `ISSUES-VI.md` §#9) và phụ thuộc **#1**
> (rotate secret Meta). Bản EN: `docs/META-APP-REVIEW-EN.md`.

---

## 0. TL;DR — đọc cái này trước

- **Vì sao cần:** App `robanme.com` đang ở chế độ phát triển. Ở chế độ này **chỉ tài khoản có
  role trên app** (admin/dev/tester) mới nhắn được cho bot. Muốn **khách lạ bất kỳ** nhắn fanpage
  và được bot trả lời, quyền `pages_messaging` phải đạt **Advanced Access** — mà điều đó **bắt buộc
  qua App Review + Xác minh doanh nghiệp (Business Verification)**.
- **Xin quyền gì:** chủ yếu **`pages_messaging`** (Advanced Access). Kèm theo:
  `pages_manage_metadata` (đăng ký webhook), `pages_show_list`/`pages_read_engagement` (chọn/đọc
  Page). Quyền hồ sơ khách (first_name/last_name) đi kèm `pages_messaging`, **không cần** xin
  riêng.
- **3 rào cản còn lại chỉ anh Hoài làm được (thủ công trên Meta Console):**
  1. **Xác minh doanh nghiệp** (Business Verification) cho Công ty CP Robanme — thường là đường
     dài nhất (vài ngày → vài tuần).
  2. **Rotate secret Meta** (#1) trước khi mở khách thật — secret cũ đã lộ trong git history.
  3. **Điền thông tin công ty thật** vào 3 trang pháp lý đã dựng + **gắn URL vào App Settings**
     (xem §5) — trang đã có, chỉ còn điền placeholder.
- **✅ Đã xử lý (Code, 24/07/2026):** (a) dựng 3 trang **Privacy / Terms / Data Deletion** phục vụ tại
  `a3s.robanme.com` (§5); (b) sửa **khai báo bot tự động** trong `system_prompt.md` + đa kênh qua tham
  số `channel` — Messenger bắt buộc, kênh khác khuyến nghị (§7). Trước đây `system_prompt.md` cố tình
  bắt bot nói như người thật (rủi ro reject cao nhất) — nay đã gỡ.

---

## 1. Bối cảnh app hiện tại (as-built)

| Hạng mục | Giá trị thật trong dự án |
|---|---|
| App name / App ID | `robanme.com` · **541838039979536** |
| Loại sản phẩm | Messenger (Facebook Page) |
| Page kết nối | **"3S Coffee"** |
| Callback URL webhook | `https://a3s.robanme.com/webhook` (VPS `160.30.157.235`, HTTPS Caddy) |
| Verify token | `META_VERIFY_TOKEN` (env, đối chiếu ở `GET /webhook`) |
| App secret | `META_APP_SECRET` (env, kiểm chữ ký `X-Hub-Signature-256`) |
| Page access token | `PAGE_ACCESS_TOKEN` (env, gọi Send API + User Profile) |
| Graph API version | Send API `v21.0`, User Profile `v19.0` |
| Webhook fields đã subscribe | nhóm `messaging` (messages, messaging_postbacks…) |
| Đáp ứng SLA webhook | `POST /webhook` chỉ validate + enqueue Redis → trả 200 **< 100ms** (Meta yêu cầu ≤ 20s) ✅ |

**Meta API thực sự đang dùng** (để mô tả trong bài nộp cho khớp hành vi thật):
1. **Messenger Platform webhook** — nhận tin khách gửi tới Page.
2. **Send API** (`POST /me/messages`, `messaging_type: RESPONSE`) — bot trả lời khách.
3. **User Profile API** (`GET /{psid}?fields=first_name,last_name`) — lấy tên để xưng hô, cache
   Redis 7 ngày (`app/services/messenger_profile.py`).

> Toàn bộ chỉ là **hội thoại phản hồi trong cửa sổ 24h chuẩn** (`RESPONSE`). Hiện **chưa** dùng
> message tag, chưa outbound chủ động ngoài 24h, chưa one-time notification — **đừng** xin các
> quyền/tính năng đó trong lần nộp này (xin thừa = dễ bị hỏi khó → chậm duyệt). Nếu sau này làm
> follow-up/outbound (xem `docs/SALES-FLOW-CURRENT-STATE-VI.md` G2) thì nộp bổ sung riêng.

---

## 2. Xin đúng những quyền nào

| Quyền / tính năng | Cần cho việc gì trong Alpha3S | Mức cần | Nộp review? |
|---|---|---|---|
| **`pages_messaging`** | Nhận & gửi tin nhắn Messenger cho **khách bất kỳ** | **Advanced Access** | **Có — trọng tâm** |
| `pages_manage_metadata` | Đăng ký/subscribe webhook cho Page qua Graph API | Advanced Access | Có (thường xin kèm) |
| `pages_show_list` | Liệt kê Page mà tài khoản quản lý (bước lấy token) | Advanced Access | Có nếu flow cần |
| `pages_read_engagement` | Đọc thông tin/metadata Page | Advanced Access | Xin nếu thực dùng |
| User Profile (first/last name) | Xưng hô khách | **Đi kèm `pages_messaging`** | Không xin riêng |
| `human_agent` tag | (Tương lai) người thật trả lời ngoài 24h khi escalate | Advanced Access + BV | **Chưa nộp lần này** |

**Nguyên tắc:** chỉ xin **những gì đang thực sự gọi trong code**. Reviewer sẽ kiểm chứng bằng
screencast; xin quyền không demo được → từ chối.

---

## 3. Danh sách điều kiện tiên quyết (làm xong hết mới bấm Submit)

| # | Điều kiện | Trạng thái Alpha3S | Ai làm |
|---|---|---|---|
| P1 | App ở chế độ **Live** (không phải Development) khi mở khách thật | ⏳ chuyển sau khi được duyệt | Hoài |
| P2 | **Facebook Page đã publish** (không ẩn) | ✅ Page "3S Coffee" đang chạy | — |
| P3 | Webhook trả **200 trong ≤ 20s** cho sự kiện | ✅ < 100ms | (đã có) |
| P4 | **Business Verification** hoàn tất cho Robanme | ❌ **chưa** — xem §4 | Hoài |
| P5 | **Privacy Policy / Terms / Data Deletion URL** công khai | ✅ **trang đã dựng** (`/privacy`, `/terms`, `/data-deletion`) — chờ Hoài điền thông tin công ty thật + go-live — xem §5 | Code (xong), Hoài (điền + gắn URL) |
| P6 | **App Icon** (1024×1024) + **Category** | ⏳ kiểm tra trong App Settings | Hoài |
| P7 | Tên & thông tin liên hệ app hợp lệ, email nhận thông báo | ⏳ kiểm tra | Hoài |
| P8 | **Rotate `META_APP_SECRET` + `PAGE_ACCESS_TOKEN`** (#1) | ❌ **chưa** — secret cũ lộ git history | Hoài |
| P9 | Có **tài khoản test/quy trình** để reviewer nhắn thử | ⏳ chuẩn bị — xem §6 | Code + Hoài |
| P10 | Xử lý xung đột **khai báo bot tự động** (§7) | ✅ **đã sửa system prompt** (Hướng A) — Messenger bắt buộc khai báo, kênh khác khuyến nghị | Code (xong) |

> **Đường găng (critical path):** P4 (Business Verification) thường lâu nhất. **Nộp hồ sơ xác minh
> doanh nghiệp NGAY**, các việc còn lại (P5, P8, P9, P10) làm song song trong lúc chờ.

---

## 4. Xác minh doanh nghiệp (Business Verification) — làm sớm nhất

Advanced Access **bắt buộc** doanh nghiệp đã xác minh. Đây là thủ tục pháp lý, không code được.

**Cần chuẩn bị (cho Công ty Cổ phần Robanme):**
- Tên pháp lý + địa chỉ đăng ký khớp giấy tờ.
- **Giấy phép kinh doanh / Mã số thuế** (giấy tờ chính phủ chứng minh pháp nhân).
- Số điện thoại + email tên miền công ty (giúp xác minh nhanh hơn email cá nhân).
- Website chính thức (nên trùng tên miền `robanme.com`).

**Các bước (Meta Business Suite → Business Settings → Security Center / Business Verification):**
1. Tạo/chọn **Meta Business Portfolio** sở hữu app `robanme.com`.
2. Vào **Security Center** → bắt đầu **Verify business**.
3. Nhập thông tin pháp nhân, tải giấy tờ, chọn cách nhận mã xác minh (điện thoại/email/thư).
4. Chờ Meta duyệt (vài ngày → vài tuần). Theo dõi trạng thái tại Security Center.

> Nếu Robanme chưa có Business Portfolio, tạo trước; app phải nằm **trong** portfolio đó thì mới
> gắn được kết quả xác minh vào quyền Advanced Access.

---

## 5. Privacy Policy / Terms / Data Deletion — ✅ ĐÃ DỰNG, chờ điền thông tin thật

Meta **bắt buộc** các URL công khai. **Đã dựng cả 3 trang** trong repo (`app/api/legal.py`, đăng ký
ở `app/main.py`), phục vụ ngay tại API domain (Caddy đã proxy sẵn, HTTPS tự động):

| URL App Settings | Đường dẫn | Route |
|---|---|---|
| Privacy Policy URL | `https://a3s.robanme.com/privacy` | `GET /privacy` |
| Terms of Service URL | `https://a3s.robanme.com/terms` | `GET /terms` |
| User Data Deletion (Instructions URL) | `https://a3s.robanme.com/datadeletion` ⚠️ **không dấu `-`** | `GET /datadeletion` (alias) + `GET /data-deletion` |

> ⚠️ **Gotcha đã gặp thật:** ô "URL hướng dẫn xóa dữ liệu" của Meta **từ chối path có dấu `-`**
> (`/data-deletion` báo "name_placeholder should represent a valid URL" dù URL live 200, trong khi
> `/privacy` `/terms` cùng host vẫn qua). Đã thêm **alias `/datadeletion`** (không gạch ngang) — Meta
> chấp nhận. Dùng `https://a3s.robanme.com/datadeletion` cho ô này.

Đã kiểm tra cả 3 trả **200** với nội dung tiếng Việt đầy đủ. Trang **Chính sách bảo mật** khai báo
đúng dữ liệu thật thu thập (PSID, tên, nội dung hội thoại, và khi đặt hàng: tên–SĐT–địa chỉ), có nêu
rõ **gửi nội dung tin nhắn cho nhà cung cấp LLM (DeepSeek) để tạo câu trả lời** — điểm reviewer hay
soi. Trang **Xóa dữ liệu** hướng dẫn 2 cách: nhắn "XÓA DỮ LIỆU" tới Page hoặc email liên hệ.

> ⚠️ **Việc còn lại của Hoài (bắt buộc trước khi go-live):** mở `app/api/legal.py`, thay các
> **PLACEHOLDER trong dấu `[ ]`** bằng thông tin thật của Công ty CP Robanme — **địa chỉ ĐKKD, email
> liên hệ, số điện thoại** (tìm ký tự `[` để ra hết). Chỉnh `EFFECTIVE_DATE` nếu cần. Sau đó dán 3 URL
> trên vào **App Settings → Basic** (Privacy Policy, Terms of Service, User Data Deletion).

**Ô "Xóa dữ liệu người dùng" có 2 lựa chọn — cả 2 đã hiện thực, chọn 1 trong Meta:**

| Lựa chọn trong dropdown | URL đặt vào Meta | Cơ chế |
|---|---|---|
| URL hướng dẫn xóa dữ liệu | `https://a3s.robanme.com/datadeletion` | Trang hướng dẫn; khách nhắn "XÓA DỮ LIỆU" → bot hỏi xác nhận → "XÁC NHẬN XÓA" → **tự xóa ngay + báo đã xóa gì** (self-service, không cần nhân viên); hoặc email |
| **URL gọi lại (Callback)** — *khuyến nghị* | `https://a3s.robanme.com/datadeletion/callback` | Meta POST `signed_request` khi khách gỡ app → hệ thống **tự xác thực + xóa ngay** |

**Self-service qua chat (khách tự xóa, không cần nhân viên)** — deterministic trong `orchestrator.py`
(trước LLM): khách nhắn "XÓA DỮ LIỆU" → bot hỏi xác nhận (cờ Redis `del_pending` 15 phút) → khách nhắn
"XÁC NHẬN XÓA" → gọi `process_deletion(sender_id)` → xóa ngay + trả tin báo **liệt kê đã xóa gì** (số
tin nhắn, tên, số đơn ẩn danh) + mã + link tra cứu. Nhận diện keyword bỏ dấu 2 phía (bài học tiếng
Việt). Chạy trên MỌI kênh (Messenger/Telegram). Đã test E2E: bước 1 giữ nguyên dữ liệu, bước 2 xóa sạch.

**Callback (`POST /datadeletion/callback`)** — `app/services/data_deletion.py` + route trong `legal.py`:
xác thực `signed_request` bằng `META_APP_SECRET` (HMAC-SHA256), lấy PSID, rồi trong 1 transaction:
**xóa hẳn** messages/escalations/conversations, **ẩn danh** đơn hàng (bỏ tên/SĐT/địa chỉ, giữ đơn cho
kế toán), **ẩn danh** customer (đổi `psid → deleted:<code>`), **xóa** cache Redis `chat:`/`profile:`.
Trả `{url, confirmation_code}`; khách tra tại `GET /datadeletion/status?code=`. Đã test E2E: xóa đúng,
chữ ký sai → HTTP 400. Lưu yêu cầu ở bảng `data_deletion_requests` (**migration 013**).

> ⚠️ **Deploy:** migration `013_data_deletion_requests.sql` **KHÔNG tự chạy** trên VPS (initdb chỉ
> chạy lúc tạo volume) — sau khi push, phải chạy tay trên DB VPS **trước khi** bật callback (thiếu
> bảng → callback 500). Lệnh ở §9.

---

## 6. Quy trình nộp trên App Dashboard (từng bước)

Vào **developers.facebook.com → App `robanme.com` → App Review → Permissions and Features**.

### 6.1. Chuẩn bị nội dung mô tả (copy-paste, chỉnh cho khớp thực tế)

**Use case của `pages_messaging`** (điền vào ô "Tell us how you'll use this permission"):

> Our app powers an automated customer-service and sales assistant for the "3S Coffee" Facebook
> Page (a Vietnamese cold-brew coffee brand operated by Robanme JSC). When a customer sends a
> message to the Page, our webhook receives the event and our assistant replies within the
> standard 24-hour messaging window using the Send API (messaging_type: RESPONSE) to answer
> product questions, check stock, and take orders. We use the User Profile API only to retrieve
> the customer's first and last name so the assistant can address them politely in Vietnamese. We
> do not send promotional or outbound messages outside the 24-hour window. Conversations that the
> assistant cannot handle are handed off to a human staff member.

**Vì sao cần Advanced Access:**
> Advanced Access is required because real customers who message the "3S Coffee" Page are not
> users, testers, or admins of our app, and Standard Access does not allow the app to receive or
> reply to their messages.

### 6.2. Quay screencast (bắt buộc)

Reviewer cần thấy **quyền được dùng thật, từ góc người dùng cuối**. Kịch bản đề xuất (~2–3 phút,
có thuyết minh/caption tiếng Anh):
1. Mở fanpage "3S Coffee" trên Messenger **bằng một tài khoản KHÔNG có role trên app** (đóng vai
   khách thật).
2. Gửi câu hỏi sản phẩm → quay cảnh bot trả lời (chứng minh `pages_messaging` + Send API).
3. Hỏi tồn kho / đặt thử 1 đơn → bot phản hồi (thể hiện luồng đủ nghĩa, không phải echo).
4. (Nếu để lộ tên) minh hoạ bot xưng hô đúng tên khách (User Profile).
5. Cho thấy màn hình cấu hình webhook (Callback URL `https://a3s.robanme.com/webhook`,
   fields `messaging`) để chứng minh tích hợp thật.
6. **Nếu đã thêm khai báo bot (§7):** quay rõ câu mở đầu bot tự nhận là trợ lý tự động.

> Video **không cần lộ token/secret**. Nếu quay màn hình App Dashboard, che các trường nhạy cảm.

### 6.3. Hướng dẫn cho reviewer (ô "Instructions")

- App gated: Yes. Trigger: **nhắn tin trực tiếp cho Page "3S Coffee" trên Messenger**.
- Cung cấp **link m.me/Page** + vài câu mẫu để reviewer thử: hỏi sản phẩm, hỏi giá, đặt đơn.
- Ghi rõ bot trả lời **tiếng Việt** (reviewer có thể dùng các câu mẫu tiếng Việt bạn cung cấp).
- Nếu reviewer cần được thêm quyền nhắn (app còn Dev mode lúc review), nêu cách hoặc để họ dùng
  chức năng test.

### 6.4. Submit

Kiểm P1–P10 (§3) xong → chọn các quyền ở §2 → đính screencast + mô tả + instructions → **Submit
for review**. Sau khi được duyệt, **bật app sang Live** rồi mới mở webhook cho khách thật.

---

## 7. Khai báo bot tự động — ✅ ĐÃ XỬ LÝ (Hướng A)

> **Đã triển khai (24/07/2026):** chọn **Hướng A**. Sửa `app/prompts/system_prompt.md`: đổi định vị
> thành "trợ lý tư vấn tự động", thêm mục **"Khai báo là trợ lý tự động"** (tin đầu phiên phải có
> một câu tự nhiên tự nhận là trợ lý tự động + sẽ chuyển nhân viên khi cần; hỏi thẳng thì trả lời
> trung thực), gỡ mâu thuẫn ở phần danh xưng/markdown. **Đa kênh (theo yêu cầu):** thêm tham số
> `channel` tường minh vào `orchestrator.handle_message()` (Messenger/Telegram tự truyền), hệ thống
> bơm mục "Boi canh phien hien tai" (kênh + có phải tin đầu + mức khai báo). **Messenger = BẮT BUỘC**
> khai báo; **Telegram/Zalo/web = KHUYẾN NGHỊ** (dễ nâng lên bắt buộc: thêm kênh vào
> `DISCLOSURE_REQUIRED_CHANNELS`). Việc còn lại: screencast phải quay rõ câu khai báo ở tin đầu.

Bối cảnh gốc (để hiểu vì sao phải sửa):

**Yêu cầu Meta (và luật CA/Đức):** trải nghiệm tự động phải **cho người dùng biết họ đang nói
chuyện với dịch vụ tự động** — ít nhất ở **đầu luồng hội thoại**, sau thời gian gián đoạn dài, và
khi chuyển từ người sang bot. Đây là **lý do bị từ chối phổ biến** với chatbot.

**Hiện trạng Alpha3S (mâu thuẫn):** `app/prompts/system_prompt.md` (dòng ~3, 9–10) mô tả bot là
**"chuyên viên tư vấn của 3S Coffee"** và coi việc **khách nhận ra đang nói chuyện với bot là "lỗi
UX nghiêm trọng nhất"**. Nghĩa là bot đang **cố tình che** bản chất tự động — ngược với yêu cầu
Meta. UAT-094 có quy tắc "không giả danh người thật" khi *bị hỏi thẳng*, nhưng Meta đòi **chủ động
khai báo**, không chỉ khi bị hỏi.

**Cần quyết (Hoài) + sửa (Code) một trong hai hướng:**
- **Hướng A (khuyến nghị, an toàn với Meta):** thêm câu khai báo tự động **một lần** ở đầu hội
  thoại/lời chào, kiểu *"Em là trợ lý tự động của 3S Coffee, khi cần em sẽ chuyển anh/chị cho nhân
  viên ạ."* Vẫn giữ giọng thân thiện, xưng "em". Chỉnh `system_prompt.md` + (nếu có) Get Started/
  greeting text. Screencast phải cho thấy câu này.
- **Hướng B (rủi ro):** giữ nguyên "nói như người thật" → **khả năng cao bị reject** và, nếu lách
  qua được, vẫn vi phạm chính sách khi vận hành thật (rủi ro bị khoá về sau).

> Đây là điểm **must-fix** trước khi quay screencast, vì video là bằng chứng reviewer soi kỹ nhất.

---

## 8. Các lý do bị từ chối thường gặp & trạng thái Alpha3S

| Lý do reject phổ biến | Alpha3S | Hành động |
|---|---|---|
| Không khai báo là dịch vụ tự động | ❌ đang che (§7) | **Sửa system prompt (Hướng A)** |
| Xin quyền không demo được trong screencast | ⚠️ tránh xin thừa | Chỉ xin §2, demo từng quyền |
| Thiếu/lỗi Privacy Policy URL | ❌ chưa có (§5) | Tạo `/privacy` |
| Chưa Business Verification | ❌ chưa (§4) | Nộp sớm |
| Screencast không rõ hành vi thật / chỉ nói lý thuyết | — | Quay flow thật end-to-end |
| Bot chỉ echo, không có giá trị thật | ✅ có tool bán hàng thật | Demo hỏi giá + đặt đơn |
| Webhook chậm / rớt sự kiện | ✅ < 100ms, enqueue Redis | (đã đạt) |
| Page chưa publish | ✅ đã publish | — |

**Chính sách vận hành cần nhớ (không phải điều kiện nộp nhưng dễ dính khi chạy thật):**
- **Cửa sổ 24h:** ngoài 24h kể từ tin cuối của khách, **không** được nhắn tự do — phải dùng message
  tag hợp lệ (chưa xin → **đừng làm outbound ngoài 24h** cho tới khi nộp bổ sung).
- Các tag `CONFIRMED_EVENT_UPDATE`, `ACCOUNT_UPDATE`, `POST_PURCHASE_UPDATE` **đã bị bỏ từ 4/2026**
  — nếu sau này làm follow-up, **không** dùng các tag này (gọi sẽ lỗi).

---

## 9. Phân vai & thứ tự thực thi

**Anh Hoài (thủ công trên Meta — không tự động hoá được):**
1. **[Ngay]** Khởi động **Business Verification** cho Robanme (§4) — đường găng.
2. **[Ngay]** **Rotate** `META_APP_SECRET` + `PAGE_ACCESS_TOKEN` (#1), cập nhật `.env` VPS, redeploy.
3. **[Quyết]** Chọn Hướng A/B cho khai báo bot (§7).
4. Bổ sung App Icon, Category, contact email, Privacy Policy URL vào App Settings.
5. **[Sau khi push code callback]** Chạy migration 013 trên DB VPS **trước khi** chọn callback URL:
   ```bash
   docker compose exec -T db psql -U alpha3s -d alpha3s < migrations/013_data_deletion_requests.sql
   ```
   Rồi đặt ô "Xóa dữ liệu người dùng" = **URL gọi lại** `https://a3s.robanme.com/datadeletion/callback`
   (khuyến nghị) hoặc **URL hướng dẫn** `https://a3s.robanme.com/datadeletion` (§5).
6. Điền use case + upload screencast + instructions → **Submit** (§6). Sau duyệt: bật **Live**.

**Claude Code:**
1. ✅ **Xong** — dựng 3 trang `/privacy`, `/terms`, `/data-deletion` (`app/api/legal.py` + `main.py`),
   đã kiểm 200. (Chờ Hoài điền placeholder + gắn URL.)
2. ✅ **Xong** — sửa `system_prompt.md` (Hướng A) + tham số `channel` tường minh trong
   `orchestrator.py`/`tasks.py`/`telegram_customer_listener.py` (§7).
3. (Nếu cần) chuẩn bị **Get Started / greeting text** qua Messenger Profile API
   (`app/services/messenger_profile.py` đã có sẵn client Graph — mở rộng thêm).
4. Soạn **bộ câu mẫu tiếng Việt** cho reviewer thử + kịch bản screencast chi tiết.
5. ✅ Đã cập nhật `ISSUES-VI.md`/`ISSUES-EN.md` #9 + tài liệu này.

---

## 10. Tham chiếu

- `ISSUES-VI.md` — #1 (rotate secret Meta), #9 (mục treo "Meta App review", "rotate secret Meta").
- `docs/VPS-RUNBOOK-VI.md` §Cutover — cấu hình webhook Meta, Callback URL, subscribe field.
- `docs/SALES-FLOW-CURRENT-STATE-VI.md` — hành vi bot thật, khoảng trống outbound (G2) & 24h policy.
- `app/api/webhook.py`, `app/services/messenger.py`, `app/services/messenger_profile.py` — mã tích hợp Meta.
- `app/prompts/system_prompt.md` — nơi phải sửa cho §7.
- Nguồn ngoài (đã xác minh 24/07/2026):
  - [Meta — Permissions Reference](https://developers.facebook.com/docs/permissions/)
  - [Meta — Messenger App Review](https://developers.facebook.com/docs/messenger-platform/app-review/)
  - [Meta Advanced Access — permissions cần App Review](https://singhamandeep.com/what-is-meta-advanced-access/)
  - [Messenger Bot App Review — vì sao chatbot bị từ chối (2026)](https://singhamandeep.com/facebook-messenger-bot-app-review-chatbot-saas/)
