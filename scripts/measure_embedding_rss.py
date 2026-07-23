"""Do RSS bo nho cua 2 model embedding (A3, AGW-ROADMAP-001 / REV2-03) -
tra loi cau hoi song-con truoc khi freeze KB V2: 2 model co vua VPS
2 vCPU / 4 GB khong?

- KB V2:  paraphrase-multilingual-MiniLM-L12-v2 (app/services/embedder.py)
- NLU:    paraphrase-multilingual-mpnet-base-v2 (app/services/nlu/nlu_embedder.py)

Cach do: MOI kich ban chay trong 1 PROCESS CON RIENG (baseline / chi KB /
chi NLU / ca hai) de RSS khong bi cong don giua cac kich ban. Doc VmRSS
(hien tai) + VmHWM (peak) tu /proc/self/status - chay trong container Linux,
khong can psutil. Do THEM sau khi encode() that (inference moi la luc cap
phat bo nho lon nhat, khong chi luc load).

Cach dung (trong container - model da co san trong cache cua image/volume):
    docker compose exec api python scripts/measure_embedding_rss.py

Ket qua can ghi vao ISSUES-VI.md / bao cao A3: bang RSS + peak tung kich
ban, va ket luan vua/khong vua budget (xem guardrails o cuoi output).
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Cau tieng Viet that (do dai khac nhau) de inference giong thuc te
_SAMPLE_TEXTS = [
    "shop có giao tới Cà Mau không",
    "cà phê sấy lạnh 100g giá bao nhiêu vậy shop",
    "mình đang cho con bú uống được không",
    "cho mình 2 hũ loại 200g chuyển khoản nhé",
    "cách pha cà phê sấy lạnh với nước lạnh như thế nào để giữ được vị ngon",
] * 10  # 50 cau ~ 1 batch build index nho


def _read_mem_mb() -> dict[str, float]:
    """Doc VmRSS/VmHWM (MB) tu /proc/self/status (Linux). VmHWM = peak RSS."""
    result = {}
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith(("VmRSS:", "VmHWM:")):
                key, value = line.split(":", 1)
                result[key] = round(int(value.strip().split()[0]) / 1024, 1)
    except FileNotFoundError:  # khong phai Linux - script nay chi ho tro do trong container
        pass
    return result


def _scenario(name: str) -> dict:
    """Chay 1 kich ban trong CHINH process nay (duoc goi qua subprocess)."""
    out: dict = {"scenario": name, "steps": {}}
    out["steps"]["start"] = _read_mem_mb()

    models = []
    if name in ("kb", "both"):
        from sentence_transformers import SentenceTransformer
        models.append(SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2"))
        out["steps"]["after_load_kb"] = _read_mem_mb()
    if name in ("nlu", "both"):
        from sentence_transformers import SentenceTransformer
        models.append(SentenceTransformer("paraphrase-multilingual-mpnet-base-v2"))
        out["steps"]["after_load_nlu"] = _read_mem_mb()

    for i, model in enumerate(models):
        model.encode(_SAMPLE_TEXTS, normalize_embeddings=True)
        out["steps"][f"after_encode_model_{i}"] = _read_mem_mb()

    out["steps"]["end"] = _read_mem_mb()
    return out


def main() -> None:
    if len(sys.argv) > 1:  # che do process con: chay 1 kich ban, in JSON
        print(json.dumps(_scenario(sys.argv[1])))
        return

    if not Path("/proc/self/status").exists():
        print("Script nay do qua /proc (Linux) - hay chay trong container:")
        print("  docker compose exec api python scripts/measure_embedding_rss.py")
        sys.exit(1)

    print("Do RSS 2 model embedding (A3) - moi kich ban 1 process rieng...\n")
    results = {}
    for scenario in ("baseline", "kb", "nlu", "both"):
        proc = subprocess.run(
            [sys.executable, __file__, scenario],
            capture_output=True, text=True, check=False,
        )
        if proc.returncode != 0:
            print(f"[{scenario}] LOI:\n{proc.stderr}")
            sys.exit(1)
        # dong JSON cuoi cung (sentence-transformers co the in log truoc do)
        results[scenario] = json.loads(proc.stdout.strip().splitlines()[-1])
        peak = results[scenario]["steps"]["end"].get("VmHWM", "?")
        print(f"[{scenario:8s}] peak (VmHWM): {peak} MB")

    print("\nChi tiet tung buoc (MB):")
    for scenario, data in results.items():
        print(f"\n  {scenario}:")
        for step, mem in data["steps"].items():
            print(f"    {step:22s} RSS={mem.get('VmRSS', '?'):>8} peak={mem.get('VmHWM', '?'):>8}")

    both_peak = results["both"]["steps"]["end"].get("VmHWM", 0)
    base_peak = results["baseline"]["steps"]["end"].get("VmHWM", 0)
    print(f"\nKET LUAN SO BO (ghi vao bao cao A3 / ISSUES-VI.md):")
    print(f"  Peak 2 model cung process : {both_peak} MB (baseline interpreter: {base_peak} MB)")
    print(f"  Budget tham chieu (VPS 4GB, AGW-ROADMAP-001 §5): API+worker+PG(~256MB")
    print(f"  shared_buffers)+Redis+dashboard+OS phai cung vua 4GB + swap 2-4GB.")
    print(f"  Neu peak 2 model > ~1.5GB -> can nhac model nho/quantized hoac hosted API (REV2-03).")


if __name__ == "__main__":
    main()
