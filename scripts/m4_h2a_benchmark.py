"""I-B M4 H2-A — benchmark latency KY, TACH RIENG khoi throughput collector.

CA H2 Design Review 1: "Benchmark phai tach latency KMS/signing khoi throughput collector,
>=5 runs, median + range."

PHUONG PHAP (rut ra tu bai hoc F-PR22-E01/E02 — CA phai chi ra 3 lan Dev moi sua duoc)
  * Moi thong ke duoc tinh TRONG script va ghi vao mot artifact JSON canonical. Bao cao PHAI
    trich so tu artifact do bang script, KHONG go tay tu man hinh.
  * Bao MEDIAN + DAI TRI SO (min..max), khong bao mot con so don. O PR #22, nhieu moi truong
    (20-37%) tung lon hon chinh hieu ung can do, va co lan lap cho delta AM.
  * Do >=5 lan lap doc lap, moi lan lap co warmup rieng.

CAI GI DUOC DO
  1. `hmac`      — duong hien tai (HMAC-SHA256), lam moc so sanh.
  2. `ed25519`   — ky bat doi xung tai cho (LocalDevBackend). Day la CHI PHI TINH TOAN thuan tuy.
  3. `kms_rtt_*` — mo phong KMS o xa bang do tre nhan tao. KHONG phai do KMS that: directive H2-A
                   cam provision KMS, va PO chua chot backend. Muc dich la cho thay BUC TRANH
                   PHU THUOC: voi KMS qua mang, chi phi bi chi phoi boi RTT chu khong phai boi
                   thuat toan ky.

GIOI HAN PHAI NOI RO (khong de CA tu phat hien)
  * Day KHONG phai do throughput collector end-to-end. No do DUNG buoc ky.
  * Con so `kms_rtt_*` la GIA LAP. No khong thay the mot phep do tren backend that; khi PO chot
    backend thi phai do lai.
  * Nguong "+5 ms" moi la MUC TIEU de xuat trong design proposal, CA ghi ro chua phai acceptance
    chinh thuc cho den khi PO xac nhan backend.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.pii.signing_backend import LocalDevBackend  # noqa: E402

_SO_LAN_LAP = 7          # >= 5 theo yeu cau CA
_SO_PHEP_MOI_LAN = 2000
_WARMUP = 200

# Transcript that co kich thuoc ~250-400 byte; dung mot mau dai dien.
_TRANSCRIPT = json.dumps({
    "v": 1, "batch_id": "9050e7e4-6f0f-4146-870b-8d457ea053fe",
    "conversation_id": 1234, "message_id": 5678,
    "sample_id": "22222222-2222-2222-2222-222222222222", "txid": 987654321,
    "canonical_digest": "ab" * 32, "canonical_len": 142, "truncated": False,
    "ciphertext_digest": "cd" * 32, "aead_algorithm": "AES-256-GCM",
    "aead_key_version": "sample-aead-v1", "aad_digest": "ef" * 32,
}, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _do(ham, so_phep: int) -> list[float]:
    """Tra danh sach latency (ms) cua tung phep goi."""
    for _ in range(_WARMUP):
        ham()
    ms = []
    for _ in range(so_phep):
        t0 = time.perf_counter()
        ham()
        ms.append((time.perf_counter() - t0) * 1000.0)
    return ms


def _thong_ke(mau: list[float]) -> dict:
    mau_sap = sorted(mau)
    return {
        "so_phep": len(mau),
        "median_ms": round(statistics.median(mau_sap), 6),
        "min_ms": round(mau_sap[0], 6),
        "max_ms": round(mau_sap[-1], 6),
        "p95_ms": round(mau_sap[int(len(mau_sap) * 0.95)], 6),
        "mean_ms": round(statistics.fmean(mau_sap), 6),
    }


def main() -> int:
    os.environ.setdefault("M4_ALLOW_LOCALDEV_SIGNING", "1")
    backend = LocalDevBackend(app_env="benchmark")
    khoa_hmac = os.urandom(32)

    def f_hmac() -> None:
        hmac.new(khoa_hmac, _TRANSCRIPT, hashlib.sha256).digest()

    def f_ed25519() -> None:
        backend.sign(_TRANSCRIPT)

    lap = []
    for i in range(_SO_LAN_LAP):
        h = _thong_ke(_do(f_hmac, _SO_PHEP_MOI_LAN))
        e = _thong_ke(_do(f_ed25519, _SO_PHEP_MOI_LAN))
        lap.append({
            "lan": i + 1,
            "hmac": h,
            "ed25519": e,
            "delta_median_ms": round(e["median_ms"] - h["median_ms"], 6),
        })

    deltas = [x["delta_median_ms"] for x in lap]
    ed_medians = [x["ed25519"]["median_ms"] for x in lap]
    hmac_medians = [x["hmac"]["median_ms"] for x in lap]

    # Mo phong phu thuoc mang: cong RTT vao chi phi ky. So RTT la GIA DINH, khong phai do dac.
    rtt_gia_lap = {
        "kms_cung_vung_1ms": round(statistics.median(ed_medians) + 1.0, 6),
        "kms_cung_vung_5ms": round(statistics.median(ed_medians) + 5.0, 6),
        "kms_khac_vung_30ms": round(statistics.median(ed_medians) + 30.0, 6),
    }

    bc = {
        "phien_ban_bao_cao": "h2a-benchmark-v1",
        "muc_dich": "do latency BUOC KY, tach khoi throughput collector",
        "so_lan_lap": _SO_LAN_LAP,
        "so_phep_moi_lan": _SO_PHEP_MOI_LAN,
        "warmup_moi_lan": _WARMUP,
        "kich_thuoc_transcript_byte": len(_TRANSCRIPT),
        "python": sys.version.split()[0],
        "tung_lan_lap": lap,
        "tong_hop": {
            "hmac_median_cua_cac_median_ms": round(statistics.median(hmac_medians), 6),
            "ed25519_median_cua_cac_median_ms": round(statistics.median(ed_medians), 6),
            "delta_median_ms": round(statistics.median(deltas), 6),
            "delta_min_ms": round(min(deltas), 6),
            "delta_max_ms": round(max(deltas), 6),
            "delta_am_o_lan_lap_nao_khong": any(d < 0 for d in deltas),
        },
        "kms_gia_lap_median_ms": rtt_gia_lap,
        "gioi_han": [
            "KHONG phai do throughput collector end-to-end; chi do buoc ky.",
            "So kms_gia_lap_* la GIA DINH RTT, khong phai do tren KMS that (directive H2-A cam provision KMS).",
            "Nguong +5 ms moi la muc tieu de xuat, CA ghi ro chua phai acceptance chinh thuc.",
            "Do tren may Dev trong container; may production co the khac.",
        ],
    }
    print(json.dumps(bc, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
