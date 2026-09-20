// CA Review 311-01 — cổng quyền UI Settings, FAIL-CLOSED (thuần, không React → test được bằng node:test).
// permState: "loading" | "loaded" | "error" | "unprovisioned".
//   - mutation control CHỈ render khi ready (permState==="loaded" và perms là mảng);
//   - can(p) CHỈ true khi đã loaded VÀ perms chứa p (không fail-open khi loading/error/unprovisioned);
//   - secret_purge (và mọi action khác) tuyệt đối không hiện trước khi xác nhận quyền.
// Backend RBAC vẫn là nguồn enforce 403; đây chỉ là lớp hiển thị.
export function makeGate(permState, perms) {
  const ready = permState === "loaded" && Array.isArray(perms);
  return {
    ready,                                   // true -> được phép render mutation controls
    loading: permState === "loading",
    error: permState === "error",
    unprovisioned: permState === "unprovisioned",
    can: (p) => ready && perms.includes(p),  // FAIL-CLOSED
  };
}
