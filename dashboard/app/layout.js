import "./globals.css";

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
        </nav>
        <main className="container">{children}</main>
      </body>
    </html>
  );
}
