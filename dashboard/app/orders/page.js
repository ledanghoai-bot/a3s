"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "../../lib/api";
import { useAuthGuard } from "../../lib/useAuthGuard";

const STATUS_OPTIONS = ["new", "confirmed", "shipped", "done", "cancelled"];
const STATUS_LABEL = {
  new: "Mới",
  confirmed: "Đã xác nhận",
  shipped: "Đang giao",
  done: "Hoàn tất",
  cancelled: "Đã huỷ",
};

function formatVnd(n) {
  return n.toLocaleString("vi-VN") + "đ";
}

export default function OrdersPage() {
  const ready = useAuthGuard();
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);

  useEffect(() => {
    if (ready) load();
  }, [ready]);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch("/dashboard/orders");
      setOrders(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function changeStatus(orderId, newStatus) {
    setBusyId(orderId);
    try {
      await apiFetch(`/dashboard/orders/${orderId}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status: newStatus }),
      });
      await load();
    } catch (err) {
      alert("Lỗi: " + err.message);
    } finally {
      setBusyId(null);
    }
  }

  if (!ready) return null;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h1 style={{ fontSize: 20 }}>Đơn hàng</h1>
        <a href="/orders/new">
          <button className="primary">+ Tạo đơn thủ công</button>
        </a>
      </div>
      {error && <div className="error-box">{error}</div>}
      {loading ? (
        <div className="empty-state">Đang tải...</div>
      ) : orders.length === 0 ? (
        <div className="empty-state">Chưa có đơn hàng nào.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Khách</th>
              <th>Sản phẩm</th>
              <th>Tổng tiền</th>
              <th>Lúc</th>
              <th>Trạng thái</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id}>
                <td>{o.id}</td>
                <td>
                  {o.shipping_name}
                  <div style={{ fontSize: 12, color: "#999" }}>{o.shipping_phone}</div>
                </td>
                <td style={{ fontSize: 13 }}>
                  {o.items.map((it, i) => (
                    <div key={i}>
                      {it.sku} × {it.quantity}
                    </div>
                  ))}
                </td>
                <td>{formatVnd(o.total_vnd)}</td>
                <td style={{ fontSize: 12, color: "#666" }}>
                  {new Date(o.created_at).toLocaleString("vi-VN")}
                </td>
                <td>
                  <span className={`badge badge-${o.status}`}>{STATUS_LABEL[o.status] || o.status}</span>
                </td>
                <td>
                  <select
                    value={o.status}
                    disabled={busyId === o.id}
                    onChange={(e) => changeStatus(o.id, e.target.value)}
                  >
                    {STATUS_OPTIONS.map((s) => (
                      <option key={s} value={s}>
                        {STATUS_LABEL[s]}
                      </option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
