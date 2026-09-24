"""CA Directive 377 §5 — kiem collector toan quoc (LAB: transport gia, dong ho gia, KHONG network, KHONG DB).
Throttle >= 1 s, 429 + Retry-After, retry gioi han -> inconclusive, checkpoint/resume khong goi lai, lock 1 worker,
401 -> fatal, validate cau truc + snapshot on dinh."""
import asyncio
import importlib
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(tmp_path, monkeypatch, **env):
    monkeypatch.setenv("GHN377_WORK", str(tmp_path))
    monkeypatch.setenv("GHN377_MODE", "LAB")
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    try:
        import ghn_nationwide_collector as c
        c = importlib.reload(c)
    finally:
        sys.path.pop(0)
    return c


PROV = [{"ProvinceID": 201, "ProvinceName": "Hà Nội", "CreatedIP": "10.0.0.1", "UpdatedEmployee": 42},
        {"ProvinceID": 210, "ProvinceName": "Đắk Lắk", "NameExtension": ["Dak Lak"]}]
DIST = {201: [{"DistrictID": 1442, "ProvinceID": 201, "DistrictName": "Quận Ba Đình"},
              {"DistrictID": 1443, "ProvinceID": 201, "DistrictName": "Quận Hoàn Kiếm"}],
        210: [{"DistrictID": 1552, "ProvinceID": 210, "DistrictName": "Thành phố Buôn Ma Thuột"}]}
WARD = {1442: [{"WardCode": "1A0101", "DistrictID": 1442, "WardName": "Phường Phúc Xá", "CreatedEmployee": "x"}],
        1443: [{"WardCode": "1A0201", "DistrictID": 1443, "WardName": "Phường Hàng Bạc"}],
        1552: [{"WardCode": "400105", "DistrictID": 1552, "WardName": "Phường Tân Lập"}]}


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def clock(self):
        return self.t

    async def sleep(self, s):
        self.sleeps.append(round(s, 3))
        self.t += s


class FakeGHN:
    """script: {(level, target): [status,...]} — tra lan luot cac status truoc khi thanh cong. 'X' = loi mang."""
    def __init__(self, clk, script=None, retry_after=None):
        self.clk, self.script, self.ra = clk, dict(script or {}), retry_after or {}
        self.calls = []

    async def send(self, level, body):
        tgt = "all" if level == "province" else str(body.get("province_id") or body.get("district_id"))
        self.calls.append((level, tgt, self.clk.t))
        self.clk.t += 0.2                                   # latency gia
        q = self.script.get((level, tgt))
        if q:
            s = q.pop(0)
            if s == "X":
                return None, None, None, "ConnectError"
            return s, self.ra.get((level, tgt)), {"code": s}, None
        if level == "province":
            data = PROV
        elif level == "district":
            data = DIST[int(tgt)]
        else:
            data = WARD[int(tgt)]
        return 200, None, {"code": 200, "data": data}, None


def _run(c, fake, clk):
    return asyncio.run(c.main(fake, sleep=clk.sleep, clock=clk.clock))


def _ledger(tmp_path):
    with open(tmp_path / "ledger.jsonl", encoding="utf-8") as fh:
        return [json.loads(x) for x in fh]


def test_full_run_complete_throttle_and_whitelist(tmp_path, monkeypatch):
    c = _load(tmp_path, monkeypatch)
    clk = FakeClock()
    fake = FakeGHN(clk)
    assert _run(c, fake, clk) == 0
    # 1 province + 2 district + 3 ward = 6 request, dung thu tu
    assert [x[0] for x in fake.calls] == ["province", "district", "district", "ward", "ward", "ward"]
    starts = [x[2] for x in fake.calls]
    assert all(b - a >= 1.0 - 1e-9 for a, b in zip(starts, starts[1:]))          # >= 1 s giua 2 request
    rep = json.loads((tmp_path / "snapshot" / "report.json").read_text(encoding="utf-8"))
    assert rep["status"] == "complete" and rep["counts"] == {"province": 2, "district": 3, "ward": 3}
    raw = (tmp_path / "snapshot" / "provinces.json").read_text(encoding="utf-8")
    assert "CreatedIP" not in raw and "UpdatedEmployee" not in raw                # whitelist truong
    assert "CreatedEmployee" not in (tmp_path / "snapshot" / "wards.json").read_text(encoding="utf-8")


def test_min_interval_cannot_go_below_one_second(tmp_path, monkeypatch):
    c = _load(tmp_path, monkeypatch, GHN377_MIN_INTERVAL="0.1")
    assert c.MIN_INTERVAL == 1.0
    c2 = _load(tmp_path, monkeypatch, GHN377_MIN_INTERVAL="2.5")
    assert c2.MIN_INTERVAL == 2.5                                                 # giam toc duoc bang env


def test_resume_does_not_refetch_completed_units(tmp_path, monkeypatch):
    c = _load(tmp_path, monkeypatch, GHN377_MAX_REQUESTS="3")
    clk = FakeClock()
    f1 = FakeGHN(clk)
    assert _run(c, f1, clk) == 3                                                  # dung vi tran request
    assert len(f1.calls) == 3
    c = _load(tmp_path, monkeypatch, GHN377_MAX_REQUESTS="0")
    f2 = FakeGHN(clk)
    assert _run(c, f2, clk) == 0
    done_first = {(lv, t) for lv, t, _ in f1.calls}
    assert not done_first & {(lv, t) for lv, t, _ in f2.calls}                    # KHONG goi lai don vi da ok
    assert len(f1.calls) + len(f2.calls) == 6
    ok = [(e["level"], e["target"]) for e in _ledger(tmp_path) if e["outcome"] == "ok"]
    assert len(ok) == len(set(ok)) == 6                                           # moi don vi ok dung 1 lan
    st = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert [r["result"] for r in st["runs"]] == ["stopped: GHN377_MAX_REQUESTS=3", "complete"]


def test_429_respects_retry_after_then_succeeds(tmp_path, monkeypatch):
    c = _load(tmp_path, monkeypatch)
    clk = FakeClock()
    fake = FakeGHN(clk, script={("district", "201"): [429, 429]}, retry_after={("district", "201"): "7"})
    assert _run(c, fake, clk) == 0
    assert clk.sleeps.count(7) == 2                                               # ton trong Retry-After
    outs = [e["outcome"] for e in _ledger(tmp_path) if e["target"] == "201"]
    assert outs == ["retry_429_wait_7s", "retry_429_wait_7s", "ok"]


def test_429_without_header_uses_conservative_backoff(tmp_path, monkeypatch):
    c = _load(tmp_path, monkeypatch)
    clk = FakeClock()
    fake = FakeGHN(clk, script={("ward", "1552"): [429]})
    assert _run(c, fake, clk) == 0
    assert 10 in clk.sleeps


def test_network_errors_bounded_then_inconclusive_and_resume_retries(tmp_path, monkeypatch):
    c = _load(tmp_path, monkeypatch)
    clk = FakeClock()
    fake = FakeGHN(clk, script={("ward", "1443"): ["X", 503, 502]})             # 3 attempt deu loi
    assert _run(c, fake, clk) == 0
    tries = [e for e in _ledger(tmp_path) if e["target"] == "1443"]
    assert [e["outcome"] for e in tries] == ["retry_net_wait_5s", "retry_net_wait_15s", "inconclusive"]
    rep = json.loads((tmp_path / "snapshot" / "report.json").read_text(encoding="utf-8"))
    assert rep["status"] == "partial" and rep["inconclusive"]["ward"] == ["1443"]   # KHONG bia du lieu
    # chay lai: chi thu lai don vi inconclusive
    c = _load(tmp_path, monkeypatch)
    f2 = FakeGHN(clk)
    assert _run(c, f2, clk) == 0
    assert [(lv, t) for lv, t, _ in f2.calls] == [("ward", "1443")]
    rep = json.loads((tmp_path / "snapshot" / "report.json").read_text(encoding="utf-8"))
    assert rep["status"] == "complete"


def test_auth_error_is_fatal(tmp_path, monkeypatch):
    c = _load(tmp_path, monkeypatch)
    clk = FakeClock()
    fake = FakeGHN(clk, script={("district", "210"): [401]})
    assert _run(c, fake, clk) == 2
    assert not any(x[0] == "ward" for x in fake.calls)                            # dung, khong goi tiep


def test_stop_file_stops_before_next_request(tmp_path, monkeypatch):
    c = _load(tmp_path, monkeypatch)
    clk = FakeClock()
    (tmp_path / "STOP").write_text("x")
    fake = FakeGHN(clk)
    assert _run(c, fake, clk) == 3 and fake.calls == []


def test_single_worker_lock(tmp_path, monkeypatch):
    import fcntl
    c = _load(tmp_path, monkeypatch)
    fh = open(tmp_path / "run.lock", "w")
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        clk = FakeClock()
        fake = FakeGHN(clk)
        assert _run(c, fake, clk) == 4 and fake.calls == []
    finally:
        fh.close()


def test_structural_validation_flags_wrong_parent(tmp_path, monkeypatch):
    c = _load(tmp_path, monkeypatch)
    clk = FakeClock()
    bad = {1552: [{"WardCode": "400105", "DistrictID": 9999, "WardName": "Phường Tân Lập"}]}
    fake = FakeGHN(clk)
    orig = WARD[1552]
    WARD[1552] = bad[1552]
    try:
        assert _run(c, fake, clk) == 0
    finally:
        WARD[1552] = orig
    rep = json.loads((tmp_path / "snapshot" / "report.json").read_text(encoding="utf-8"))
    assert rep["status"] == "partial" and any("9999" in s for s in rep["structural_issues"])


@pytest.mark.parametrize("n", [1])
def test_snapshot_is_deterministic(tmp_path, monkeypatch, n):
    c = _load(tmp_path, monkeypatch)
    clk = FakeClock()
    _run(c, FakeGHN(clk), clk)
    r1 = json.loads((tmp_path / "snapshot" / "report.json").read_text(encoding="utf-8"))["sha256"]
    c.finalize(c.load_state())
    r2 = json.loads((tmp_path / "snapshot" / "report.json").read_text(encoding="utf-8"))["sha256"]
    assert r1 == r2
