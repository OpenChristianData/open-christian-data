"""Describe the existing Equiano receipt mismatch without rebuilding a release."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from ocd_kernel.projection.categories.prose import verify_accepted_prose
from ocd_kernel.release.work_metadata import check_work_metadata


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/_logs/equiano-private-release-20261002-v1"
RELEASE = OUT / "release"
ACCEPTANCE = ROOT / "library/works/equiano-interesting-narrative-1789/forms/equiano-english/editions/ecco-second-edition/acceptance.json"


def _sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def main() -> None:
    rows = [json.loads(line) for line in (RELEASE / "public/data/prose/train.jsonl").read_text(encoding="utf-8").splitlines()]
    receipt = json.loads((RELEASE / "internal/projection-receipts/equiano-interesting-narrative-1789.json").read_text(encoding="utf-8"))
    rows, receipt = check_work_metadata(ROOT, rows, receipt)
    captured: dict = {}

    def tracer(frame, event, _arg):
        if event == "return" and frame.f_code.co_name == "verify_document" and frame.f_code.co_filename.endswith("native_documents.py"):
            if "wanted" in frame.f_locals:
                captured["wanted"] = frame.f_locals["wanted"]
        return tracer

    sys.setprofile(tracer)
    try:
        errors = verify_accepted_prose(ROOT, acceptance_path=ACCEPTANCE, rows=rows, receipt=receipt)
    finally:
        sys.setprofile(None)
    wanted = captured.get("wanted")
    if wanted is None:
        raise ValueError("Independent wanted receipt was not captured")
    differences = {}
    for key in sorted(set(receipt) | set(wanted)):
        if receipt.get(key) != wanted.get(key):
            left, right = receipt.get(key), wanted.get(key)
            differences[key] = {"saved_sha256": _sha(left), "wanted_sha256": _sha(right),
                                "saved_preview": str(left)[:400], "wanted_preview": str(right)[:400]}
    result = {"diagnostics": errors, "different_keys": differences,
              "saved_receipt_sha256": hashlib.sha256((RELEASE / "internal/projection-receipts/equiano-interesting-narrative-1789.json").read_bytes()).hexdigest(),
              "rows": len(rows)}
    path = OUT / "focused-receipt-diff.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != result:
            raise ValueError("Existing Equiano focused diagnostic differs")
    else:
        path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
