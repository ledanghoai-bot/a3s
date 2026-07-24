"""Trang phap ly cong khai (khong can dang nhap) phuc vu Meta App Review.

Meta bat buoc 3 URL cong khai trong App Settings:
- Privacy Policy URL        -> GET /privacy
- Terms of Service URL      -> GET /terms
- User Data Deletion URL    -> GET /data-deletion  (dang "Data Deletion Instructions URL")

Cac trang nay PHAI truy cap duoc khong can dang nhap (reviewer Meta va khach mo
truc tiep). Caddy da proxy {$DOMAIN} -> api:8000 nen tu phuc vu tai:
  https://a3s.robanme.com/privacy | /terms | /data-deletion

⚠️ CHO ANH HOAI: cac gia tri trong dau [] la PLACEHOLDER phai dien thong tin THAT
(dia chi DKKD, email, SDT, MST...) TRUOC KHI submit App Review. Tim chuoi "[" de ra
het cho can dien. Ngay hieu luc mac dinh 24/07/2026 - doi neu can.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

# ---- Thong tin phap nhan (SUA cho khop giay to that truoc khi go live) ----
BRAND = "3S Coffee"
COMPANY = "Công ty Cổ phần Robanme"
CONTACT_EMAIL = "3scoffee.cs@gmail.com"
CONTACT_PHONE = "0947273235"
COMPANY_ADDRESS = "31 Mai Thị Lựu - Phường Ea Kao - Đắk Lắk - Việt Nam"
PAGE_NAME = "3S Coffee"
EFFECTIVE_DATE = "24/07/2026"
DELETE_KEYWORD = "XÓA DỮ LIỆU"

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  line-height: 1.65; color: #1a1a1a; background: #fafafa;
}
.wrap { max-width: 760px; margin: 0 auto; padding: 32px 20px 64px; }
header { border-bottom: 2px solid #6f4e37; padding-bottom: 16px; margin-bottom: 8px; }
header .brand { font-size: 20px; font-weight: 700; color: #6f4e37; }
header .co { font-size: 14px; color: #666; }
h1 { font-size: 26px; margin: 24px 0 4px; }
.updated { color: #888; font-size: 14px; margin-bottom: 24px; }
h2 { font-size: 19px; margin: 32px 0 8px; color: #6f4e37; }
p, li { font-size: 16px; }
ul { padding-left: 22px; }
a { color: #6f4e37; }
.note {
  background: #fff6e6; border: 1px solid #e6c98a; border-radius: 8px;
  padding: 12px 16px; margin: 16px 0; font-size: 15px;
}
nav.legal { margin-top: 40px; padding-top: 16px; border-top: 1px solid #ddd; font-size: 14px; }
nav.legal a { margin-right: 16px; }
footer { margin-top: 24px; color: #999; font-size: 13px; }
@media (prefers-color-scheme: dark) {
  body { color: #e6e6e6; background: #161513; }
  header .co, .updated { color: #aaa; }
  .note { background: #2a2419; border-color: #5a4a2a; }
  a, header .brand, h2 { color: #d3a56b; }
  nav.legal { border-color: #333; }
}
"""


def _page(title: str, body: str) -> HTMLResponse:
    html = f"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{title} — {BRAND}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="brand">☕ {BRAND}</div>
  <div class="co">{COMPANY}</div>
</header>
{body}
<nav class="legal">
  <a href="/privacy">Chính sách bảo mật</a>
  <a href="/terms">Điều khoản dịch vụ</a>
  <a href="/data-deletion">Xóa dữ liệu người dùng</a>
</nav>
<footer>© {EFFECTIVE_DATE[-4:]} {COMPANY}. Mọi thắc mắc: {CONTACT_EMAIL}.</footer>
</div>
</body>
</html>"""
    return HTMLResponse(content=html)


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_policy() -> HTMLResponse:
    body = f"""
<h1>Chính sách bảo mật</h1>
<p class="updated">Ngày hiệu lực: {EFFECTIVE_DATE}</p>

<p>{COMPANY} ("chúng tôi") vận hành trợ lý tự động {BRAND} trên Facebook Messenger
(trang "{PAGE_NAME}") và các kênh nhắn tin khác. Chính sách này giải thích chúng tôi
thu thập, sử dụng, lưu trữ và bảo vệ dữ liệu cá nhân của bạn như thế nào khi bạn nhắn
tin với chúng tôi.</p>

<h2>1. Dữ liệu chúng tôi thu thập</h2>
<ul>
  <li><strong>Định danh nền tảng:</strong> mã người dùng do Messenger cung cấp (PSID) —
      không phải số điện thoại hay email Facebook của bạn.</li>
  <li><strong>Tên hiển thị:</strong> họ và tên trên hồ sơ Messenger của bạn, dùng để
      xưng hô lịch sự. Chúng tôi <strong>không</strong> thu thập ảnh đại diện, giới tính,
      danh sách bạn bè hay bài đăng của bạn.</li>
  <li><strong>Nội dung hội thoại:</strong> tin nhắn bạn gửi cho trợ lý và câu trả lời
      của trợ lý.</li>
  <li><strong>Thông tin đặt hàng (chỉ khi bạn chủ động đặt hàng):</strong> tên người
      nhận, số điện thoại, địa chỉ giao hàng, sản phẩm và số lượng.</li>
</ul>

<h2>2. Cách chúng tôi sử dụng dữ liệu</h2>
<ul>
  <li>Tư vấn sản phẩm, trả lời câu hỏi và tiếp nhận đơn hàng của bạn.</li>
  <li>Xưng hô đúng và duy trì mạch hội thoại tự nhiên.</li>
  <li>Chuyển cho nhân viên hỗ trợ khi trợ lý tự động không xử lý được yêu cầu của bạn.</li>
  <li>Xử lý và giao đơn hàng bạn đã đặt.</li>
</ul>
<p>Chúng tôi <strong>không</strong> dùng dữ liệu của bạn để quảng cáo nhắm mục tiêu và
<strong>không</strong> bán dữ liệu cho bên thứ ba.</p>

<h2>3. Chia sẻ với bên thứ ba</h2>
<ul>
  <li><strong>Meta Platforms (Facebook/Messenger):</strong> việc nhắn tin diễn ra trên
      hạ tầng của Meta và tuân theo
      <a href="https://www.facebook.com/privacy/policy/" target="_blank" rel="noopener">Chính sách quyền riêng tư của Meta</a>.</li>
  <li><strong>Nhà cung cấp mô hình ngôn ngữ (AI):</strong> để tạo câu trả lời, nội dung
      tin nhắn của bạn được gửi tới một nhà cung cấp mô hình ngôn ngữ (DeepSeek) xử lý.
      Chúng tôi chỉ gửi nội dung cần thiết cho việc trả lời.</li>
  <li><strong>Đơn vị vận chuyển:</strong> khi bạn đặt hàng, thông tin giao hàng có thể
      được chia sẻ với đối tác vận chuyển để giao đơn.</li>
</ul>

<h2>4. Lưu trữ dữ liệu</h2>
<ul>
  <li>Dữ liệu được lưu trên máy chủ do chúng tôi kiểm soát (đặt tại Việt Nam).</li>
  <li>Tên hồ sơ được lưu tạm (cache) tối đa 7 ngày; lịch sử hội thoại gần nhất giữ tạm
      khoảng 24 giờ để duy trì ngữ cảnh.</li>
  <li>Bản ghi hội thoại và đơn hàng được lưu phục vụ chăm sóc khách hàng và nghĩa vụ
      kế toán/pháp lý, cho tới khi bạn yêu cầu xóa (xem mục 6).</li>
</ul>

<h2>5. Bảo mật</h2>
<p>Kết nối tới hệ thống của chúng tôi được mã hóa qua HTTPS. Chúng tôi áp dụng các biện
pháp kỹ thuật và quản trị hợp lý để bảo vệ dữ liệu khỏi truy cập trái phép.</p>

<h2>6. Quyền của bạn &amp; xóa dữ liệu</h2>
<p>Bạn có quyền yêu cầu xem, chỉnh sửa hoặc xóa dữ liệu cá nhân của mình. Xem hướng dẫn
xóa dữ liệu tại <a href="/data-deletion">trang Xóa dữ liệu người dùng</a>, hoặc liên hệ
{CONTACT_EMAIL}.</p>

<h2>7. Trẻ em</h2>
<p>Dịch vụ không hướng tới người dưới 16 tuổi. Chúng tôi không cố ý thu thập dữ liệu của
trẻ em; nếu phát hiện, chúng tôi sẽ xóa.</p>

<h2>8. Thay đổi chính sách</h2>
<p>Chúng tôi có thể cập nhật chính sách này. Bản mới sẽ được đăng tại trang này kèm ngày
hiệu lực mới.</p>

<h2>9. Liên hệ</h2>
<p>{COMPANY}<br>
Địa chỉ: {COMPANY_ADDRESS}<br>
Email: {CONTACT_EMAIL}<br>
Điện thoại: {CONTACT_PHONE}</p>
"""
    return _page("Chính sách bảo mật", body)


@router.get("/terms", response_class=HTMLResponse)
async def terms_of_service() -> HTMLResponse:
    body = f"""
<h1>Điều khoản dịch vụ</h1>
<p class="updated">Ngày hiệu lực: {EFFECTIVE_DATE}</p>

<p>Điều khoản này áp dụng khi bạn tương tác với trợ lý tự động {BRAND} do {COMPANY} vận
hành trên Facebook Messenger và các kênh nhắn tin khác. Khi tiếp tục nhắn tin, bạn đồng ý
với các điều khoản dưới đây.</p>

<h2>1. Mô tả dịch vụ</h2>
<p>{BRAND} cung cấp một <strong>trợ lý tự động (chatbot)</strong> giúp tư vấn sản phẩm cà
phê, giải đáp thắc mắc và tiếp nhận đơn hàng. Trợ lý là hệ thống tự động; khi cần, hội
thoại sẽ được chuyển cho nhân viên hỗ trợ.</p>

<h2>2. Đơn hàng &amp; xác nhận</h2>
<ul>
  <li>Đơn đặt qua trợ lý được ghi nhận ở trạng thái chờ và <strong>chỉ hoàn tất khi được
      chúng tôi xác nhận</strong> (qua tin nhắn hoặc điện thoại).</li>
  <li>Giá, khuyến mãi và tình trạng còn hàng có thể thay đổi; giá áp dụng là giá tại thời
      điểm chúng tôi xác nhận đơn.</li>
  <li>Bạn chịu trách nhiệm cung cấp thông tin giao hàng chính xác.</li>
</ul>

<h2>3. Sử dụng hợp lệ</h2>
<p>Bạn đồng ý không dùng dịch vụ để gửi nội dung trái pháp luật, quấy rối, lừa đảo, phá
hoại hệ thống hoặc mạo danh người khác.</p>

<h2>4. Tính chính xác của thông tin tự động</h2>
<p>Trợ lý tự động có thể đưa ra thông tin chưa đầy đủ hoặc sai sót. Các thông tin quan
trọng (giá, tồn kho, chính sách) sẽ được nhân viên xác nhận. Nội dung về sức khỏe chỉ
mang tính tham khảo, <strong>không thay thế tư vấn y tế</strong> chuyên môn.</p>

<h2>5. Sở hữu trí tuệ</h2>
<p>Thương hiệu, nội dung và tài liệu của {BRAND} thuộc quyền sở hữu của {COMPANY}. Không
sao chép, sử dụng cho mục đích thương mại khi chưa được cho phép.</p>

<h2>6. Giới hạn trách nhiệm</h2>
<p>Dịch vụ được cung cấp "nguyên trạng". Trong phạm vi pháp luật cho phép, chúng tôi
không chịu trách nhiệm cho thiệt hại gián tiếp phát sinh từ việc sử dụng trợ lý tự động,
ngoài giá trị đơn hàng liên quan.</p>

<h2>7. Chấm dứt</h2>
<p>Chúng tôi có thể tạm ngừng phục vụ tài khoản có hành vi vi phạm điều khoản này.</p>

<h2>8. Luật áp dụng</h2>
<p>Điều khoản này được điều chỉnh bởi pháp luật Việt Nam.</p>

<h2>9. Thay đổi điều khoản</h2>
<p>Chúng tôi có thể cập nhật điều khoản; bản mới đăng tại trang này kèm ngày hiệu lực mới.</p>

<h2>10. Liên hệ</h2>
<p>{COMPANY}<br>
Địa chỉ: {COMPANY_ADDRESS}<br>
Email: {CONTACT_EMAIL}<br>
Điện thoại: {CONTACT_PHONE}</p>
"""
    return _page("Điều khoản dịch vụ", body)


@router.get("/data-deletion", response_class=HTMLResponse)
async def data_deletion() -> HTMLResponse:
    body = f"""
<h1>Xóa dữ liệu người dùng</h1>
<p class="updated">Ngày hiệu lực: {EFFECTIVE_DATE}</p>

<p>Bạn có quyền yêu cầu xóa dữ liệu cá nhân mà {COMPANY} đã lưu khi bạn nhắn tin với trợ
lý tự động {BRAND}. Trang này hướng dẫn cách yêu cầu.</p>

<h2>Dữ liệu sẽ được xóa</h2>
<ul>
  <li>Mã người dùng Messenger (PSID) và tên hồ sơ đã lưu tạm.</li>
  <li>Toàn bộ nội dung hội thoại giữa bạn và trợ lý.</li>
  <li>Thông tin cá nhân trong đơn hàng (tên, số điện thoại, địa chỉ) — trừ phần bắt buộc
      phải lưu theo nghĩa vụ kế toán/pháp lý, khi đó sẽ được ẩn danh.</li>
</ul>

<h2>Cách yêu cầu xóa dữ liệu</h2>
<p>Chọn một trong hai cách:</p>
<ol>
  <li><strong>Qua Messenger:</strong> nhắn cụm từ <strong>"{DELETE_KEYWORD}"</strong> tới
      trang "{PAGE_NAME}". Trợ lý sẽ chuyển yêu cầu tới nhân viên để xử lý.</li>
  <li><strong>Qua email:</strong> gửi email tới {CONTACT_EMAIL} với tiêu đề
      "Yêu cầu xóa dữ liệu", kèm tên hiển thị Messenger để chúng tôi xác định đúng hồ sơ.</li>
</ol>

<div class="note">
Để bảo vệ bạn, chúng tôi có thể cần xác minh bạn chính là chủ hồ sơ trước khi xóa (ví dụ
xác nhận từ chính tài khoản Messenger đã nhắn tin).
</div>

<h2>Thời gian xử lý</h2>
<p>Yêu cầu hợp lệ sẽ được xử lý trong vòng <strong>30 ngày</strong>. Sau khi hoàn tất,
chúng tôi sẽ thông báo cho bạn.</p>

<h2>Sau khi xóa</h2>
<p>Dữ liệu đã xóa không thể khôi phục. Nếu sau này bạn tiếp tục nhắn tin, một hồ sơ mới sẽ
được tạo lại theo Chính sách bảo mật hiện hành.</p>

<h2>Liên hệ</h2>
<p>{COMPANY}<br>
Email: {CONTACT_EMAIL}<br>
Điện thoại: {CONTACT_PHONE}</p>
"""
    return _page("Xóa dữ liệu người dùng", body)


# Alias KHONG co dau gach ngang: o "URL huong dan xoa du lieu" cua Meta tu choi
# path co dau '-' (bao "name_placeholder should represent a valid URL") du URL
# live 200 - /privacy va /terms cung host van qua. Phuc vu y het /data-deletion.
@router.get("/datadeletion", response_class=HTMLResponse)
async def data_deletion_alias() -> HTMLResponse:
    return await data_deletion()
