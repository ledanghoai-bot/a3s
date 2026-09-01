"use client";

// Trang huong dan niem phong hoi thoai. MOT canonical page (CA Guidance 99), 2 tab in-page:
//  - "Co ban": ngon ngu doi thuong cho nguoi dung cuoi (CA Addendum 97).
//  - "Huong dan chuyen sau": noi dung handover van hanh 8 muc (CA Guidance 99), da chinh mem
//    mot phan thuat ngu. Noi dung TINH — khong API/permission/secret/PIN/token/private key/
//    credential path/lenh production cu the/du lieu khach. Quyen that do backend + Activation
//    Gate enforce; trang chi huong dan.

import { useState } from "react";
import { useAuthGuard } from "../../lib/useAuthGuard";

const box = { border: "1px solid #e5e7eb", borderRadius: 8, padding: 16, marginTop: 14, background: "#fff" };
const li = { marginBottom: 6 };
const th = { textAlign: "left", padding: "6px 8px", borderBottom: "2px solid #e5e7eb", fontSize: 13.5 };
const td = { padding: "6px 8px", borderBottom: "1px solid #f1f5f9", fontSize: 13.5, verticalAlign: "top" };

function tabBtn(active) {
  return {
    padding: "8px 16px", border: "1px solid #e5e7eb", borderBottom: active ? "2px solid #2563eb" : "1px solid #e5e7eb",
    background: active ? "#fff" : "#f8fafc", color: active ? "#2563eb" : "#475569", fontWeight: active ? 600 : 400,
    borderRadius: "8px 8px 0 0", cursor: "pointer", marginRight: 6, fontSize: 14,
  };
}

export default function SigningGuidePage() {
  const ready = useAuthGuard();
  const [tab, setTab] = useState("basic");
  if (!ready) return null;
  return (
    <main style={{ padding: 24, maxWidth: 860 }}>
      <h1>Hướng dẫn niêm phong hội thoại</h1>

      <div style={{ display: "flex", marginTop: 8, borderBottom: "1px solid #e5e7eb" }}>
        <button style={tabBtn(tab === "basic")} onClick={() => setTab("basic")}>Cơ bản</button>
        <button style={tabBtn(tab === "deep")} onClick={() => setTab("deep")}>Hướng dẫn chuyên sâu</button>
      </div>

      {tab === "basic" ? <BasicGuide /> : <DeepGuide />}

      <p style={{ fontSize: 13, color: "#6b7280", marginTop: 16 }}>
        Hiện tính năng đã sẵn sàng nhưng <b>đang tạm nghỉ</b> — chưa bật niêm phong thật. Việc niêm phong hội
        thoại thật của khách cần <b>người phụ trách quyết định</b> và bật riêng.
      </p>
      <p style={{ fontSize: 12.5, color: "#94a3b8", marginTop: 6 }}>
        Trang này chỉ để <b>hướng dẫn</b>. Có hướng dẫn không đồng nghĩa có quyền — quyền thực tế do hệ thống
        và bước “bật quyền ký” quyết định.
      </p>
    </main>
  );
}

function BasicGuide() {
  return (
    <>
      <div style={box}>
        <h3>“Niêm phong” là gì?</h3>
        <p style={{ fontSize: 15, lineHeight: 1.7 }}>
          Là <b>đóng dấu điện tử</b> lên một cuộc hội thoại đã lưu, mục đích <b>bảo toàn dữ liệu</b>. Nếu dữ
          liệu bị sửa, sẽ <b>để lại dấu vết và bị phát hiện</b>. <b>Người niêm phong</b> và <b>thời điểm niêm
          phong</b> cũng được ghi lại.
        </p>
        <p style={{ fontSize: 14.5, lineHeight: 1.7 }}>
          Việc này <b>góp phần</b> bảo vệ dữ liệu khách hàng và <b>hỗ trợ</b> tuân thủ <b>Nghị định
          13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân</b> (yêu cầu bảo đảm <b>an toàn</b> và <b>tính toàn vẹn</b>
          của dữ liệu).
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
    </>
  );
}

function DeepGuide() {
  return (
    <>
      <p style={{ fontSize: 13, color: "#6b7280", marginTop: 14 }}>
        Phần này dành cho người phụ trách vận hành. Diễn giải chi tiết hơn phần “Cơ bản”, kèm trách nhiệm,
        theo dõi và xử lý sự cố.
      </p>

      <div style={box}>
        <h3>1. Mục đích &amp; phạm vi</h3>
        <p style={{ fontSize: 14.5, lineHeight: 1.7 }}>
          Niêm phong = <b>đóng dấu điện tử</b> (chữ ký số) lên một hội thoại đã lưu, để <b>chống sửa</b> và
          <b> chứng minh nguồn gốc</b> (ai đóng, lúc nào). Đây <b>không phải mã hóa</b> — nội dung vẫn xem
          được bình thường, chỉ được bảo vệ khỏi bị sửa lén. Phạm vi áp dụng: các hội thoại đã lưu cần bảo
          toàn.
        </p>
      </div>

      <div style={box}>
        <h3>2. Quy trình đầy đủ</h3>
        <ol style={{ fontSize: 14.5, lineHeight: 1.7 }}>
          <li style={li}>Người ký <b>gửi yêu cầu</b>: chọn hội thoại + thời hạn cần quyền.</li>
          <li style={li}>Người phụ trách <b>duyệt</b> (phải khác người ký).</li>
          <li style={li}>Hệ thống <b>cấp vai ký tạm thời</b> kèm <b>cửa sổ thời gian</b> (ví dụ 30 phút).</li>
          <li style={li}>Người ký <b>thực hiện niêm phong</b> trong cửa sổ đó.</li>
          <li style={li}>Xong → phiên <b>tự đóng</b> khi hết giờ; hoặc người phụ trách <b>thu hồi sớm</b> nếu cần.</li>
        </ol>
      </div>

      <div style={box}>
        <h3>3. Ai chịu trách nhiệm (phân vai)</h3>
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", width: "100%", marginTop: 6 }}>
            <thead>
              <tr><th style={th}>Vai</th><th style={th}>Làm gì</th></tr>
            </thead>
            <tbody>
              <tr><td style={td}><b>Người ký</b> (signer)</td><td style={td}>Gửi yêu cầu và thực hiện niêm phong.</td></tr>
              <tr><td style={td}><b>Người duyệt</b> (phụ trách)</td><td style={td}>Duyệt yêu cầu; <b>phải khác</b> người ký.</td></tr>
              <tr><td style={td}><b>Người vận hành hệ thống</b></td><td style={td}>Theo dõi hạ tầng, xử lý trục trặc kỹ thuật.</td></tr>
              <tr><td style={td}><b>Chủ sự cố</b></td><td style={td}>Điều phối khi có sự cố, quyết định “cửa thoát hiểm”.</td></tr>
              <tr><td style={td}><b>Leo thang</b> (escalation)</td><td style={td}>Khi vượt thẩm quyền → báo người phụ trách cao nhất.</td></tr>
            </tbody>
          </table>
        </div>
        <p style={{ fontSize: 13, color: "#6b7280", marginTop: 8 }}>
          Giai đoạn hiện tại, <b>người phụ trách kiêm nhiều vai</b>; sẽ tách khi có thêm nhân sự.
        </p>
      </div>

      <div style={box}>
        <h3>4. Điều kiện, an toàn &amp; xử lý lỗi</h3>
        <ul style={{ fontSize: 14.5, lineHeight: 1.7 }}>
          <li style={li}><b>Kiểm tra điều kiện trước</b>: hệ thống tự rà các điều kiện cần thiết; thiếu bất kỳ điều kiện nào thì <b>từ chối</b> (không cho ký nửa vời) — gọi là “an toàn khi lỗi”.</li>
          <li style={li}><b>Có thời hạn</b>: quyền tự mất khi hết cửa sổ thời gian; không cần thu hồi tay.</li>
          <li style={li}><b>Thu hồi</b>: người phụ trách có thể thu hồi sớm bất cứ lúc nào.</li>
          <li style={li}><b>Lỗi giữa chừng</b>: dừng an toàn, không để trạng thái dang dở; có thể làm lại từ đầu sau khi khắc phục.</li>
        </ul>
      </div>

      <div style={box}>
        <h3>5. Chế độ thử vs niêm phong thật</h3>
        <p style={{ fontSize: 14.5, lineHeight: 1.7 }}>
          <b>Chế độ thử</b>: đi hết quy trình để tập, <b>không đóng dấu thật, không đụng dữ liệu khách</b>, không
          cấp quyền thật. <b>Niêm phong thật</b> và bước <b>“bật quyền ký thật”</b> là hai thứ <b>tách riêng</b>:
          niêm phong thật chỉ chạy được sau khi người phụ trách bật quyền đó một cách có chủ đích.
        </p>
      </div>

      <div style={box}>
        <h3>6. Theo dõi, nhật ký &amp; sự cố</h3>
        <ul style={{ fontSize: 14.5, lineHeight: 1.7 }}>
          <li style={li}><b>Nhật ký bất biến</b>: mọi thao tác (xin phép, duyệt, ký, thu hồi) đều được ghi lại và <b>không sửa/xóa được</b>.</li>
          <li style={li}><b>Theo dõi &amp; cảnh báo</b>: hệ thống giám sát bất thường và báo động khi có dấu hiệu lạ.</li>
          <li style={li}><b>Sự cố</b>: theo quy trình xử lý sự cố; có <b>“cửa thoát hiểm” (break-glass)</b> do người phụ trách kích hoạt và <b>ghi vết đầy đủ</b>.</li>
          <li style={li}><b>Leo thang</b>: khi vượt thẩm quyền hoặc nghi ngờ lộ lọt → báo người phụ trách cao nhất ngay.</li>
        </ul>
      </div>

      <div style={box}>
        <h3>7. Xoay &amp; thu hồi chìa khóa (nguyên tắc)</h3>
        <p style={{ fontSize: 14.5, lineHeight: 1.7 }}>
          Chìa khóa dùng để đóng dấu được <b>giữ tách biệt, an toàn</b> — <b>không</b> nằm trong web hay máy chủ
          ứng dụng. Định kỳ, hoặc khi nghi ngờ bị lộ, chìa khóa được <b>xoay/thu hồi</b> theo một quy trình riêng
          có kiểm soát. Trang này <b>không chứa</b> chìa khóa hay đường dẫn bí mật nào.
        </p>
      </div>

      <div style={box}>
        <h3>8. Checklist bàn giao</h3>
        <ul style={{ fontSize: 14.5, lineHeight: 1.7, listStyle: "none", paddingLeft: 0 }}>
          <li style={li}>☐ Đã hiểu quy trình 2 bước (xin phép → thực hiện).</li>
          <li style={li}>☐ Biết ai duyệt / ai ký (phải khác nhau).</li>
          <li style={li}>☐ Đã thử qua “Chế độ thử” ít nhất một lần.</li>
          <li style={li}>☐ Biết nơi tra nhật ký khi cần đối chiếu.</li>
          <li style={li}>☐ Biết cách leo thang khi có sự cố.</li>
        </ul>
        <p style={{ fontSize: 13, color: "#6b7280", marginTop: 8 }}>
          Chủ tài liệu: người phụ trách (PO). Phiên bản: v2 (có phần chuyên sâu). Cập nhật: 2026-09-01.
        </p>
      </div>
    </>
  );
}
