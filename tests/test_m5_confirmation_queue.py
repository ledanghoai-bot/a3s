"""M5 Phase 3 — unit test nhe (import health + candidate-code extraction). CA Directive 112.

Cac case nghiep vu (replay/stale/binding/expiry/self-approval/immutability) duoc chung minh o DB rehearsal
scripts/m5_phase3_rehearsal.py (can Postgres). Test nay chi kiem tra logic thuan + import sach cho CI.
"""
from app.services.address import confirmation as conf
from app.services.address import review_queue as rq


def test_codes_extraction():
    snap = [{"level": "province", "code": "P01"}, {"level": "district", "code": "D01"}, {"nocode": 1}]
    assert conf._codes(snap) == {"P01", "D01"}
    assert rq._codes(snap) == {"P01", "D01"}
    assert conf._codes([]) == set()
    assert conf._codes(None) == set()


def test_row_normalizes_snapshot_json():
    # candidate_snapshot dang str (asyncpg JSONB) -> parse ve list
    row = {"id": "x", "resolution_id": None, "result_resolution_id": None,
           "candidate_snapshot": '[{"code": "P01"}]'}
    out = conf._row(dict(row))
    assert out["candidate_snapshot"] == [{"code": "P01"}]
