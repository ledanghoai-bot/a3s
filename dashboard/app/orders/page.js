"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "../../lib/api";
import { useAuthGuard } from "../../lib/useAuthGuard";

// CA Directive 387: "Huỷ" KHÔNG còn trong dropdown (PATCH cũ không set cancelled) — dùng nút Huỷ đơn + lý do bắt buộc.
const STATUS_OPTIONS = ["new", "confirmed", "shipped", "done"];
const STATUS_LABEL = {
  new: "Mới",
  confirmed: "Đã xác nhận",
  shipped: "Đang giao",
  done: "Hoàn tất",
  cancelled: "Đã huỷ",
  cancelled_by_exception: "Đã huỷ (ngoại lệ)",
};
const CANCELLED = ["cancelled", "cancelled_by_exception"];
const NOT_CANCELLABLE = [...CANCELLED, "done", "completed"];
const REASON_MIN = 5;
const REASON_MAX = 500;

function newKey() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return "k-" + Date.now() + "-" + Math.random().toString(36).slice(2);
}

function CancelModal({ order, onClose, onDone }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  // 1 Idempotency-Key cho 1 lần mở hộp thoại: bấm lại/retry mạng không huỷ 2 lần
  const [key] = useState(newKey);
  const len = reason.trim().length;
  const valid = len >= REASON_MIN && len <= REASON_MAX;

  async function submit() {
    if (!valid || busy) return;
    setBusy(true);
    setErr(null);
    try {
      await apiFetch(`/dashboard/orders/${order.id}/cancel`, {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: JSON.stringify({ reason: reason.trim() }),
      });
      onDone();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.4)", display: "flex",
                  alignItems: "center", justifyContent: "center", zIndex: 50, padding: 16 }}>
      <div style={{ background: "#fff", borderRadius: 8, padding: 20, width: "100%", maxWidth: 480 }}>
        <h2 style={{ fontSize: 17, marginBottom: 8 }}>Huỷ đơn #{order.id}</h2>
        <div style={{ fontSize: 13, color: "#555", marginBottom: 10 }}>
          Lý do được ghi vào nhật ký đơn (nội bộ). Khách chỉ nhận thông báo “Đơn #{order.id} đã được huỷ”.
        </div>
        <textarea
          rows={4}
          style={{ width: "100%", boxSizing: "border-box" }}
          placeholder={`Lý do huỷ (${REASON_MIN}–${REASON_MAX} ký tự)`}
          value={reason}
          maxLength={REASON_MAX + 50}
          onChange={(e) => setReason(e.target.value)}
          autoFocus
        />
        <div style={{ fontSize: 12, color: valid || len === 0 ? "#888" : "#c00", marginTop: 4 }}>
          {len}/{REASON_MAX} ký tự{len > 0 && len < REASON_MIN ? ` — tối thiểu ${REASON_MIN}` : ""}
          {len > REASON_MAX ? " — vượt quá giới hạn" : ""}
        </div>
        {err && <div className="error-box" style={{ marginTop: 8 }}>{err}</div>}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 12 }}>
          <button onClick={onClose} disabled={busy}>Đóng</button>
          <button className="primary" onClick={submit} disabled={!valid || busy}>
            {busy ? "Đang huỷ..." : "Xác nhận huỷ"}
          </button>
        </div>
      </div>
    </div>
  );
}

function formatVnd(n) {
  return n.toLocaleString("vi-VN") + "đ";
}

export default function OrdersPage() {
  const ready = useAuthGuard();
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [cancelOrder, setCancelOrder] = useState(null);

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
                  {o.account_channel === "dashboard" ? (
                    <div style={{ fontSize: 11, color: "#a60" }}>Dashboard — không có kênh nhắn tin khách</div>
                  ) : o.account_name && o.account_name !== o.shipping_name ? (
                    <div style={{ fontSize: 11, color: "#999" }}>Tài khoản: {o.account_name}</div>
                  ) : null}
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
                <td style={{ whiteSpace: "nowrap" }}>
                  {!CANCELLED.includes(o.status) && (
                    <select
                      value={STATUS_OPTIONS.includes(o.status) ? o.status : ""}
                      disabled={busyId === o.id}
                      onChange={(e) => changeStatus(o.id, e.target.value)}
                    >
                      {!STATUS_OPTIONS.includes(o.status) && <option value="">{STATUS_LABEL[o.status] || o.status}</option>}
                      {STATUS_OPTIONS.map((s) => (
                        <option key={s} value={s}>
                          {STATUS_LABEL[s]}
                        </option>
                      ))}
                    </select>
                  )}
                  {!NOT_CANCELLABLE.includes(o.status) && (
                    <button style={{ marginLeft: 6 }} onClick={() => setCancelOrder(o)}>
                      Huỷ đơn
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {cancelOrder && (
        <CancelModal
          order={cancelOrder}
          onClose={() => setCancelOrder(null)}
          onDone={async () => {
            setCancelOrder(null);
            await load();
          }}
        />
      )}
    </div>
  );
}
