"use client";

import { useEffect, useState } from "react";
import { apiFetch, clearToken, getToken } from "../../lib/api";

// Hien ten nhan vien dang dang nhap + nut Dang xuat (issue #8, Bat 4 - khac
// phuc gioi han da biet truoc do "chua co nut dang xuat tren UI").
export default function NavUser() {
  const [name, setName] = useState(null);

  useEffect(() => {
    if (!getToken()) return;
    apiFetch("/dashboard/auth/me")
      .then((data) => setName(data.name || data.username))
      .catch(() => {});
  }, []);

  async function logout() {
    try {
      await apiFetch("/dashboard/auth/logout", { method: "POST" });
    } catch {
      // Token co the da het han - van xoa local + dieu huong binh thuong
    }
    clearToken();
    window.location.href = "/login";
  }

  if (!name) return null;

  return (
    <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
      <span style={{ fontSize: 13, color: "#666" }}>Xin chào, {name}</span>
      <button onClick={logout} style={{ fontSize: 12 }}>
        Đăng xuất
      </button>
    </span>
  );
}
