"use client";

// CA Directive 305 (+ Review 307 V02) — Cài đặt Shop / Tích hợp (kiểu WooCommerce). GĐ1: tab Vận chuyển (GHN staging).
// Secret WRITE-ONLY (không đọc lại plaintext). Save ≠ Enable; test-pass (khớp config_revision + secret version) mới Enable.
// Mọi mutation gửi command_key (idempotency) + expected_version (CAS). Module OFF -> API 404 -> hiển thị "chưa bật".
import { useEffect, useState } from "react";
import { apiFetch } from "../../lib/api";
import { useAuthGuard } from "../../lib/useAuthGuard";

const GHN_STAGING_BASE = "https://dev-online-gateway.ghn.vn/shiip/public-api";

function uuid() {
  try { if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID(); } catch { /* noop */ }
  return "ck-" + Date.now() + "-" + Math.random().toString(16).slice(2);
}
// gộp command_key vào body JSON của mutation.
function withCmd(obj) { return JSON.stringify({ ...obj, command_key: uuid() }); }

function Badge({ text, tone }) {
  const bg = { ok: "#e6f4ea", warn: "#fff4e5", bad: "#fdecea", neutral: "#eef1f4" }[tone] || "#eef1f4";
  const fg = { ok: "#1e7e34", warn: "#9a6700", bad: "#b71c1c", neutral: "#444" }[tone] || "#444";
  return <span style={{ background: bg, color: fg, padding: "2px 8px", borderRadius: 10, fontSize: 12 }}>{text}</span>;
}

// Enable được khi: test PASS + config_version(test) == config_revision hiện tại + secret_version khớp + đang tắt.
function canEnable(it) {
  const t = it.last_test || {};
  const secrets = it.secrets || {};
  const secVer = Object.keys(secrets).length ? Math.max(...Object.values(secrets).map((s) => s.version)) : null;
  return t.status === "pass" && t.config_version === it.config_revision && t.secret_version === secVer && !it.enabled;
}

export default function SettingsPage() {
  const ready = useAuthGuard();
  const [tab, setTab] = useState("shipping");
  const [items, setItems] = useState([]);
  const [meta, setMeta] = useState({ crypto_configured: false, module_enabled: false });
  const [moduleOff, setModuleOff] = useState(false);
  const [sel, setSel] = useState(null); // integration đang Manage (hoặc {new:true})
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [perms, setPerms] = useState(null); // null = chưa biết -> KHÔNG ẩn (backend vẫn enforce 403)

  // can(p): role-specific controls (309-02). perms===null (chưa load/không provisioned) -> không ẩn; backend là nguồn enforce.
  const can = (p) => perms === null || perms.includes(p);

  useEffect(() => {
    if (!ready) return;
    load();
    apiFetch("/dashboard/auth/me")
      .then((me) => setPerms(me.rbac_provisioned ? (me.permissions || []) : null))
      .catch(() => setPerms(null));
    /* eslint-disable-next-line */
  }, [ready]);

  async function load() {
    setErr(null);
    try {
      const d = await apiFetch(`/dashboard/settings/integrations?kind=shipping`);
      setItems(d.items || []);
      setMeta({ crypto_configured: d.crypto_configured, module_enabled: d.module_enabled });
      setModuleOff(false);
    } catch (e) {
      if (String(e.message).includes("404") || /chua bat/i.test(e.message)) { setModuleOff(true); }
      else setErr(e.message);
    }
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

      {moduleOff && (
        <p style={{ background: "#eef1f4", color: "#444", padding: 12, borderRadius: 6 }}>
          Module Cài đặt tích hợp <b>chưa được bật</b> trên server (đang dormant). Sau khi vận hành Apply và bật
          <code> settings_integrations_enabled</code>, màn hình này mới hoạt động.</p>
      )}
      {msg && <p style={{ color: "#1e7e34" }}>{msg}</p>}
      {err && <p style={{ color: "#b71c1c" }}>{err}</p>}

      {tab === "general" && (
        <p style={{ color: "#555" }}>Thông tin shop chung. Các chính sách giao/phí/đơn-lớn vẫn ở màn hình vận hành hiện có
          (không gom vào đây) — GĐ1 chỉ liên kết, không sao chép.</p>
      )}

      {tab === "payment" && (
        <div style={{ padding: 16, background: "#f6f8fa", borderRadius: 8 }}>
          <b>Thanh toán</b> — Chuyển khoản/VietQR, COD, SePay Test Mode. <Badge text="Sắp có (D306)" tone="neutral" />
          <p style={{ color: "#555", marginTop: 6 }}>SePay Live: <Badge text="Khóa — cần gate S1" tone="bad" /></p>
        </div>
      )}

      {tab === "shipping" && !moduleOff && (
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

          {/* Hàng đợi địa chỉ chưa khớp (Directive 305 §2) — link tới màn hình review địa chỉ THẬT (/address-review), không sao chép dữ liệu. */}
          <div style={{ border: "1px solid #e3e6ea", borderRadius: 8, padding: 12, marginBottom: 16, background: "#fbfcfd" }}>
            <b>Địa chỉ chưa khớp (GHN)</b>
            <div style={{ color: "#555", fontSize: 13 }}>
              Đơn có địa chỉ chưa map sang mã GHN sẽ chờ nhân viên xử lý ở hàng đợi review địa chỉ.
              {" "}<a href="/address-review">Mở hàng đợi review địa chỉ →</a>
            </div>
          </div>

          <h3>Đơn vị vận chuyển</h3>
          {ghn ? (
            <ProviderRow it={ghn} can={can} onManage={() => setSel(ghn)}
              onTest={() => act(() => apiFetch(`/dashboard/settings/integrations/${ghn.id}/test-connection`, { method: "POST" }), "Đã test kết nối")}
              onToggle={() => act(() => ghn.enabled
                ? apiFetch(`/dashboard/settings/integrations/${ghn.id}/disable`, { method: "POST", body: withCmd({ expected_version: ghn.version }) })
                : apiFetch(`/dashboard/settings/integrations/${ghn.id}/enable`, { method: "POST", body: withCmd({ expected_version: ghn.version }) }),
                ghn.enabled ? "Đã tắt" : "Đã bật")}
              busy={busy} />
          ) : (
            can("settings.integration.manage_public") && (
              <button disabled={busy} onClick={() => act(() => apiFetch(`/dashboard/settings/integrations`, {
                method: "POST", body: withCmd({ kind: "shipping", provider: "ghn", label: "GHN staging", mode: "staging",
                  config_public: { base_url: GHN_STAGING_BASE } }) }), "Đã tạo GHN staging").then((r) => r && setSel(r))}>
                + Thêm GHN staging
              </button>
            )
          )}

          {sel && sel.provider === "ghn" && (
            <GhnManage it={sel} can={can} busy={busy} onClose={() => setSel(null)} reload={load} setBusy={setBusy}
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

function ProviderRow({ it, can, onManage, onTest, onToggle, busy }) {
  const t = it.last_test || {};
  const c = can || (() => true);
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
      {c("settings.integration.test") && <button disabled={busy} onClick={onTest}>Test kết nối</button>}
      {c("settings.integration.activate") &&
        <button disabled={busy || (!it.enabled && !canEnable(it))} onClick={onToggle}>{it.enabled ? "Tắt" : "Bật"}</button>}
    </div>
  );
}

function GhnManage({ it, can, busy, onClose, reload, setBusy, setMsg, setErr }) {
  const c = can || (() => true);
  const cp = it.config_public || {};
  const init = {
    label: it.label, shop_id: cp.shop_id || "", from_district_id: cp.from_district_id ?? "",
    from_ward_code: cp.from_ward_code || "", timeout_seconds: cp.timeout_seconds ?? 8,
    max_retries: cp.max_retries ?? 2, light_max_g: cp.light_max_g ?? 20000, address_map_version: cp.address_map_version ?? 1,
  };
  const [form, setForm] = useState(init);
  const [token, setToken] = useState("");
  const dirty = JSON.stringify(form) !== JSON.stringify(init);

  async function run(fn, ok) {
    setBusy(true); setErr(null); setMsg(null);
    try { await fn(); if (ok) setMsg(ok); await reload(); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  }
  const num = (v) => (v === "" || v == null ? null : Number(v));

  return (
    <div style={{ border: "1px solid #cdd3da", borderRadius: 8, padding: 16, marginTop: 12, background: "#fafbfc" }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>Quản lý GHN staging (#{it.id}, v{it.version}, cfg-rev {it.config_revision})</h3>
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
          {c("settings.integration.secret_write") &&
            <button disabled={busy || !token} style={{ marginLeft: 8 }}
              onClick={() => run(() => apiFetch(`/dashboard/settings/integrations/${it.id}/secret`, {
                method: "POST", body: withCmd({ key_name: "token", value: token, expected_version: it.version }) }).then(() => setToken("")),
                "Đã lưu token")}>
              {it.secrets?.token ? "Xoay token" : "Lưu token"}</button>}
          {/* Xóa hẳn (purge) CHỈ hiện cho PO/owner có settings.integration.secret_purge (309-02). */}
          {it.secrets?.token && c("settings.integration.secret_purge") && (
            <button disabled={busy} style={{ marginLeft: 8, color: "#b71c1c" }}
              title="Xóa hẳn token (PO/owner)"
              onClick={() => { if (confirm("Xóa hẳn token GHN? Tích hợp sẽ bị tắt.")) run(() =>
                apiFetch(`/dashboard/settings/integrations/${it.id}/secret/token/purge`, {
                  method: "POST", body: withCmd({ expected_version: it.version }) }), "Đã xóa token"); }}>
              Xóa token (PO)</button>
          )}
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

      <div style={{ marginTop: 14, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        {c("settings.integration.manage_public") &&
          <button disabled={busy || !dirty} onClick={() => run(() => apiFetch(`/dashboard/settings/integrations/${it.id}`, {
            method: "PATCH", body: withCmd({ label: form.label, expected_version: it.version, config_public: {
              shop_id: form.shop_id, from_district_id: num(form.from_district_id), from_ward_code: form.from_ward_code,
              timeout_seconds: num(form.timeout_seconds), max_retries: num(form.max_retries),
              light_max_g: num(form.light_max_g), address_map_version: num(form.address_map_version) } }) }), "Đã lưu cấu hình")}>
            Lưu cấu hình{dirty ? " *" : ""}</button>}
        {c("settings.integration.test") &&
          <button disabled={busy} onClick={() => run(() => apiFetch(`/dashboard/settings/integrations/${it.id}/test-connection`, { method: "POST" }), "Đã test kết nối")}>
            Test kết nối (read-only)</button>}
        {c("settings.integration.activate") && <button disabled={busy || !canEnable(it)} title={canEnable(it) ? "" : "Cần test PASS khớp cấu hình hiện tại"}
          onClick={() => run(() => apiFetch(`/dashboard/settings/integrations/${it.id}/enable`, {
            method: "POST", body: withCmd({ expected_version: it.version }) }), "Đã bật")}>Bật</button>}
        {c("settings.integration.activate") && it.enabled && <button disabled={busy} onClick={() => run(() => apiFetch(`/dashboard/settings/integrations/${it.id}/disable`, { method: "POST", body: withCmd({ expected_version: it.version }) }), "Đã tắt")}>Tắt</button>}
      </div>
      {dirty && <p style={{ fontSize: 12, color: "#9a6700", marginTop: 6 }}>Có thay đổi chưa lưu (*). Lưu trước khi test/bật.</p>}
      <p style={{ fontSize: 12, color: "#888", marginTop: 8 }}>
        Lưu và Bật là hai bước riêng. Đổi cấu hình/token làm kết quả test hết hiệu lực — phải test lại trước khi bật.
        Token không bao giờ hiển thị lại; muốn đổi thì nhập giá trị mới. Xóa hẳn token là quyền riêng của PO/owner.</p>
    </div>
  );
}
