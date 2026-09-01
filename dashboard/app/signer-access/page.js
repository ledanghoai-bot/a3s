"use client";

// Directive 91: Signer Access Request (control/approval surface).
// Luong hop nhat: signer-role TAM THOI + activation window. submit -> preflight -> approve
// (SoD: approver != requester -> tach 2 event: provision temp role + issue window) -> close/revoke.
// KHONG nhap PIN/khoa/token o day. Backend enforce RBAC + SoD + fail-closed + digest lock.

import { useEffect, useState } from "react";
import { apiFetch } from "../../lib/api";
import { useAuthGuard } from "../../lib/useAuthGuard";

function fmtTime(t) {
  return t ? new Date(t).toLocaleString("vi-VN") : "—";
}

// State -> nut hop le (phan chieu allowlist TRANSITIONS backend).
const ACTIONS = {
  SUBMITTED: [["preflight", "Chạy Preflight"], ["revoke", "Hủy"]],
  PREFLIGHT_PASSED: [["approve", "Duyệt + Cấp window (SoD)"], ["revoke", "Hủy"]],
  ACTIVE: [["close", "Đóng (Close)"], ["revoke", "Thu hồi (Revoke)"]],
  CLOSED: [],
  EXPIRED: [],
  REVOKED: [],
};

// Quyen tuong ung (khop RBAC backend). Backend van enforce 403 (defense-in-depth); UI an nut = UX.
const ACTION_PERM = {
  preflight: "m4.signer_access.request",
  approve: "m4.signer_access.approve",
  close: "m4.signer_access.approve",
  revoke: "m4.signer_access.approve",
};

export default function SignerAccessPage() {
  const ready = useAuthGuard();
  const [reqs, setReqs] = useState([]);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [perms, setPerms] = useState(null);
  const [pfChecks, setPfChecks] = useState(null);

  const can = (p) => perms === null || perms.includes(p);

  useEffect(() => {
    if (!ready) return;
    loadReqs();
    apiFetch("/dashboard/auth/me")
      .then((me) => setPerms(me.rbac_provisioned ? (me.permissions || []) : null))
      .catch(() => setPerms(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  async function loadReqs() {
    setLoading(true);
    setError(null);
    try {
      setReqs(await apiFetch("/dashboard/signer-access/requests"));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function openDetail(rid) {
    setError(null);
    setPfChecks(null);
    try {
      setDetail(await apiFetch(`/dashboard/signer-access/requests/${rid}`));
    } catch (err) {
      setError(err.message);
    }
  }

  async function createReq(form) {
    setBusy(true);
    setError(null);
    try {
      const body = {
        request_id: form.request_id,
        scope: form.scope ? JSON.parse(form.scope) : {},
        artifact_digest: form.artifact_digest,
        ticket: form.ticket,
        reason: form.reason,
        rollback_owner: form.rollback_owner,
        window_minutes: Number(form.window_minutes || 30),
        is_rehearsal: !!form.is_rehearsal,
      };
      await apiFetch("/dashboard/signer-access/requests", {
        method: "POST", body: JSON.stringify(body),
      });
      setShowCreate(false);
      await loadReqs();
      await openDetail(form.request_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function doAction(rid, action) {
    setBusy(true);
    setError(null);
    try {
      if (action === "preflight") {
        const r = await apiFetch(`/dashboard/signer-access/requests/${rid}/preflight`, { method: "POST" });
        setPfChecks(r.checks || []);
      } else if (action === "approve") {
        if (!window.confirm("Duyệt request? Bạn phải KHÁC người requester (SoD). Sẽ cấp signer-role tạm + activation window.")) { setBusy(false); return; }
        await apiFetch(`/dashboard/signer-access/requests/${rid}/approve`, { method: "POST" });
      } else if (action === "close") {
        if (!window.confirm("Đóng request? Sẽ auto-revoke signer-role tạm + đóng window.")) { setBusy(false); return; }
        await apiFetch(`/dashboard/signer-access/requests/${rid}/close`, { method: "POST" });
      } else if (action === "revoke") {
        const reason = window.prompt("Lý do thu hồi (bắt buộc):");
        if (!reason) { setBusy(false); return; }
        await apiFetch(`/dashboard/signer-access/requests/${rid}/revoke`, {
          method: "POST", body: JSON.stringify({ reason }),
        });
      }
      await loadReqs();
      await openDetail(rid);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!ready) return null;

  return (
    <main style={{ padding: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1>Mở phiên niêm phong — Cấp quyền ký (Signer Access)</h1>
        <div>
          <button onClick={loadReqs} disabled={loading}>Tải lại</button>{" "}
          {can("m4.signer_access.request") && (
            <button className="primary" onClick={() => setShowCreate(!showCreate)}>
              + Gửi request
            </button>
          )}
        </div>
      </div>

      <p style={{ color: "#6b7280", fontSize: 13 }}>
        Request cấp <b>signer-role tạm thời + activation window</b>. Approver phải KHÁC requester (SoD).
        KHÔNG nhập PIN/khóa/token. Backend enforce RBAC/SoD/digest-lock/fail-closed; role tự động thu hồi
        khi close/expire/revoke. Bật <b>Rehearsal</b> để test không cấp quyền thật.
      </p>

      {error && <div className="error-box">{error}</div>}
      {showCreate && <CreateForm onSubmit={createReq} busy={busy} onCancel={() => setShowCreate(false)} />}

      <table style={{ marginTop: 16 }}>
        <thead>
          <tr><th>Request ID</th><th>Trạng thái</th><th>Rehearsal</th><th>Ticket</th><th>Window đến</th><th>Tạo lúc</th><th></th></tr>
        </thead>
        <tbody>
          {reqs.length === 0 && (
            <tr><td colSpan={7} className="empty-state">{loading ? "Đang tải..." : "Chưa có request nào"}</td></tr>
          )}
          {reqs.map((r) => (
            <tr key={r.request_id}>
              <td style={{ fontFamily: "monospace", fontSize: 12 }}>{r.request_id}</td>
              <td><span className={`badge badge-${r.state}`}>{r.state}</span></td>
              <td>{r.is_rehearsal ? "🧪 có" : "—"}</td>
              <td>{r.ticket || "—"}</td>
              <td>{fmtTime(r.window_end)}</td>
              <td>{fmtTime(r.created_at)}</td>
              <td><button onClick={() => openDetail(r.request_id)}>Chi tiết</button></td>
            </tr>
          ))}
        </tbody>
      </table>

      {detail && <DetailPanel req={detail} busy={busy} onAction={doAction} can={can} pfChecks={pfChecks} onClose={() => setDetail(null)} />}
    </main>
  );
}

function CreateForm({ onSubmit, busy, onCancel }) {
  const [form, setForm] = useState({
    request_id: "", scope: '{"tenant":"internal","batch":"eval-1"}',
    artifact_digest: "sha256:", ticket: "", reason: "", rollback_owner: "",
    window_minutes: 30, is_rehearsal: true,
  });
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  return (
    <div style={{ border: "1px solid #e5e7eb", borderRadius: 8, padding: 16, marginTop: 12, background: "#fff" }}>
      <h3>Gửi Signer Access Request</h3>
      <div style={{ display: "grid", gap: 8, maxWidth: 640 }}>
        <label>Request ID <input value={form.request_id} onChange={set("request_id")} placeholder="req-2026..." /></label>
        <label>Artifact digest <input value={form.artifact_digest} onChange={set("artifact_digest")} placeholder="sha256:..." /></label>
        <label>Scope (JSON, KHÔNG secret) <input value={form.scope} onChange={set("scope")} /></label>
        <label>Change ticket <input value={form.ticket} onChange={set("ticket")} /></label>
        <label>Lý do <input value={form.reason} onChange={set("reason")} /></label>
        <label>Rollback owner <input value={form.rollback_owner} onChange={set("rollback_owner")} /></label>
        <label>Window (phút, 1–240) <input type="number" value={form.window_minutes} onChange={set("window_minutes")} style={{ width: 90 }} /></label>
        <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input type="checkbox" checked={form.is_rehearsal}
                 onChange={(e) => setForm({ ...form, is_rehearsal: e.target.checked })} />
          <span>🧪 <b>Rehearsal</b> (test — KHÔNG cấp quyền thật, không chạm KMS/customer data)</span>
        </label>
      </div>
      <div style={{ marginTop: 12 }}>
        <button className="primary" disabled={busy} onClick={() => onSubmit(form)}>Gửi</button>{" "}
        <button disabled={busy} onClick={onCancel}>Đóng</button>
      </div>
    </div>
  );
}

function DetailPanel({ req, busy, onAction, can, pfChecks, onClose }) {
  const actions = (ACTIONS[req.state] || []).filter(([a]) => !can || can(ACTION_PERM[a]));
  return (
    <div style={{ border: "1px solid #d1d5db", borderRadius: 8, padding: 16, marginTop: 16, background: "#fff" }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <h3>{req.request_id} <span className={`badge badge-${req.state}`}>{req.state}</span>
          {req.is_rehearsal && <span style={{ marginLeft: 8, color: "#9a3412" }}>🧪 REHEARSAL</span>}</h3>
        <button onClick={onClose}>Đóng</button>
      </div>
      <div style={{ fontSize: 13, color: "#374151" }}>
        <div>requester: {req.requester_staff_id || "—"} · approver: {req.approver_staff_id || "—"} (phải khác — SoD)</div>
        <div>ticket: {req.ticket || "—"} · window: {req.window_minutes || "—"} phút · đến {fmtTime(req.window_end)}</div>
        <div>activation_id: {req.activation_id ? String(req.activation_id).slice(0, 8) + "…" : "—"} · digest: <span style={{ fontFamily: "monospace", fontSize: 12 }}>{(req.artifact_digest || "").slice(0, 20)}…</span></div>
        {req.terminal_reason && <div>Kết thúc: {req.terminal_reason}</div>}
      </div>

      {pfChecks && (
        <div style={{ margin: "12px 0", padding: 10, background: "#f9fafb", borderRadius: 6 }}>
          <b style={{ fontSize: 13 }}>Preflight checklist:</b>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: 13 }}>
            {pfChecks.map((c) => (
              <li key={c.name} style={{ color: c.passed ? "#14532d" : "#7f1d1d" }}>
                {c.passed ? "✓" : "✗"} <b>{c.name}</b> — {c.detail}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div style={{ margin: "12px 0" }}>
        {actions.length === 0 && <span className="empty-state">Trạng thái kết thúc — không còn hành động</span>}
        {actions.map(([a, label]) => (
          <button key={a} className={a === "revoke" ? "" : "primary"} disabled={busy}
                  style={{ marginRight: 8 }} onClick={() => onAction(req.request_id, a)}>
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
