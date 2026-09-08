"""CA Directive 243 §2.2 — runtime READBACK cho M5 Gate F scope. In state hien tai (channel/full-scope/
kill-switch/wiring) + deployed commit/tree. TUYET DOI KHONG in secret/token. Chay tren VPS de ops xac nhan
truoc/sau khi bat full-scope."""
import json
import subprocess

from app.services import m5_scope


def _git(*args) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd="/srv/alpha3s",
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:  # noqa: BLE001
        return "(unavailable)"


def main() -> None:
    rb = m5_scope.readback()
    rb["deployed_commit"] = _git("rev-parse", "HEAD")
    rb["deployed_tree"] = _git("rev-parse", "HEAD^{tree}")
    print(json.dumps(rb, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
