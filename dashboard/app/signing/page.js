"use client";

// M4-9: Dashboard-triggered Production Signing Run (control/approval surface).
// Xem docs/M4-9-DASHBOARD-TRIGGER-DESIGN-VI.md. Trang nay CHI la control surface:
// tao run -> confirm -> preflight -> ceremony (public metadata) -> canary approve -> execute.
// KHONG nhap PIN/khoa/token o day. Backend enforce RBAC + SoD + fail-closed.

import { useEffect, useState } from "react";
import { apiFetch } from "../../lib/api";
import { useAuthGuard } from "../../lib/useAuthGuard";

function fmtTime(t) {
  return t ? new Date(t).toLocaleString("vi-VN") : "—";
}

// State -> nut hanh dong hop le (phan chieu allowlist TRANSITIONS o backend).
const ACTIONS = {
  CREATED: [["confirm", "Xác nhận (Confirm)"], ["abort", "Hủy (Abort)"]],
  CONFIRMED: [["preflight", "Chạy Preflight"], ["abort", "Hủy"]],
  PREFLIGHT_PASSED: [["ceremony", "Ghi Ceremony (metadata công khai)"], ["abort", "Hủy"]],
  CEREMONY_RECORDED: [["canary-request", "Yêu cầu Canary"], ["abort", "Hủy"]],
  CANARY_PENDING: [["canary-approve", "Duyệt Canary (SoD)"], ["abort", "Hủy"]],
  CANARY_APPROVED: [["execute", "Thực thi (Execute)"], ["abort", "Hủy"]],
  EXECUTING: [["abort", "Abort (break-glass)"]],
  CLOSED: [],
  ABORTED: [],
  FAILED: [],
};

// Quyen tuong ung tung action (khop RBAC backend). Backend van enforce 403 (defense in depth);
// UI an nut chi la UX (M4-9 tracked action #3).
const ACTION_PERM = {
  confirm: "m4.signing.run.start",
  preflight: "m4.signing.run.operate",
  ceremony: "m4.signing.run.operate",
  "canary-request": "m4.signing.run.operate",
  "canary-approve": "m4.signing.run.approve",
  execute: "m4.signing.run.operate",
  abort: "m4.signing.run.abort",
};

export default function SigningPage() {
  const ready = useAuthGuard();
  const [runs, setRuns] = useState([]);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [perms, setPerms] = useState(null); // null = chua biet -> khong an (backend van chan)
  const [pfChecks, setPfChecks] = useState(null); // preflight checklist gan nhat (xanh/do)

  const can = (p) => perms === null || perms.includes(p);

  useEffect(() => {
    if (!ready) return;
    loadRuns();
    apiFetch("/dashboard/auth/me")
      .then((me) => setPerms(me.rbac_provisioned ? (me.permissions || []) : null))
      .catch(() => setPerms(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  async function loadRuns() {
    setLoading(true);
    setError(null);
    try {
      setRuns(await apiFetch("/dashboard/signing/runs"));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function openDetail(runId) {
    setError(null);
    setPfChecks(null);
    try {
      setDetail(await apiFetch(`/dashboard/signing/runs/${runId}`));
    } catch (err) {
      setError(err.message);
    }
  }

  async function createRun(form) {
    setBusy(true);
    setError(null);
    try {
      const body = {
        run_kind: form.run_kind || "evidence_batch",
        change_ticket: form.change_ticket || null,
        scope: form.scope ? JSON.parse(form.scope) : {},
        data_boundary: form.data_boundary ? JSON.parse(form.data_boundary) : {},
        window_start: form.window_start || null,
        window_end: form.window_end || null,
        quota_sts: Number(form.quota_sts || 3),
        quota_sign: Number(form.quota_sign || 3),
      };
      const run = await apiFetch("/dashboard/signing/runs", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setShowCreate(false);
      await loadRuns();
      await openDetail(run.run_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function doAction(runId, action, state) {
    setBusy(true);
    setError(null);
    try {
      if (action === "abort") {
        const reason = window.prompt("Lý do abort (bắt buộc):");
        if (!reason) { setBusy(false); return; }
        await apiFetch(`/dashboard/signing/runs/${runId}/abort`, {
          method: "POST", body: JSON.stringify({ reason }),
        });
      } else if (action === "confirm") {
        if (!window.confirm("Xác nhận plan của run này?")) { setBusy(false); return; }
        await apiFetch(`/dashboard/signing/runs/${runId}/confirm`, {
          method: "POST", body: JSON.stringify({}),
        });
      } else if (action === "preflight") {
        const r = await apiFetch(`/dashboard/signing/runs/${runId}/preflight`, { method: "POST" });
        // Hien checklist xanh/do ngay tren man hinh — operator ĐỌC, khong phai NHỚ tien dieu kien.
        setPfChecks(r.preflight?.checks || []);
      } else if (action === "ceremony") {
        const fp = window.prompt("Fingerprint/serial cert (metadata CÔNG KHAI — KHÔNG nhập PIN/khóa):");
        if (fp == null) { setBusy(false); return; }
        await apiFetch(`/dashboard/signing/runs/${runId}/ceremony`, {
          method: "POST",
          body: JSON.stringify({ public_metadata: { cert_fingerprint: fp } }),
        });
      } else if (action === "canary-request") {
        await apiFetch(`/dashboard/signing/runs/${runId}/canary-request`, { method: "POST" });
      } else if (action === "canary-approve") {
        if (!window.confirm("Duyệt canary? Bạn phải KHÁC người operator (SoD).")) { setBusy(false); return; }
        await apiFetch(`/dashboard/signing/runs/${runId}/canary-approve`, {
          method: "POST", body: JSON.stringify({}),
        });
      } else if (action === "execute") {
        const manifest = window.prompt("Đường dẫn manifest (synthetic):");
        if (!manifest) { setBusy(false); return; }
        const approval_ref = window.prompt("approval_ref:");
        if (!approval_ref) { setBusy(false); return; }
        const reviewer = window.prompt("reviewer_staff_id:");
        if (!reviewer) { setBusy(false); return; }
        await apiFetch(`/dashboard/signing/runs/${runId}/execute`, {
          method: "POST",
          body: JSON.stringify({ manifest, approval_ref, reviewer_staff_id: Number(reviewer) }),
        });
      }
      await loadRuns();
      await openDetail(runId);
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
        <h1>Thực hiện niêm phong — Ký transcript (Signing Run)</h1>
        <div>
          <button onClick={loadRuns} disabled={loading}>Tải lại</button>{" "}
          {can("m4.signing.run.start") && (
            <button className="primary" onClick={() => setShowCreate(!showCreate)}>
              + Start Production Signing Run
            </button>
          )}
        </div>
      </div>

      <p style={{ color: "#6b7280", fontSize: 13 }}>
        Trang này là <b>control/approval surface</b>. Không nhập PIN/khóa/token ở đây — ceremony USB
        và secret nằm ngoài luồng. Backend enforce RBAC, SoD (approve≠operator) và fail-closed.
      </p>

      {error && <div className="error-box">{error}</div>}

      {showCreate && <CreateForm onSubmit={createRun} busy={busy} onCancel={() => setShowCreate(false)} />}

      <table style={{ marginTop: 16 }}>
        <thead>
          <tr>
            <th>Run ID</th><th>Trạng thái</th><th>Loại</th><th>Ticket</th><th>Tạo lúc</th><th></th>
          </tr>
        </thead>
        <tbody>
          {runs.length === 0 && (
            <tr><td colSpan={6} className="empty-state">{loading ? "Đang tải..." : "Chưa có run nào"}</td></tr>
          )}
          {runs.map((r) => (
            <tr key={r.run_id}>
              <td style={{ fontFamily: "monospace", fontSize: 12 }}>{r.run_id.slice(0, 8)}…</td>
              <td><span className={`badge badge-${r.state}`}>{r.state}</span></td>
              <td>{r.run_kind}</td>
              <td>{r.change_ticket || "—"}</td>
              <td>{fmtTime(r.created_at)}</td>
              <td><button onClick={() => openDetail(r.run_id)}>Chi tiết</button></td>
            </tr>
          ))}
        </tbody>
      </table>

      {detail && <DetailPanel detail={detail} busy={busy} onAction={doAction} can={can} pfChecks={pfChecks} onClose={() => setDetail(null)} />}
    </main>
  );
}

function CreateForm({ onSubmit, busy, onCancel }) {
  const [form, setForm] = useState({
    run_kind: "evidence_batch", change_ticket: "", scope: '{"batch_size":100}',
    data_boundary: '{"scope":"internal-eval"}',
    window_start: "", window_end: "", quota_sts: 3, quota_sign: 3,
  });
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const tierA = form.run_kind === "evidence_batch";
  return (
    <div style={{ border: "1px solid #e5e7eb", borderRadius: 8, padding: 16, marginTop: 12, background: "#fff" }}>
      <h3>Tạo Signing Run</h3>
      <div style={{ display: "grid", gap: 8, maxWidth: 640 }}>
        <label>Loại run{" "}
          <select value={form.run_kind} onChange={set("run_kind")}>
            <option value="evidence_batch">Tier A — Routine evidence batch (1 người)</option>
            <option value="production">Tier B — Production KMS (SoD + ceremony)</option>
            <option value="synthetic_rehearsal">Synthetic rehearsal (test)</option>
          </select>
        </label>
        <div style={{ fontSize: 12, color: tierA ? "#065f46" : "#9a3412" }}>
          {tierA
            ? "Tier A: 1 operator, không SoD/USB. Tự nâng Tier B nếu non-repudiation / PII ngoài scope / batch>260 / quota>5."
            : "Tier B: bắt buộc SoD (approve≠operate) + ceremony + Ed25519-KMS."}
        </div>
        <label>Change ticket <input value={form.change_ticket} onChange={set("change_ticket")} /></label>
        <label>Scope (JSON) <input value={form.scope} onChange={set("scope")} /></label>
        <label>Data boundary (JSON) <input value={form.data_boundary} onChange={set("data_boundary")} /></label>
        <label>Window start (ISO UTC) <input value={form.window_start} onChange={set("window_start")} placeholder="2026-08-28T01:15:00Z" /></label>
        <label>Window end (ISO UTC) <input value={form.window_end} onChange={set("window_end")} placeholder="2026-08-28T03:15:00Z" /></label>
        <div style={{ display: "flex", gap: 8 }}>
          <label>Quota STS <input type="number" value={form.quota_sts} onChange={set("quota_sts")} style={{ width: 70 }} /></label>
          <label>Quota sign <input type="number" value={form.quota_sign} onChange={set("quota_sign")} style={{ width: 70 }} /></label>
        </div>
      </div>
      <div style={{ marginTop: 12 }}>
        <button className="primary" disabled={busy} onClick={() => onSubmit(form)}>Tạo</button>{" "}
        <button disabled={busy} onClick={onCancel}>Đóng</button>
      </div>
    </div>
  );
}

function DetailPanel({ detail, busy, onAction, can, pfChecks, onClose }) {
  const run = detail.run;
  // Loc action theo quyen (backend van enforce 403). can=undefined -> hien het.
  const actions = (ACTIONS[run.state] || []).filter(
    ([a]) => !can || can(ACTION_PERM[a]),
  );
  const fresh = detail.preflight_fresh || {};
  return (
    <div style={{ border: "1px solid #d1d5db", borderRadius: 8, padding: 16, marginTop: 16, background: "#fff" }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <h3>Run {run.run_id.slice(0, 8)}… <span className={`badge badge-${run.state}`}>{run.state}</span></h3>
        <button onClick={onClose}>Đóng</button>
      </div>
      <div style={{ fontSize: 13, color: "#374151" }}>
        <div>Loại: <b>{run.run_kind}</b>{run.escalation_flags?.length ? ` (đã nâng cấp: ${run.escalation_flags.join(", ")})` : ""} · Ticket: {run.change_ticket || "—"}</div>
        <div>operator: {run.operator_staff_id || "—"} · approver: {run.approver_staff_id || "—"}</div>
        <div>Quota: STS {detail.attempt_counts?.sts || 0}/{run.quota_sts} · sign {detail.attempt_counts?.sign || 0}/{run.quota_sign}</div>
        <div>Preflight tươi: {fresh.ok ? "✓" : "✗"} ({fresh.detail})</div>
      </div>

      {/* Preflight checklist — operator ĐỌC xanh/đỏ, không phải NHỚ tiền điều kiện */}
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
          <button key={a} className={a === "abort" ? "" : "primary"} disabled={busy}
                  style={{ marginRight: 8 }} onClick={() => onAction(run.run_id, a, run.state)}>
            {label}
          </button>
        ))}
      </div>

      <h4>Lịch sử sự kiện</h4>
      <table>
        <thead><tr><th>Sự kiện</th><th>Từ→Đến</th><th>Actor</th><th>Lý do</th><th>Lúc</th></tr></thead>
        <tbody>
          {(detail.events || []).map((e, i) => (
            <tr key={i}>
              <td>{e.event_type}</td>
              <td>{e.from_state || "—"} → {e.to_state || "—"}</td>
              <td>{e.actor_staff_id ?? "system"}</td>
              <td>{e.reason || "—"}</td>
              <td>{fmtTime(e.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
