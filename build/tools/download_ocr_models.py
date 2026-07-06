"""Download pre-trained OCR models for Kraken and Calamari.

Kraken: CATMuS-Print (catmus-print-fondue-large.mlmodel)
  - Trained on Roman print, 16th-21st century, multiple languages including English/Latin/German
  - Zenodo: 10.5281/zenodo.10592716, CC-BY-4.0
  - Target: ~/ocr-engines/kraken-models/catmus-print-fondue-large.mlmodel

Calamari: antiqua_historical (release 2.2, compatible with Calamari 2.3.1)
  - Trained on GT4HistOCR antiqua (Roman typeface) historical documents
  - GitHub: Calamari-OCR/calamari_models release 2.2
  - Target: ~/ocr-engines/calamari-models/antiqua_historical/
"""

from __future__ import annotations

import hashlib
import os
import sys
import tarfile
import urllib.request
from pathlib import Path

KRAKEN_MODEL_URL = (
    "https://zenodo.org/api/records/10592716/files/"
    "catmus-print-fondue-large.mlmodel/content"
)
KRAKEN_MODEL_NAME = "catmus-print-fondue-large.mlmodel"

CALAMARI_MODEL_URL = (
    "https://github.com/Calamari-OCR/calamari_models/releases/download/2.2/"
    "antiqua_historical.tar.gz"
)
CALAMARI_MODEL_ARCHIVE = "antiqua_historical.tar.gz"
CALAMARI_MODEL_DIR = "antiqua_historical"

ENGINES_ROOT = Path(os.path.expanduser("~")) / "ocr-engines"
KRAKEN_MODELS_DIR = ENGINES_ROOT / "kraken-models"
CALAMARI_MODELS_DIR = ENGINES_ROOT / "calamari-models"


def _download(url: str, dest: Path, label: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    print(f"  Downloading {label}...", flush=True)

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ocd-ocr-pipeline/1.0)",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        total = int(response.headers.get("Content-Length", 0))
        downloaded = 0
        chunk = 65536
        with tmp.open("wb") as fh:
            while True:
                block = response.read(chunk)
                if not block:
                    break
                fh.write(block)
                downloaded += len(block)
                if total:
                    pct = downloaded * 100 // total
                    print(f"\r  {label}: {downloaded // 1024}KB / {total // 1024}KB ({pct}%)", end="", flush=True)
    print()
    tmp.rename(dest)
    print(f"  Saved -> {dest}", flush=True)


def download_kraken_model() -> Path:
    dest = KRAKEN_MODELS_DIR / KRAKEN_MODEL_NAME
    if dest.exists():
        print(f"  Kraken model already present: {dest}", flush=True)
        return dest
    _download(KRAKEN_MODEL_URL, dest, "catmus-print-fondue-large.mlmodel")
    return dest


def download_calamari_model() -> Path:
    model_dir = CALAMARI_MODELS_DIR / CALAMARI_MODEL_DIR
    if model_dir.exists() and any(model_dir.iterdir()):
        print(f"  Calamari model already present: {model_dir}", flush=True)
        return model_dir

    archive = CALAMARI_MODELS_DIR / CALAMARI_MODEL_ARCHIVE
    _download(CALAMARI_MODEL_URL, archive, "antiqua_historical.tar.gz")

    print(f"  Extracting to {CALAMARI_MODELS_DIR}...", flush=True)
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(CALAMARI_MODELS_DIR)  # noqa: S202 -- controlled URL
    archive.unlink()
    print(f"  Calamari model extracted -> {model_dir}", flush=True)
    return model_dir


def main() -> int:
    print("Downloading OCR models...", flush=True)

    print("\n[1/2] Kraken -- CATMuS-Print", flush=True)
    try:
        kraken_path = download_kraken_model()
        print(f"  OK: {kraken_path}", flush=True)
    except Exception as exc:
        print(f"  FAILED: {exc}", flush=True)
        return 1

    print("\n[2/2] Calamari -- antiqua_historical", flush=True)
    try:
        calamari_path = download_calamari_model()
        print(f"  OK: {calamari_path}", flush=True)
        # List checkpoint files found
        ckpts = list(calamari_path.rglob("*.ckpt.json")) + list(calamari_path.rglob("*.h5"))
        if ckpts:
            print(f"  Checkpoint files: {[f.name for f in ckpts[:5]]}", flush=True)
        else:
            all_files = list(calamari_path.rglob("*"))
            print(f"  Files found: {[f.name for f in all_files[:10]]}", flush=True)
    except Exception as exc:
        print(f"  FAILED: {exc}", flush=True)
        return 1

    print("\nDone. Models ready.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
