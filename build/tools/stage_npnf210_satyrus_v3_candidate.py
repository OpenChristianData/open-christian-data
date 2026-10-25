"""Reconstruct the Satyrus child with its explicit Book II headings shown once."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from build.tei.npnf_ambrose_satyrus_title_v3_oracle import _closure
from build.tools.reconstruct_candidate import run as reconstruct_candidate


ROOT = Path("\\\\?\\" + str(Path(__file__).resolve().parents[2]))
WORK_ID = "ambrose-of-milan-on-satyrus"
SOURCE = Path("raw/ccel/npnf2/npnf210.xml")
SOURCE_SHA = "c6f1a9d66653852d8b743c84a613c72c521dfb1b05602f0a2eff400c17665ee8"
OLD = Path(f"sources/structured-text/{WORK_ID}/npnf210-work-heading-repair-v2.source-manifest.json")
MANIFEST = Path(f"sources/structured-text/{WORK_ID}/npnf210-satyrus-title-v3.source-manifest.json")
DESTINATION = Path(f"D:/Library/Open Christian Data/candidate-reviews/npnf210-work-{WORK_ID}-title-v3-20260926")
RECEIPT = Path("plans/2026-09-22-source-preflight/npnf210-satyrus-title-v3-candidate-20260926.json")
CONVERTER = Path("build/tei/npnf_ambrose_satyrus_title_v3.py")
ORACLE = Path("build/tei/npnf_ambrose_satyrus_title_v3_oracle.py")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def stage() -> dict[str, object]:
    if DESTINATION.exists() or (ROOT / MANIFEST).exists() or (ROOT / RECEIPT).exists():
        raise ValueError("Satyrus v3 output already exists")
    if _sha((ROOT / SOURCE).read_bytes()) != SOURCE_SHA:
        raise ValueError("retained NPNF210 XML changed")
    record = json.loads((ROOT / OLD).read_bytes())
    if record["work_id"] != WORK_ID or record["source_id"] != f"ccel-npnf210-work-{WORK_ID}":
        raise ValueError("source manifest identity changed")
    record["converter"] = {"id": "ocd-npnf210-satyrus-title-v3-to-tei", "version": "3", "callable": "_convert", "implementation_path": CONVERTER.as_posix(), "implementation_sha256": _sha((ROOT / CONVERTER).read_bytes())}
    record["validator"] = {"id": "ocd-npnf210-satyrus-title-v3-source-oracle", "version": "3", "callable": "_oracle", "implementation_path": ORACLE.as_posix(), "implementation_sha256": _sha((ROOT / ORACLE).read_bytes()), "import_closure_sha256": _closure(ROOT)}
    manifest_bytes = _json(record)
    (ROOT / MANIFEST).write_bytes(manifest_bytes)
    result = reconstruct_candidate(manifest=MANIFEST.as_posix(), destination=str(DESTINATION), repository_root=str(ROOT))
    if result["status"] != "pass" or result["acceptance_status"] != "nonaccepted":
        raise ValueError("Satyrus v3 source reconstruction failed")
    package = DESTINATION / "package"
    receipt = {"contract": "ocd-npnf210-satyrus-title-v3-candidate-v1", "status": "pass", "work_id": WORK_ID, "source_root_id": "iv.iii", "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA, "manifest_path": MANIFEST.as_posix(), "manifest_sha256": _sha(manifest_bytes), "candidate_path": str(DESTINATION), "candidate_sha256": result["digests"]["candidate"], "validation_sha256": _sha((DESTINATION / "validation.json").read_bytes()), "files": {path.name: _sha(path.read_bytes()) for path in sorted(package.iterdir()) if path.is_file()}, "canonical_install": False, "acceptance": "not-recorded"}
    (ROOT / RECEIPT).write_bytes(_json(receipt))
    return receipt


if __name__ == "__main__":
    print(_json(stage()).decode(), end="")
