// Static site generator cho "Sổ tay PM" (pm-a3s.robanme.com).
//
// Đầu vào : thư mục Markdown (bản sao repo cẩm nang) — mặc định ../content
// Đầu ra  : HTML tĩnh — mặc định ../dist. Mỗi tệp .md -> .html cùng đường dẫn; README.md -> index.html.
//
// Nguyên tắc:
// - Không sửa nội dung Markdown. Chỉ chuyển đổi và bọc layout (sidebar + prev/next).
// - Liên kết .md nội bộ -> .html. Liên kết đi ra NGOÀI thư mục nội dung (hồ sơ Alpha3s trong workspace,
//   ví dụ ../../CA-Docs/...) KHÔNG được công bố -> hiển thị dạng chữ thường kèm chú thích, không tạo link hỏng.
// - Không có JavaScript phía client. CSP của site chỉ cho phép style/img cùng nguồn.
//
// Dùng: node build.mjs --content <dir> --out <dir>   (biến môi trường GIT_COMMIT để in vào footer, tuỳ chọn)

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { marked } from "marked";

// ---------- tham số ----------
const argv = process.argv.slice(2);
function arg(name, def) {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : def;
}
const CONTENT = path.resolve(arg("--content", "../content"));
const OUT = path.resolve(arg("--out", "../dist"));
const SITE_NAME = "Sổ tay PM";
const SITE_TAGLINE = "Dẫn dắt dự án AI · học từ case Alpha3s";
const GIT_COMMIT = (process.env.GIT_COMMIT || "").trim();
const BUILD_DATE = new Date().toISOString().slice(0, 10);

// ---------- cấu trúc điều hướng (thứ tự đọc theo MUC-LUC.md) ----------
// Mỗi mục: [đường dẫn .md tương đối content, nhãn ngắn]. Nhãn dài (H1) lấy từ chính tệp.
const NAV = [
  { group: "Bắt đầu", items: [
    ["README.md", "Giới thiệu"],
    ["MUC-LUC.md", "Mục lục và lộ trình học"],
    ["HANDBOOK.md", "Bản đọc liền mạch"],
  ]},
  { group: "I. Hiểu việc cần làm", items: [
    ["chuong/01-tu-bai-toan-kinh-doanh.md", "1. Bài toán kinh doanh"],
    ["chuong/02-doc-hanh-trinh-alpha3s.md", "2. Hành trình Alpha3s"],
    ["chuong/03-hieu-he-thong-ai.md", "3. Hệ thống AI"],
    ["chuong/04-pham-vi-va-roadmap.md", "4. Phạm vi và roadmap"],
  ]},
  { group: "II. Tổ chức để làm đúng", items: [
    ["chuong/05-vai-tro-va-quyet-dinh.md", "5. Vai trò và quyết định"],
    ["chuong/06-quan-ly-tri-thuc.md", "6. Quản lý tri thức"],
    ["chuong/07-dac-ta-va-nghiem-thu.md", "7. Đặc tả và nghiệm thu"],
    ["chuong/08-danh-gia-chat-luong.md", "8. Đánh giá chất lượng"],
  ]},
  { group: "III. Kiểm soát hậu quả", items: [
    ["chuong/09-ai-va-giao-dich.md", "9. AI và giao dịch"],
    ["chuong/10-rui-ro-tuong-xung.md", "10. Rủi ro tương xứng"],
    ["chuong/11-bao-ve-du-lieu.md", "11. Bảo vệ dữ liệu"],
    ["chuong/12-du-lieu-dia-chi.md", "12. Dữ liệu địa chỉ"],
  ]},
  { group: "IV. Đưa vào sử dụng", items: [
    ["chuong/13-bang-chung-va-review.md", "13. Bằng chứng và review"],
    ["chuong/14-phat-hanh-va-kich-hoat.md", "14. Phát hành và kích hoạt"],
    ["chuong/15-van-hanh-va-su-co.md", "15. Vận hành và sự cố"],
    ["chuong/16-chi-phi-va-gia-tri.md", "16. Chi phí và giá trị"],
  ]},
  { group: "V. Duy trì năng lực", items: [
    ["chuong/17-con-nguoi-va-thay-doi.md", "17. Con người và thay đổi"],
    ["chuong/18-he-dieu-hanh-quan-ly.md", "18. Nhịp quản lý"],
  ]},
  { group: "Phụ lục", items: [
    ["phu-luc/A-bo-bieu-mau.md", "A. Bộ biểu mẫu"],
    ["phu-luc/B-workbook.md", "B. Workbook"],
    ["phu-luc/C-thuat-ngu.md", "C. Từ điển thuật ngữ"],
    ["phu-luc/D-lien-he-thong-le-quoc-te.md", "D. NIST, ISO, Scrum"],
  ]},
  { group: "Nguồn và biên tập", items: [
    ["nguon/NGUON-VA-PHUONG-PHAP.md", "Nguồn và phương pháp"],
    ["nguon/DAU-VAN-TAY-NGUON.md", "Dấu vân tay nguồn"],
    ["bien-tap/BAO-CAO-KIEM-TRA.md", "Báo cáo kiểm tra bản thảo"],
    ["bien-tap/BAO-CAO-REVIEW-DEV-PM.md", "Review Dev/PM"],
    ["bien-tap/DANH-GIA-DONG-GOP-REVIEW-DEV-PM.md", "Đánh giá đóng góp review"],
    ["bien-tap/HUONG-DAN-CAP-NHAT.md", "Hướng dẫn cập nhật"],
    ["CHANGELOG.md", "Lịch sử biên soạn"],
  ]},
];
const ORDER = NAV.flatMap((g) => g.items.map((it) => it[0]));

// ---------- tiện ích ----------
function walk(dir) {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...walk(p));
    else if (e.isFile() && e.name.toLowerCase().endsWith(".md")) out.push(p);
  }
  return out;
}
function toPosix(p) { return p.split(path.sep).join("/"); }
function outRel(mdRel) {
  // README.md -> index.html ; X.md -> X.html
  if (mdRel === "README.md") return "index.html";
  return mdRel.replace(/\.md$/i, ".html");
}
function siteHref(mdRel, hash = "") {
  const o = outRel(mdRel);
  return "/" + (o === "index.html" ? "" : o) + hash;
}
function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function slugify(text) {
  return String(text)
    .toLowerCase()
    .replace(/<[^>]+>/g, "")
    .replace(/&[a-z]+;/g, "")
    .replace(/[^\p{L}\p{N}\s-]/gu, "")
    .trim()
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .slice(0, 80) || "muc";
}
function firstH1(md) {
  const m = md.match(/^#\s+(.+?)\s*$/m);
  return m ? m[1].replace(/[*_`]/g, "") : null;
}

// ---------- renderer marked ----------
function makeRenderer(mdRel) {
  const usedIds = new Map();
  const renderer = new marked.Renderer();
  const headings = []; // {level, text, id}

  renderer.heading = function (text, level) {
    let id = slugify(text);
    const n = usedIds.get(id) || 0;
    usedIds.set(id, n + 1);
    if (n) id = `${id}-${n + 1}`;
    headings.push({ level, text, id });
    return `<h${level} id="${id}"><a class="anchor" href="#${id}" aria-hidden="true">#</a>${text}</h${level}>\n`;
  };

  renderer.link = function (href, title, text) {
    const t = title ? ` title="${esc(title)}"` : "";
    if (/^(https?:)?\/\//i.test(href) || /^mailto:/i.test(href)) {
      return `<a href="${esc(href)}"${t} target="_blank" rel="noopener noreferrer">${text}</a>`;
    }
    if (href.startsWith("#")) return `<a href="${esc(href)}"${t}>${text}</a>`;

    const [file, hash = ""] = href.split("#");
    const fromDir = path.posix.dirname(mdRel);
    const target = path.posix.normalize(path.posix.join(fromDir, file));
    if (target.startsWith("..")) {
      // Liên kết ra ngoài thư mục nội dung: hồ sơ nội bộ Alpha3s, không công bố.
      return `<span class="doc-ref" title="Hồ sơ nội bộ Alpha3s (${esc(target)}) — không công bố trên site này">${text}<sup>†</sup></span>`;
    }
    if (/\.md$/i.test(target)) {
      if (!fs.existsSync(path.join(CONTENT, target))) {
        console.warn(`  ! link thiếu đích: ${mdRel} -> ${href}`);
      }
      return `<a href="${siteHref(target, hash ? "#" + hash : "")}"${t}>${text}</a>`;
    }
    return `<a href="${esc(href)}"${t}>${text}</a>`;
  };

  renderer.table = function (header, body) {
    return `<div class="table-wrap"><table><thead>${header}</thead><tbody>${body}</tbody></table></div>\n`;
  };

  return { renderer, headings };
}

// ---------- layout ----------
function navHtml(currentRel) {
  return NAV.map((g) => {
    const items = g.items.map(([rel, label]) => {
      const cur = rel === currentRel ? ' class="current" aria-current="page"' : "";
      return `<li${cur}><a href="${siteHref(rel)}">${esc(label)}</a></li>`;
    }).join("");
    return `<div class="nav-group"><div class="nav-title">${esc(g.group)}</div><ul>${items}</ul></div>`;
  }).join("\n");
}

function prevNext(currentRel, titles) {
  const i = ORDER.indexOf(currentRel);
  if (i < 0) return "";
  const prev = i > 0 ? ORDER[i - 1] : null;
  const next = i < ORDER.length - 1 ? ORDER[i + 1] : null;
  const a = (rel, cls, pre) => rel
    ? `<a class="${cls}" href="${siteHref(rel)}"><span class="pn-label">${pre}</span><span>${esc(titles.get(rel) || rel)}</span></a>`
    : `<span class="${cls} empty"></span>`;
  return `<nav class="prevnext" aria-label="Chương trước / sau">${a(prev, "prev", "← Trước")}${a(next, "next", "Tiếp →")}</nav>`;
}

function pageToc(headings) {
  const h2 = headings.filter((h) => h.level === 2);
  if (h2.length < 3) return "";
  return `<details class="page-toc" open><summary>Trong trang này</summary><ol>${
    h2.map((h) => `<li><a href="#${h.id}">${h.text}</a></li>`).join("")
  }</ol></details>`;
}

function layout({ title, body, currentRel, headings, titles }) {
  const commit = GIT_COMMIT ? `build ${esc(GIT_COMMIT.slice(0, 12))}` : "build local";
  return `<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)} · ${SITE_NAME}</title>
<meta name="description" content="${esc(SITE_TAGLINE)}">
<meta name="robots" content="noindex">
<link rel="stylesheet" href="/style.css">
<link rel="icon" href="data:,">
</head>
<body>
<a class="skip" href="#main">Bỏ qua điều hướng</a>
<header class="topbar">
  <a class="brand" href="/">${SITE_NAME}</a>
  <span class="tagline">${esc(SITE_TAGLINE)}</span>
  <label class="menu-toggle" for="nav-toggle" aria-label="Mở mục lục">☰ Mục lục</label>
</header>
<input type="checkbox" id="nav-toggle" hidden>
<div class="shell">
  <aside class="sidebar" aria-label="Điều hướng cẩm nang">
    ${navHtml(currentRel)}
  </aside>
  <main id="main" class="content">
    ${pageToc(headings)}
    <article class="md">
${body}
    </article>
    ${prevNext(currentRel, titles)}
    <footer class="foot">
      <p>Nội dung học tập ngoài phạm vi vận hành Alpha3s; Alpha3s chỉ là case tham chiếu. Liên kết có dấu <sup>†</sup> trỏ tới hồ sơ nội bộ, không công bố.</p>
      <p>Nguồn: <code>pm-handbook/content</code> trong repo a3s · ${commit} · ${BUILD_DATE}</p>
    </footer>
  </main>
</div>
</body>
</html>
`;
}

// ---------- chạy ----------
if (!fs.existsSync(CONTENT)) {
  console.error(`Không thấy thư mục nội dung: ${CONTENT}`);
  process.exit(1);
}
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

const files = walk(CONTENT).map((p) => toPosix(path.relative(CONTENT, p))).sort();
const titles = new Map();
for (const rel of files) {
  const md = fs.readFileSync(path.join(CONTENT, rel), "utf8");
  titles.set(rel, firstH1(md) || rel);
}
// nhãn ngắn trong NAV ưu tiên cho prev/next
for (const g of NAV) for (const [rel, label] of g.items) if (titles.has(rel)) titles.set(rel, label);

const missingInNav = files.filter((f) => !ORDER.includes(f));
if (missingInNav.length) console.warn("Tệp có trong content nhưng chưa có trong NAV (vẫn build, chỉ không hiện ở sidebar):", missingInNav);
const missingFiles = ORDER.filter((f) => !files.includes(f));
if (missingFiles.length) { console.error("NAV trỏ tới tệp không tồn tại:", missingFiles); process.exit(1); }

marked.setOptions({ gfm: true, breaks: false });
let n = 0;
for (const rel of files) {
  const md = fs.readFileSync(path.join(CONTENT, rel), "utf8");
  const { renderer, headings } = makeRenderer(rel);
  const body = marked.parse(md, { renderer });
  const html = layout({ title: firstH1(md) || titles.get(rel), body, currentRel: rel, headings, titles });
  const outPath = path.join(OUT, outRel(rel));
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, html);
  n++;
}
fs.copyFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), "style.css"), path.join(OUT, "style.css"));
fs.writeFileSync(path.join(OUT, "404.html"), layout({
  title: "Không tìm thấy trang",
  body: `<h1>Không tìm thấy trang</h1><p>Địa chỉ không tồn tại. Quay về <a href="/">trang giới thiệu</a> hoặc chọn mục ở thanh bên.</p>`,
  currentRel: null, headings: [], titles,
}));
fs.writeFileSync(path.join(OUT, "robots.txt"), "User-agent: *\nDisallow: /\n");
console.log(`Đã tạo ${n} trang HTML + style.css + 404.html vào ${OUT}`);
