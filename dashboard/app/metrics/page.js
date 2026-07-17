"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "../../lib/api";
import { useAuthGuard } from "../../lib/useAuthGuard";

// Trang Metrics/Analytics (issue #8, Bat 3) - 3 chi so, tan dung hoan toan
// du lieu san co (messages/conversations/orders), khong can bang moi.
// Khong dung thu vien chart ngoai (giu nhe, khong them dependency moi) -
// ve bar don gian bang div width theo %.

function formatDate(dateStr) {
  // Backend tra ve "YYYY-MM-DD" (tu Postgres DATE) - hien dang vi VN
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" });
}

export default function MetricsPage() {
  const ready = useAuthGuard();
  const [conversion, setConversion] = useState(null);
  const [messagesPerDay, setMessagesPerDay] = useState([]);
  const [unanswered, setUnanswered] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (ready) load();
  }, [ready]);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [conv, perDay, unans] = await Promise.all([
        apiFetch("/dashboard/metrics/conversion-rate"),
        apiFetch("/dashboard/metrics/messages-per-day?days=14"),
        apiFetch("/dashboard/metrics/unanswered-questions?limit=15"),
      ]);
      setConversion(conv);
      setMessagesPerDay(perDay);
      setUnanswered(unans);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  if (!ready) return null;

  const maxTotal = messagesPerDay.reduce((m, d) => Math.max(m, d.total), 1);

  return (
    <div>
      <h1 style={{ fontSize: 20, marginBottom: 16 }}>Metrics / Analytics</h1>
      {error && <div className="error-box">{error}</div>}
      {loading ? (
        <div className="empty-state">Đang tải...</div>
      ) : (
        <>
          {/* Tổng quan */}
          <div style={{ display: "flex", gap: 16, marginBottom: 24, flexWrap: "wrap" }}>
            <div style={{ border: "1px solid #eee", borderRadius: 8, padding: 16, minWidth: 160 }}>
              <div style={{ fontSize: 12, color: "#999" }}>Tổng số khách đã chat</div>
              <div style={{ fontSize: 28, fontWeight: 700 }}>{conversion?.total_customers ?? "-"}</div>
            </div>
            <div style={{ border: "1px solid #eee", borderRadius: 8, padding: 16, minWidth: 160 }}>
              <div style={{ fontSize: 12, color: "#999" }}>Khách đã có đơn hàng</div>
              <div style={{ fontSize: 28, fontWeight: 700 }}>{conversion?.customers_with_orders ?? "-"}</div>
            </div>
            <div style={{ border: "1px solid #eee", borderRadius: 8, padding: 16, minWidth: 160 }}>
              <div style={{ fontSize: 12, color: "#999" }}>Tỷ lệ chat → đơn</div>
              <div style={{ fontSize: 28, fontWeight: 700, color: "#2563eb" }}>
                {conversion?.conversion_rate_pct ?? "-"}%
              </div>
            </div>
          </div>

          {/* Tin nhắn/ngày */}
          <h2 style={{ fontSize: 16, marginBottom: 8 }}>Tin nhắn / ngày (14 ngày gần nhất)</h2>
          {messagesPerDay.length === 0 ? (
            <div className="empty-state" style={{ marginBottom: 24 }}>
              Chưa có dữ liệu tin nhắn.
            </div>
          ) : (
            <div style={{ marginBottom: 24 }}>
              {messagesPerDay.map((d) => (
                <div key={d.day} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                  <div style={{ width: 48, fontSize: 12, color: "#666" }}>{formatDate(d.day)}</div>
                  <div style={{ flex: 1, display: "flex", height: 18, borderRadius: 3, overflow: "hidden" }}>
                    <div
                      title={`Khách: ${d.customer_count}`}
                      style={{ width: `${(d.customer_count / maxTotal) * 100}%`, background: "#93c5fd" }}
                    />
                    <div
                      title={`Bot: ${d.bot_count}`}
                      style={{ width: `${(d.bot_count / maxTotal) * 100}%`, background: "#86efac" }}
                    />
                    <div
                      title={`Nhân viên: ${d.agent_count}`}
                      style={{ width: `${(d.agent_count / maxTotal) * 100}%`, background: "#fdba74" }}
                    />
                  </div>
                  <div style={{ width: 40, fontSize: 12, textAlign: "right" }}>{d.total}</div>
                </div>
              ))}
              <div style={{ display: "flex", gap: 12, fontSize: 11, color: "#999", marginTop: 8 }}>
                <span>🟦 Khách</span>
                <span>🟩 Bot</span>
                <span>🟧 Nhân viên</span>
              </div>
            </div>
          )}

          {/* Câu hỏi bot không trả lời được */}
          <h2 style={{ fontSize: 16, marginBottom: 8 }}>Top câu hỏi bot không trả lời được</h2>
          <p style={{ fontSize: 12, color: "#999", marginBottom: 12 }}>
            Đếm số lần bot phải dùng câu trả lời mặc định "chưa có thông tin xác nhận" —
            gom nhóm theo câu hỏi giống hệt nhau (không nhận diện câu hỏi gần giống).
          </p>
          {unanswered.length === 0 ? (
            <div className="empty-state">Chưa ghi nhận câu hỏi nào bot không trả lời được 🎉</div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Câu hỏi khách</th>
                  <th>Số lần</th>
                  <th>Gần nhất</th>
                </tr>
              </thead>
              <tbody>
                {unanswered.map((u, i) => (
                  <tr key={i}>
                    <td style={{ maxWidth: 420 }}>{u.question}</td>
                    <td style={{ fontWeight: 600 }}>{u.count}</td>
                    <td style={{ fontSize: 12, color: "#666" }}>
                      {new Date(u.last_seen).toLocaleString("vi-VN")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}
