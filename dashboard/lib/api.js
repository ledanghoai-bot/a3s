const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Doi ten key tu "admin_token" -> "staff_token" (Bat 4, issue #8) - phan anh
// dung ban chat: gio la session token cua TUNG nhan vien dang nhap, khong
// phai token tinh dung chung nhu truoc. Ai da dang nhap voi ten cu se bi
// day ve /login (khong tu dong migrate) - chap nhan duoc vi day la thay doi
// bao mat co chu dich (moi nguoi phai dang nhap lai bang tai khoan that).
const TOKEN_KEY = "staff_token";

export function getToken() {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
}

// Goi API backend FastAPI, tu dong dinh kem header Authorization: Bearer
// (session token rieng cho tung nhan vien - Bat 4, thay the X-Admin-Token
// tinh dung chung truoc day).
// Neu server tra ve 401 (token sai/het han), xoa token va day nguoi dung ve /login.
export async function apiFetch(path, options = {}) {
  const token = getToken();
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: token ? `Bearer ${token}` : "",
      ...(options.headers || {}),
    },
  });

  if (res.status === 401) {
    clearToken();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new Error("Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại");
  }

  if (!res.ok) {
    let detail = `Lỗi ${res.status}`;
    try {
      const body = await res.json();
      if (body && body.detail) detail = body.detail;
    } catch {
      // body khong phai JSON, giu detail mac dinh
    }
    throw new Error(detail);
  }

  if (res.status === 204) return null;
  return res.json();
}
