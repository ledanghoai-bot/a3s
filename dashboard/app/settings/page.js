"use client";

// CA Directive 305 — Cài đặt Shop / Tích hợp (kiểu WooCommerce). GĐ1: tab Vận chuyển hoạt động (GHN staging);
// Thanh toán "sắp có". Secret WRITE-ONLY (không đọc lại plaintext). Save ≠ Enable; test-pass mới Enable được.
import { useEffect, useState } from "react";
import { apiFetch } from "../../lib/api";
import { useAuthGuard } from "../../lib/useAuthGuard";

const GHN_STAGING_BASE = "https://dev-online-gateway.ghn.vn/shiip/public-api";

function Badge({ text, tone }) {
  const bg = { ok: "#e6f4ea", warn: "#fff4e5", bad: "#fdecea", neutral: "#eef1f4" }[tone] || "#eef1f4";
  const fg = { ok: "#1e7e34", warn: "#9a6700", bad: "#b71c1c", neutral: "#444" }[tone] || "#444";
  return <span style={{ background: bg, color: fg, padding: "2px 8px", borderRadius: 10, fontSize: 12 }}>{text}</span>;
}

function canEnable(it) {
  const t = it.last_test || {};
  const vers = Object.values(it.secrets || {}).map((s) => s.version);
  const secVer = vers.length ? Math.max(...vers) : null;   // khớp max(secret version) như enable-gate backend
  return t.status === "pass" && t.config_version === it.version && t.secret_version === secVer && !it.enabled;
}

export default function SettingsPage() {
  const ready = useAuthGuard();
  const [tab, setTab] = useState("shipping");
  const [items, setItems] = useState([]);
  const [meta, setMeta] = useState({ crypto_configured: false, module_enabled: false });
  const [sel, setSel] = useState(null); // integration đang Manage (hoặc {new:true})
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (ready) load(); /* eslint-disable-next-line */ }, [ready]);

  async function load() {
    setErr(null);
    try {
      const d = await apiFetch(`/dashboard/settings/integrations?kind=shipping`);
      setItems(d.items || []);
      setMeta({ crypto_configured: d.crypto_configured, module_enabled: d.module_enabled });
    } catch (e) { setErr(e.message); }
  }

  async function act(fn, ok) {
    setBusy(true); setErr(null); setMsg(null);
    try { const r = await fn(); if (ok) setMsg(ok); await load(); return r; }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  }

  if (!ready) return null;
  const ghn = items.find((i) => i.provider === "ghn");

  return (
    <div>
      <h1>Cài đặt</h1>
      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid #ddd", marginBottom: 16 }}>
        {[["general", "Chung"], ["shipping", "Vận chuyển"], ["payment", "Thanh toán"]].map(([k, l]) => (
          <button key={k} onClick={() => { setTab(k); setSel(null); }}
            style={{ padding: "8px 14px", border: "none", borderBottom: tab === k ? "2px solid #1a73e8" : "2px solid transparent",
              background: "none", fontWeight: tab === k ? 600 : 400, cursor: "pointer" }}>{l}</button>
        ))}
      </div>

      {msg && <p style={{ color: "#1e7e34" }}>{msg}</p>}
      {err && <p style={{ color: "#b71c1c" }}>{err}</p>}

      {tab === "general" && (
        <p style={{ color: "#555" }}>Thông tin shop chung. Các chính sách giao/phí/đơn-lớn vẫn ở màn hình vận hành hiện có
          (không gom vào đây) — GĐ1 chỉ liên kết, không sao chép.</p>
      )}

      {tab === "payment" && <PaymentSettings setMsg={setMsg} setErr={setErr} />}

      {tab === "shipping" && (
        <div>
          {!meta.crypto_configured && (
            <p style={{ background: "#fff4e5", color: "#9a6700", padding: 10, borderRadius: 6 }}>
              ⚠ Khóa mã hóa (CONFIG_ENC_KEYS) chưa cấu hình trên server — chưa lưu/xoay được secret. Liên hệ vận hành.</p>
          )}
          {/* Shipping zones (WooCommerce-style summary) */}
          <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 240, border: "1px solid #e3e6ea", borderRadius: 8, padding: 12 }}>
              <b>Nội thành Buôn Ma Thuột</b><div style={{ color: "#555", fontSize: 13 }}>Tự giao (allowlist phường) — phí theo bảng phí nội bộ.</div>
            </div>
            <div style={{ flex: 1, minWidth: 240, border: "1px solid #e3e6ea", borderRadius: 8, padding: 12 }}>
              <b>Ngoài vùng tự giao</b><div style={{ color: "#555", fontSize: 13 }}>Định tuyến qua đơn vị vận chuyển (GHN). Thiếu/mơ hồ map → nhân viên xử lý.</div>
            </div>
          </div>

          <h3>Đơn vị vận chuyển</h3>
          {ghn ? (
            <ProviderRow it={ghn} onManage={() => setSel(ghn)}
              onTest={() => act(() => apiFetch(`/dashboard/settings/integrations/${ghn.id}/test-connection`, { method: "POST" }), "Đã test kết nối")}
              onToggle={() => act(() => ghn.enabled
                ? apiFetch(`/dashboard/settings/integrations/${ghn.id}/disable`, { method: "POST" })
                : apiFetch(`/dashboard/settings/integrations/${ghn.id}/enable`, { method: "POST", body: JSON.stringify({ expected_version: ghn.version }) }),
                ghn.enabled ? "Đã tắt" : "Đã bật")}
              busy={busy} />
          ) : (
            <button disabled={busy} onClick={() => act(() => apiFetch(`/dashboard/settings/integrations`, {
              method: "POST", body: JSON.stringify({ kind: "shipping", provider: "ghn", label: "GHN staging", mode: "staging",
                config_public: { base_url: GHN_STAGING_BASE } }) }), "Đã tạo GHN staging").then((r) => r && setSel(r))}>
              + Thêm GHN staging
            </button>
          )}

          {sel && sel.provider === "ghn" && (
            <GhnManage it={sel} busy={busy} onClose={() => setSel(null)} reload={load} setBusy={setBusy}
              setMsg={setMsg} setErr={setErr} />
          )}
          <p style={{ color: "#888", fontSize: 12, marginTop: 16 }}>
            Trạng thái module: {meta.module_enabled ? "ON" : "OFF (dormant)"} · Nguồn cấu hình live theo loader (env|database).
            Bật GHN quote là gate kế tiếp (ngoài phạm vi màn hình này).</p>
        </div>
      )}
    </div>
  );
}

function ProviderRow({ it, onManage, onTest, onToggle, busy }) {
  const t = it.last_test || {};
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, border: "1px solid #e3e6ea", borderRadius: 8, padding: 12, marginTop: 8 }}>
      <div style={{ flex: 1 }}>
        <b>{it.label}</b> <Badge text={it.mode} tone="neutral" /> {it.enabled ? <Badge text="Đang bật" tone="ok" /> : <Badge text="Tắt" tone="neutral" />}
        <div style={{ fontSize: 12, color: "#555" }}>
          Secret token: {it.secrets?.token ? `đã lưu (v${it.secrets.token.version})` : "chưa nhập"} ·
          Test gần nhất: {t.status ? <Badge text={t.status === "pass" ? "Đạt" : "Lỗi"} tone={t.status === "pass" ? "ok" : "bad"} /> : "chưa test"}
        </div>
      </div>
      <button disabled={busy} onClick={onManage}>Quản lý</button>
      <button disabled={busy} onClick={onTest}>Test kết nối</button>
      <button disabled={busy || (!it.enabled && !canEnable(it))} onClick={onToggle}>{it.enabled ? "Tắt" : "Bật"}</button>
    </div>
  );
}

function GhnManage({ it, busy, onClose, reload, setBusy, setMsg, setErr }) {
  const cp = it.config_public || {};
  const [form, setForm] = useState({
    label: it.label, shop_id: cp.shop_id || "", from_district_id: cp.from_district_id ?? "",
    from_ward_code: cp.from_ward_code || "", timeout_seconds: cp.timeout_seconds ?? 8,
    max_retries: cp.max_retries ?? 2, light_max_g: cp.light_max_g ?? 20000, address_map_version: cp.address_map_version ?? 1,
  });
  const [token, setToken] = useState("");

  async function run(fn, ok) {
    setBusy(true); setErr(null); setMsg(null);
    try { await fn(); if (ok) setMsg(ok); await reload(); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  }
  const num = (v) => (v === "" || v == null ? null : Number(v));

  return (
    <div style={{ border: "1px solid #cdd3da", borderRadius: 8, padding: 16, marginTop: 12, background: "#fafbfc" }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>Quản lý GHN staging (#{it.id}, v{it.version})</h3>
        <button onClick={onClose}>Đóng</button>
      </div>

      <fieldset style={{ marginTop: 12 }}><legend>Môi trường</legend>
        Mode: <b>staging</b> · Base URL (ghim): <code>{cp.base_url || GHN_STAGING_BASE}</code>
      </fieldset>

      <fieldset style={{ marginTop: 12 }}><legend>Thông tin đăng nhập (Credentials)</legend>
        <label>ShopId <input value={form.shop_id} onChange={(e) => setForm({ ...form, shop_id: e.target.value })} /></label>
        <div style={{ marginTop: 8 }}>
          <label>Token (bí mật, chỉ ghi){" "}
            <input type="password" placeholder={it.secrets?.token ? "•••• đã lưu — để trống nếu không đổi" : "dán token staging"}
              value={token} onChange={(e) => setToken(e.target.value)} style={{ width: 320 }} />
          </label>
          <button disabled={busy || !token} style={{ marginLeft: 8 }}
            onClick={() => run(() => apiFetch(`/dashboard/settings/integrations/${it.id}/secret`, {
              method: "POST", body: JSON.stringify({ key_name: "token", value: token }) }).then(() => setToken("")), "Đã lưu token")}>
            Lưu/Xoay token</button>
        </div>
      </fieldset>

      <fieldset style={{ marginTop: 12 }}><legend>Điểm lấy hàng (Pickup)</legend>
        <label>District ID <input value={form.from_district_id} onChange={(e) => setForm({ ...form, from_district_id: e.target.value })} /></label>{" "}
        <label>Ward code <input value={form.from_ward_code} onChange={(e) => setForm({ ...form, from_ward_code: e.target.value })} /></label>
      </fieldset>

      <fieldset style={{ marginTop: 12 }}><legend>Cấu hình báo giá</legend>
        <label>Timeout(s) <input value={form.timeout_seconds} onChange={(e) => setForm({ ...form, timeout_seconds: e.target.value })} style={{ width: 60 }} /></label>{" "}
        <label>Retry <input value={form.max_retries} onChange={(e) => setForm({ ...form, max_retries: e.target.value })} style={{ width: 50 }} /></label>{" "}
        <label>Ngưỡng nhẹ(g) <input value={form.light_max_g} onChange={(e) => setForm({ ...form, light_max_g: e.target.value })} style={{ width: 90 }} /></label>{" "}
        <label>Map version <input value={form.address_map_version} onChange={(e) => setForm({ ...form, address_map_version: e.target.value })} style={{ width: 50 }} /></label>
      </fieldset>

      <div style={{ marginTop: 14, display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button disabled={busy} onClick={() => run(() => apiFetch(`/dashboard/settings/integrations/${it.id}`, {
          method: "PATCH", body: JSON.stringify({ label: form.label, expected_version: it.version, config_public: {
            shop_id: form.shop_id, from_district_id: num(form.from_district_id), from_ward_code: form.from_ward_code,
            timeout_seconds: num(form.timeout_seconds), max_retries: num(form.max_retries),
            light_max_g: num(form.light_max_g), address_map_version: num(form.address_map_version) } }) }), "Đã lưu cấu hình")}>
          Lưu cấu hình</button>
        <button disabled={busy} onClick={() => run(() => apiFetch(`/dashboard/settings/integrations/${it.id}/test-connection`, { method: "POST" }), "Đã test kết nối")}>
          Test kết nối (read-only)</button>
        <button disabled={busy || !canEnable(it)} title={canEnable(it) ? "" : "Cần test PASS khớp version hiện tại"}
          onClick={() => run(() => apiFetch(`/dashboard/settings/integrations/${it.id}/enable`, {
            method: "POST", body: JSON.stringify({ expected_version: it.version }) }), "Đã bật")}>Bật</button>
        {it.enabled && <button disabled={busy} onClick={() => run(() => apiFetch(`/dashboard/settings/integrations/${it.id}/disable`, { method: "POST" }), "Đã tắt")}>Tắt</button>}
      </div>
      <p style={{ fontSize: 12, color: "#888", marginTop: 8 }}>
        Lưu và Bật là hai bước riêng. Đổi cấu hình/token làm kết quả test hết hiệu lực — phải test lại trước khi bật.
        Token không bao giờ hiển thị lại; muốn đổi thì nhập giá trị mới.</p>
    </div>
  );
}

// CA Directive 306 — tab Thanh toán: Chuyển khoản/VietQR (bank_accounts, MASK account) + COD + SePay Test Mode S0.
function PaymentSettings({ setMsg, setErr }) {
  const [ov, setOv] = useState(null);
  const [busy, setBusy] = useState(false);
  const [bank, setBank] = useState({ bank: "", account_number: "", holder_name: "", branch: "", bin: "", is_test: false });
  const [sepayKey, setSepayKey] = useState("");

  async function load() {
    setErr(null);
    try { const d = await apiFetch(`/dashboard/settings/payments`); setOv(d); } catch (e) { setErr(e.message); }
  }
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);
  async function run(fn, ok) {
    setBusy(true); setErr(null); setMsg(null);
    try { const r = await fn(); if (ok) setMsg(ok); await load(); return r; } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }
  if (!ov) return <p>Đang tải…</p>;
  const sepay = (ov.sepay?.integrations || []).find((i) => i.provider === "sepay");

  return (
    <div>
      {/* Chuyển khoản / VietQR */}
      <div style={{ border: "1px solid #e3e6ea", borderRadius: 8, padding: 14, marginBottom: 12 }}>
        <b>Chuyển khoản / VietQR</b>
        <div style={{ fontSize: 13, color: "#555", marginTop: 4 }}>
          {ov.bank_transfer.account
            ? `${ov.bank_transfer.account.bank} · BIN ${ov.bank_transfer.account.bin || "—"} · ${ov.bank_transfer.account.holder_name} · ••••${ov.bank_transfer.account.account_last4 || "----"} ${ov.bank_transfer.account.is_test ? "· TEST" : ""}`
            : "Chưa cấu hình tài khoản nhận."}
        </div>
        <details style={{ marginTop: 8 }}>
          <summary>Cập nhật tài khoản nhận</summary>
          <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
            <input placeholder="ngân hàng" value={bank.bank} onChange={(e) => setBank({ ...bank, bank: e.target.value })} />
            <input placeholder="số tài khoản" value={bank.account_number} onChange={(e) => setBank({ ...bank, account_number: e.target.value })} />
            <input placeholder="chủ TK" value={bank.holder_name} onChange={(e) => setBank({ ...bank, holder_name: e.target.value })} />
            <input placeholder="BIN NAPAS" value={bank.bin} onChange={(e) => setBank({ ...bank, bin: e.target.value })} />
            <label style={{ fontSize: 13 }}><input type="checkbox" checked={bank.is_test} onChange={(e) => setBank({ ...bank, is_test: e.target.checked })} /> test</label>
            <button disabled={busy} onClick={() => run(() => apiFetch(`/dashboard/settings/payments/bank`, { method: "POST", body: JSON.stringify(bank) }), "Đã lưu tài khoản")}>Lưu</button>
          </div>
        </details>
        <button style={{ marginTop: 8 }} disabled={busy} onClick={() => run(async () => {
          const r = await apiFetch(`/dashboard/settings/payments/vietqr-self-test`, { method: "POST", body: JSON.stringify({ amount_vnd: 10000 }) });
          setMsg(r.ok ? `VietQR self-test ĐẠT (BIN ${r.bin}, ••••${r.account_last4}, CRC hợp lệ)` : `VietQR self-test LỖI: ${r.error_class}`);
        })}>Test VietQR (local, không chuyển tiền)</button>
      </div>

      {/* COD */}
      <div style={{ border: "1px solid #e3e6ea", borderRadius: 8, padding: 14, marginBottom: 12 }}>
        <b>COD</b> <Badge text="Vận hành qua Giao & Thu tiền" tone="neutral" />
        <div style={{ fontSize: 13, color: "#555" }}>{ov.cod.note}</div>
      </div>

      {/* SePay Test Mode S0 */}
      <div style={{ border: "1px solid #e3e6ea", borderRadius: 8, padding: 14 }}>
        <b>SePay Test Mode (S0)</b> {sepay ? (sepay.enabled ? <Badge text="Bật" tone="ok" /> : <Badge text="Tắt" tone="neutral" />) : <Badge text="Chưa tạo" tone="neutral" />}
        {" "}<Badge text="Live: Khóa — cần gate S1" tone="bad" />
        {!sepay ? (
          <div style={{ marginTop: 8 }}>
            <button disabled={busy} onClick={() => run(() => apiFetch(`/dashboard/settings/integrations`, { method: "POST", body: JSON.stringify({ kind: "payment", provider: "sepay", label: "SePay Test", mode: "test", config_public: { code_prefix: "3SCF" } }) }), "Đã tạo SePay Test")}>+ Thêm SePay Test</button>
          </div>
        ) : (
          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: 13, color: "#555" }}>
              API key: {sepay.secrets?.api_key ? `đã lưu (v${sepay.secrets.api_key.version})` : "chưa nhập"} ·
              Readiness: {sepay.last_test?.status ? <Badge text={sepay.last_test.status === "pass" ? "Sẵn sàng" : "Lỗi"} tone={sepay.last_test.status === "pass" ? "ok" : "bad"} /> : "chưa test"}
            </div>
            <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
              <input type="password" placeholder={sepay.secrets?.api_key ? "•••• đã lưu — để trống nếu không đổi" : "SePay Test API key"} value={sepayKey} onChange={(e) => setSepayKey(e.target.value)} style={{ width: 280 }} />
              <button disabled={busy || !sepayKey} onClick={() => run(() => apiFetch(`/dashboard/settings/integrations/${sepay.id}/secret`, { method: "POST", body: JSON.stringify({ key_name: "api_key", value: sepayKey }) }).then(() => setSepayKey("")), "Đã lưu API key")}>Lưu key</button>
              <button disabled={busy} onClick={() => run(() => apiFetch(`/dashboard/settings/integrations/${sepay.id}/test-connection`, { method: "POST" }), "Đã test readiness")}>Test readiness</button>
              <button disabled={busy || (!sepay.enabled && !canEnable(sepay))} onClick={() => run(() => sepay.enabled
                ? apiFetch(`/dashboard/settings/integrations/${sepay.id}/disable`, { method: "POST" })
                : apiFetch(`/dashboard/settings/integrations/${sepay.id}/enable`, { method: "POST", body: JSON.stringify({ expected_version: sepay.version }) }), sepay.enabled ? "Đã tắt" : "Đã bật")}>{sepay.enabled ? "Tắt" : "Bật"}</button>
            </div>
            <p style={{ fontSize: 12, color: "#888", marginTop: 6 }}>Bật ở đây KHÔNG tự vượt kill-switch runtime (m7_sepay_test_connector) — cần authorization kích hoạt riêng.</p>
          </div>
        )}
      </div>
    </div>
  );
}
