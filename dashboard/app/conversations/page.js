"use client";

import { useEffect, useRef, useState, Fragment } from "react";
import { apiFetch } from "../../lib/api";
import { useAuthGuard } from "../../lib/useAuthGuard";

const POLL_INTERVAL_MS = 5000;

export default function ConversationsPage() {
  const ready = useAuthGuard();
  const [conversations, setConversations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busyPsid, setBusyPsid] = useState(null);

  // Mo rong 1 hoi thoai ngay trong trang (khong chuyen trang) - issue #8 nang cap
  const [expandedPsid, setExpandedPsid] = useState(null);
  const [expandedMessages, setExpandedMessages] = useState([]);
  const [expandedLoading, setExpandedLoading] = useState(false);
  const [expandedDraft, setExpandedDraft] = useState(null); // {customer, active_override, overrides[], notes[]}

  const busyRef = useRef(busyPsid);
  busyRef.current = busyPsid;

  useEffect(() => {
    if (!ready) return;
    load(); // lan dau: co hien "Dang tai..."

    // Auto-refresh moi 5s de thay ngay khi trang thai handover doi (vd khach
    // moi bi escalate, hoac nhan vien resume tu Telegram) - khong can F5 tay.
    const interval = setInterval(() => {
      if (busyRef.current) return; // dang bam nut o 1 dong nao do thi bo qua tick nay
      loadSilent();
      if (expandedPsid) {
        loadExpandedMessages(expandedPsid, /* silent */ true);
        loadExpandedDraft(expandedPsid);
      }
    }, POLL_INTERVAL_MS);

    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, expandedPsid]);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch("/dashboard/conversations");
      setConversations(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  // Refresh nen, khong bat loading spinner toan trang (tranh nhap nhay UI moi 5s)
  async function loadSilent() {
    try {
      const data = await apiFetch("/dashboard/conversations");
      setConversations(data);
    } catch (err) {
      console.warn("Auto-refresh loi (bo qua, giu du lieu cu):", err.message);
    }
  }

  async function togglePause(psid, isPaused) {
    let note = null;
    if (isPaused) {
      // Dang paused -> sap resume: hoi ghi chu tuy chon (vd sep vua chot chinh
      // sach dac biet qua dien thoai/ngoai Messenger) - bot se dung ghi chu nay
      // o cac luot chat sau, tranh noi trai thoa thuan (issue #8).
      note = window.prompt(
        "Ghi chú thoả thuận (tuỳ chọn) — để trống nếu không có gì cần lưu ý cho bot:",
        ""
      );
      if (note === null) return; // bam Cancel -> huy thao tac, khong resume
    }

    setBusyPsid(psid);
    try {
      const path = isPaused
        ? `/dashboard/conversations/${encodeURIComponent(psid)}/resume`
        : `/dashboard/conversations/${encodeURIComponent(psid)}/pause`;
      const options = { method: "POST" };
      if (isPaused && note && note.trim()) {
        options.body = JSON.stringify({ note: note.trim() });
      }
      await apiFetch(path, options);
      await load();
    } catch (err) {
      alert("Lỗi: " + err.message);
    } finally {
      setBusyPsid(null);
    }
  }

  async function loadExpandedMessages(psid, silent = false) {
    if (!silent) setExpandedLoading(true);
    try {
      const data = await apiFetch(`/dashboard/conversations/${encodeURIComponent(psid)}/messages`);
      setExpandedMessages(data);
    } catch (err) {
      if (!silent) alert("Lỗi tải tin nhắn: " + err.message);
    } finally {
      if (!silent) setExpandedLoading(false);
    }
  }

  // Lay thong tin noi bo (note /approve, /note) de hien truc tiep trong khung
  // chat - moi note/approve la 1 dong rieng kem nut hanh dong cua rieng no
  // (issue #8 - nang cap UX 16/7, thay the viec chi hien note gan nhat).
  async function loadExpandedDraft(psid) {
    try {
      const data = await apiFetch(`/dashboard/conversations/${encodeURIComponent(psid)}/order_draft`);
      setExpandedDraft(data);
    } catch (err) {
      console.warn("Khong tai duoc order_draft:", err.message);
      setExpandedDraft(null);
    }
  }

  function toggleExpand(psid) {
    if (expandedPsid === psid) {
      setExpandedPsid(null);
      setExpandedMessages([]);
      setExpandedDraft(null);
      return;
    }
    setExpandedPsid(psid);
    loadExpandedMessages(psid);
    loadExpandedDraft(psid);
  }

  // Danh dau 1 note la da xu ly - KHONG can popup xac nhan (theo yeu cau
  // anh Hoai 16/7). Reload ca draft (an note khoi list) va danh sach chinh
  // (cap nhat lai so dem /n(N)).
  async function markNoteHandled(messageId, psid) {
    try {
      await apiFetch(`/dashboard/notes/${messageId}/mark-handled`, { method: "POST" });
      await loadExpandedDraft(psid);
      loadSilent();
    } catch (err) {
      alert("Lỗi: " + err.message);
    }
  }

  // Danh dau 1 phe duyet /approve la "da tao don" - BAT BUOC popup xac nhan
  // truoc (theo yeu cau anh Hoai 16/7), vi day la hanh dong quan trong hon
  // (lien quan don hang that).
  async function markOverrideUsed(overrideId, psid) {
    const ok = window.confirm("Bạn chắc chắn đã tạo đơn cho phê duyệt này?");
    if (!ok) return;
    try {
      await apiFetch(`/dashboard/overrides/${overrideId}/mark-used`, { method: "POST" });
      await loadExpandedDraft(psid);
      loadSilent();
    } catch (err) {
      alert("Lỗi: " + err.message);
    }
  }

  // Tu choi 1 phe duyet vi ly do khac (khach doi y, sep huy...) - can nhap ly
  // do, khong chi xac nhan don thuan (issue #8 - nang cap UX 16/7 lan 5).
  async function rejectOverride(overrideId, psid) {
    const reason = window.prompt("Vui lòng nhập lý do từ chối phê duyệt này:", "");
    if (reason === null) return; // bam Cancel -> huy
    if (!reason.trim()) {
      alert("Cần nhập lý do từ chối.");
      return;
    }
    try {
      await apiFetch(`/dashboard/overrides/${overrideId}/reject`, {
        method: "POST",
        body: JSON.stringify({ reason: reason.trim() }),
      });
      await loadExpandedDraft(psid);
      loadSilent();
    } catch (err) {
      alert("Lỗi: " + err.message);
    }
  }

  if (!ready) return null;

  return (
    <div>
      <h1 style={{ fontSize: 20, marginBottom: 16 }}>Hội thoại</h1>
      {error && <div className="error-box">{error}</div>}
      {loading ? (
        <div className="empty-state">Đang tải...</div>
      ) : conversations.length === 0 ? (
        <div className="empty-state">Chưa có hội thoại nào.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Khách</th>
              <th title="Số ghi chú (/note) và phê duyệt (/approve) chưa xử lý">Status</th>
              <th>Tin nhắn gần nhất</th>
              <th>Lúc</th>
              <th>Trạng thái</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {conversations.map((c) => {
              const noteCount = c.unhandled_notes_count || 0;
              const approveCount = c.unused_overrides_count || 0;
              return (
                <Fragment key={c.psid}>
                  <tr>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span>{c.name || "(chưa có tên)"}</span>
                        <button
                          onClick={() => toggleExpand(c.psid)}
                          style={{ fontSize: 12, padding: "3px 8px" }}
                        >
                          {expandedPsid === c.psid ? "▲ Thu gọn" : "▼ Mở rộng chat"}
                        </button>
                      </div>
                      <div style={{ fontSize: 12, color: "#999" }}>{c.phone || c.psid}</div>
                    </td>
                    <td style={{ fontSize: 12 }}>
                      <span
                        title="Số ghi chú (/note) chưa xử lý"
                        style={{ color: noteCount > 0 ? "#c2410c" : "#ccc", marginRight: 8 }}
                      >
                        /n(<strong>{noteCount}</strong>)
                      </span>
                      <span
                        title="Số phê duyệt (/approve) chưa dùng"
                        style={{ color: approveCount > 0 ? "#c2410c" : "#ccc" }}
                      >
                        /a(<strong>{approveCount}</strong>)
                      </span>
                    </td>
                    <td style={{ maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {c.last_message || "-"}
                    </td>
                    <td style={{ fontSize: 12, color: "#666" }}>
                      {c.last_message_at ? new Date(c.last_message_at).toLocaleString("vi-VN") : "-"}
                    </td>
                    <td>
                      <span className={c.bot_paused ? "badge badge-paused" : "badge badge-active"}>
                        {c.bot_paused ? "Chờ nhân viên" : "Bot đang trả lời"}
                      </span>
                    </td>
                    <td>
                      <button
                        disabled={busyPsid === c.psid}
                        onClick={() => togglePause(c.psid, c.bot_paused)}
                      >
                        {busyPsid === c.psid
                          ? "Đang xử lý..."
                          : c.bot_paused
                          ? "Resume bot"
                          : "Tiếp quản"}
                      </button>
                    </td>
                  </tr>
                  {expandedPsid === c.psid && (
                    <tr key={`${c.psid}-expanded`}>
                      <td colSpan={6} style={{ background: "#fafaf8", padding: "12px 16px" }}>
                        {expandedLoading ? (
                          <div className="empty-state">Đang tải tin nhắn...</div>
                        ) : expandedMessages.length === 0 ? (
                          <div className="empty-state">Chưa có tin nhắn nào được ghi log.</div>
                        ) : (
                          <div style={{ maxHeight: 320, overflowY: "auto", display: "flex", flexDirection: "column" }}>
                            {expandedMessages.map((m, i) => (
                              <div
                                key={i}
                                style={{
                                  display: "flex",
                                  flexDirection: "column",
                                  alignItems: m.role === "customer" ? "flex-start" : "flex-end",
                                }}
                              >
                                <div className={`bubble bubble-${m.role}`}>{m.content}</div>
                                <div className="bubble-time">
                                  {m.role === "customer" ? "Khách" : m.role === "agent" ? "Nhân viên" : "Bot"} ·{" "}
                                  {new Date(m.created_at).toLocaleString("vi-VN")}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}

                        {expandedDraft && expandedDraft.notes?.length > 0 && (
                          <div style={{ marginTop: 12 }}>
                            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: "#666" }}>
                              📝 Ghi chú (tất cả):
                            </div>
                            {expandedDraft.notes.map((n) => (
                              <div
                                key={n.id}
                                style={{
                                  background: n.handled ? "#f3f4f6" : "#fffbeb",
                                  border: n.handled ? "1px solid #e5e7eb" : "1px solid #fde68a",
                                  borderRadius: 6,
                                  padding: 8,
                                  marginBottom: 6,
                                  fontSize: 12,
                                  display: "flex",
                                  justifyContent: "space-between",
                                  alignItems: "center",
                                  gap: 8,
                                  opacity: n.handled ? 0.65 : 1,
                                }}
                              >
                                <span style={{ color: n.handled ? "#666" : "#7c5a05" }}>{n.content}</span>
                                {n.handled ? (
                                  <span style={{ fontSize: 12, color: "#16a34a", whiteSpace: "nowrap" }}>
                                    ✓ Đã xử lý
                                  </span>
                                ) : (
                                  <button
                                    style={{ fontSize: 12, whiteSpace: "nowrap" }}
                                    onClick={() => markNoteHandled(n.id, c.psid)}
                                  >
                                    ✓ Đã xử lý
                                  </button>
                                )}
                              </div>
                            ))}
                          </div>
                        )}

                        {expandedDraft && expandedDraft.overrides?.length > 0 && (
                          <div style={{ marginTop: 12 }}>
                            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: "#666" }}>
                              ✅ Phê duyệt (/approve) (tất cả):
                            </div>
                            {expandedDraft.overrides.map((o) => {
                              const isFrozen = o.status !== "active";
                              return (
                                <div
                                  key={o.id}
                                  style={{
                                    background: isFrozen ? "#f3f4f6" : "#fffbeb",
                                    border: isFrozen ? "1px solid #e5e7eb" : "1px solid #fde68a",
                                    borderRadius: 6,
                                    padding: 8,
                                    marginBottom: 6,
                                    fontSize: 12,
                                    display: "flex",
                                    justifyContent: "space-between",
                                    alignItems: "center",
                                    gap: 8,
                                    opacity: isFrozen ? 0.65 : 1,
                                  }}
                                >
                                  <span style={{ color: isFrozen ? "#666" : "#7c5a05" }}>
                                    <strong>
                                      {o.quantity} hũ × {Number(o.unit_price_vnd).toLocaleString("vi-VN")}đ
                                    </strong>
                                    {o.note ? ` — ${o.note}` : ""}
                                    {o.status === "rejected" && o.reject_reason ? (
                                      <span style={{ color: "#b91c1c" }}> (Từ chối: {o.reject_reason})</span>
                                    ) : null}
                                  </span>
                                  {o.status === "active" && (
                                    <div style={{ display: "flex", gap: 6 }}>
                                      <button
                                        style={{ fontSize: 12, whiteSpace: "nowrap" }}
                                        onClick={() => markOverrideUsed(o.id, c.psid)}
                                      >
                                        ✓ Đã tạo đơn
                                      </button>
                                      <button
                                        style={{ fontSize: 12, whiteSpace: "nowrap" }}
                                        onClick={() => rejectOverride(o.id, c.psid)}
                                      >
                                        ✗ Từ chối
                                      </button>
                                    </div>
                                  )}
                                  {o.status === "used" && (
                                    <span style={{ fontSize: 12, color: "#16a34a", whiteSpace: "nowrap" }}>
                                      ✓ Đã tạo đơn
                                    </span>
                                  )}
                                  {o.status === "rejected" && (
                                    <span style={{ fontSize: 12, color: "#b91c1c", whiteSpace: "nowrap" }}>
                                      ✗ Đã từ chối
                                    </span>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}

                        <div style={{ marginTop: 12 }}>
                          <a href={`/orders/new?psid=${encodeURIComponent(c.psid)}`}>
                            <button className="primary">🧾 Tạo đơn (tự điền từ /approve, /note)</button>
                          </a>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
