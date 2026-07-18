"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "../../lib/api";
import { useAuthGuard } from "../../lib/useAuthGuard";

// Quan ly tai khoan nhan vien (issue #8, Bat 4). Bat ky staff nao dang dang
// nhap deu lam duoc - CHUA co phan quyen chi tiet theo role, phu hop quy mo
// doi nho hien tai (ghi ro trong docs la gioi han da biet).
export default function StaffPage() {
  const ready = useAuthGuard();
  const [staff, setStaff] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState(null);

  useEffect(() => {
    if (ready) load();
  }, [ready]);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch("/dashboard/auth/staff");
      setStaff(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function createStaff() {
    setFormError(null);
    if (!username || !password) {
      setFormError("Điền đủ tên đăng nhập và mật khẩu.");
      return;
    }
    if (password.length < 6) {
      setFormError("Mật khẩu cần tối thiểu 6 ký tự.");
      return;
    }
    setSaving(true);
    try {
      await apiFetch("/dashboard/auth/staff", {
        method: "POST",
        body: JSON.stringify({ username: username.trim(), password, name: name.trim() }),
      });
      setUsername("");
      setPassword("");
      setName("");
      setShowAddForm(false);
      await load();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function toggleActive(s) {
    const action = s.is_active ? "vô hiệu hoá" : "kích hoạt lại";
    if (!window.confirm(`Xác nhận ${action} tài khoản "${s.username}"?`)) return;
    try {
      await apiFetch(`/dashboard/auth/staff/${s.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !s.is_active }),
      });
      await load();
    } catch (err) {
      alert("Lỗi: " + err.message);
    }
  }

  if (!ready) return null;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h1 style={{ fontSize: 20 }}>Nhân viên</h1>
        {!showAddForm && (
          <button className="primary" onClick={() => setShowAddForm(true)}>
            + Thêm nhân viên
          </button>
        )}
      </div>

      <p style={{ fontSize: 12, color: "#999", marginBottom: 12 }}>
        Bất kỳ nhân viên nào đang đăng nhập cũng tạo/vô hiệu hoá được tài khoản khác — chưa có
        phân quyền chi tiết theo vai trò, phù hợp quy mô đội nhỏ hiện tại.
      </p>

      {showAddForm && (
        <div style={{ border: "1px solid #eee", borderRadius: 8, padding: 12, background: "#fff", marginBottom: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Thêm nhân viên mới</div>
          {formError && <div className="error-box">{formError}</div>}
          <div style={{ display: "flex", flexDirection: "column", gap: 6, maxWidth: 320 }}>
            <input
              placeholder="Tên đăng nhập"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
            <input
              type="password"
              placeholder="Mật khẩu (tối thiểu 6 ký tự)"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <input
              placeholder="Tên hiển thị (tuỳ chọn)"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <button className="primary" disabled={saving} onClick={createStaff}>
              {saving ? "Đang lưu..." : "Lưu"}
            </button>
            <button onClick={() => setShowAddForm(false)}>Huỷ</button>
          </div>
        </div>
      )}

      {error && <div className="error-box">{error}</div>}
      {loading ? (
        <div className="empty-state">Đang tải...</div>
      ) : staff.length === 0 ? (
        <div className="empty-state">Chưa có nhân viên nào.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Tên đăng nhập</th>
              <th>Tên hiển thị</th>
              <th>Trạng thái</th>
              <th>Tạo lúc</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {staff.map((s) => (
              <tr key={s.id}>
                <td>{s.username}</td>
                <td>{s.name || "-"}</td>
                <td>
                  <span className={s.is_active ? "badge badge-active" : "badge badge-paused"}>
                    {s.is_active ? "Đang hoạt động" : "Đã vô hiệu hoá"}
                  </span>
                </td>
                <td style={{ fontSize: 12, color: "#666" }}>
                  {new Date(s.created_at).toLocaleDateString("vi-VN")}
                </td>
                <td>
                  <button style={{ fontSize: 12 }} onClick={() => toggleActive(s)}>
                    {s.is_active ? "Vô hiệu hoá" : "Kích hoạt lại"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
