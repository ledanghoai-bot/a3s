"use client";

// M7 Hàng đợi cần nhân viên (CA Directive 272 §4 + Review 274-04). Danh sách staff_attention đang mở theo
// reason; xem chi tiết đơn/hội thoại; resolve kèm ghi chú (RBAC fulfillment.attention_resolve).
import { useEffect, useState } from "react";
import { apiFetch } from "../../../lib/api";
import { useAuthGuard } from "../../../lib/useAuthGuard";

const REASON_LABEL = {
  payment_timeout: "Quá hạn chuyển khoản",
  payment_mismatch: "Lệch/sai thanh toán",
  large_order_review: "Đơn số lượng lớn",
  quantity_unit_review: "Đơn vị số lượng cần kiểm",
  unmatched_webhook: "Webhook không khớp",
  address: "Địa chỉ",
  quote: "Phí giao",
  account: "Tài khoản nhận",
  method: "Phương thức",
  provider_error: "Lỗi nhà vận chuyển",
  other: "Khác",
  refund_required: "Đơn huỷ — cần hoàn tiền",
  order_cancel_exception: "Đơn huỷ — hàng đã bàn giao",
  shipment_create: "Tạo vận đơn GHN cần kiểm tra",
};

function tone(reason) {
  if (reason === "payment_mismatch" || reason === "unmatched_webhook" || reason === "refund_required" ||
      reason === "order_cancel_exception") return "bad";
  if (reason === "payment_timeout" || reason === "large_order_review") return "warn";
  return "neutral";
}

export default function AttentionQueue() {
  const ready = useAuthGuard();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [notes, setNotes] = useState({});

  useEffect(() => {
    if (ready) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setRows(await apiFetch("/dashboard/fulfillment/attention"));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function resolve(id) {
    const note = (notes[id] || "").trim();
    if (!note) {
      setError("Nhập ghi chú xử lý trước khi resolve");
      return;
    }
    setBusyId(id);
    setMsg(null);
    setError(null);
    try {
      await apiFetch(`/dashboard/fulfillment/attention/${id}/resolve`, {
        method: "POST",
        body: JSON.stringify({ note }),
      });
      setMsg(`Đã resolve #${id}`);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyId(null);
    }
  }

  if (!ready) return null;
  return (
    <div>
      <h1>Hàng đợi cần nhân viên (M7)</h1>
      <p><a href="/fulfillment">← Bảng Giao &amp; Thu tiền</a></p>
      {msg && <p style={{ color: "#1e7e34" }}>{msg}</p>}
      {error && <p style={{ color: "#b71c1c" }}>Lỗi: {error}</p>}
      <button onClick={load} disabled={loading}>Làm mới</button>
      {loading ? (
        <p>Đang tải…</p>
      ) : rows.length === 0 ? (
        <p>Không có mục nào cần xử lý.</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 12 }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "2px solid #ddd" }}>
              <th>#</th><th>Đơn</th><th>Lý do</th><th>Bước hội thoại</th><th>Thanh toán</th><th>Xử lý</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} style={{ borderBottom: "1px solid #eee", verticalAlign: "top" }}>
                <td>{r.id}</td>
                <td>{r.order_id ? <a href={`/fulfillment/${r.order_id}`}>#{r.order_id}</a> : "—"}</td>
                <td>
                  <span style={{
                    background: { bad: "#fdecea", warn: "#fff4e5", neutral: "#eef1f4" }[tone(r.reason)],
                    color: { bad: "#b71c1c", warn: "#9a6700", neutral: "#444" }[tone(r.reason)],
                    padding: "2px 8px", borderRadius: 10, fontSize: 12,
                  }}>{REASON_LABEL[r.reason] || r.reason}</span>
                </td>
                <td>{r.conversation_step || "—"}</td>
                <td>{r.payment_status || "—"}{r.payment_method ? ` (${r.payment_method})` : ""}</td>
                <td>
                  <input placeholder="ghi chú xử lý" value={notes[r.id] || ""}
                         onChange={(e) => setNotes({ ...notes, [r.id]: e.target.value })} style={{ width: 200 }} />
                  <button disabled={busyId === r.id} onClick={() => resolve(r.id)} style={{ marginLeft: 6 }}>
                    Resolve
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
