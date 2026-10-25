"""Stage the nine LIB-044 work-local candidates without changing accepted state."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build.tools.reconstruct_candidate import run as reconstruct_candidate


ROOT = Path("\\\\?\\" + str(Path(__file__).resolve().parents[2]))
ASSIGNED = (
    ("iv.i", "ambrose-of-milan-on-duties-of-clergy"),
    ("iv.ii", "ambrose-of-milan-on-holy-spirit"),
    ("iv.iii", "ambrose-of-milan-on-satyrus"),
    ("iv.iv", "ambrose-of-milan-exposition-of-christian-faith"),
    ("iv.v", "ambrose-of-milan-on-mysteries"),
    ("iv.vi", "ambrose-of-milan-concerning-repentance"),
    ("iv.vii", "ambrose-of-milan-concerning-virgins"),
    ("iv.viii", "ambrose-of-milan-concerning-widows"),
    ("v", "ambrose-of-milan-letters"),
)
SOURCE_SHA256 = "c6f1a9d66653852d8b743c84a613c72c521dfb1b05602f0a2eff400c17665ee8"
EVIDENCE = ROOT / "plans/2026-09-22-source-preflight/npnf210-nine-work-local-heading-repair-v2-20260926.json"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _binding(path: str, name: str, role: str) -> dict[str, object]:
    content = (ROOT / path).read_bytes()
    return {"name": name, "path": path, "role": role, "bytes": len(content), "sha256": _sha(content)}


def _manifest(scope: str, work_id: str) -> tuple[Path, dict[str, object]]:
    work_path = f"library/works/{work_id}/work.json"
    work = json.loads((ROOT / work_path).read_bytes())
    if work["work_id"] != work_id:
        raise ValueError(f"work identity mismatch: {work_id}")
    edition = work["textual_forms"][0]["editions"][0]
    if edition["containing_source"]["locator"] != f"raw/ccel/npnf2/npnf210.xml#{scope}":
        raise ValueError(f"source locator mismatch: {work_id}")
    edition_path = f"library/works/{work_id}/forms/{work['textual_forms'][0]['textual_form_id']}/editions/{edition['edition_id']}"
    acquisition_path = f"{edition_path}/acquisitions/{edition['acquisition_ids'][0]}.json"
    acquisition = json.loads((ROOT / acquisition_path).read_bytes())
    if acquisition["source_sha256"] != SOURCE_SHA256 or acquisition["source_path"] != "raw/ccel/npnf2/npnf210.xml":
        raise ValueError(f"acquisition source binding mismatch: {work_id}")
    authorities = [
        _binding("raw/ccel/npnf2/npnf210.xml", "retained-thml", "primary-source"),
        _binding(work_path, "work-identity", "work-identity"),
        _binding(acquisition_path, "acquisition", "acquisition"),
        _binding("sources/structured-text/ambrose-npnf210/npnf-ambrose.reconstruction-profile.json", "reconstruction-profile", "complete-source-feature-profile"),
        _binding("sources/structured-text/ambrose-npnf210/npnf210-work-local.validation-policy.json", "validation-policy", "independent-validation-policy"),
        _binding("ocd_kernel/tei/vendor/xsd/tei_all.xsd", "tei-p5-xsd", "tei-validation-schema"),
        _binding("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json", "candidate-package-schema", "candidate-package-schema"),
        _binding("build/tei/npnf_ambrose_reconstruction.py", "family-converter-support", "converter-support"),
        _binding("build/tei/npnf_ambrose_oracle.py", "family-oracle-support", "validator-support"),
    ]
    converter_path = "build/tei/npnf_ambrose_work_local.py"
    oracle_path = "build/tei/npnf_ambrose_work_local_oracle.py"
    from build.tei.npnf_ambrose_work_local_oracle import _closure

    record = {
        "contract": "ocd-source-manifest-v1",
        "source_id": f"ccel-npnf210-work-{work_id}",
        "work_id": work_id,
        "authorities": authorities,
        "converter": {"id": "ocd-npnf210-work-local-to-tei", "version": "1", "callable": "_convert", "implementation_path": converter_path, "implementation_sha256": _sha((ROOT / converter_path).read_bytes())},
        "validator": {"id": "ocd-npnf210-work-local-source-oracle", "version": "1", "callable": "_oracle", "implementation_path": oracle_path, "implementation_sha256": _sha((ROOT / oracle_path).read_bytes()), "import_closure_sha256": _closure(ROOT)},
        "package_schema": {"path": "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json", "sha256": _sha((ROOT / "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json").read_bytes())},
    }
    path = ROOT / f"sources/structured-text/{work_id}/npnf210-work-heading-repair-v2.source-manifest.json"
    return path, record


def stage() -> dict[str, object]:
    source = ROOT / "raw/ccel/npnf2/npnf210.xml"
    if _sha(source.read_bytes()) != SOURCE_SHA256:
        raise ValueError("retained NPNF210 XML changed")
    rows = []
    for scope, work_id in ASSIGNED:
        manifest_path, record = _manifest(scope, work_id)
        manifest_bytes = _json(record)
        manifest_path.write_bytes(manifest_bytes)
        destination = Path("D:/Library/Open Christian Data/candidate-reviews") / f"npnf210-work-{work_id}-heading-repair-v2-20260926"
        result = reconstruct_candidate(manifest=manifest_path.relative_to(ROOT).as_posix(), destination=str(destination), repository_root=str(ROOT))
        if result["status"] != "pass" or result["acceptance_status"] != "nonaccepted":
            raise ValueError(f"work-local reconstruction failed: {work_id}")
        package = destination / "package"
        file_hashes = {path.name: _sha(path.read_bytes()) for path in sorted(package.iterdir()) if path.is_file()}
        rows.append({"work_id": work_id, "source_root_id": scope, "manifest_path": manifest_path.relative_to(ROOT).as_posix(), "manifest_sha256": _sha(manifest_bytes), "candidate_path": str(destination), "candidate_sha256": result["digests"]["candidate"], "validation_sha256": _sha((destination / "validation.json").read_bytes()), "files": file_hashes})
    receipt = {"contract": "ocd-npnf210-nine-work-local-heading-repair-v2", "status": "pass", "source_path": "raw/ccel/npnf2/npnf210.xml", "source_sha256": SOURCE_SHA256, "source_is_archive": False, "work_count": len(rows), "works": rows, "acceptance": "not-recorded", "canonical_install": False, "publication": "not-ready"}
    EVIDENCE.write_bytes(_json(receipt))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    receipt = stage()
    print(_json({"status": receipt["status"], "work_count": receipt["work_count"], "receipt": str(EVIDENCE)}).decode(), end="")


if __name__ == "__main__":
    main()
