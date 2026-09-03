"use client";

// M5 Phase 3 (CA Directive 112) — Staff review queue: CHI TRINH BAY (read-only presentation).
// Backend la nguon enforce (permission address.review; quyet dinh/override qua API co audit bat bien).
// Dormant: queue rong toi khi co resolution 'needs_staff_review' that. Trang khong tu quyet dinh gi.

import { useEffect, useState } from "react";
import { apiFetch } from "../../lib/api";
import { useAuthGuard } from "../../lib/useAuthGuard";

const box = { border: "1px solid #e5e7eb", borderRadius: 8, padding: 16, marginTop: 14, background: "#fff" };
const th = { textAlign: "left", padding: "6px 8px", borderBottom: "2px solid #e5e7eb", fontSize: 13 };
const td = { padding: "6px 8px", borderBottom: "1px solid #f1f5f9", fontSize: 13, verticalAlign: "top" };

const STATE_LABEL = {
  open: "Chờ xử lý", assigned: "Đã giao", resolved: "Đã xử lý", rejected: "Từ chối", expired: "Hết hạn",
};

export default function AddressReviewPage() {
  const ready = useAuthGuard();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!ready) return;
    apiFetch("/dashboard/address-review/list")
      .then((r) => setRows(Array.isArray(r) ? r : []))
      .catch((e) => setError(e?.message || "Không tải được danh sách"));
  }, [ready]);

  if (!ready) return null;
  return (
    <main style={{ padding: 24, maxWidth: 960 }}>
      <h1>Hàng đợi xác minh địa chỉ (staff)</h1>
      <p style={{ fontSize: 13.5, color: "#6b7280" }}>
        Danh sách địa chỉ cần người phụ trách xem lại (kết quả “cần staff review”). Trang chỉ hiển thị; mọi
        quyết định thực hiện qua thao tác có kiểm soát ở backend (quyền <b>address.review</b>, ghi vết đầy đủ).
      </p>

      {error && <div style={{ ...box, borderColor: "#fca5a5", color: "#b91c1c" }}>{error}</div>}

      <div style={box}>
        {rows === null && <p style={{ fontSize: 14 }}>Đang tải…</p>}
        {rows !== null && rows.length === 0 && (
          <p style={{ fontSize: 14, color: "#6b7280" }}>
            Hàng đợi trống — hiện chưa có địa chỉ nào cần xem lại. (Tính năng đang ở trạng thái tạm nghỉ.)
          </p>
        )}
        {rows !== null && rows.length > 0 && (
          <div style={{ overflowX: "auto" }}>
            <table style={{ borderCollapse: "collapse", width: "100%" }}>
              <thead>
                <tr>
                  <th style={th}>Trạng thái</th><th style={th}>Đối tượng</th><th style={th}>Lý do</th>
                  <th style={th}>Người xử lý</th><th style={th}>Tạo lúc</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td style={td}>{STATE_LABEL[r.state] || r.state}</td>
                    <td style={td}>{r.subject_type}{r.subject_id ? ` #${r.subject_id}` : ""}</td>
                    <td style={td}>{r.reason || "—"}</td>
                    <td style={td}>{r.assignee || r.resolved_by || "—"}</td>
                    <td style={td}>{r.created_at ? String(r.created_at).slice(0, 19).replace("T", " ") : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </main>
  );
}
