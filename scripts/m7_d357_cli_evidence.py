#!/usr/bin/env python3
"""CA Directive 357 §5 — evidence tooling: chay CLI ghn_g1_prep o mode production (dry-run) + compare-modes,
voi TRIPWIRE chan moi HTTP: httpx bi patch de RAISE neu co bat ky request nao.

=> output kem bang chung "ZERO HTTP" (khong goi GHN production trong luc build/test).
Chay tren m5lab. Khong credential that (chi doc config DB neu co; token khong bao gio in ra).
"""
import asyncio
import importlib.util
import io
import json
import pathlib
import sys
import traceback
from contextlib import redirect_stdout

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTTP_ATTEMPTS = []


class Tripwire(Exception):
    pass


def _arm():
    """Moi loi goi HTTP (bat ky method nao cua AsyncClient) -> ghi nhan + raise."""
    def blocker(name):
        async def _f(self, *a, **k):
            HTTP_ATTEMPTS.append({"method": name, "url": str(a[0]) if a else k.get("url")})
            raise Tripwire(f"HTTP bi chan boi tripwire: {name}")
        return _f
    for m in ("post", "get", "request", "send"):
        setattr(httpx.AsyncClient, m, blocker(m))


def _cli():
    spec = importlib.util.spec_from_file_location("ghn_g1_prep", ROOT / "scripts" / "ghn_g1_prep.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def run(cli, argv):
    buf = io.StringIO()
    rc, err = 0, ""
    try:
        with redirect_stdout(buf):
            rc = await cli.main(argv)
    except SystemExit as e:
        rc, err = f"SystemExit({e.code})", ""
    except Exception as e:  # noqa: BLE001
        rc, err = "EXC", f"{type(e).__name__}: {e}"
        if isinstance(e, Tripwire):
            err += "\n" + traceback.format_exc(limit=3)
    return {"argv": argv, "rc": rc, "error": err, "stdout": buf.getvalue().strip()}


async def main():
    _arm()
    cli = _cli()
    ADDR = ["--address", "66/99001"]        # dia chi co trong map staging cua m5lab (khong phai khach that)
    cases = [
        ["plan", "--mode", "production", *ADDR],
        ["plan", "--mode", "staging", *ADDR],
        ["snapshot", "--mode", "production", "--target", "Đắk Lắk=Krông Pắc"],          # dry-run: KHONG HTTP
        ["compare-modes", "--mode", "production", "--base-mode", "staging", *ADDR],
        ["compare-modes", "--mode", "staging", "--base-mode", "staging", *ADDR],
    ]
    out = []
    for argv in cases:
        out.append(await run(cli, argv))
    # negative: thieu --mode / mode sai / --execute thieu actor
    for argv in (["plan"], ["plan", "--mode", "prod"], ["snapshot", "--mode", "production", "--target", "X=Y",
                                                        "--execute"]):
        out.append(await run(cli, argv))
    print(json.dumps({"http_attempts": HTTP_ATTEMPTS, "zero_http": len(HTTP_ATTEMPTS) == 0, "cases": out},
                     ensure_ascii=False, indent=2, default=str))
    return 0 if not HTTP_ATTEMPTS else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
