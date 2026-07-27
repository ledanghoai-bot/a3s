"use client";

// I-B M2 (Slice 6): trang Kho — balances + reconciliation + hàng đợi điều chỉnh (approve/reject).
// Đọc dữ liệu từ backend (đã redact/committed). Mutation đi qua command service với Idempotency-Key;
// backend enforce RBAC (inventory.view / .movement.view / .reconcile / .adjust / .adjust.approve) +
// SoD/Unit Head + audit fail-closed. UI chỉ hiển thị + gọi lệnh, KHÔNG tự quyết tồn.

import { useEffect, useState } from "react";
import { apiFetch } from "../../lib/api";
import { useAuthGuard } from "../../lib/useAuthGuard";

function idemKey() {
  return (typeof crypto !== "undefined" && crypto.randomUUID)
    ? crypto.randomUUID()
    : `idem-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
}

export default function InventoryPage() {
  const ready = useAuthGuard();
  const [tab, setTab] = useState("balances");
  const [balances, setBalances] = useState([]);
  const [recon, setRecon] = useState(null);
  const [adjustments, setAdjustments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busyId, setBusyId] = useState(null);

  useEffect(() => {
    if (!ready) return;
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, tab]);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      if (tab === "balances") setBalances(await apiFetch("/dashboard/inventory/balances"));
      else if (tab === "reconciliation") setRecon(await apiFetch("/dashboard/inventory/reconciliation"));
      else if (tab === "adjustments") setAdjustments(await apiFetch("/dashboard/inventory/adjustments?status=pending"));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function decide(id, action) {
    if (action === "reject" && !window.confirm("Từ chối điều chỉnh này?")) return;
    setBusyId(id);
    setMsg(null);
    setError(null);
    try {
      const opts = { method: "POST", headers: { "Idempotency-Key": idemKey() } };
      if (action === "reject") opts.body = JSON.stringify({ reason: "rejected by unit head" });
      await apiFetch(`/dashboard/inventory/adjustments/${id}/${action}`, opts);
      setMsg(`Điều chỉnh ${id.slice(0, 8)} đã ${action === "approve" ? "duyệt" : "từ chối"}.`);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyId(null);
    }
  }

  if (!ready) return null;

  return (
    <div style={{ padding: 24 }}>
      <h1>Kho / Tồn</h1>
      <div style={{ display: "flex", gap: 8, margin: "12px 0" }}>
        {["balances", "reconciliation", "adjustments"].map((t) => (
          <button key={t} onClick={() => setTab(t)}
            style={{ fontWeight: tab === t ? 700 : 400 }}>
            {t === "balances" ? "Số dư tồn" : t === "reconciliation" ? "Đối soát" : "Điều chỉnh chờ duyệt"}
          </button>
        ))}
        <button onClick={load} disabled={loading}>↻ Tải lại</button>
      </div>

      {error && <p style={{ color: "crimson" }}>Lỗi: {error}</p>}
      {msg && <p style={{ color: "green" }}>{msg}</p>}
      {loading && <p>Đang tải…</p>}

      {tab === "balances" && (
        <table border="1" cellPadding="6" style={{ borderCollapse: "collapse" }}>
          <thead><tr><th>Location</th><th>SKU</th><th>On hand</th><th>Reserved</th><th>Available</th></tr></thead>
          <tbody>
            {balances.map((b, i) => (
              <tr key={i}><td>{b.location}</td><td>{b.sku}</td><td>{b.on_hand}</td>
                <td>{b.reserved}</td><td>{b.available}</td></tr>
            ))}
            {!balances.length && !loading && <tr><td colSpan="5">Chưa có số dư tồn.</td></tr>}
          </tbody>
        </table>
      )}

      {tab === "reconciliation" && recon && (
        <div>
          <p>Đã kiểm: <b>{recon.balances_checked}</b> balance — {" "}
            {recon.ok
              ? <span style={{ color: "green" }}>✓ Khớp (ledger = balance = reservation, stock = available)</span>
              : <span style={{ color: "crimson" }}>✗ {recon.mismatches.length} sai lệch</span>}
          </p>
          {!recon.ok && (
            <ul>{recon.mismatches.map((m, i) => <li key={i} style={{ color: "crimson" }}>{m}</li>)}</ul>
          )}
        </div>
      )}

      {tab === "adjustments" && (
        <table border="1" cellPadding="6" style={{ borderCollapse: "collapse" }}>
          <thead><tr><th>ID</th><th>Loc</th><th>SP</th><th>Δ</th><th>Lớn?</th><th>Lý do</th><th>Người yêu cầu</th><th></th></tr></thead>
          <tbody>
            {adjustments.map((a) => (
              <tr key={a.id}>
                <td>{a.id.slice(0, 8)}</td><td>{a.location_id}</td><td>{a.product_id}</td>
                <td>{a.quantity_delta}</td><td>{a.is_large ? "Lớn" : "Nhỏ"}</td>
                <td>{a.reason}</td><td>{a.requested_by_staff_id}</td>
                <td>
                  <button disabled={busyId === a.id} onClick={() => decide(a.id, "approve")}>Duyệt</button>{" "}
                  <button disabled={busyId === a.id} onClick={() => decide(a.id, "reject")}>Từ chối</button>
                </td>
              </tr>
            ))}
            {!adjustments.length && !loading && <tr><td colSpan="8">Không có điều chỉnh chờ duyệt.</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  );
}
