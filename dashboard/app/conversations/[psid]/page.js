"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiFetch } from "../../../lib/api";
import { useAuthGuard } from "../../../lib/useAuthGuard";

const POLL_INTERVAL_MS = 5000;

export default function ConversationDetailPage() {
  const ready = useAuthGuard();
  const params = useParams();
  const psid = decodeURIComponent(params.psid);

  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!ready) return;
    load();

    // Cua so nay thuong duoc mo rieng (popup) de theo doi song song luc dang
    // xu ly khach - can tu cap nhat tin nhan moi, khong bat nguoi dung phai F5.
    const interval = setInterval(() => loadSilent(), POLL_INTERVAL_MS);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch(`/dashboard/conversations/${encodeURIComponent(psid)}/messages`);
      setMessages(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadSilent() {
    try {
      const data = await apiFetch(`/dashboard/conversations/${encodeURIComponent(psid)}/messages`);
      setMessages(data);
    } catch (err) {
      console.warn("Auto-refresh loi (bo qua, giu du lieu cu):", err.message);
    }
  }

  if (!ready) return null;

  return (
    <div>
      <a href="/conversations" style={{ fontSize: 13 }}>&larr; Quay lại danh sách</a>
      <h1 style={{ fontSize: 18, margin: "12px 0" }}>Lịch sử hội thoại — {psid}</h1>
      {error && <div className="error-box">{error}</div>}
      {loading ? (
        <div className="empty-state">Đang tải...</div>
      ) : messages.length === 0 ? (
        <div className="empty-state">Chưa có tin nhắn nào được ghi log cho hội thoại này.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", padding: "12px 0" }}>
          {messages.map((m, i) => (
            <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: m.role === "customer" ? "flex-start" : "flex-end" }}>
              <div className={`bubble bubble-${m.role}`}>{m.content}</div>
              <div className="bubble-time">
                {m.role === "customer" ? "Khách" : m.role === "agent" ? "Nhân viên" : "Bot"} ·{" "}
                {new Date(m.created_at).toLocaleString("vi-VN")}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
