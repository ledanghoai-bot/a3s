"use client";

// CA Acceptance 96: nhom menu "Niem phong hoi thoai" (cosmetic) gom 2 muc signing:
// - Mo phien niem phong (/signer-access) = cap phien/quyen (signer access)
// - Thuc hien niem phong (/signing)       = chay ky (signing run)
// CHI trinh bay: route/permission/API khong doi. "Niem phong" = chu ky so chong gia mao/choi bo
// (KHONG phai encryption).

import { useState } from "react";

export default function NavSigning() {
  const [open, setOpen] = useState(false);
  return (
    <span
      style={{ position: "relative", display: "inline-block" }}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <a
        href="#"
        onClick={(e) => { e.preventDefault(); setOpen(!open); }}
        aria-haspopup="true"
        aria-expanded={open}
      >
        Niêm phong hội thoại ▾
      </a>
      {open && (
        <span
          style={{
            position: "absolute", top: "100%", left: 0, background: "#fff",
            border: "1px solid #e5e7eb", borderRadius: 6, padding: 6, minWidth: 200,
            boxShadow: "0 4px 12px rgba(0,0,0,0.12)", zIndex: 50,
            display: "flex", flexDirection: "column",
          }}
        >
          <a href="/signer-access" style={{ padding: "6px 10px", whiteSpace: "nowrap" }}>
            Mở phiên niêm phong
          </a>
          <a href="/signing" style={{ padding: "6px 10px", whiteSpace: "nowrap" }}>
            Thực hiện niêm phong
          </a>
        </span>
      )}
    </span>
  );
}
