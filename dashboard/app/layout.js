import "./globals.css";
import NavUser from "./components/NavUser";

// BẮT BUỘC cho nonce-CSP (CA-REVIEW-M0-DEV-004 §5): ép mọi route dashboard render động per-request để
// Next 14 gắn nonce (đọc từ CSP request header ở middleware) vào MỌI <script> (bootstrap inline RSC +
// external chunk). Trang static-optimized KHÔNG nhận nonce/request -> 'strict-dynamic' chặn -> hydration
// vỡ (login không hiện). Dashboard là công cụ nội bộ traffic thấp -> bỏ static optimization chấp nhận được.
export const dynamic = "force-dynamic";

export const metadata = {
  title: "3S Coffee - Dashboard",
  description: "Dashboard quan tri fanpage 3S Coffee",
};

export default function RootLayout({ children }) {
  return (
    <html lang="vi">
      <body>
        <nav className="topnav">
          <span className="brand">3S Coffee</span>
          <a href="/conversations">Hội thoại</a>
          <a href="/orders">Đơn hàng</a>
          <a href="/products">Sản phẩm</a>
          <a href="/faq">FAQ</a>
          <a href="/metrics">Metrics</a>
          <a href="/ops">Vận hành</a>
          <a href="/staff">Nhân viên</a>
          <NavUser />
        </nav>
        <main className="container">{children}</main>
      </body>
    </html>
  );
}
