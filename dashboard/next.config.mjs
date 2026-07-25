/** @type {import('next').NextConfig} */

// CSP resource-level cho dashboard (I-B M0.5, CA-REVIEW-M0-DEV-003 §8).
// Luu y: Next 14 App Router chen inline hydration script -> script-src can 'unsafe-inline'
// (hoac nonce middleware). => CSP nay chan connect/frame/object/base + form-action (thu hep kenh
// exfil + clickjacking), NHUNG chua chan hoan toan inline-script doc localStorage. Nonce-based CSP
// (middleware) la follow-up bat buoc truoc khi kich hoat auth/session temporary exception
// (xem PHASE1B-AUTH-SESSION-DECISION-RECORD §5). Cookie HttpOnly (3.1) tranh duoc van de nay.
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  `connect-src 'self' ${API}`,
  "frame-ancestors 'none'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const nextConfig = {
  reactStrictMode: true,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: CSP },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "no-referrer" },
        ],
      },
    ];
  },
};

export default nextConfig;
