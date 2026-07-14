"""
Doc file ISSUES.md (backlog da duoc dung lai + cap nhat trong qua trinh lam viec) va day
toan bo issue len mot project GitLab moi qua REST API. Khong can cai them thu vien ngoai
(chi dung urllib co san trong Python).

ISSUES.md la "nguon that duy nhat" (single source of truth) - script parse truc tiep tu
file nay, khong hardcode noi dung issue trong script. Sua ISSUES.md roi chay lai script la
du, khong can sua script.

Cach parse:
  - Moi issue la 1 khoi bat dau bang dong "## #<so> · <tieu de>"
  - Dong "**Trang thai...:**" ngay sau do quyet dinh issue se tao o trang thai
    opened hay closed (co chua tu "Closed"/"closed" -> closed)
  - Toan bo noi dung con lai cua khoi (tru dong heading va dong trang thai) duoc dung
    lam description cho issue tren GitLab

Cach chay:
    export GITLAB_TOKEN=glpat-xxxxxxxxxxxx   # Personal Access Token, scope "api"
    python push_issues_to_gitlab.py --project ledanghoai-group/alpha3s

    # Xem truoc se tao/dong nhung gi ma KHONG goi API that:
    python push_issues_to_gitlab.py --project ledanghoai-group/alpha3s --dry-run

    # Neu file ISSUES.md khong nam cung thu muc script:
    python push_issues_to_gitlab.py --project ledanghoai-group/alpha3s --file /path/to/ISSUES.md

    # Neu dung GitLab tu-host (khong phai gitlab.com):
    python push_issues_to_gitlab.py --project mygroup/alpha3s --gitlab-url https://gitlab.company.com

--project chap nhan ca dang "namespace/project" (vd: ledanghoai-group/alpha3s) lan numeric
project ID (vd: 12345678) - lay duoc o trang Settings > General cua project tren GitLab.

Script se TU DONG BO QUA issue da ton tai (khop theo title chinh xac) de chay lai nhieu
lan khong bi tao trung.
Luu token vao .env:
    Them 1 dong vao file .env o project root (cung file dang chua PAGE_ACCESS_TOKEN, v.v.):
        GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
    Script se TU DONG doc file .env nay (khong can `export` tay), mien la .env nam o
    project root (cung cap voi ISSUES.md) hoac cung thu muc voi script.
    QUAN TRONG: dam bao .env dang nam trong .gitignore, KHONG duoc commit len git
    (repo nay tung bi lo PAGE_ACCESS_TOKEN qua .env truoc do, xem ghi chu o issue #1).
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ISSUE_HEADING_RE = re.compile(r"^## #(\d+) · (.+)$", re.MULTILINE)
STATE_LINE_RE = re.compile(r"^\*\*Trạng thái[^*]*\*\*\s*(.+)$", re.MULTILINE)


def load_env_file(*candidate_paths: Path) -> None:
    """Doc file .env don gian (KEY=VALUE moi dong) va set vao os.environ neu
    bien do CHUA duoc set san (uu tien bien moi truong that neu co ca hai)."""
    for path in candidate_paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        return  # chi doc file .env dau tien tim thay


def parse_issues(md_text: str) -> list[dict]:
    """Tach ISSUES.md thanh danh sach issue: {number, title, state, description}."""
    blocks = re.split(r"(?=^## #\d+ · )", md_text, flags=re.MULTILINE)
    issues = []
    for block in blocks:
        heading_m = ISSUE_HEADING_RE.search(block)
        if not heading_m:
            continue  # phan truoc issue dau tien (title file, bang tom tat...) bo qua

        number, title = int(heading_m.group(1)), heading_m.group(2).strip()

        state_m = STATE_LINE_RE.search(block)
        state_text = state_m.group(1) if state_m else ""
        state = "closed" if "closed" in state_text.lower() else "opened"

        description = block
        description = description.replace(heading_m.group(0), "", 1)
        if state_m:
            description = description.replace(state_m.group(0), "", 1)
        # Bo dong phan cach "---" cuoi khoi (do split lookahead de lai o cuoi block)
        description = re.sub(r"\n-{3,}\s*$", "", description.strip()).strip()

        issues.append(
            {"number": number, "title": title, "state": state, "description": description}
        )
    return issues


class GitLabClient:
    def __init__(self, base_url: str, token: str, project: str):
        self.base = base_url.rstrip("/") + "/api/v4"
        self.token = token
        self.project_enc = urllib.parse.quote(project, safe="")

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{self.base}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("PRIVATE-TOKEN", self.token)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitLab API loi {e.code} tai {method} {path}: {err_body}") from e

    def list_existing(self) -> dict[str, dict]:
        """Tra ve {title: {"iid": int, "state": "opened"|"closed"}} cho toan bo
        issue hien co tren GitLab (ca opened lan closed, nho scope=all)."""
        existing = {}
        page = 1
        while True:
            data = self._request(
                "GET", f"/projects/{self.project_enc}/issues?per_page=100&page={page}&scope=all"
            )
            if not data:
                break
            for item in data:
                existing[item["title"]] = {
                    "iid": item["iid"],
                    "state": item["state"],
                    "description": item.get("description") or "",
                }
            if len(data) < 100:
                break
            page += 1
        return existing

    def create_issue(self, title: str, description: str) -> dict:
        return self._request(
            "POST",
            f"/projects/{self.project_enc}/issues",
            {"title": title, "description": description},
        )

    def close_issue(self, issue_iid: int) -> dict:
        return self._request(
            "PUT",
            f"/projects/{self.project_enc}/issues/{issue_iid}",
            {"state_event": "close"},
        )

    def reopen_issue(self, issue_iid: int) -> dict:
        return self._request(
            "PUT",
            f"/projects/{self.project_enc}/issues/{issue_iid}",
            {"state_event": "reopen"},
        )

    def update_issue(self, issue_iid: int, **fields) -> dict:
        return self._request("PUT", f"/projects/{self.project_enc}/issues/{issue_iid}", fields)


def main():
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    load_env_file(project_root / ".env", script_dir / ".env")

    parser = argparse.ArgumentParser(description="Day issue tu ISSUES.md len GitLab")
    parser.add_argument("--project", required=True, help="namespace/project hoac numeric project ID")
    parser.add_argument("--gitlab-url", default="https://gitlab.com", help="Base URL GitLab (mac dinh gitlab.com)")
    parser.add_argument(
        "--file", default=str(Path(__file__).resolve().parent.parent / "ISSUES.md"),
        help="Duong dan toi ISSUES.md",
    )
    parser.add_argument(
        "--token", default=os.environ.get("GITLAB_TOKEN"),
        help="Personal Access Token (scope 'api'). Mac dinh doc tu bien moi truong GITLAB_TOKEN",
    )
    parser.add_argument("--dry-run", action="store_true", help="Chi in ra se lam gi, khong goi API that")
    args = parser.parse_args()

    if not args.dry_run and not args.token:
        print("Thieu token. Truyen --token hoac set bien moi truong GITLAB_TOKEN.")
        sys.exit(1)

    md_text = Path(args.file).read_text(encoding="utf-8")
    issues = parse_issues(md_text)
    if not issues:
        print(f"Khong tim thay issue nao trong {args.file}. Kiem tra lai format file.")
        return

    print(f"Da doc {len(issues)} issue tu {args.file}.\n")

    if args.dry_run:
        for iss in issues:
            print(f"[DRY-RUN] #{iss['number']} ({iss['state']}) — {iss['title']}")
        print("\nKhong co gi duoc gui len GitLab (dang dry-run).")
        return

    client = GitLabClient(args.gitlab_url, args.token, args.project)

    print("Dang lay danh sach issue da ton tai tren GitLab (kem trang thai)...")
    existing = client.list_existing()
    print(f"Da co {len(existing)} issue tren project.\n")

    created, synced, unchanged, closed = 0, 0, 0, 0
    for iss in sorted(issues, key=lambda x: x["number"]):
        found = existing.get(iss["title"])

        if found is None:
            result = client.create_issue(iss["title"], iss["description"])
            created += 1
            print(f"[da tao] #{iss['number']} — iid={result['iid']} — '{iss['title']}'")
            if iss["state"] == "closed":
                client.close_issue(result["iid"])
                closed += 1
                print(f"         → da dong issue iid={result['iid']}")
            time.sleep(0.3)
            continue

        # Issue da ton tai - so sanh state va description, dong bo neu khac
        state_changed = found["state"] != iss["state"]
        desc_changed = found["description"].strip() != iss["description"].strip()

        if not state_changed and not desc_changed:
            print(f"[khong doi] #{iss['number']} — '{iss['title']}' da khop, khong can dong bo")
            unchanged += 1
            continue

        update_fields = {}
        if desc_changed:
            update_fields["description"] = iss["description"]
        if state_changed:
            update_fields["state_event"] = "close" if iss["state"] == "closed" else "reopen"

        client.update_issue(found["iid"], **update_fields)
        changes = []
        if desc_changed:
            changes.append("mo ta")
        if state_changed:
            changes.append(f"trang thai -> {iss['state']}")
        print(f"[da dong bo] #{iss['number']} — iid={found['iid']} — {', '.join(changes)}")
        synced += 1
        time.sleep(0.3)

    print(
        f"\nXong. Tao moi: {created} | Dong bo lai trang thai: {synced} | "
        f"Khong doi: {unchanged} | Da dong luc tao: {closed}"
    )


if __name__ == "__main__":
    main()
