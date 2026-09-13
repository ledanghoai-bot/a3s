"use client";

// M6 Giao & Thu tiền — bảng điều phối (CA Directive 265 §4.1 + Review 266-01).
// Danh sách đơn kèm trạng thái shipment + payment, lọc theo trạng thái, mở chi tiết để thao tác.
import { useEffect, useState } from "react";
import { apiFetch } from "../../lib/api";
import { useAuthGuard } from "../../lib/useAuthGuard";

const SHIP_LABEL = {
  pending_prep: "Chờ chuẩn bị",
  ready_to_ship: "Sẵn sàng giao",
  in_transit: "Đang giao",
  delivered: "Đã giao",
  delivery_failed: "Giao lỗi",
  return_pending: "Chờ hoàn",
};
const PAY_LABEL = {
  awaiting: "Chờ thanh toán",
  reported: "Khách báo CK",
  collected: "COD đã thu",
  confirmed: "Đã xác nhận",
  reconciled: "Đã đối soát",
  discrepancy: "Lệch — cần xử lý",
};
const FEE_LABEL = { quoted: "Đã báo phí", quote_required: "Cần báo phí", unknown: "Chưa xác định" };

function vnd(n) {
  return n == null ? "—" : n.toLocaleString("vi-VN") + "đ";
}
function Tag({ text, tone }) {
  const bg = { ok: "#e6f4ea", warn: "#fff4e5", bad: "#fdecea", neutral: "#eef1f4" }[tone] || "#eef1f4";
  const fg = { ok: "#1e7e34", warn: "#9a6700", bad: "#b71c1c", neutral: "#444" }[tone] || "#444";
  return (
    <span style={{ background: bg, color: fg, padding: "2px 8px", borderRadius: 10, fontSize: 12 }}>{text}</span>
  );
}
function payTone(s) {
  if (s === "confirmed" || s === "reconciled") return "ok";
  if (s === "discrepancy") return "bad";
  if (s === "awaiting" || !s) return "neutral";
  return "warn";
}
function shipTone(s) {
  if (s === "delivered") return "ok";
  if (s === "delivery_failed" || s === "return_pending") return "bad";
  if (s === "in_transit") return "warn";
  return "neutral";
}

export default function FulfillmentBoard() {
  const ready = useAuthGuard();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [shipFilter, setShipFilter] = useState("");
  const [payFilter, setPayFilter] = useState("");

  useEffect(() => {
    if (ready) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, shipFilter, payFilter]);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams();
      if (shipFilter) qs.set("shipment_status", shipFilter);
      if (payFilter) qs.set("payment_status", payFilter);
      const data = await apiFetch(`/dashboard/fulfillment/board?${qs.toString()}`);
      setRows(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  if (!ready) return null;
  return (
    <div>
      <h1>Giao &amp; Thu tiền</h1>
      <div style={{ display: "flex", gap: 12, margin: "12px 0", flexWrap: "wrap" }}>
        <label>
          Trạng thái giao:{" "}
          <select value={shipFilter} onChange={(e) => setShipFilter(e.target.value)}>
            <option value="">Tất cả</option>
            {Object.entries(SHIP_LABEL).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </label>
        <label>
          Trạng thái thu tiền:{" "}
          <select value={payFilter} onChange={(e) => setPayFilter(e.target.value)}>
            <option value="">Tất cả</option>
            {Object.entries(PAY_LABEL).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </label>
        <button onClick={load}>Làm mới</button>
      </div>
      {error && <p style={{ color: "#b71c1c" }}>Lỗi: {error}</p>}
      {loading ? (
        <p>Đang tải…</p>
      ) : rows.length === 0 ? (
        <p>Không có đơn nào khớp bộ lọc.</p>
      ) : (
        <table className="table" style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "2px solid #ddd" }}>
              <th>Mã đơn</th>
              <th>Khách</th>
              <th>Tổng hàng</th>
              <th>Giao</th>
              <th>Phí</th>
              <th>Thu tiền</th>
              <th>Cần thu</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.order_id} style={{ borderBottom: "1px solid #eee" }}>
                <td>#{r.order_id}</td>
                <td>{r.customer_name || "—"}</td>
                <td>{vnd(r.total_vnd)}</td>
                <td><Tag text={SHIP_LABEL[r.shipment_status] || "Chưa tạo"} tone={shipTone(r.shipment_status)} /></td>
                <td>{FEE_LABEL[r.fee_status] || "—"}{r.delivery_fee_vnd != null ? ` (${vnd(r.delivery_fee_vnd)})` : ""}</td>
                <td><Tag text={PAY_LABEL[r.payment_status] || "Chưa tạo"} tone={payTone(r.payment_status)} /></td>
                <td>{vnd(r.amount_due_vnd)}</td>
                <td><a href={`/fulfillment/${r.order_id}`}>Mở →</a></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
