"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { setToken } from "../../lib/api";

// Tu Bat 4 (issue #8, 17/7): dang nhap that theo tung nhan vien
// (username/password) thay vi dan token tinh dung chung. Tai khoan dau tien
// phai tao qua script `scripts/create_staff_user.py` (xem ISSUES-VI.md).
//
// QUAN TRONG (fix 18/7): doc gia tri truc tiep tu FormData luc submit, KHONG
// chi dua vao state React (`username`/`password`) - trinh duyet autofill co
// the dien chu vao o input ma KHONG kich hoat onChange, khien state React
// van rong/cu trong khi mat nguoi dung thay co chu hien thi. Doc qua
// FormData luon phan anh dung gia tri THAT SU dang hien trong o, bat ke co
// qua onChange hay khong.
export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);

    const formData = new FormData(e.target);
    const username = (formData.get("username") || "").toString().trim();
    const password = (formData.get("password") || "").toString();

    if (!username || !password) {
      setError("Điền đủ tên đăng nhập và mật khẩu.");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/dashboard/auth/login`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, password }),
        }
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Sai tài khoản hoặc mật khẩu");
      }
      const data = await res.json();
      setToken(data.token);
      router.push("/conversations");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ maxWidth: 360, margin: "80px auto" }}>
      <h1 style={{ fontSize: 20, marginBottom: 20 }}>Đăng nhập</h1>
      {error && <div className="error-box">{error}</div>}
      <form
        onSubmit={handleSubmit}
        autoComplete="off"
        style={{ display: "flex", flexDirection: "column", gap: 12 }}
      >
        <input
          type="text"
          name="username"
          placeholder="Tên đăng nhập"
          autoComplete="off"
          autoFocus
        />
        <input
          type="password"
          name="password"
          placeholder="Mật khẩu"
          autoComplete="new-password"
        />
        <button className="primary" type="submit" disabled={loading}>
          {loading ? "Đang đăng nhập..." : "Đăng nhập"}
        </button>
      </form>
    </div>
  );
}
