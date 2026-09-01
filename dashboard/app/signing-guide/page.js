"use client";

// Trang huong dan (runbook) — ngon ngu doi thuong, khong thuat ngu ky thuat. Noi dung TINH
// (khong API/permission/secret). "Niem phong" = dong dau dien tu chong sua trom, KHONG phai
// khoa/giau noi dung (khong phai encryption). CA Addendum 97.

import { useAuthGuard } from "../../lib/useAuthGuard";

const box = { border: "1px solid #e5e7eb", borderRadius: 8, padding: 16, marginTop: 14, background: "#fff" };
const li = { marginBottom: 6 };

export default function SigningGuidePage() {
  const ready = useAuthGuard();
  if (!ready) return null;
  return (
    <main style={{ padding: 24, maxWidth: 820 }}>
      <h1>Hướng dẫn niêm phong hội thoại</h1>

      <div style={box}>
        <h3>“Niêm phong” là gì?</h3>
        <p style={{ fontSize: 15, lineHeight: 1.7 }}>
          Là <b>đóng dấu điện tử</b> lên một cuộc hội thoại đã lưu, mục đích <b>bảo toàn dữ liệu</b>. Nếu dữ
          liệu bị sửa, sẽ <b>để lại dấu vết và bị phát hiện</b>. <b>Người niêm phong</b> và <b>thời điểm niêm
          phong</b> cũng được ghi lại.
        </p>
        <p style={{ fontSize: 14.5, lineHeight: 1.7 }}>
          Việc này nhằm bảo vệ dữ liệu khách hàng và phục vụ tuân thủ <b>Nghị định 13/2023/NĐ-CP về bảo vệ
          dữ liệu cá nhân</b> (yêu cầu bảo đảm <b>an toàn</b> và <b>tính toàn vẹn</b> của dữ liệu).
        </p>
        <p style={{ fontSize: 13, color: "#6b7280" }}>
          Lưu ý: niêm phong <b>không phải khóa/giấu</b> nội dung — vẫn xem được; nó chỉ <b>chống bị sửa</b>.
        </p>
      </div>

      <div style={box}>
        <h3>Làm theo 2 bước</h3>
        <p style={{ fontSize: 15, margin: "4px 0" }}><b>Bước 1 — Mở phiên niêm phong</b> (xin phép)</p>
        <ul style={{ fontSize: 14.5, lineHeight: 1.6, marginTop: 4 }}>
          <li style={li}>Người ký gửi yêu cầu: chọn hội thoại cần niêm phong + thời hạn.</li>
          <li style={li}><b>Người phụ trách duyệt</b> — phải là người <b>khác</b> người ký (2 người cùng kiểm cho chắc).</li>
          <li style={li}>Được duyệt → người ký có <b>quyền tạm thời, có thời hạn</b> (ví dụ 30 phút).</li>
        </ul>
        <p style={{ fontSize: 15, margin: "10px 0 4px" }}><b>Bước 2 — Thực hiện niêm phong</b> (đóng dấu)</p>
        <ul style={{ fontSize: 14.5, lineHeight: 1.6, marginTop: 4 }}>
          <li style={li}>Trong thời hạn đó, vào mục <b>“Thực hiện niêm phong”</b> để đóng dấu lên hội thoại.</li>
          <li style={li}>Xong → quyền <b>tự hết hạn</b>, không cần thu hồi tay.</li>
        </ul>
      </div>

      <div style={box}>
        <h3>Vài điều cần nhớ</h3>
        <ul style={{ fontSize: 14.5, lineHeight: 1.6 }}>
          <li style={li}><b>Không nhập mật khẩu / mã bí mật</b> ở đây — chìa khóa được giữ an toàn ở nơi khác.</li>
          <li style={li}><b>Hai người khác nhau:</b> người ký ≠ người duyệt.</li>
          <li style={li}><b>Có thời hạn:</b> quyền chỉ dùng trong khoảng thời gian đã cấp, sau đó tự mất.</li>
          <li style={li}><b>Mọi thao tác đều được ghi lại</b> (không sửa/xóa được) để tra cứu sau.</li>
          <li style={li}>Thiếu điều kiện → hệ thống <b>tự động từ chối</b> (cho an toàn).</li>
        </ul>
      </div>

      <div style={box}>
        <h3>Muốn thử trước?</h3>
        <p style={{ fontSize: 14.5, lineHeight: 1.7 }}>
          Bật <b>“Chế độ thử”</b> khi gửi yêu cầu → bạn đi hết quy trình để làm quen, <b>mà không niêm phong
          thật và không đụng dữ liệu của khách</b>.
        </p>
      </div>

      <p style={{ fontSize: 13, color: "#6b7280", marginTop: 16 }}>
        Hiện tính năng đã sẵn sàng nhưng <b>đang tạm nghỉ</b> — chưa bật niêm phong thật. Việc niêm phong hội
        thoại thật của khách cần <b>người phụ trách quyết định</b> và bật riêng.
      </p>
    </main>
  );
}
