"use client";

// CA Directive 393 §2.2/§7 — Vận đơn GHN: review → staff xác nhận TƯỜNG MINH (nhập lại mã đơn) → tạo YÊU CẦU.
// Không gọi GHN từ trình duyệt/API request: worker dispatch sau gate riêng (mặc định TẮT). Không hiện token; SĐT mask.
import { useState } from "react";
import { apiFetch } from "../../../lib/api";

const STATE_LABEL = {
  prepared: "Đã tạo yêu cầu (chờ gửi)",
  dispatching: "Đang gửi GHN",
  succeeded: "Đã tạo vận đơn",
  failed_retryable: "Lỗi tạm — sẽ đối soát rồi thử lại",
  failed_terminal: "Thất bại (cần nhân viên)",
  unknown_reconciliation_required: "KHÔNG CHẮC CHẮN — cần đối soát",
  cancelled_before_dispatch: "Đã huỷ trước khi gửi",
};
const BLOCKER_LABEL = {
  order_cancelled: "Đơn đã huỷ", customer_not_messaging: "Khách không có kênh nhắn tin",
  recipient_incomplete: "Thiếu tên/SĐT người nhận", recipient_phone_invalid: "SĐT người nhận không hợp lệ",
  operation_active: "Đã có yêu cầu vận đơn đang hoạt động", staff_attention_open: "Còn việc chờ nhân viên",
  refund_or_exception_pending: "Đang chờ hoàn tiền/ngoại lệ huỷ", self_delivery: "Đơn giao nội bộ (không GHN)",
  route_manual_review: "Địa chỉ cần kiểm tra thủ công", weight_missing: "Thiếu khối lượng",
  heavy_goods: "Hàng nặng >20kg (xử lý thủ công)", shipment_missing: "Chưa có shipment",
  quote_not_ghn_api_ok: "Chưa có phí GHN hợp lệ", quote_stale: "Phí GHN đã cũ so với kiện hàng",
  quote_expired: "Phí GHN quá hạn — báo phí lại", ghn_not_configured: "Chưa cấu hình GHN đúng mode",
  address_unmapped: "Phường/xã chưa map GHN", payment_missing: "Chưa có thanh toán",
  payment_not_confirmed: "Chuyển khoản chưa xác nhận", payment_amount_unknown: "Chưa rõ số tiền",
};

function newKey() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return "k-" + Date.now() + "-" + Math.random().toString(36).slice(2);
}
function vnd(n) {
  return n == null ? "—" : Number(n).toLocaleString("vi-VN") + "đ";
}

export default function GhnCreatePanel({ orderId, cancelled, onChange }) {
  const [pv, setPv] = useState(null);
  const [confirmId, setConfirmId] = useState("");
  const [note, setNote] = useState("");
  const [key, setKey] = useState(newKey);   // 1 key / lần xác nhận: bấm lại/retry mạng không tạo 2 yêu cầu
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [msg, setMsg] = useState(null);

  async function loadPreview() {
    setBusy(true); setErr(null); setMsg(null);
    try { setPv(await apiFetch(`/dashboard/fulfillment/orders/${orderId}/ghn-create/preview`)); }
    catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }
  async function submit() {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const r = await apiFetch(`/dashboard/fulfillment/orders/${orderId}/ghn-create`, {
        method: "POST",
        body: JSON.stringify({ command_key: key, confirm_order_id: confirmId, preview_fingerprint: pv.fingerprint,
                               note: note.trim() || null }),
      });
      setMsg(r.duplicate ? "Yêu cầu đã tồn tại (không tạo lại)." :
        (r.gates && r.gates.dashboard ? "Đã tạo yêu cầu — worker sẽ gửi GHN." :
          "Đã tạo yêu cầu — GATE đang TẮT: chưa gửi GHN cho tới khi được kích hoạt."));
      setKey(newKey()); setConfirmId("");
      await loadPreview(); if (onChange) onChange();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }
  async function act(opId, action, body) {
    setBusy(true); setErr(null); setMsg(null);
    try {
      await apiFetch(`/dashboard/fulfillment/ghn-create/operations/${opId}/${action}`, {
        method: "POST", body: JSON.stringify(body || {}) });
      setMsg(action === "reconcile" ? "Đã đối soát" : "Đã dừng yêu cầu");
      await loadPreview(); if (onChange) onChange();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  const s = pv && pv.snapshot;
  const canSubmit = pv && pv.eligible && !cancelled && confirmId.trim().replace(/^#/, "") === String(orderId) && !busy;
  return (
    <section style={{ border: "1px solid #e3e3e3", borderRadius: 8, padding: 16, marginBottom: 16 }}>
      <h2 style={{ marginTop: 0, fontSize: 18 }}>Vận đơn GHN</h2>
      <button disabled={busy} onClick={loadPreview}>{pv ? "Tải lại xem trước" : "Xem trước tạo vận đơn"}</button>
      {err && <p style={{ color: "#b71c1c" }}>Lỗi: {err}</p>}
      {msg && <p style={{ color: "#1e7e34" }}>{msg}</p>}
      {pv && (
        <div style={{ marginTop: 10, fontSize: 14 }}>
          <div style={{ fontSize: 12, color: pv.gates.dashboard ? "#1e7e34" : "#9a6700" }}>
            Gate Dashboard: <b>{pv.gates.dashboard ? "BẬT" : "TẮT"}</b> · Gate Bot: {pv.gates.bot ? "BẬT" : "TẮT"} · mode {pv.gates.mode}
            {!pv.gates.dashboard && " — yêu cầu sẽ được lưu nhưng CHƯA gửi GHN."}
          </div>
          {pv.blockers.length > 0 && (
            <div style={{ background: "#fdecea", color: "#b71c1c", padding: 8, borderRadius: 6, marginTop: 8 }}>
              Chưa đủ điều kiện: {pv.blockers.map((b) => BLOCKER_LABEL[b] || b).join(" · ")}
            </div>
          )}
          {pv.warnings && pv.warnings.length > 0 && (
            <div style={{ background: "#fff4e5", color: "#9a6700", padding: 8, borderRadius: 6, marginTop: 8 }}>
              Lưu ý: {pv.warnings.join(" · ")}
            </div>
          )}
          {s && (
            <table style={{ marginTop: 8, fontSize: 13 }}><tbody>
              <tr><td>Người nhận</td><td>{s.recipient.name} · {s.recipient.phone}</td></tr>
              <tr><td>Địa chỉ</td><td>{s.recipient.address_text}</td></tr>
              <tr><td>Map GHN</td><td>quận {s.address.carrier_district_id} / phường {s.address.carrier_ward_code} (map v{s.address.map_version}, {s.address.mode})</td></tr>
              <tr><td>Lấy hàng</td><td>quận {s.pickup.from_district_id} / phường {s.pickup.from_ward_code} · config rev {s.pickup.config_revision}</td></tr>
              <tr><td>Kiện hàng</td><td>{s.parcel.weight_g}g · {s.parcel.length_cm}×{s.parcel.width_cm}×{s.parcel.height_cm}cm · dịch vụ {s.parcel.service_type_id}</td></tr>
              <tr><td>Phí / ETA</td><td>{vnd(s.quote.fee_vnd)} · {s.quote.eta_text || "—"}</td></tr>
              <tr><td>Thanh toán</td><td>{s.payment.method} ({s.payment.status}) · thu hộ {vnd(s.payment.cod_amount_vnd)}</td></tr>
              <tr><td>Hàng</td><td>{s.items.map((i) => `${i.name} ×${i.quantity}`).join(", ")}</td></tr>
            </tbody></table>
          )}
          {pv.eligible && !cancelled && (
            <div style={{ marginTop: 10 }}>
              <input placeholder={`Nhập lại mã đơn (${orderId}) để xác nhận`} value={confirmId}
                     onChange={(e) => setConfirmId(e.target.value)} />
              <input placeholder="Ghi chú (tuỳ chọn)" value={note} maxLength={500} style={{ marginLeft: 6 }}
                     onChange={(e) => setNote(e.target.value)} />
              <button className="primary" style={{ marginLeft: 6 }} disabled={!canSubmit} onClick={submit}>
                Tạo yêu cầu vận đơn
              </button>
            </div>
          )}
          {pv.operations && pv.operations.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <b>Yêu cầu vận đơn</b>
              {pv.operations.map((op) => (
                <div key={op.id} style={{ borderTop: "1px solid #eee", padding: "6px 0", fontSize: 13 }}>
                  #{op.id} · <b>{STATE_LABEL[op.state] || op.state}</b> · nguồn {op.source}
                  {op.initiator_staff_id ? ` (staff ${op.initiator_staff_id})` : ""} · mã tương quan {op.client_order_code_masked}
                  {op.provider_order_code && <> · mã GHN <b>{op.provider_order_code}</b></>}
                  {op.gate_blocked_reason && <> · chặn: {op.gate_blocked_reason}</>}
                  {op.terminal_reason && <> · lý do: {op.terminal_reason}</>}
                  <div style={{ color: "#666" }}>
                    Lần gửi: {op.attempt_count}/{op.max_attempts}
                    {op.attempts && op.attempts.length > 0 && " · " + op.attempts.map((a) =>
                      `${a.kind}:${a.outcome}${a.http_status ? `(${a.http_status})` : ""}`).join(", ")}
                  </div>
                  {["unknown_reconciliation_required", "failed_retryable"].includes(op.state) && (
                    <button disabled={busy} onClick={() => act(op.id, "reconcile")}>Đối soát với GHN</button>
                  )}
                  {["prepared", "failed_retryable", "unknown_reconciliation_required"].includes(op.state) && (
                    <button disabled={busy} style={{ marginLeft: 6 }} onClick={() => {
                      const n = window.prompt(op.state === "unknown_reconciliation_required"
                        ? "Xác nhận đã kiểm tra GHN KHÔNG có vận đơn — ghi chú:" : "Lý do dừng yêu cầu:");
                      if (n && n.trim()) act(op.id, "abandon", { note: n.trim() });
                    }}>Dừng yêu cầu</button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
