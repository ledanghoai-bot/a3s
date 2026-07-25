/** @type {import('next').NextConfig} */

// Security headers + CSP -> chuyen sang dashboard/middleware.js (nonce-based CSP, bo 'unsafe-inline'
// cho script-src, CA-REVIEW-M0-DEV-004 §5). next.config chi giu config chung.
const nextConfig = {
  reactStrictMode: true,
};

export default nextConfig;
