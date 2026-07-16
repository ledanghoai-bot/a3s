"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuthGuard } from "../../../lib/useAuthGuard";
import OrderForm from "../../components/OrderForm";

// Khu vuc tao don o day dong 2 vai tro (issue #8):
// 1. Doc lap hoan toan voi khung chat - dung cho don khong qua Messenger (dien
//    thoai, tai quay...). Truy cap thang /orders/new, khong co psid -> OrderForm
//    chi hien nut "NV tao don".
// 2. Duoc dieu huong toi TU khung chat 1 hoi thoai cu the (nut "Tao don" trong
//    conversations/page.js) kem query param ?psid=... - CHI mang theo psid
//    (khong dua ten/sdt/dia chi vao URL vi la du lieu nhay cam). Trang nay tu
//    goi lai dung API /dashboard/conversations/{psid}/order_draft (qua
//    OrderForm) de tu dien so luong/gia tu /approve + ten/sdt/dia chi da luu,
//    dong thoi hien ca nut "Goi bot tao don".
//
// useSearchParams() bat buoc phai nam trong <Suspense>, neu khong `next build`
// (production build - Dockerfile dang dung) se loi. Tach thanh component con.
function NewOrderContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const psid = searchParams.get("psid");

  return (
    <div>
      <a href={psid ? "/conversations" : "/orders"} style={{ fontSize: 13 }}>
        &larr; Quay lại {psid ? "hội thoại" : "đơn hàng"}
      </a>
      <h1 style={{ fontSize: 20, margin: "12px 0" }}>Tạo đơn thủ công</h1>
      <p style={{ fontSize: 13, color: "#666", marginBottom: 16 }}>
        {psid
          ? "Dữ liệu đã được tự điền từ /approve và /note của hội thoại này — kiểm tra lại trước khi tạo đơn."
          : "Dùng cho đơn không qua Messenger (điện thoại, tại quầy...). Đơn tạo ở đây không gắn với hội thoại chat nào."}
      </p>
      <div style={{ maxWidth: 420 }}>
        <OrderForm psid={psid} onCreated={() => router.push("/orders")} />
      </div>
    </div>
  );
}

export default function NewOrderPage() {
  const ready = useAuthGuard();

  if (!ready) return null;

  return (
    <Suspense fallback={<div className="empty-state">Đang tải...</div>}>
      <NewOrderContent />
    </Suspense>
  );
}
