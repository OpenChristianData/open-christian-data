"""Quick benchmark: run all four OCR engines on 10 representative vol_01 leaves.

Reports avg confidence and a 2-line text sample per engine per page. Use to
compare model quality or verify a fix before a full corpus run.

Usage:
    py -3 build/tools/benchmark_10_pages.py
    py -3 build/tools/benchmark_10_pages.py --leaves 40 80 120 160 200
    py -3 build/tools/benchmark_10_pages.py --calamari-model ~/ocr-engines/calamari-models/gt4histocr
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys

# Force UTF-8 stdout so non-Latin OCR text (Greek, Hebrew, Syriac) prints
# correctly on Windows without cp1252 UnicodeEncodeError.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
from typing import Any

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.engine_inventory import ENGINE_SPECS, venv_python  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402

# Default leaf indices to sample (skip ~35 front-matter leaves, spread through body)
# Indices into the sorted list of ALL *.jpg files in vol_01 (leaf_* + page_*)
DEFAULT_LEAVES = [60, 110, 160, 210, 260, 310, 360, 410, 450, 490]

INPUT_ROOT = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages" / "vol_01"
CALAMARI_RUNNER = REPO_ROOT / "build" / "tools" / "ocr_runners" / "calamari_page.py"
KRAKEN_RUNNER = REPO_ROOT / "build" / "tools" / "ocr_runners" / "kraken_page.py"
SURYA_RUNNER = REPO_ROOT / "build" / "tools" / "ocr_runners" / "surya_page.py"
TESSERACT_RUNNER = REPO_ROOT / "build" / "tools" / "ocr_runners" / "tesseract_page.py"

DEFAULT_CALAMARI_MODEL = (
    Path.home() / "ocr-engines" / "calamari-models" / "antiqua_historical"
)
DEFAULT_CALAMARI_CHECKPOINTS = 2  # use 2 checkpoints to balance speed/accuracy


def _venv_py(engine_name: str) -> Path | None:
    spec = next((s for s in ENGINE_SPECS if s.name == engine_name), None)
    if spec is None:
        return None
    try:
        return venv_python(spec)
    except Exception:
        return None


def _run_engine(
    script: Path,
    image: Path,
    venv: Path | None,
    extra_args: list[str] | None = None,
    timeout: int = 180,
) -> dict[str, Any]:
    if venv is None or not venv.exists():
        return {"ok": False, "failure_class": "venv_not_found", "error": str(venv)}
    cmd = [str(venv), str(script), "--image", str(image)] + (extra_args or [])
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=False, timeout=timeout, check=True
        )
        stdout = result.stdout.decode("utf-8", errors="replace")
        return json.loads(stdout.strip().splitlines()[-1])
    except subprocess.TimeoutExpired:
        return {"ok": False, "failure_class": "timeout"}
    except subprocess.CalledProcessError as exc:
        stdout = (exc.stdout or b"").decode("utf-8", errors="replace")
        try:
            payload = json.loads(stdout.strip().splitlines()[-1])
            return payload
        except Exception:
            return {"ok": False, "failure_class": "subprocess_error",
                    "error": (exc.stderr or b"").decode("utf-8", errors="replace")[:300]}
    except Exception as exc:
        return {"ok": False, "failure_class": "error", "error": str(exc)[:300]}


def _avg_conf(result: dict[str, Any]) -> float | None:
    confs = []
    for block in result.get("blocks", []):
        for line in block.get("lines", []):
            c = line.get("confidence")
            if c is not None:
                confs.append(float(c))
    if not confs:
        return None
    return sum(confs) / len(confs)


def _text_sample(result: dict[str, Any], max_chars: int = 120) -> str:
    lines = []
    for block in result.get("blocks", []):
        for line in block.get("lines", []):
            text = (line.get("source_raw") or "").strip()
            if text:
                lines.append(text)
        if len(lines) >= 2:
            break
    sample = " | ".join(lines[:2])
    return sample[:max_chars] + ("..." if len(sample) > max_chars else "")


def _status(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        fc = result.get("failure_class", "?")
        err = str(result.get("error", ""))[:60]
        return f"FAIL:{fc} {err}"
    conf = _avg_conf(result)
    n_blocks = len(result.get("blocks", []))
    conf_str = f"{conf:.2f}" if conf is not None else "n/a"
    return f"conf={conf_str} blocks={n_blocks}"


def run_benchmark(
    leaf_indices: list[int],
    calamari_model: Path,
    calamari_checkpoints: int,
) -> None:
    all_leaves = sorted(INPUT_ROOT.glob("*.jpg"))
    if not all_leaves:
        print(f"ERROR: No leaf_*.jpg files found in {INPUT_ROOT}")
        sys.exit(1)

    tesseract_py = _venv_py("tesseract")
    surya_py = _venv_py("surya")
    calamari_py = _venv_py("calamari")
    kraken_py = _venv_py("kraken")

    calamari_args = []
    if calamari_model.exists():
        calamari_args = [
            "--model", str(calamari_model),
            "--max-checkpoints", str(calamari_checkpoints),
        ]
    else:
        print(f"WARNING: Calamari model not found at {calamari_model} -- skipping Calamari")

    print(f"\nBenchmark: {len(leaf_indices)} leaves from vol_01")
    print(f"Calamari model: {calamari_model.name if calamari_model.exists() else 'absent'} "
          f"(checkpoints={calamari_checkpoints})")
    print(f"Tesseract lang: eng+grc+heb+lat+deu+fra+syr\n")
    print(f"{'Leaf':<12} {'Engine':<12} {'Status':<30} Sample text")
    print("-" * 100)

    for idx in leaf_indices:
        if idx >= len(all_leaves):
            print(f"leaf_{idx:04d}  -- skipped (only {len(all_leaves)} leaves)")
            continue
        image = all_leaves[idx]
        leaf_label = image.stem

        # Tesseract
        r = _run_engine(TESSERACT_RUNNER, image, tesseract_py, timeout=60)
        print(f"{leaf_label:<12} {'tesseract':<12} {_status(r):<30} {_text_sample(r)}")

        # Surya
        r = _run_engine(SURYA_RUNNER, image, surya_py, timeout=120)
        print(f"{leaf_label:<12} {'surya':<12} {_status(r):<30} {_text_sample(r)}")

        # Kraken
        r = _run_engine(KRAKEN_RUNNER, image, kraken_py, timeout=300)
        print(f"{leaf_label:<12} {'kraken':<12} {_status(r):<30} {_text_sample(r)}")

        # Calamari
        if calamari_args:
            r = _run_engine(CALAMARI_RUNNER, image, calamari_py, extra_args=calamari_args, timeout=300)
            print(f"{leaf_label:<12} {'calamari':<12} {_status(r):<30} {_text_sample(r)}")

        print()

    print("Done.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--leaves", type=int, nargs="+", default=DEFAULT_LEAVES,
                        metavar="N", help="Leaf indices to test (0-based within vol_01 sorted list)")
    parser.add_argument("--calamari-model", type=Path, default=DEFAULT_CALAMARI_MODEL,
                        help="Path to Calamari checkpoint directory")
    parser.add_argument("--calamari-checkpoints", type=int, default=DEFAULT_CALAMARI_CHECKPOINTS,
                        help="Number of Calamari ensemble checkpoints to use (0=all)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_benchmark(
        leaf_indices=args.leaves,
        calamari_model=args.calamari_model,
        calamari_checkpoints=args.calamari_checkpoints,
    )
