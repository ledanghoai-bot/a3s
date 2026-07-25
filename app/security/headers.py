"""Security headers middleware cho FastAPI API (I-B M0.5, CA-REVIEW-IMPL-M0 §12.2).

Luu y ranh gioi: middleware nay chi bao ve RESPONSE cua API. Dashboard Next.js o container/domain
rieng phai tu set header (Next middleware/config) + Caddy/reverse proxy la lop chinh. Test header
tren ca a3s.robanme.com (API) va a3s-dash.robanme.com (dashboard).

CSP dung 'frame-ancestors none' (chong clickjacking) — KHONG dat 'default-src none' de tranh vo
trang HTML legacy /admin/ui. Resource-CSP day du thuoc dashboard.
"""
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
        return resp
