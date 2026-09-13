"use client";

// M6 Giao & Thu tiền — chi tiết 1 đơn + thao tác (CA Directive 265 + Review 266/267).
// Quote (auto/thủ công), hãng/tracking, chuyển trạng thái giao, ghi lần giao; tạo payment, hướng dẫn CK
// (render + copy), ghi evidence, điều chỉnh discrepancy (chọn event gốc từ lịch sử), cấu hình TK nhận.
//
// CA 267-01: idempotency key ỔN ĐỊNH qua retry/reload — key sinh theo (action, payload fingerprint), lưu
// sessionStorage, RETRY cùng payload DÙNG LẠI key, chỉ consume sau khi SUCCESS. Đổi payload → key mới.
// Backend từ chối cùng key khác payload (fingerprint mismatch) nên double-submit/ambiguous-retry an toàn.
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiFetch } from "../../../lib/api";
import { useAuthGuard } from "../../../lib/useAuthGuard";

function vnd(n) {
  return n == null ? "—" : n.toLocaleString("vi-VN") + "đ";
}
function newUuid() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return "k-" + Date.now() + "-" + Math.random().toString(36).slice(2);
}
function hashStr(s) {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
  return h.toString(36);
}
// CA 267-01: key ổn định theo (sig, payload). Lưu sessionStorage → retry/reload cùng payload tái dùng key.
function opKey(sig, payload) {
  const store = `m6op:${sig}:${hashStr(JSON.stringify(payload))}`;
  let k = null;
  try {
    k = sessionStorage.getItem(store);
  } catch {
    /* private mode */
  }
  if (!k) {
    k = newUuid();
    try {
      sessionStorage.setItem(store, k);
    } catch {
      /* ignore */
    }
  }
  return {
    key: k,
    consume: () => {
      try {
        sessionStorage.removeItem(store);
      } catch {
        /* ignore */
      }
    },
  };
}
async function copyText(t) {
  // Async Clipboard API (cần secure context + focus). Fallback execCommand cho môi trường chặn API.
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(t);
      return true;
    }
  } catch {
    /* rơi xuống fallback */
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = t;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
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
  // CA 267-01: consume chỉ chạy sau success → retry (network/timeout) tái dùng key; 4xx dứt khoát không reload.
  async function act(fn, okMsg, consume) {
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      await fn();
      if (consume) consume();
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
  const instr = d.payment_instruction;
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
            <button disabled={busy} onClick={() => {
              const payload = {
                result: att.result, reason: att.reason || null, note: att.note || null,
                next_contact_at: att.next_contact_at ? new Date(att.next_contact_at).toISOString() : null,
              };
              const { key, consume } = opKey(`attempt:${orderId}`, payload);
              act(() => post(`/orders/${orderId}/shipment/attempt`, { ...payload, command_key: key }),
                "Đã ghi lần giao", consume);
            }}>Ghi nhận</button>
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
        {/* CA 267-05: render snapshot instruction + copy từng trường */}
        {instr && (
          <div style={{ marginTop: 8, padding: 12, background: "#f6f8fa", borderRadius: 6, fontSize: 14 }}>
            <div style={{ marginBottom: 6 }}>
              <b>Hướng dẫn chuyển khoản</b>{instr.is_test ? <span style={{ color: "#b71c1c", marginLeft: 8 }}>[TEST — KHÔNG CHUYỂN TIỀN]</span> : null}
            </div>
            {[["Ngân hàng", instr.bank_snapshot], ["Số TK", instr.account_number_snapshot],
              ["Chủ TK", instr.holder_snapshot], ["Số tiền", vnd(instr.amount_vnd)],
              ["Nội dung", instr.transfer_content]].map(([k, v]) => (
              <div key={k} style={{ display: "flex", gap: 8, alignItems: "center", margin: "3px 0" }}>
                <span style={{ minWidth: 90, color: "#555" }}>{k}:</span>
                <code>{v}</code>
                <button onClick={async () => { (await copyText(String(v))) ? setMsg(`Đã copy ${k}`) : setError("Không copy được"); }}>Copy</button>
              </div>
            ))}
            <button style={{ marginTop: 6 }} onClick={async () => {
              const block = `Ngân hàng: ${instr.bank_snapshot}\nSố TK: ${instr.account_number_snapshot}\n`
                + `Chủ TK: ${instr.holder_snapshot}\nSố tiền: ${vnd(instr.amount_vnd)}\nNội dung: ${instr.transfer_content}`;
              (await copyText(block)) ? setMsg("Đã copy toàn bộ hướng dẫn") : setError("Không copy được");
            }}>Copy toàn bộ</button>
          </div>
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
          <button disabled={busy} onClick={() => {
            const payload = {
              kind: ev.kind, amount_vnd: ev.amount_vnd === "" ? null : Number(ev.amount_vnd),
              reference: ev.reference || null, note: ev.note || null,
            };
            const { key, consume } = opKey(`evidence:${orderId}`, payload);
            act(() => post(`/orders/${orderId}/payment/evidence`, { ...payload, command_key: key }),
              "Đã ghi evidence", consume);
          }}>Ghi nhận</button>
        </Row>
        {p && p.status === "discrepancy" && (
          <Row label="Điều chỉnh (±)">
            <input placeholder="delta VNĐ (±)" value={corr.amount_vnd} onChange={(e) => setCorr({ ...corr, amount_vnd: e.target.value })} style={{ width: 120 }} />
            {/* CA 267-05: chọn event gốc từ lịch sử, không bắt PO đoán id */}
            <select value={corr.corrects_event_id} onChange={(e) => setCorr({ ...corr, corrects_event_id: e.target.value })}>
              <option value="">— chọn event gốc —</option>
              {(d.payment_events || []).filter((e) => e.kind !== "correction").map((e) => (
                <option key={e.id} value={e.id}>#{e.id} {e.kind} {vnd(e.amount_vnd)}{e.reference ? ` · ${e.reference}` : ""}</option>
              ))}
            </select>
            <input placeholder="lý do (bắt buộc)" value={corr.note} onChange={(e) => setCorr({ ...corr, note: e.target.value })} />
            <button disabled={busy} onClick={() => {
              const payload = {
                kind: "correction", amount_vnd: corr.amount_vnd === "" ? null : Number(corr.amount_vnd),
                corrects_event_id: corr.corrects_event_id === "" ? null : Number(corr.corrects_event_id),
                note: corr.note || null,
              };
              const { key, consume } = opKey(`correction:${orderId}`, payload);
              act(() => post(`/orders/${orderId}/payment/evidence`, { ...payload, command_key: key }),
                "Đã điều chỉnh", consume);
            }}>Điều chỉnh</button>
          </Row>
        )}
        {d.payment_events && d.payment_events.length > 0 && (
          <div style={{ marginTop: 8, fontSize: 13 }}>
            <b>Lịch sử thu tiền:</b>
            <ul>{d.payment_events.map((e) => (
              <li key={e.id}>#{e.id} {e.kind} — {vnd(e.amount_vnd)}{e.reference ? ` · ${e.reference}` : ""}
                {e.corrects_event_id ? ` · sửa #${e.corrects_event_id}` : ""}{e.note ? ` · ${e.note}` : ""} · {e.recorded_by}</li>
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
