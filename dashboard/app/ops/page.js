"use client";

// I-B M1 (Slice 9): trang Van hanh — command executions + outbox events + recovery actions.
// Doc du lieu da redact tu backend (§10.3). Retry/Cancel/Replay yeu cau ly do; backend enforce
// RBAC (commands.view / outbox.view / outbox.retry|cancel|replay) + audit fail-closed.

import { useEffect, useState } from "react";
import { apiFetch } from "../../lib/api";
import { useAuthGuard } from "../../lib/useAuthGuard";

const OUTBOX_STATUSES = ["", "pending", "delivering", "delivered", "retry_scheduled", "dead_lettered", "cancelled"];
const CMD_STATUSES = ["", "accepted", "processing", "succeeded", "failed_terminal"];

function fmtTime(t) {
  return t ? new Date(t).toLocaleString("vi-VN") : "—";
}

export default function OpsPage() {
  const ready = useAuthGuard();
  const [tab, setTab] = useState("outbox");
  const [outbox, setOutbox] = useState([]);
  const [commands, setCommands] = useState([]);
  const [obStatus, setObStatus] = useState("");
  const [cmdStatus, setCmdStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [detail, setDetail] = useState(null);

  useEffect(() => {
    if (!ready) return;
    if (tab === "outbox") loadOutbox();
    else loadCommands();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, tab, obStatus, cmdStatus]);

  async function loadOutbox() {
    setLoading(true);
    setError(null);
    try {
      const q = obStatus ? `?status=${obStatus}` : "";
      setOutbox(await apiFetch(`/dashboard/outbox${q}`));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadCommands() {
    setLoading(true);
    setError(null);
    try {
      const q = cmdStatus ? `?status=${cmdStatus}` : "";
      setCommands(await apiFetch(`/dashboard/commands${q}`));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function openDetail(id) {
    try {
      setDetail(await apiFetch(`/dashboard/outbox/${id}`));
    } catch (err) {
      alert("Lỗi: " + err.message);
    }
  }

  async function action(id, kind) {
    const reason = window.prompt(`Lý do ${kind} (bắt buộc):`);
    if (!reason) return;
    setBusyId(id);
    try {
      await apiFetch(`/dashboard/outbox/${id}/${kind}`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      });
      await loadOutbox();
      if (detail && detail.id === id) await openDetail(id);
    } catch (err) {
      alert("Lỗi: " + err.message);
    } finally {
      setBusyId(null);
    }
  }

  if (!ready) return null;

  return (
    <div>
      <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, marginRight: 8 }}>Vận hành (M1)</h1>
        <button className={tab === "outbox" ? "primary" : ""} onClick={() => setTab("outbox")}>
          Outbox
        </button>
        <button className={tab === "commands" ? "primary" : ""} onClick={() => setTab("commands")}>
          Commands
        </button>
      </div>

      {error && <div className="error-box">{error}</div>}

      {tab === "outbox" && (
        <>
          <div style={{ marginBottom: 12 }}>
            Trạng thái:{" "}
            <select value={obStatus} onChange={(e) => setObStatus(e.target.value)}>
              {OUTBOX_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s || "(tất cả)"}
                </option>
              ))}
            </select>{" "}
            <button onClick={loadOutbox}>Tải lại</button>
          </div>
          {loading ? (
            <div className="empty-state">Đang tải...</div>
          ) : outbox.length === 0 ? (
            <div className="empty-state">Không có outbox event nào.</div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Đích</th>
                  <th>Loại</th>
                  <th>Trạng thái</th>
                  <th>Attempt</th>
                  <th>Lỗi cuối</th>
                  <th>Cập nhật</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {outbox.map((e) => (
                  <tr key={e.id}>
                    <td>{e.destination}</td>
                    <td style={{ fontSize: 13 }}>{e.event_type}</td>
                    <td>
                      <span className={`badge badge-${e.status}`}>{e.status}</span>
                    </td>
                    <td>
                      {e.attempt_count}/{e.max_attempts}
                    </td>
                    <td style={{ fontSize: 12, color: "#c0392b" }}>{e.last_error_code || "—"}</td>
                    <td style={{ fontSize: 12, color: "#666" }}>{fmtTime(e.updated_at)}</td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      <button onClick={() => openDetail(e.id)}>Chi tiết</button>{" "}
                      {e.status === "dead_lettered" && (
                        <>
                          <button disabled={busyId === e.id} onClick={() => action(e.id, "retry")}>
                            Retry
                          </button>{" "}
                          <button disabled={busyId === e.id} onClick={() => action(e.id, "replay")}>
                            Replay
                          </button>{" "}
                        </>
                      )}
                      {e.status !== "delivered" && e.status !== "cancelled" && (
                        <button disabled={busyId === e.id} onClick={() => action(e.id, "cancel")}>
                          Cancel
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}

      {tab === "commands" && (
        <>
          <div style={{ marginBottom: 12 }}>
            Trạng thái:{" "}
            <select value={cmdStatus} onChange={(e) => setCmdStatus(e.target.value)}>
              {CMD_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s || "(tất cả)"}
                </option>
              ))}
            </select>{" "}
            <button onClick={loadCommands}>Tải lại</button>
          </div>
          {loading ? (
            <div className="empty-state">Đang tải...</div>
          ) : commands.length === 0 ? (
            <div className="empty-state">Không có command nào.</div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Loại</th>
                  <th>Trạng thái</th>
                  <th>Kênh</th>
                  <th>Resource</th>
                  <th>Lỗi</th>
                  <th>Tạo lúc</th>
                </tr>
              </thead>
              <tbody>
                {commands.map((c) => (
                  <tr key={c.id}>
                    <td>
                      {c.command_type} v{c.command_version}
                    </td>
                    <td>
                      <span className={`badge badge-${c.status}`}>{c.status}</span>
                    </td>
                    <td>{c.channel}</td>
                    <td>{c.resource_id ? `${c.resource_type} #${c.resource_id}` : "—"}</td>
                    <td style={{ fontSize: 12, color: "#c0392b" }}>{c.error_code || "—"}</td>
                    <td style={{ fontSize: 12, color: "#666" }}>{fmtTime(c.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}

      {detail && (
        <div className="detail-panel" style={{ marginTop: 20, borderTop: "1px solid #ddd", paddingTop: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <h2 style={{ fontSize: 16 }}>
              Chi tiết outbox · <span className={`badge badge-${detail.status}`}>{detail.status}</span>
            </h2>
            <button onClick={() => setDetail(null)}>Đóng</button>
          </div>
          <div style={{ fontSize: 13, color: "#444", margin: "8px 0" }}>
            {detail.destination} · {detail.event_type} · dedupe: {detail.dedupe_key}
          </div>
          <pre style={{ background: "#f6f6f6", padding: 10, fontSize: 12, overflowX: "auto" }}>
            {JSON.stringify(detail.payload, null, 2)}
          </pre>
          <h3 style={{ fontSize: 14, marginTop: 12 }}>Lịch sử gửi ({detail.attempts.length})</h3>
          {detail.attempts.length === 0 ? (
            <div className="empty-state">Chưa có lần gửi nào.</div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Kết quả</th>
                  <th>HTTP</th>
                  <th>Provider ID</th>
                  <th>Lỗi</th>
                  <th>ms</th>
                  <th>Lúc</th>
                </tr>
              </thead>
              <tbody>
                {detail.attempts.map((a) => (
                  <tr key={a.attempt_no}>
                    <td>{a.attempt_no}</td>
                    <td>
                      <span className={`badge badge-${a.outcome}`}>{a.outcome}</span>
                    </td>
                    <td>{a.http_status || "—"}</td>
                    <td style={{ fontSize: 12 }}>{a.provider_message_id || "—"}</td>
                    <td style={{ fontSize: 12, color: "#c0392b" }}>{a.error_class || "—"}</td>
                    <td>{a.duration_ms ?? "—"}</td>
                    <td style={{ fontSize: 12, color: "#666" }}>{fmtTime(a.started_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
