"""Run the OCR engine readiness smoke and write one sidecar per engine.

Tesseract gets a real OCR run on a sample leaf; surya/calamari/kraken get an
import+version readiness probe inside their own venvs (their production runners
are batch B4). Exits non-zero if any "ocr"-kind engine (i.e. the newly installed
Tesseract) fails -- a fail-closed readiness gate for the one engine this batch
installs.

Run:  py -3 build/tools/run_engine_smoke.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.engine_inventory import (  # noqa: E402
    ENGINE_SPECS,
    SMOKE_REPORT_SUBDIR,
    run_all_smokes,
)

OUTPUT_DIR = REPO_ROOT / SMOKE_REPORT_SUBDIR


def _write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    sidecars = run_all_smokes(REPO_ROOT)
    ocr_kind_names = {spec.name for spec in ENGINE_SPECS if spec.kind == "ocr"}
    failed_required = []
    for sidecar in sidecars:
        out = OUTPUT_DIR / f"{sidecar['engine']}.smoke.json"
        _write_atomic(out, sidecar)
        status = "OK" if sidecar.get("ok") else "FAIL"
        ver = sidecar.get("version") or "-"
        extra = f"text_len={sidecar.get('text_len')}" if sidecar.get("mode") == "ocr" else ""
        print(f"  [{status}] {sidecar['engine']:<10} mode={sidecar['mode']:<9} "
              f"version={ver} {extra}".rstrip())
        if sidecar["engine"] in ocr_kind_names and not sidecar.get("ok"):
            failed_required.append(sidecar["engine"])

    print(f"Wrote {len(sidecars)} smoke sidecars to {SMOKE_REPORT_SUBDIR.as_posix()}/")
    if failed_required:
        print(f"REQUIRED engine(s) failed: {', '.join(failed_required)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
