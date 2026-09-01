"use client";

// Trang huong dan (runbook) cho quy trinh Niem phong hoi thoai. NOI DUNG TINH (khong API/permission/
// secret) — chi tai lieu van hanh. "Niem phong" = chu ky so chong gia mao/choi bo (Ed25519 KMS),
// KHONG phai encryption.

import { useAuthGuard } from "../../lib/useAuthGuard";

const box = { border: "1px solid #e5e7eb", borderRadius: 8, padding: 16, marginTop: 12, background: "#fff" };

export default function SigningGuidePage() {
  const ready = useAuthGuard();
  if (!ready) return null;
  return (
    <main style={{ padding: 24, maxWidth: 900 }}>
      <h1>Hướng dẫn niêm phong hội thoại</h1>
      <p style={{ color: "#6b7280", fontSize: 14 }}>
        <b>Niêm phong</b> = đóng dấu <b>chữ ký số</b> lên bản ghi hội thoại (transcript) để <b>chống giả mạo
        và chống chối bỏ</b> — chứng minh bản ghi không bị sửa và ai đã ký. Đây <b>không phải mã hóa</b>
        (nội dung vẫn đọc được); nó là <i>đóng dấu xác thực</i>. Khóa ký nằm ở KMS (Ed25519), không bao giờ
        lộ. Trang này chỉ là tài liệu — không nhập PIN/khóa/token ở bất kỳ đâu trên dashboard.
      </p>

      <div style={box}>
        <h3>Hai bước — hai menu</h3>
        <ol style={{ fontSize: 14, lineHeight: 1.7 }}>
          <li><b>Mở phiên niêm phong</b> (cấp quyền): người ký gửi yêu cầu (scope, digest, ticket, thời
            lượng window). <b>PO/Approver duyệt</b> — phải là người <b>KHÁC</b> người ký (SoD). Khi duyệt:
            hệ thống cấp <b>quyền ký tạm thời</b> (tự hết hạn theo window) + mở <b>cửa sổ kích hoạt</b>.</li>
          <li><b>Thực hiện niêm phong</b> (chạy ký): người ký đã có quyền + trong window → tạo run →
            confirm → preflight → ceremony (USB) → canary (duyệt SoD) → <b>execute</b> (ký thật qua KMS).</li>
        </ol>
        <p style={{ fontSize: 13, color: "#374151" }}>
          Xong → đóng phiên → <b>quyền ký tự động thu hồi</b>. Người ký hết quyền, hệ thống về trạng thái nghỉ.
        </p>
      </div>

      <div style={box}>
        <h3>Nguyên tắc bắt buộc (an ninh)</h3>
        <ul style={{ fontSize: 14, lineHeight: 1.7 }}>
          <li><b>SoD:</b> người <b>ký</b> (request + execute) phải KHÁC người <b>duyệt</b>. Backend ép, không
            phải chỉ UI.</li>
          <li><b>Không nhập secret trên dashboard:</b> PIN/khóa riêng/token nằm ở ceremony USB + KMS, ngoài
            luồng UI. Chỉ nhập dữ liệu công khai (digest, ticket, fingerprint).</li>
          <li><b>Thời hạn (TTL):</b> quyền ký + cửa sổ có giới hạn giờ, hết hạn tự thu hồi. Không có "quyền
            ký thường trực".</li>
          <li><b>Fail-closed:</b> thiếu điều kiện (preflight hỏng, hết hạn, digest lệch) → hệ thống từ chối.</li>
          <li><b>Audit bất biến:</b> mọi bước ghi log không thể sửa/xóa, không chứa secret.</li>
        </ul>
      </div>

      <div style={box}>
        <h3>Chế độ Rehearsal (tập dượt)</h3>
        <p style={{ fontSize: 14 }}>
          Khi tạo yêu cầu ở <b>Mở phiên niêm phong</b>, bật <b>🧪 Rehearsal</b> để <b>tập dượt toàn bộ luồng
          mà KHÔNG cấp quyền thật, KHÔNG chạm KMS/dữ liệu khách</b>. Dùng để làm quen/kiểm thử trước khi ký thật.
        </p>
      </div>

      <div style={box}>
        <h3>Trạng thái hiện tại</h3>
        <p style={{ fontSize: 14 }}>
          Hạ tầng niêm phong đã sẵn sàng nhưng đang ở <b>trạng thái nghỉ (dormant)</b>: chưa cấp quyền ký
          production, chưa mở cổng ký thật. Việc ký production trên dữ liệu khách thật cần <b>quyết định của
          PO</b> + phê duyệt riêng. Tập dượt (rehearsal) thì dùng được ngay khi tài khoản có quyền tương ứng.
        </p>
      </div>
    </main>
  );
}
