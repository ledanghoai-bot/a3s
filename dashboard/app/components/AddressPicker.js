"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "../../lib/api";

// CA Directive 396 §3.1 (F2): dia chi Dashboard CO CAU TRUC — Tinh + Phuong/Xa chon tu danh muc dataset ACTIVE,
// So nha/duong nhap tu do. Khi server tra 409 address_needs_staff_confirmation (kem candidates) -> hien danh sach
// de nhan vien chon dung Phuong/Xa + nhap LY DO xac nhan (bat buoc, 5-500 ky tu) roi gui lai.
export const EMPTY_ADDRESS = {
  province_code: "", province_name: "", ward_code: "", ward_name: "", street_text: "", confirm_reason: "",
};

export function addressPayload(v) {
  const p = { province_code: v.province_code, ward_code: v.ward_code, street_text: v.street_text.trim() };
  if (v.confirm_reason && v.confirm_reason.trim()) p.staff_confirm = { reason: v.confirm_reason.trim() };
  return p;
}

export function addressText(v) {
  return [v.street_text.trim(), v.ward_name, v.province_name].filter(Boolean).join(", ");
}

export function addressComplete(v) {
  return Boolean(v.province_code && v.ward_code && v.street_text.trim());
}

export default function AddressPicker({ value, onChange, candidates = null, disabled = false }) {
  const [provinces, setProvinces] = useState([]);
  const [wards, setWards] = useState([]);
  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    apiFetch("/dashboard/address-catalog/provinces")
      .then((r) => setProvinces(r.provinces || []))
      .catch((e) => setLoadError(e.message));
  }, []);

  useEffect(() => {
    if (!value.province_code) {
      setWards([]);
      return;
    }
    apiFetch(`/dashboard/address-catalog/wards?province_code=${encodeURIComponent(value.province_code)}`)
      .then((r) => setWards(r.wards || []))
      .catch((e) => setLoadError(e.message));
  }, [value.province_code]);

  function set(patch) {
    onChange({ ...value, ...patch });
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {loadError && <div className="error-box">Không tải được danh mục địa chỉ: {loadError}</div>}
      <select
        disabled={disabled}
        value={value.province_code}
        onChange={(e) => {
          const p = provinces.find((x) => x.code === e.target.value);
          set({ province_code: e.target.value, province_name: p ? p.name : "", ward_code: "", ward_name: "" });
        }}
      >
        <option value="">-- Chọn Tỉnh/Thành phố --</option>
        {provinces.map((p) => (
          <option key={p.code} value={p.code}>{p.name}</option>
        ))}
      </select>
      <select
        disabled={disabled || !value.province_code}
        value={value.ward_code}
        onChange={(e) => {
          const w = wards.find((x) => x.code === e.target.value);
          set({ ward_code: e.target.value, ward_name: w ? w.name : "" });
        }}
      >
        <option value="">-- Chọn Phường/Xã --</option>
        {wards.map((w) => (
          <option key={w.code} value={w.code}>{w.name}</option>
        ))}
      </select>
      <input
        disabled={disabled}
        placeholder="Số nhà, tên đường"
        maxLength={300}
        value={value.street_text}
        onChange={(e) => set({ street_text: e.target.value })}
      />
      {candidates && candidates.length > 0 && (
        <div style={{ background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 6, padding: 8, fontSize: 12 }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>
            Địa chỉ chưa tự xác minh được — chọn đúng Phường/Xã và nhập lý do xác nhận:
          </div>
          {candidates.map((c) => (
            <label key={c.ward_code} style={{ display: "block", marginBottom: 2 }}>
              <input
                type="radio"
                name="addr-candidate"
                checked={value.ward_code === c.ward_code}
                disabled={disabled || c.province_code !== value.province_code}
                onChange={() => set({ ward_code: c.ward_code, ward_name: c.name })}
              />{" "}
              {c.name} ({c.ward_code}){c.chosen ? " — đang chọn" : ""}
            </label>
          ))}
          <textarea
            disabled={disabled}
            placeholder="Lý do xác nhận (bắt buộc, 5–500 ký tự)"
            maxLength={500}
            rows={2}
            style={{ width: "100%", marginTop: 4 }}
            value={value.confirm_reason}
            onChange={(e) => set({ confirm_reason: e.target.value })}
          />
        </div>
      )}
    </div>
  );
}
