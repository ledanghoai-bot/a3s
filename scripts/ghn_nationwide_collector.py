#!/usr/bin/env python3
"""CA Directive 377 §3 — GHN PRODUCTION master-data toan quoc, READ-ONLY, co checkpoint.

Thu tu: province -> district cho tung province -> ward cho tung district -> snapshot normalized + manifest + checksum.
KHONG ghi DB, KHONG quote/shipment/label/tracking/COD/webhook. Chi 3 endpoint master-data cua host production.

Rang buoc (Directive 377 §3):
  - MOT worker, tuan tu; khoang cach giua 2 request >= GHN377_MIN_INTERVAL giay (mac dinh 1.0, KHONG nho hon 1.0).
  - Checkpoint NGUYEN TU (ghi tmp + os.replace) sau moi province/district xong. Chay lai: doc checkpoint, KHONG goi lai
    don vi da `ok`; don vi `inconclusive` duoc thu lai.
  - 429: ton trong Retry-After (tran 300 s); vang header -> backoff 10/20/40/80/160 s; toi da 6 attempt.
    Network/5xx: toi da 3 attempt (backoff 5/15 s). Het retry -> don vi `inconclusive` (khong bia du lieu).
    401/403 -> dung toan bo (loi he thong). >= 5 don vi inconclusive lien tiep -> dung.
  - Khoa `run.lock` (flock) chong chay song song. Dung an toan: tao file `STOP` trong thu muc lam viec (hoac SIGTERM)
    -> dung truoc request ke tiep, checkpoint giu nguyen.
  - Khong log token/header/secret. Response loc theo whitelist truong (bo Created*/Updated* IP/nhan vien...).

Env: GHN377_WORK (thu muc lam viec, mac dinh /work), GHN377_MIN_INTERVAL, GHN377_MAX_REQUESTS (tran request moi lan
chay — dung de kiem checkpoint/resume), GHN377_MODE=REAL|LAB (LAB: transport gia, khong network, khong DB).

Chay REAL (VPS):
  docker compose -f docker-compose.prod.yml run --rm --no-deps -T -e PYTHONPATH=/srv -v /root/ghn377:/work \
      api python /work/ghn_nationwide_collector.py
Dung:  touch /root/ghn377/STOP
"""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone

WORK = os.environ.get("GHN377_WORK", "/work")
MODE = os.environ.get("GHN377_MODE", "REAL").upper()
MIN_INTERVAL = max(1.0, float(os.environ.get("GHN377_MIN_INTERVAL", "1.0") or 1.0))
MAX_REQUESTS = int(os.environ.get("GHN377_MAX_REQUESTS", "0") or 0)          # 0 = khong tran
PROD_BASE = "https://online-gateway.ghn.vn/shiip/public-api"
PATHS = {"province": "/master-data/province", "district": "/master-data/district", "ward": "/master-data/ward"}
KEEP = {
    "province": ("ProvinceID", "ProvinceName", "CountryID", "Code", "NameExtension", "IsEnable", "RegionID",
                 "CanUpdateCOD", "Status"),
    "district": ("DistrictID", "ProvinceID", "DistrictName", "Code", "Type", "SupportType", "NameExtension",
                 "IsEnable", "CanUpdateCOD", "Status"),
    "ward": ("WardCode", "DistrictID", "WardName", "NameExtension", "IsEnable", "CanUpdateCOD", "SupportType",
             "Status"),
}
MAX_429_ATTEMPTS, MAX_NET_ATTEMPTS = 6, 3
BACKOFF_429 = (10, 20, 40, 80, 160)
BACKOFF_NET = (5, 15)
MAX_CONSEC_INCONCLUSIVE = 5
RETRY_AFTER_CAP = 300


class Fatal(Exception):
    pass


class Stop(Exception):
    pass


def utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def p(*a):
    print(*a, flush=True)


# ------------------------------------------------------------------ checkpoint (nguyen tu)
def _path(name):
    return os.path.join(WORK, name)


def load_state():
    try:
        with open(_path("state.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {"format": 1, "created": utc(), "province": None, "district": {}, "ward": {}, "runs": []}


def save_state(st):
    tmp = _path("state.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(st, fh, ensure_ascii=False, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, _path("state.json"))


def ledger(entry):
    with open(_path("ledger.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def keep(level, rows):
    ks = KEEP[level]
    return [{k: r.get(k) for k in ks if k in r} for r in rows]


# ------------------------------------------------------------------ transport
class Transport:
    """REAL: httpx toi DUNG host production + 3 path. Tra (status, retry_after_header, json|None, error_class|None)."""

    def __init__(self, token: str):
        import httpx
        self._httpx = httpx
        self._token = token

    async def send(self, level, body):
        url = PROD_BASE + PATHS[level]
        if not url.startswith(PROD_BASE + "/master-data/"):
            raise Fatal("url ngoai allowlist")
        try:
            async with self._httpx.AsyncClient(timeout=self._httpx.Timeout(20.0, connect=5.0)) as c:
                r = await c.post(url, headers={"Content-Type": "application/json", "Token": self._token}, json=body)
            try:
                js = r.json()
            except Exception:  # noqa: BLE001
                js = None
            return r.status_code, r.headers.get("Retry-After"), js, None
        except self._httpx.TimeoutException:
            return None, None, None, "timeout"
        except self._httpx.HTTPError as e:
            return None, None, None, type(e).__name__


class Runner:
    def __init__(self, transport, *, sleep=asyncio.sleep, clock=time.monotonic):
        self.t = transport
        self.sleep = sleep
        self.clock = clock
        self.last_start = None
        self.n = 0                      # attempt HTTP trong lan chay nay
        self.consec_inconclusive = 0
        self.stop_flag = False

    async def _throttle(self):
        if self.last_start is not None:
            wait = MIN_INTERVAL - (self.clock() - self.last_start)
            if wait > 0:
                await self.sleep(wait)
        self.last_start = self.clock()

    def _check_stop(self):
        if self.stop_flag or os.path.exists(_path("STOP")):
            raise Stop("STOP file/signal")
        if MAX_REQUESTS and self.n >= MAX_REQUESTS:
            raise Stop(f"GHN377_MAX_REQUESTS={MAX_REQUESTS}")

    async def fetch(self, level, target, body):
        """Mot don vi (province list / districts cua 1 province / wards cua 1 district). Tra (status, data|None, info)."""
        attempt, n429, nnet = 0, 0, 0
        while True:
            self._check_stop()
            await self._throttle()
            attempt += 1
            self.n += 1
            t0 = self.clock()
            st, ra, js, err = await self.t.send(level, body)
            ms = int((self.clock() - t0) * 1000)
            ok = st == 200 and isinstance(js, dict) and js.get("code") == 200 and isinstance(js.get("data"), list)
            e = {"ts": utc(), "n_run": self.n, "level": level, "target": target, "attempt": attempt, "status": st,
                 "code": js.get("code") if isinstance(js, dict) else None, "error": err, "ms": ms,
                 "retry_after": ra}
            if ok:
                e["outcome"] = "ok"
                e["rows"] = len(js["data"])
                ledger(e)
                self.consec_inconclusive = 0
                return "ok", js["data"], {"attempts": attempt}
            if st in (401, 403):
                e["outcome"] = "fatal_auth"
                ledger(e)
                raise Fatal(f"HTTP {st} tai {level} {target}")
            if st == 429:
                n429 += 1
                if n429 < MAX_429_ATTEMPTS:
                    delay = BACKOFF_429[min(n429 - 1, len(BACKOFF_429) - 1)]
                    try:
                        if ra is not None:
                            delay = min(RETRY_AFTER_CAP, max(1, int(float(ra))))
                    except ValueError:
                        pass
                    e["outcome"] = f"retry_429_wait_{delay}s"
                    ledger(e)
                    await self.sleep(delay)
                    continue
            elif st is None or st >= 500 or st == 408:
                nnet += 1
                if nnet < MAX_NET_ATTEMPTS:
                    delay = BACKOFF_NET[min(nnet - 1, len(BACKOFF_NET) - 1)]
                    e["outcome"] = f"retry_net_wait_{delay}s"
                    ledger(e)
                    await self.sleep(delay)
                    continue
            e["outcome"] = "inconclusive"
            ledger(e)
            self.consec_inconclusive += 1
            if self.consec_inconclusive >= MAX_CONSEC_INCONCLUSIVE:
                raise Fatal(f"{MAX_CONSEC_INCONCLUSIVE} don vi inconclusive lien tiep")
            return "inconclusive", None, {"attempts": attempt, "last_status": st, "last_error": err,
                                          "last_code": e["code"]}


# ------------------------------------------------------------------ thu thap
async def collect(runner, st):
    if not st["province"] or st["province"].get("status") != "ok":
        status, data, info = await runner.fetch("province", "all", {})
        st["province"] = {"status": status, "data": keep("province", data or []), **info, "at": utc()}
        save_state(st)
        if status != "ok":
            raise Fatal("khong lay duoc danh sach province")
    provinces = sorted(st["province"]["data"], key=lambda r: r["ProvinceID"])
    for pr in provinces:
        pid = str(pr["ProvinceID"])
        if st["district"].get(pid, {}).get("status") == "ok":
            continue
        status, data, info = await runner.fetch("district", pid, {"province_id": pr["ProvinceID"]})
        st["district"][pid] = {"status": status, "data": keep("district", data or []), **info, "at": utc()}
        save_state(st)
    for pid in sorted(st["district"], key=int):
        if st["district"][pid]["status"] != "ok":
            continue
        for d in sorted(st["district"][pid]["data"], key=lambda r: r["DistrictID"]):
            did = str(d["DistrictID"])
            if st["ward"].get(did, {}).get("status") == "ok":
                continue
            status, data, info = await runner.fetch("ward", did, {"district_id": d["DistrictID"]})
            st["ward"][did] = {"status": status, "province_id": int(pid), "data": keep("ward", data or []), **info,
                               "at": utc()}
            save_state(st)


def _dump(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def finalize(st):
    """Validate cau truc + ghi snapshot normalized (sap xep on dinh) + checksum. Tra report."""
    provs = st["province"]["data"] if st["province"] else []
    dists, wards, issues = [], [], []
    incon = {"district": sorted(k for k, v in st["district"].items() if v["status"] != "ok"),
             "ward": sorted(k for k, v in st["ward"].items() if v["status"] != "ok")}
    pids = {r["ProvinceID"] for r in provs}
    if len(pids) != len(provs):
        issues.append("province_id_trung")
    for pid, v in st["district"].items():
        for d in v["data"]:
            if d.get("ProvinceID") != int(pid):
                issues.append(f"district {d.get('DistrictID')} ProvinceID {d.get('ProvinceID')} != parent {pid}")
            dists.append(d)
    dids = [d["DistrictID"] for d in dists]
    if len(set(dids)) != len(dids):
        issues.append(f"district_id_trung: {len(dids) - len(set(dids))}")
    missing_ward_units = []
    for d in dists:
        did = str(d["DistrictID"])
        v = st["ward"].get(did)
        if v is None:
            missing_ward_units.append(did)
            continue
        for w in v["data"]:
            if w.get("DistrictID") != d["DistrictID"]:
                issues.append(f"ward {w.get('WardCode')} DistrictID {w.get('DistrictID')} != parent {did}")
            wards.append(w)
    wkeys = [(w["DistrictID"], w["WardCode"]) for w in wards]
    if len(set(wkeys)) != len(wkeys):
        issues.append(f"(district,ward)_trung: {len(wkeys) - len(set(wkeys))}")
    dup_wardcode_global = len(wards) - len({w["WardCode"] for w in wards})
    provs_s = sorted(provs, key=lambda r: r["ProvinceID"])
    dists_s = sorted(dists, key=lambda r: r["DistrictID"])
    wards_s = sorted(wards, key=lambda r: (r["DistrictID"], str(r["WardCode"])))
    os.makedirs(_path("snapshot"), exist_ok=True)
    sums = {}
    for name, rows in (("provinces", provs_s), ("districts", dists_s), ("wards", wards_s)):
        b = _dump(rows).encode("utf-8")
        with open(_path(f"snapshot/{name}.json"), "wb") as fh:
            fh.write(b)
        sums[name] = hashlib.sha256(b).hexdigest()
    complete = not incon["district"] and not incon["ward"] and not missing_ward_units and not issues
    rep = {"generated": utc(), "counts": {"province": len(provs_s), "district": len(dists_s), "ward": len(wards_s)},
           "inconclusive": incon, "missing_ward_units": missing_ward_units, "structural_issues": issues,
           "wardcode_duplicate_across_districts": dup_wardcode_global, "sha256": sums,
           "snapshot_digest": hashlib.sha256(_dump(sums).encode()).hexdigest(),
           "status": "complete" if complete else "partial", "field_whitelist": KEEP}
    with open(_path("snapshot/report.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1, sort_keys=True)
    return rep


# ------------------------------------------------------------------ main
async def _token_real():
    import asyncpg

    from app.config import settings
    from app.services.settings import integrations as S
    conn = await asyncpg.connect(settings.database_url.replace("+asyncpg", ""))
    try:
        saved = await S.load_saved_ghn_config(conn, "production")
        base = (saved["config"].get("base_url") or "").rstrip("/")
        if base != PROD_BASE:
            raise Fatal("base_url integration production khong phai endpoint production ghim")
        if not saved.get("token"):
            raise Fatal("thieu token production")
        return saved["token"]
    finally:
        await conn.close()


async def main(transport=None, *, sleep=asyncio.sleep, clock=time.monotonic):
    os.makedirs(WORK, exist_ok=True)
    lock = open(_path("run.lock"), "w")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        p("DUNG: da co mot lan chay khac dang giu run.lock")
        return 4
    st = load_state()
    run = {"started": utc(), "mode": MODE, "min_interval_s": MIN_INTERVAL, "max_requests": MAX_REQUESTS,
           "pid": os.getpid()}
    st["runs"].append(run)
    save_state(st)
    if transport is None:
        transport = Transport(await _token_real())
    runner = Runner(transport, sleep=sleep, clock=clock)

    def _sig(*_):
        runner.stop_flag = True
    try:
        signal.signal(signal.SIGTERM, _sig)
    except ValueError:
        pass
    rc, why = 0, "complete"
    try:
        await collect(runner, st)
    except Stop as e:
        rc, why = 3, f"stopped: {e}"
    except Fatal as e:
        rc, why = 2, f"fatal: {e}"
    run.update({"ended": utc(), "http_attempts": runner.n, "result": why})
    save_state(st)
    p(f"RUN RESULT: {why} | http_attempts_this_run={runner.n}")
    if rc == 0:
        rep = finalize(st)
        p("SNAPSHOT:", json.dumps({k: rep[k] for k in ("status", "counts", "snapshot_digest",
                                                        "wardcode_duplicate_across_districts")}, ensure_ascii=False))
        if rep["status"] != "complete":
            p("PARTIAL:", json.dumps({k: rep[k] for k in ("inconclusive", "missing_ward_units", "structural_issues")},
                                     ensure_ascii=False)[:2000])
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
