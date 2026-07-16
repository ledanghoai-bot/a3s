"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, setToken } from "../../lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [tokenInput, setTokenInput] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    setToken(tokenInput.trim());
    try {
      await apiFetch("/dashboard/ping");
      router.push("/conversations");
    } catch (err) {
      setError("Token không hợp lệ. Kiểm tra lại ADMIN_API_TOKEN trong .env của backend.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ maxWidth: 360, margin: "80px auto" }}>
      <h1 style={{ fontSize: 20, marginBottom: 20 }}>Đăng nhập admin</h1>
      {error && <div className="error-box">{error}</div>}
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <input
          type="password"
          placeholder="Dán ADMIN_API_TOKEN vào đây"
          value={tokenInput}
          onChange={(e) => setTokenInput(e.target.value)}
          autoFocus
        />
        <button className="primary" type="submit" disabled={loading || !tokenInput}>
          {loading ? "Đang kiểm tra..." : "Đăng nhập"}
        </button>
      </form>
    </div>
  );
}
