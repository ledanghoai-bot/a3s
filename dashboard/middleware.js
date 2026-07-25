// Nonce-based CSP cho dashboard (I-B M0.5, CA-REVIEW-M0-DEV-004 §5).
// Bỏ 'unsafe-inline' cho script-src -> XSS injected inline-script KHÔNG chạy được -> không đọc/exfil
// được token trong localStorage (đúng threat model CA). Next 14 App Router đọc nonce từ CSP header
// (middleware) và tự gắn vào bootstrap/hydration scripts. 'strict-dynamic' cho script do nonce-script nạp.
// style-src giữ 'unsafe-inline' (inline style KHÔNG execute -> không exfil token); style nonce là follow-up UX.
import { NextResponse } from "next/server";

export function middleware(request) {
  const nonce = crypto.randomUUID();
  const api = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const csp = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    `connect-src 'self' ${api}`,
    "frame-ancestors 'none'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("Referrer-Policy", "no-referrer");
  return response;
}

export const config = {
  // Ap cho moi route tru static assets cua Next
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
