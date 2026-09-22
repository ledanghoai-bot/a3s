"use client";

// CA Directive 305 (+ Review 307 V02) — Cài đặt Shop / Tích hợp (kiểu WooCommerce). GĐ1: tab Vận chuyển (GHN staging).
// Secret WRITE-ONLY (không đọc lại plaintext). Save ≠ Enable; test-pass (khớp config_revision + secret version) mới Enable.
// Mọi mutation gửi command_key (idempotency) + expected_version (CAS). Module OFF -> API 404 -> hiển thị "chưa bật".
import { useEffect, useState } from "react";
import { apiFetch } from "../../lib/api";
import { useAuthGuard } from "../../lib/useAuthGuard";
import { makeGate } from "./permGate.mjs";

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
  // CA 311-01: FAIL-CLOSED. permState = loading|loaded|error|unprovisioned; mutation controls chỉ hiện khi loaded.
  const [permState, setPermState] = useState("loading");
  const [perms, setPerms] = useState([]);
  const gate = makeGate(permState, perms);
  const can = gate.can;

  async function loadPerms() {
    setPermState("loading");
    try {
      const me = await apiFetch("/dashboard/auth/me");
      if (!me.rbac_provisioned) { setPerms([]); setPermState("unprovisioned"); }
      else { setPerms(me.permissions || []); setPermState("loaded"); }
    } catch { setPerms([]); setPermState("error"); }
  }

  useEffect(() => {
    if (!ready) return;
    load();
    loadPerms();
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
        moduleOff
          ? null
          : <PaymentSettings can={can} setMsg={setMsg} setErr={setErr} />
      )}

      {tab === "shipping" && !moduleOff && (
        <div>
          {!meta.crypto_configured && (
            <p style={{ background: "#fff4e5", color: "#9a6700", padding: 10, borderRadius: 6 }}>
              ⚠ Khóa mã hóa (CONFIG_ENC_KEYS) chưa cấu hình trên server — chưa lưu/xoay được secret. Liên hệ vận hành.</p>
          )}
          {/* CA 311-01: trong lúc loading/error/unprovisioned KHÔNG render mutation control (gate.can=false); hiện trạng thái. */}
          {gate.loading && <p style={{ color: "#555" }}>Đang tải quyền…</p>}
          {gate.error && (
            <p style={{ background: "#fdecea", color: "#b71c1c", padding: 10, borderRadius: 6 }}>
              Không tải được quyền — các thao tác đang bị ẩn để an toàn.{" "}
              <button onClick={loadPerms}>Thử lại</button></p>
          )}
          {gate.unprovisioned && (
            <p style={{ background: "#eef1f4", color: "#444", padding: 10, borderRadius: 6 }}>
              Tài khoản chưa được gán quyền cấu hình tích hợp — chỉ xem, không có thao tác.</p>
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

      {/* CA Directive 340 §1.2 — Shipping Settings: packing overhead (độc lập module integrations, endpoint riêng). */}
      {tab === "shipping" && <PackingSettings can={can} setMsg={setMsg} setErr={setErr} />}
    </div>
  );
}


function PackingSettings({ can, setMsg, setErr }) {
  const [st, setSt] = useState(null);      // {packing_overhead_percent, version, updated_by, updated_at}
  const [val, setVal] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const d = await apiFetch("/dashboard/shipping-settings");
      setSt(d);
      setVal(d.packing_overhead_percent == null ? "" : String(d.packing_overhead_percent));
    } catch (e) { setErr && setErr(e.message); }
  }
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  async function save() {
    setMsg && setMsg(null); setErr && setErr(null);
    if (val === "" || Number(val) < 0 || !isFinite(Number(val))) {
      setErr && setErr("Nhập % đóng thùng ≥ 0."); return;
    }
    setBusy(true);
    try {
      const r = await apiFetch("/dashboard/shipping-settings", {
        method: "PUT",
        body: JSON.stringify({ packing_overhead_percent: Number(val), expected_version: st?.version }),
      });
      setSt((s) => ({ ...s, packing_overhead_percent: r.packing_overhead_percent, version: r.version,
        updated_by: r.updated_by }));
      setMsg && setMsg("Đã lưu % đóng thùng.");
    } catch (e) { setErr && setErr(e.message); await load(); } finally { setBusy(false); }
  }

  return (
    <div style={{ border: "1px solid #e3e6ea", borderRadius: 8, padding: 12, marginTop: 16, background: "#fbfcfd" }}>
      <b>Hệ số đóng thùng (packing overhead)</b>
      <div style={{ color: "#555", fontSize: 13, marginBottom: 8 }}>
        Phần trăm thể tích tăng thêm khi đóng chung nhiều đơn vị (chỉ áp khi đơn có &gt; 1 đơn vị). Dùng để tính
        trọng lượng quy đổi cho phí giao dự phòng khi GHN không báo giá được. Để trống → phí giao dự phòng chuyển
        nhân viên (fail-closed).
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input type="number" min="0" step="0.1" style={{ width: 140 }} placeholder="vd 10 (%)"
          value={val} onChange={(e) => setVal(e.target.value)} disabled={!can("shipment.manage")} />
        <span style={{ color: "#555" }}>%</span>
        {can("shipment.manage") && (
          <button className="primary" disabled={busy} onClick={save}>{busy ? "Đang lưu…" : "Lưu"}</button>
        )}
      </div>
      <div style={{ color: "#888", fontSize: 12, marginTop: 6 }}>
        Hiện tại: {st == null ? "…" : (st.packing_overhead_percent == null
          ? <span style={{ color: "#c00" }}>chưa cấu hình</span>
          : `${st.packing_overhead_percent}%`)}
        {st && ` · phiên bản ${st.version}${st.updated_by ? ` · sửa bởi ${st.updated_by}` : ""}`}
        {!can("shipment.manage") && " · (chỉ xem — cần quyền quản lý vận chuyển để sửa)"}
      </div>
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

// CA Directive 306 + Review 308 — tab Thanh toán. Bank field-level (public=manage_public / account=secret_write) + CAS
// + command_key; VietQR test không silent-substitute; SePay S0 (readiness trung thực, allowed-account/prefix qua config);
// webhook/health readback; role-specific controls (can() fail-closed từ parent). Live: khóa.
function PaymentSettings({ can, setMsg, setErr }) {
  const [ov, setOv] = useState(null);
  const [off, setOff] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pub, setPub] = useState(null);
  const [acct, setAcct] = useState("");
  const [amount, setAmount] = useState("");
  const [orderId, setOrderId] = useState("");
  const [sepayKey, setSepayKey] = useState("");
  const [sepayCfg, setSepayCfg] = useState(null);

  async function load() {
    setErr(null);
    try {
      const d = await apiFetch(`/dashboard/settings/payments`);
      setOv(d); setOff(false);
      const a = d.bank_transfer.account;
      setPub(a ? { bank: a.bank, bin: a.bin || "", holder_name: a.holder_name, branch: a.branch || "", is_test: a.is_test } : { bank: "", bin: "", holder_name: "", branch: "", is_test: false });
      const sp = (d.sepay?.integrations || []).find((i) => i.provider === "sepay");
      const cp = sp?.config_public || {};
      setSepayCfg({ allowed_accounts: cp.allowed_accounts || "", code_prefix: cp.code_prefix || "" });
    } catch (e) { if (String(e.message).includes("404")) setOff(true); else setErr(e.message); }
  }
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);
  async function run(fn, ok) {
    setBusy(true); setErr(null); setMsg(null);
    try { const r = await fn(); if (ok) setMsg(ok); await load(); return r; } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }
  if (off) return <p style={{ background: "#eef1f4", color: "#444", padding: 12, borderRadius: 6 }}>Module Cài đặt chưa bật (dormant) — tab Thanh toán chưa hoạt động.</p>;
  if (!ov || !pub) return <p>Đang tải…</p>;
  const acctRow = ov.bank_transfer.account;
  const ver = acctRow?.version ?? 0;
  const sepay = (ov.sepay?.integrations || []).find((i) => i.provider === "sepay");
  const hasBank = !!acctRow;

  return (
    <div>
      <div style={{ border: "1px solid #e3e6ea", borderRadius: 8, padding: 14, marginBottom: 12 }}>
        <b>Chuyển khoản / VietQR</b> {acctRow?.is_test && <Badge text="TEST" tone="warn" />}
        <div style={{ fontSize: 13, color: "#555", marginTop: 4 }}>
          {hasBank ? `${acctRow.bank} · BIN ${acctRow.bin || "—"} · ${acctRow.holder_name} · ••••${acctRow.account_last4 || "----"} · v${ver}` : "Chưa cấu hình tài khoản nhận."}
        </div>
        <p style={{ fontSize: 12, color: "#9a6700", marginTop: 4 }}>⚠ Đổi tài khoản chỉ áp dụng cho hướng dẫn chuyển khoản MỚI; snapshot đã phát cho khách bất biến.</p>

        {can("settings.integration.manage_public") && (
          <details style={{ marginTop: 8 }}>
            <summary>Sửa thông tin công khai (không gồm số TK)</summary>
            <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
              <input placeholder="ngân hàng" value={pub.bank} onChange={(e) => setPub({ ...pub, bank: e.target.value })} />
              <input placeholder="BIN NAPAS (6 số)" value={pub.bin} onChange={(e) => setPub({ ...pub, bin: e.target.value })} />
              <input placeholder="chủ TK" value={pub.holder_name} onChange={(e) => setPub({ ...pub, holder_name: e.target.value })} />
              <input placeholder="chi nhánh" value={pub.branch} onChange={(e) => setPub({ ...pub, branch: e.target.value })} />
              <label style={{ fontSize: 13 }}><input type="checkbox" checked={pub.is_test} onChange={(e) => setPub({ ...pub, is_test: e.target.checked })} /> test</label>
              <button disabled={busy || !hasBank} title={hasBank ? "" : "Cần nhập số TK trước (secret_write)"}
                onClick={() => run(() => apiFetch(`/dashboard/settings/payments/bank/public`, { method: "POST", body: withCmd({ expected_version: ver, bank: pub.bank, bin: pub.bin, holder_name: pub.holder_name, branch: pub.branch, is_test: pub.is_test }) }), "Đã lưu thông tin công khai")}>Lưu công khai</button>
            </div>
          </details>
        )}
        {can("settings.integration.secret_write") && (
          <details style={{ marginTop: 8 }}>
            <summary>{hasBank ? "Thay số tài khoản (write-only)" : "Nhập số tài khoản (write-only)"}</summary>
            <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
              {!hasBank && <><input placeholder="ngân hàng" value={pub.bank} onChange={(e) => setPub({ ...pub, bank: e.target.value })} /><input placeholder="chủ TK" value={pub.holder_name} onChange={(e) => setPub({ ...pub, holder_name: e.target.value })} /></>}
              <input placeholder="số tài khoản (6-19 số)" value={acct} onChange={(e) => setAcct(e.target.value)} />
              <button disabled={busy || !acct} onClick={() => run(() => apiFetch(`/dashboard/settings/payments/bank/account`, { method: "POST", body: withCmd(hasBank ? { expected_version: ver, account_number: acct } : { expected_version: 0, account_number: acct, create: { bank: pub.bank, holder_name: pub.holder_name, bin: pub.bin, is_test: pub.is_test } }) }).then(() => setAcct("")), "Đã lưu số tài khoản")}>Lưu số TK</button>
              {hasBank && (
                <button style={{ color: "#b71c1c" }} disabled={busy}
                  title="Xóa (ngừng dùng) tài khoản nhận hiện hành — hướng dẫn CK mới sẽ bị khóa cho tới khi nhập lại"
                  onClick={() => { if (confirm("Xóa tài khoản nhận hiện hành? Hướng dẫn chuyển khoản MỚI sẽ bị khóa (snapshot đã phát vẫn giữ). Cần nhập tài khoản mới để phát lại.")) run(() => apiFetch(`/dashboard/settings/payments/bank/account/clear`, { method: "POST", body: withCmd({ expected_version: ver }) }), "Đã xóa tài khoản nhận"); }}>
                  Xóa tài khoản</button>
              )}
            </div>
          </details>
        )}
        {can("settings.integration.test") && hasBank && (
          <div style={{ marginTop: 10, display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            <input placeholder="số tiền (VND)" value={amount} onChange={(e) => setAmount(e.target.value)} style={{ width: 120 }} />
            <input placeholder="mã đơn (order id)" value={orderId} onChange={(e) => setOrderId(e.target.value)} style={{ width: 120 }} />
            <button disabled={busy} onClick={() => {
              const a = Number(amount), o = Number(orderId);
              if (!Number.isInteger(a) || a <= 0) { setErr("Số tiền phải là số nguyên > 0"); return; }
              if (!Number.isInteger(o) || o < 1) { setErr("Mã đơn phải là số nguyên ≥ 1"); return; }
              run(async () => { const r = await apiFetch(`/dashboard/settings/payments/vietqr-self-test`, { method: "POST", body: JSON.stringify({ amount_vnd: a, order_id: o }) }); setMsg(r.ok ? `VietQR self-test ĐẠT (BIN ${r.bin}, ••••${r.account_last4}, CRC hợp lệ)` : `VietQR self-test LỖI: ${r.error_class}`); });
            }}>Test VietQR (local, không chuyển tiền)</button>
          </div>
        )}
      </div>

      <div style={{ border: "1px solid #e3e6ea", borderRadius: 8, padding: 14, marginBottom: 12 }}>
        <b>COD</b> <Badge text="Vận hành qua Giao & Thu tiền" tone="neutral" />
        <div style={{ fontSize: 13, color: "#555" }}>{ov.cod.note}</div>
      </div>

      <div style={{ border: "1px solid #e3e6ea", borderRadius: 8, padding: 14 }}>
        <b>SePay Test Mode (S0)</b> {sepay ? (sepay.enabled ? <Badge text="Bật" tone="ok" /> : <Badge text="Tắt" tone="neutral" />) : <Badge text="Chưa tạo" tone="neutral" />}
        {" "}<Badge text="Live: Khóa — cần gate S1" tone="bad" />
        <div style={{ fontSize: 12, color: "#555", marginTop: 4 }}>
          Webhook: <code>{ov.sepay?.webhook?.endpoint}</code> · Auth: {ov.sepay?.webhook?.auth_mode} ·
          Connector: {ov.sepay?.webhook?.connector_enabled ? "ON" : "OFF (kill-switch)"} ·
          Sự kiện gần nhất: {ov.sepay?.health?.last_event_at || "—"} · Đếm theo trạng thái: {JSON.stringify(ov.sepay?.health?.event_counts || {})}
        </div>
        {!sepay ? (
          can("settings.integration.manage_public") && (
            <div style={{ marginTop: 8 }}>
              <button disabled={busy} onClick={() => run(() => apiFetch(`/dashboard/settings/integrations`, { method: "POST", body: withCmd({ kind: "payment", provider: "sepay", label: "SePay Test", mode: "test", config_public: {} }) }), "Đã tạo SePay Test")}>+ Thêm SePay Test</button>
            </div>
          )
        ) : (
          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: 13, color: "#555" }}>
              API key: {sepay.secrets?.api_key ? `đã lưu (v${sepay.secrets.api_key.version})` : "chưa nhập"} ·
              Readiness: {sepay.last_test?.status ? <Badge text={sepay.last_test.status === "pass" ? "Đã lưu + đủ cấu hình (chưa xác thực với SePay)" : "Lỗi"} tone={sepay.last_test.status === "pass" ? "ok" : "bad"} /> : "chưa test"}
            </div>
            {can("settings.integration.manage_public") && sepayCfg && (
              <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                <input placeholder="TK nhận cho phép (CSV)" value={sepayCfg.allowed_accounts} onChange={(e) => setSepayCfg({ ...sepayCfg, allowed_accounts: e.target.value })} style={{ width: 220 }} />
                <input placeholder="tiền tố mã (prefix, vd SEVQR)" value={sepayCfg.code_prefix} onChange={(e) => setSepayCfg({ ...sepayCfg, code_prefix: e.target.value })} style={{ width: 160 }} />
                <button disabled={busy} onClick={() => run(() => apiFetch(`/dashboard/settings/integrations/${sepay.id}`, { method: "PATCH", body: withCmd({ expected_version: sepay.version, config_public: { allowed_accounts: sepayCfg.allowed_accounts, code_prefix: sepayCfg.code_prefix } }) }), "Đã lưu cấu hình SePay")}>Lưu cấu hình</button>
              </div>
            )}
            <p style={{ fontSize: 12, color: "#888", marginTop: 4 }}>Tiền tố mã (prefix) do bạn tự cấu hình để hệ thống nhận diện đơn (2–12 ký tự A-Z/0-9, tự chuyển hoa). Phải có prefix hợp lệ trước khi readiness/bật. Nội dung CK mới sẽ là "&lt;prefix&gt; &lt;mã đơn&gt;".</p>
            <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
              {can("settings.integration.secret_write") && <>
                <input type="password" placeholder={sepay.secrets?.api_key ? "•••• đã lưu — để trống nếu không đổi" : "SePay Test API key"} value={sepayKey} onChange={(e) => setSepayKey(e.target.value)} style={{ width: 280 }} />
                <button disabled={busy || !sepayKey} onClick={() => run(() => apiFetch(`/dashboard/settings/integrations/${sepay.id}/secret`, { method: "POST", body: withCmd({ key_name: "api_key", value: sepayKey, expected_version: sepay.version }) }).then(() => setSepayKey("")), "Đã lưu API key")}>Lưu key</button>
              </>}
              {can("settings.integration.test") && <button disabled={busy} onClick={() => run(() => apiFetch(`/dashboard/settings/integrations/${sepay.id}/test-connection`, { method: "POST" }), "Đã test readiness")}>Test readiness</button>}
              {can("settings.integration.activate") && <button disabled={busy || (!sepay.enabled && !canEnable(sepay))} onClick={() => run(() => sepay.enabled ? apiFetch(`/dashboard/settings/integrations/${sepay.id}/disable`, { method: "POST", body: withCmd({ expected_version: sepay.version }) }) : apiFetch(`/dashboard/settings/integrations/${sepay.id}/enable`, { method: "POST", body: withCmd({ expected_version: sepay.version }) }), sepay.enabled ? "Đã tắt" : "Đã bật")}>{sepay.enabled ? "Tắt" : "Bật"}</button>}
            </div>
            <p style={{ fontSize: 12, color: "#888", marginTop: 6 }}>Readiness chỉ xác nhận key đã lưu/giải mã được + đủ cấu hình — KHÔNG phải xác thực với SePay (xác thực xảy ra khi SePay gửi webhook). Bật ở đây KHÔNG tự vượt kill-switch runtime (m7_sepay_test_connector) — cần authorization kích hoạt riêng.</p>
          </div>
        )}
      </div>
    </div>
  );
}
