"""API noi bo cho nhan vien: bat lai bot sau khi da xu ly xong hoi thoai
(issue #7 - human handoff).

⚠️ LEGACY: trang `/admin/ui` la giai phap tam thoi tu truoc khi dashboard
Next.js (issue #8) hoan thien - gio dashboard chinh (`/conversations`) da co
y het chuc nang nay (liet ke + resume 1-click), nên dùng dashboard chính làm
chinh. Trang nay van giu lai nhu 1 fallback nhe, khong can build/deploy
Next.js - từ Bat 4 (17/7) cần dán **session token** (lấy sau khi đăng nhập
ở dashboard chính, xem `localStorage.staff_token` qua DevTools) thay vì
ADMIN_API_TOKEN tĩnh như trước.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from app.api.auth import require_staff_session
from app.services.handoff import list_paused_conversations, resume_bot

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/conversations/{psid}/resume", dependencies=[Depends(require_staff_session)])
async def resume_conversation(psid: str) -> dict:
    """Bat lai bot cho 1 khach (bot_paused=FALSE). Goi sau khi nhan vien da
    tra loi/xu ly xong hoi thoai ngoai Messenger."""
    found = await resume_bot(psid)
    if not found:
        raise HTTPException(status_code=404, detail=f"Khong tim thay hoi thoai cho psid {psid}")
    return {"psid": psid, "bot_paused": False}


@router.get("/conversations/paused", dependencies=[Depends(require_staff_session)])
async def list_paused() -> list[dict]:
    """Liet ke hoi thoai dang cho nhan vien, dung cho trang /admin/ui."""
    return await list_paused_conversations()


_UI_HTML = """<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<title>3S Coffee - Hoi thoai cho xu ly</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 720px; margin: 40px auto; padding: 0 16px; color: #222; }
  h1 { font-size: 20px; }
  .row { display: flex; gap: 8px; margin-bottom: 16px; }
  input { flex: 1; padding: 8px; font-size: 14px; }
  button { padding: 8px 16px; font-size: 14px; cursor: pointer; }
  .card { border: 1px solid #ddd; border-radius: 8px; padding: 12px 16px; margin-bottom: 10px; }
  .card .meta { color: #666; font-size: 13px; margin: 4px 0; }
  .empty { color: #888; padding: 20px 0; }
  .resume-btn { background: #2563eb; color: #fff; border: none; border-radius: 6px; }
  .resume-btn:disabled { background: #999; }
</style>
</head>
<body>
  <h1>3S Coffee — Hoi thoai dang cho nhan vien</h1>
  <div class="row">
    <input id="token" type="password" placeholder="Dan SESSION TOKEN (lay sau khi dang nhap dashboard chinh)">
    <button onclick="saveToken()">Luu token</button>
    <button onclick="load()">Tai lai danh sach</button>
  </div>
  <div id="list" class="empty">Nhap token roi bam "Luu token"...</div>

<script>
function saveToken() {
  localStorage.setItem('admin_token', document.getElementById('token').value);
  load();
}
window.onload = () => {
  const t = localStorage.getItem('admin_token');
  if (t) { document.getElementById('token').value = t; load(); }
};

async function load() {
  const token = document.getElementById('token').value;
  const listEl = document.getElementById('list');
  listEl.textContent = 'Dang tai...';
  try {
    const res = await fetch('/admin/conversations/paused', { headers: { 'Authorization': 'Bearer ' + token } });
    if (res.status === 401) { listEl.textContent = 'Token sai hoac thieu.'; return; }
    const data = await res.json();
    if (!data.length) { listEl.className = 'empty'; listEl.textContent = 'Khong co hoi thoai nao dang cho.'; return; }
    listEl.className = '';
    listEl.innerHTML = data.map(c => `
      <div class="card">
        <strong>${c.name || '(chua co ten)'} — ${c.phone || '(chua co sdt)'}</strong>
        <div class="meta">PSID: ${c.psid}</div>
        <div class="meta">Ly do: ${c.reason || '(khong ro)'}</div>
        <div class="meta">Luc: ${c.escalated_at || ''}</div>
        <button class="resume-btn" onclick="resume('${c.psid}', this)">Resume bot</button>
      </div>
    `).join('');
  } catch (e) {
    listEl.textContent = 'Loi tai danh sach: ' + e;
  }
}

async function resume(psid, btn) {
  btn.disabled = true;
  btn.textContent = 'Dang xu ly...';
  const token = document.getElementById('token').value;
  try {
    const res = await fetch(`/admin/conversations/${encodeURIComponent(psid)}/resume`, {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token },
    });
    if (res.ok) { load(); } else { alert('Loi: ' + res.status); btn.disabled = false; btn.textContent = 'Resume bot'; }
  } catch (e) {
    alert('Loi: ' + e); btn.disabled = false; btn.textContent = 'Resume bot';
  }
}
</script>
</body>
</html>"""


@router.get("/ui", response_class=HTMLResponse)
async def admin_ui() -> str:
    """Trang web don gian de xem danh sach hoi thoai dang cho + resume bang 1 cu click,
    khong can goi curl/bash. Token nhap 1 lan, luu trong localStorage cua trinh duyet
    (day la trang web that cua anh, khac voi Claude Artifacts nen localStorage dung
    binh thuong, khong bi cam)."""
    return _UI_HTML
