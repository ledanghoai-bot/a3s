"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "../../lib/api";

// Component tao don dung chung (issue #8 - nang cap chon "goi bot" / "NV tao don"):
// - psid duoc truyen vao: dung trong khung chat 1 hoi thoai cu the, co ca 2 nut.
// - psid = null: dung o khu vuc doc lap ngoai khung chat, chi co nut "NV tao don"
//   (khong co "goi bot" vi khong gan voi cuoc chat nao de bot doc ngu canh).
export default function OrderForm({ psid = null, onCreated }) {
  const [products, setProducts] = useState([]);
  const [form, setForm] = useState({
    customer_name: "",
    phone: "",
    address: "",
    sku: "",
    quantity: "",
    unit_price_vnd: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [agentNotes, setAgentNotes] = useState([]);
  const [draftLoaded, setDraftLoaded] = useState(false);

  useEffect(() => {
    apiFetch("/dashboard/products")
      .then(setProducts)
      .catch(() => {});
  }, []);

  // Tu dien san form tu du lieu da co (issue #8 - lay data tu /approve + /note
  // thay vi staff phai go lai tay): so luong/don gia lay tu phe duyet /approve
  // gan nhat (du lieu co cau truc, dang tin cay); ten/sdt/dia chi lay tu don
  // truoc do cua khach (neu co). Ghi chu tho (/note tu do) hien rieng ben duoi
  // de staff doi chieu tay phan con thieu - KHONG tu dong parse text tu do vao
  // form vi khong du tin cay cho truong nhu dia chi.
  useEffect(() => {
    if (!psid) return;
    apiFetch(`/dashboard/conversations/${encodeURIComponent(psid)}/order_draft`)
      .then((draft) => {
        setForm((f) => ({
          ...f,
          customer_name: draft.customer?.name || f.customer_name,
          phone: draft.customer?.phone || f.phone,
          address: draft.customer?.address || f.address,
          quantity: draft.active_override ? String(draft.active_override.quantity) : f.quantity,
          unit_price_vnd: draft.active_override
            ? String(draft.active_override.unit_price_vnd)
            : f.unit_price_vnd,
        }));
        setAgentNotes(draft.notes || []);
        setDraftLoaded(true);
      })
      .catch(() => setDraftLoaded(true));
  }, [psid]);

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  function formatVnd(n) {
    return Number(n).toLocaleString("vi-VN") + "đ";
  }

  async function submit(mode) {
    setError(null);
    setSuccess(null);

    if (!form.customer_name || !form.phone || !form.address || !form.sku || !form.quantity) {
      setError("Điền đủ tên, SĐT, địa chỉ, sản phẩm, số lượng.");
      return;
    }
    if (mode === "manual" && !form.unit_price_vnd) {
      setError("NV tạo đơn cần nhập đơn giá.");
      return;
    }

    setBusy(true);
    try {
      let path;
      let body;

      if (mode === "bot") {
        path = `/dashboard/conversations/${encodeURIComponent(psid)}/create_order`;
        body = {
          customer_name: form.customer_name,
          phone: form.phone,
          address: form.address,
          sku: form.sku,
          quantity: Number(form.quantity),
        };
      } else if (psid) {
        path = `/dashboard/conversations/${encodeURIComponent(psid)}/create_order_manual`;
        body = {
          customer_name: form.customer_name,
          phone: form.phone,
          address: form.address,
          sku: form.sku,
          quantity: Number(form.quantity),
          unit_price_vnd: Number(form.unit_price_vnd),
        };
      } else {
        path = "/dashboard/orders/manual";
        body = {
          customer_name: form.customer_name,
          phone: form.phone,
          address: form.address,
          sku: form.sku,
          quantity: Number(form.quantity),
          unit_price_vnd: Number(form.unit_price_vnd),
        };
      }

      const result = await apiFetch(path, { method: "POST", body: JSON.stringify(body) });
      setSuccess(`Đã tạo đơn #${result.order_id} — tổng ${formatVnd(result.total_vnd)}`);
      setForm({ customer_name: "", phone: "", address: "", sku: "", quantity: "", unit_price_vnd: "" });
      if (onCreated) onCreated(result);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ border: "1px solid #eee", borderRadius: 8, padding: 12, background: "#fff" }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Tạo đơn hàng</div>
      {psid && agentNotes.length > 0 && (
        <div
          style={{
            background: "#fffbeb",
            border: "1px solid #fde68a",
            borderRadius: 6,
            padding: 8,
            marginBottom: 10,
            fontSize: 12,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 4 }}>
            📝 Ghi chú/thỏa thuận gần đây (từ /note, /approve) — đối chiếu tay phần còn thiếu:
          </div>
          {agentNotes.map((n, i) => (
            <div key={i} style={{ color: "#7c5a05", marginBottom: 2 }}>
              • {n.content}
            </div>
          ))}
        </div>
      )}
      {psid && draftLoaded && (form.quantity || form.unit_price_vnd) && (
        <div style={{ fontSize: 12, color: "#2563eb", marginBottom: 8 }}>
          ✓ Đã tự điền số lượng/đơn giá từ phê duyệt /approve gần nhất — kiểm tra lại trước khi tạo đơn.
        </div>
      )}
      {error && <div className="error-box">{error}</div>}
      {success && (
        <div className="error-box" style={{ background: "#dcfce7", color: "#14532d" }}>
          {success}
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <input
          placeholder="Tên người nhận"
          value={form.customer_name}
          onChange={(e) => update("customer_name", e.target.value)}
        />
        <input placeholder="SĐT" value={form.phone} onChange={(e) => update("phone", e.target.value)} />
        <input
          placeholder="Địa chỉ giao hàng"
          value={form.address}
          onChange={(e) => update("address", e.target.value)}
        />
        <select value={form.sku} onChange={(e) => update("sku", e.target.value)}>
          <option value="">-- Chọn sản phẩm --</option>
          {products.map((p) => (
            <option key={p.sku} value={p.sku}>
              {p.sku} — {p.name} (còn {p.stock})
            </option>
          ))}
        </select>
        <input
          type="number"
          placeholder="Số lượng"
          value={form.quantity}
          onChange={(e) => update("quantity", e.target.value)}
        />
        <input
          type="number"
          placeholder="Đơn giá VNĐ (chỉ dùng cho NV tạo đơn)"
          value={form.unit_price_vnd}
          onChange={(e) => update("unit_price_vnd", e.target.value)}
        />
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        {psid && (
          <button className="primary" disabled={busy} onClick={() => submit("bot")}>
            🤖 Gọi bot tạo đơn
          </button>
        )}
        <button disabled={busy} onClick={() => submit("manual")}>
          👤 NV tạo đơn
        </button>
      </div>
    </div>
  );
}
