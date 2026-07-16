"""Dependency xac thuc dung chung cho cac router noi bo (admin.py, dashboard.py).

Van la co che token tinh don gian (chua co dang nhap/JWT that - xem ISSUES.md #8,
muc "Auth don gian" con lai chua lam). Du dung cho quy mo hien tai.
"""

from fastapi import Header, HTTPException

from app.config import settings


def require_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    if not settings.admin_api_token or x_admin_token != settings.admin_api_token:
        raise HTTPException(
            status_code=401, detail="Token khong hop le hoac thieu header X-Admin-Token"
        )
