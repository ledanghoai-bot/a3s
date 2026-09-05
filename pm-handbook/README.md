# Sổ tay PM — site tĩnh `pm-a3s.robanme.com`

Nội dung học tập cho PO/manager về quản lý dự án AI, lấy Alpha3s làm case tham chiếu. **Ngoài phạm vi vận hành Alpha3s**: không API, không dữ liệu khách, không quyền, không migration. Không cần directive CA hay window để cập nhật.

## Cấu trúc

| Thư mục/tệp | Vai trò |
|---|---|
| `content/` | Bản sao repo cẩm nang (`E:\Alpha3s\ai-project-management-handbook`), giữ nguyên Markdown. Sửa nội dung ở đây. |
| `site/build.mjs` | Chuyển Markdown → HTML tĩnh, thêm sidebar, prev/next, mục lục trong trang. Không JavaScript phía client. |
| `site/style.css` | Giao diện. |
| `site/serve.mjs` | Máy chủ tĩnh để xem thử ở máy dev. |
| `Dockerfile` | Stage node build → stage `caddy:2-alpine` phục vụ `/srv`. Có nhãn `GIT_COMMIT` như mọi image khác. |
| `Caddyfile` | Caddy bên trong container: file_server + header bảo mật. |

Caddy chính của VPS (`docker/caddy/Caddyfile`) có block `{$PM_DOMAIN}` reverse_proxy tới `pm_site:80`. Biến `PM_DOMAIN` trong `docker-compose.prod.yml` mặc định `pm-a3s.robanme.com`; đổi qua `.env` trên VPS nếu cần.

## Xem thử ở máy dev

```bash
cd pm-handbook/site && npm ci && npm run build && npm run serve
```

Mở `http://127.0.0.1:3210/`.

## Liên kết ra hồ sơ nội bộ

Cẩm nang dẫn tới hồ sơ gốc trong workspace (`../../CA-Docs/...`). Site không công bố các hồ sơ đó: liên kết được hiển thị thành chữ thường kèm dấu † và tooltip ghi đường dẫn. Phần diễn giải và tóm tắt nguồn trong cẩm nang vẫn đọc được.

## Cập nhật nội dung

1. Sửa Markdown trong `content/` (giữ quy ước của `content/bien-tap/HUONG-DAN-CAP-NHAT.md`).
2. Chạy build thử, xem trang.
3. Commit, PR, merge `main` → CI deploy `pm_site` như các service khác.
