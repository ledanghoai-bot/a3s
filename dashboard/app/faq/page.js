"use client";

import { useEffect, useState, Fragment } from "react";
import { apiFetch } from "../../lib/api";
import { useAuthGuard } from "../../lib/useAuthGuard";

// Form them/sua 1 FAQ - dung chung cho ca 2 truong hop (issue #8, Bat 2).
// Luu la tu dong tinh embedding + dong bo knowledge_chunks ngay lap tuc
// (xem app/services/knowledge_entries.py) - bot dung duoc tu cau hoi ke tiep,
// khong can chay ingest.py tay.
function FaqForm({ entry, onSaved, onCancel }) {
  const isEdit = !!entry;
  const [question, setQuestion] = useState(entry?.question || "");
  const [answer, setAnswer] = useState(entry?.answer || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function save() {
    setError(null);
    if (!question.trim() || !answer.trim()) {
      setError("Điền đủ câu hỏi và câu trả lời.");
      return;
    }
    setBusy(true);
    try {
      if (isEdit) {
        await apiFetch(`/dashboard/faq/${entry.id}`, {
          method: "PATCH",
          body: JSON.stringify({ question: question.trim(), answer: answer.trim() }),
        });
      } else {
        await apiFetch("/dashboard/faq", {
          method: "POST",
          body: JSON.stringify({ question: question.trim(), answer: answer.trim() }),
        });
      }
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ border: "1px solid #eee", borderRadius: 8, padding: 12, background: "#fff", marginBottom: 12 }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
        {isEdit ? "Sửa FAQ" : "Thêm FAQ mới"}
      </div>
      {error && <div className="error-box">{error}</div>}
      <div style={{ display: "flex", flexDirection: "column", gap: 6, maxWidth: 520 }}>
        <input
          placeholder="Câu hỏi (vd: Pha với nước đá được không?)"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <textarea
          placeholder="Câu trả lời"
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          rows={4}
        />
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <button className="primary" disabled={busy} onClick={save}>
          {busy ? "Đang lưu (tính embedding)..." : "Lưu"}
        </button>
        <button onClick={onCancel}>Huỷ</button>
      </div>
    </div>
  );
}

export default function FaqPage() {
  const ready = useAuthGuard();
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [busyDeleteId, setBusyDeleteId] = useState(null);

  useEffect(() => {
    if (ready) load();
  }, [ready]);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch("/dashboard/faq");
      setEntries(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function afterSave() {
    setShowAddForm(false);
    setEditingId(null);
    load();
  }

  async function deleteFaq(id) {
    const ok = window.confirm("Xoá FAQ này? Bot sẽ không còn dùng nội dung này để trả lời nữa.");
    if (!ok) return;
    setBusyDeleteId(id);
    try {
      await apiFetch(`/dashboard/faq/${id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      alert("Lỗi: " + err.message);
    } finally {
      setBusyDeleteId(null);
    }
  }

  if (!ready) return null;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h1 style={{ fontSize: 20 }}>FAQ</h1>
        {!showAddForm && (
          <button className="primary" onClick={() => setShowAddForm(true)}>
            + Thêm FAQ
          </button>
        )}
      </div>

      <p style={{ fontSize: 12, color: "#999", marginBottom: 12 }}>
        Mỗi FAQ ở đây tự động tính lại embedding và cập nhật ngay vào kiến thức bot dùng để
        trả lời (RAG) — không cần chạy script <code>ingest.py</code>. Nội dung tĩnh gốc trong{" "}
        <code>data/knowledge/*.md</code> vẫn còn nguyên, không bị ảnh hưởng.
      </p>

      {showAddForm && <FaqForm onSaved={afterSave} onCancel={() => setShowAddForm(false)} />}

      {error && <div className="error-box">{error}</div>}
      {loading ? (
        <div className="empty-state">Đang tải...</div>
      ) : entries.length === 0 ? (
        <div className="empty-state">Chưa có FAQ nào tạo qua dashboard.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Câu hỏi</th>
              <th>Câu trả lời</th>
              <th>Cập nhật lúc</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <Fragment key={e.id}>
                <tr>
                  <td style={{ maxWidth: 220 }}>{e.question}</td>
                  <td style={{ maxWidth: 320, fontSize: 13, color: "#666" }}>{e.answer}</td>
                  <td style={{ fontSize: 12, color: "#999" }}>
                    {new Date(e.updated_at).toLocaleString("vi-VN")}
                  </td>
                  <td style={{ display: "flex", gap: 6 }}>
                    <button
                      style={{ fontSize: 12 }}
                      onClick={() => setEditingId(editingId === e.id ? null : e.id)}
                    >
                      Sửa
                    </button>
                    <button
                      style={{ fontSize: 12 }}
                      disabled={busyDeleteId === e.id}
                      onClick={() => deleteFaq(e.id)}
                    >
                      {busyDeleteId === e.id ? "..." : "Xoá"}
                    </button>
                  </td>
                </tr>
                {editingId === e.id && (
                  <tr>
                    <td colSpan={4}>
                      <FaqForm entry={e} onSaved={afterSave} onCancel={() => setEditingId(null)} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
