"use client";

// M6 Giao & Thu tiền — chi tiết 1 đơn + thao tác (CA Directive 265 §4 + Review 266-01).
// Quote (auto/thủ công), hãng/tracking, chuyển trạng thái giao, ghi lần giao; tạo payment, hướng dẫn CK,
// ghi evidence (khách báo / COD thu / shop xác nhận / đối soát / điều chỉnh), cấu hình tài khoản nhận.
// Mọi mutation ghi evidence/lần-giao gửi kèm command_key (idempotency — 266-03) sinh phía client mỗi lần bấm.
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiFetch } from "../../../lib/api";
import { useAuthGuard } from "../../../lib/useAuthGuard";

function vnd(n) {
  return n == null ? "—" : n.toLocaleString("vi-VN") + "đ";
}
function newKey() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return "k-" + Date.now() + "-" + Math.random().toString(36).slice(2);
}
const SHIP_TRANSITIONS = {
  pending_prep: ["ready_to_ship"],
  ready_to_ship: ["in_transit", "pending_prep"],
  in_transit: ["delivered", "delivery_failed"],
  delivery_failed: ["in_transit", "return_pending"],
  delivered: [],
  return_pending: [],
};
const SHIP_LABEL = {
  pending_prep: "Chờ chuẩn bị", ready_to_ship: "Sẵn sàng giao", in_transit: "Đang giao",
  delivered: "Đã giao", delivery_failed: "Giao lỗi", return_pending: "Chờ hoàn",
};

function Section({ title, children }) {
  return (
    <section style={{ border: "1px solid #e3e3e3", borderRadius: 8, padding: 16, marginBottom: 16 }}>
      <h2 style={{ marginTop: 0, fontSize: 18 }}>{title}</h2>
      {children}
    </section>
  );
}
function Row({ label, children }) {
  return (
    <div style={{ display: "flex", gap: 8, margin: "6px 0", alignItems: "center", flexWrap: "wrap" }}>
      <span style={{ minWidth: 140, color: "#555" }}>{label}</span>
      {children}
    </div>
  );
}

export default function FulfillmentDetail() {
  const ready = useAuthGuard();
  const { orderId } = useParams();
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  // form state
  const [mq, setMq] = useState({ zone: "", weight_g: "", fee_vnd: "", eta_text: "" });
  const [carrier, setCarrier] = useState({ carrier: "", tracking_text: "" });
  const [method, setMethod] = useState("COD");
  const [ev, setEv] = useState({ kind: "cod_collected", amount_vnd: "", reference: "", note: "" });
  const [corr, setCorr] = useState({ amount_vnd: "", note: "", corrects_event_id: "" });
  const [att, setAtt] = useState({ result: "failed", reason: "", note: "", next_contact_at: "" });
  const [bank, setBank] = useState({ bank: "", account_number: "", holder_name: "", branch: "" });

  useEffect(() => {
    if (ready) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  async function load() {
    setError(null);
    try {
      setD(await apiFetch(`/dashboard/fulfillment/orders/${orderId}`));
    } catch (err) {
      setError(err.message);
    }
  }
  async function act(fn, okMsg) {
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      await fn();
      setMsg(okMsg || "Đã cập nhật");
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  const post = (path, body) =>
    apiFetch(`/dashboard/fulfillment${path}`, { method: "POST", body: JSON.stringify(body || {}) });

  if (!ready) return null;
  if (error && !d) return <p style={{ color: "#b71c1c" }}>Lỗi: {error}</p>;
  if (!d) return <p>Đang tải…</p>;

  const sh = d.shipment;
  const p = d.payment;
  const transitions = sh ? SHIP_TRANSITIONS[sh.status] || [] : [];

  return (
    <div>
      <p><a href="/fulfillment">← Về bảng điều phối</a></p>
      <h1>Đơn #{d.order.id}</h1>
      {msg && <p style={{ color: "#1e7e34" }}>{msg}</p>}
      {error && <p style={{ color: "#b71c1c" }}>Lỗi: {error}</p>}

      <Section title="Khách & địa chỉ">
        <Row label="Khách">{d.order.customer_name || "—"}</Row>
        <Row label="Tổng hàng">{vnd(d.order.total_vnd)}</Row>
        <Row label="Địa chỉ">
          {d.address_snapshot
            ? [d.address_snapshot.street_text, d.address_snapshot.ward_name, d.address_snapshot.district_name,
               d.address_snapshot.province_name].filter(Boolean).join(", ")
            : "Chưa có địa chỉ đã xác minh"}
        </Row>
      </Section>

      <Section title="Giao hàng">
        {sh ? (
          <>
            <Row label="Trạng thái"><b>{SHIP_LABEL[sh.status] || sh.status}</b> (phiên bản {sh.version})</Row>
            <Row label="Khu vực / Phí">{sh.zone} — {sh.fee_status}{sh.delivery_fee_vnd != null ? ` (${vnd(sh.delivery_fee_vnd)})` : ""}</Row>
            <Row label="ETA">{sh.eta_text || "—"}{sh.eta_start_source ? ` · mốc: ${sh.eta_start_source}` : ""}</Row>
            <Row label="Hãng / Mã">{sh.carrier || "—"} / {sh.tracking_text || "—"}</Row>
          </>
        ) : (
          <p>Chưa có vận đơn. Báo phí để tạo.</p>
        )}
        <Row label="Báo phí tự động">
          <button disabled={busy} onClick={() => act(() => post(`/orders/${orderId}/shipment/quote`), "Đã báo phí tự động")}>
            Tính phí theo địa chỉ
          </button>
        </Row>
        <Row label="Báo phí thủ công">
          <input placeholder="zone" value={mq.zone} onChange={(e) => setMq({ ...mq, zone: e.target.value })} style={{ width: 90 }} />
          <input placeholder="gram" value={mq.weight_g} onChange={(e) => setMq({ ...mq, weight_g: e.target.value })} style={{ width: 70 }} />
          <input placeholder="phí VNĐ" value={mq.fee_vnd} onChange={(e) => setMq({ ...mq, fee_vnd: e.target.value })} style={{ width: 90 }} />
          <input placeholder="ETA" value={mq.eta_text} onChange={(e) => setMq({ ...mq, eta_text: e.target.value })} />
          <button disabled={busy} onClick={() => act(() => post(`/orders/${orderId}/shipment/manual-quote`, {
            zone: mq.zone || undefined,
            weight_g: mq.weight_g === "" ? undefined : Number(mq.weight_g),
            fee_vnd: mq.fee_vnd === "" ? undefined : Number(mq.fee_vnd),
            eta_text: mq.eta_text || undefined,
          }), "Đã báo phí thủ công")}>Lưu phí</button>
        </Row>
        <Row label="Hãng / tracking">
          <input placeholder="hãng" value={carrier.carrier} onChange={(e) => setCarrier({ ...carrier, carrier: e.target.value })} />
          <input placeholder="mã vận đơn" value={carrier.tracking_text} onChange={(e) => setCarrier({ ...carrier, tracking_text: e.target.value })} />
          <button disabled={busy} onClick={() => act(() => post(`/orders/${orderId}/shipment/carrier`, {
            carrier: carrier.carrier || null, tracking_text: carrier.tracking_text || null,
            expected_version: sh ? sh.version : undefined,
          }), "Đã lưu hãng/tracking")}>Lưu</button>
        </Row>
        {sh && (
          <Row label="Chuyển trạng thái">
            {transitions.length === 0 ? <i>(trạng thái cuối)</i> : transitions.map((t) => (
              <button key={t} disabled={busy} onClick={() => act(() => post(`/orders/${orderId}/shipment/status`, {
                to_status: t, expected_version: sh.version,
              }), `Đã chuyển → ${SHIP_LABEL[t] || t}`)}>→ {SHIP_LABEL[t] || t}</button>
            ))}
          </Row>
        )}
        {sh && sh.status === "in_transit" && (
          <Row label="Ghi lần giao">
            <select value={att.result} onChange={(e) => setAtt({ ...att, result: e.target.value })}>
              <option value="success">Giao thành công</option>
              <option value="failed">Thất bại</option>
              <option value="no_contact">Không liên lạc được</option>
              <option value="rescheduled">Hẹn lại</option>
            </select>
            <input placeholder="lý do" value={att.reason} onChange={(e) => setAtt({ ...att, reason: e.target.value })} />
            <input type="datetime-local" value={att.next_contact_at} onChange={(e) => setAtt({ ...att, next_contact_at: e.target.value })} />
            <button disabled={busy} onClick={() => act(() => post(`/orders/${orderId}/shipment/attempt`, {
              result: att.result, reason: att.reason || null, note: att.note || null,
              next_contact_at: att.next_contact_at ? new Date(att.next_contact_at).toISOString() : null,
              command_key: newKey(),
            }), "Đã ghi lần giao")}>Ghi nhận</button>
          </Row>
        )}
        {d.attempts && d.attempts.length > 0 && (
          <div style={{ marginTop: 8, fontSize: 13 }}>
            <b>Các lần giao:</b>
            <ul>{d.attempts.map((a) => (
              <li key={a.attempt_no}>#{a.attempt_no} — {a.result}{a.reason ? ` (${a.reason})` : ""} · {a.recorded_by}</li>
            ))}</ul>
          </div>
        )}
      </Section>

      <Section title="Thu tiền">
        {p ? (
          <>
            <Row label="Phương thức / Trạng thái"><b>{p.method}</b> — {p.status} (phiên bản {p.version})</Row>
            <Row label="Cần thu / Đã nhận">{vnd(p.amount_due_vnd)} / {vnd(p.amount_received_vnd)}</Row>
            {p.status === "discrepancy" && (
              <Row label="⚠ Lệch"><span style={{ color: "#b71c1c" }}>Số nhận khác số cần thu — cần điều chỉnh.</span></Row>
            )}
          </>
        ) : (
          <p>Chưa tạo thanh toán.</p>
        )}
        <Row label="Tạo / phương thức">
          <select value={method} onChange={(e) => setMethod(e.target.value)}>
            <option value="COD">COD (thu khi giao)</option>
            <option value="BANK_TRANSFER">Chuyển khoản</option>
          </select>
          <button disabled={busy} onClick={() => act(() => post(`/orders/${orderId}/payment/ensure`, { method }), "Đã tạo/cập nhật thanh toán")}>Lưu</button>
        </Row>
        {p && p.method === "BANK_TRANSFER" && (
          <Row label="Hướng dẫn CK">
            <button disabled={busy} onClick={() => act(() => post(`/orders/${orderId}/payment/instruction`), "Đã tạo hướng dẫn chuyển khoản")}>Tạo nội dung CK</button>
          </Row>
        )}
        <Row label="Ghi evidence">
          <select value={ev.kind} onChange={(e) => setEv({ ...ev, kind: e.target.value })}>
            <option value="customer_reported">Khách báo đã CK</option>
            <option value="cod_collected">COD: đã thu tiền</option>
            <option value="shop_confirmed_received">Shop xác nhận nhận CK</option>
            <option value="reconciled">Đối soát COD</option>
          </select>
          <input placeholder="số tiền VNĐ" value={ev.amount_vnd} onChange={(e) => setEv({ ...ev, amount_vnd: e.target.value })} style={{ width: 110 }} />
          <input placeholder="mã GD (nếu có)" value={ev.reference} onChange={(e) => setEv({ ...ev, reference: e.target.value })} />
          <input placeholder="ghi chú" value={ev.note} onChange={(e) => setEv({ ...ev, note: e.target.value })} />
          <button disabled={busy} onClick={() => act(() => post(`/orders/${orderId}/payment/evidence`, {
            kind: ev.kind,
            amount_vnd: ev.amount_vnd === "" ? null : Number(ev.amount_vnd),
            reference: ev.reference || null, note: ev.note || null, command_key: newKey(),
          }), "Đã ghi evidence")}>Ghi nhận</button>
        </Row>
        {p && p.status === "discrepancy" && (
          <Row label="Điều chỉnh (±)">
            <input placeholder="delta VNĐ (±)" value={corr.amount_vnd} onChange={(e) => setCorr({ ...corr, amount_vnd: e.target.value })} style={{ width: 120 }} />
            <input placeholder="event gốc (id)" value={corr.corrects_event_id} onChange={(e) => setCorr({ ...corr, corrects_event_id: e.target.value })} style={{ width: 110 }} />
            <input placeholder="lý do (bắt buộc)" value={corr.note} onChange={(e) => setCorr({ ...corr, note: e.target.value })} />
            <button disabled={busy} onClick={() => act(() => post(`/orders/${orderId}/payment/evidence`, {
              kind: "correction", amount_vnd: corr.amount_vnd === "" ? null : Number(corr.amount_vnd),
              corrects_event_id: corr.corrects_event_id === "" ? null : Number(corr.corrects_event_id),
              note: corr.note || null, command_key: newKey(),
            }), "Đã điều chỉnh")}>Điều chỉnh</button>
          </Row>
        )}
        {d.payment_events && d.payment_events.length > 0 && (
          <div style={{ marginTop: 8, fontSize: 13 }}>
            <b>Lịch sử thu tiền:</b>
            <ul>{d.payment_events.map((e, i) => (
              <li key={i}>{e.kind} — {vnd(e.amount_vnd)}{e.reference ? ` · ${e.reference}` : ""}{e.note ? ` · ${e.note}` : ""} · {e.recorded_by}</li>
            ))}</ul>
          </div>
        )}
      </Section>

      <Section title="Tài khoản nhận tiền (cấu hình chung)">
        <Row label="Ngân hàng / STK">
          <input placeholder="ngân hàng" value={bank.bank} onChange={(e) => setBank({ ...bank, bank: e.target.value })} />
          <input placeholder="số tài khoản" value={bank.account_number} onChange={(e) => setBank({ ...bank, account_number: e.target.value })} />
          <input placeholder="chủ TK" value={bank.holder_name} onChange={(e) => setBank({ ...bank, holder_name: e.target.value })} />
          <input placeholder="chi nhánh" value={bank.branch} onChange={(e) => setBank({ ...bank, branch: e.target.value })} />
          <button disabled={busy} onClick={() => act(() => post(`/bank-account`, {
            bank: bank.bank, account_number: bank.account_number, holder_name: bank.holder_name,
            branch: bank.branch || null,
          }), "Đã cập nhật tài khoản nhận")}>Lưu tài khoản</button>
        </Row>
      </Section>
    </div>
  );
}
