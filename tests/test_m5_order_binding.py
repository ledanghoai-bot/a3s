"""M5 Phase 4 — unit nhe (import health + verified-status set + snapshot row helper). CA Directive 116.

Cac case nghiep vu (bind/snapshot immutability/wrong-owner/stale/unverified/idempotency/dataset preservation/
no-shipping-from-unverified) o DB rehearsal scripts/m5_phase4_rehearsal.py (can Postgres).
"""
from app.services.address import order_binding as ob


def test_verified_status_set():
    assert set(ob.VERIFIED) == {"auto_verified", "customer_confirmed", "staff_confirmed"}
    assert "needs_customer_confirmation" not in ob.VERIFIED
    assert "failed" not in ob.VERIFIED


def test_snap_normalizes_provenance_json():
    row = {"id": "x", "resolution_id": "r", "provenance_ref": '{"source": "gso"}'}
    out = ob._snap(dict(row))
    assert out["provenance_ref"] == {"source": "gso"}
    assert out["id"] == "x" and out["resolution_id"] == "r"
