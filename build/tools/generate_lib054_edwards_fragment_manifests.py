"""Seal only the two Edwards fragment manifests with their enclosing volumes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build.tei.lib054_edwards_fragments_oracle import _import_closure_sha256

ROOT = Path(__file__).resolve().parents[2]
FAMILY = Path("sources/structured-text/lib054-ccel-puritan")
POLICY = FAMILY / "lib054-edwards-fragment.validation-policy.json"
CONVERTER = Path("build/tei/lib054_edwards_fragments.py")
ORACLE = Path("build/tei/lib054_edwards_fragments_oracle.py")
VOLUMES = {
    "edwards-distinguishing-marks": Path("raw/ccel/edwards/works2.xml"),
    "edwards-history-of-redemption": Path("raw/ccel/edwards/works1.xml"),
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _authority(root: Path, name: str, relative: Path, role: str) -> dict[str, object]:
    content = (root / relative).read_bytes()
    return {"name": name, "path": relative.as_posix(), "role": role,
            "bytes": len(content), "sha256": _sha(content)}


def manifest_bytes(root: Path, work_id: str) -> bytes:
    if work_id not in VOLUMES:
        raise ValueError(f"outside Edwards fragment scope: {work_id}")
    base_path = FAMILY / "work-bindings" / work_id / "lib054-work.source-manifest.json"
    record = json.loads((root / base_path).read_bytes())
    if record.get("work_id") != work_id:
        raise ValueError("fragment baseline manifest identity differs")
    authorities = list(record["authorities"])
    authorities.extend([
        _authority(root, "enclosing-edwards-volume", VOLUMES[work_id], "enclosing-volume"),
        _authority(root, "validation-policy", POLICY, "independent-validation-policy"),
        _authority(root, "fragment-converter-support", Path("build/tei/lib054_work_local.py"), "converter-support"),
        _authority(root, "fragment-oracle-support", Path("build/tei/lib054_work_local_oracle.py"), "validator-support"),
    ])
    authorities = [item for item in authorities if item["role"] != "independent-validation-policy" or item["path"] == POLICY.as_posix()]
    record["authorities"] = authorities
    record["source_id"] = "ccel-lib054-enclosing-volume-" + work_id
    record["converter"] = {"id": "ocd-lib054-edwards-volume-fragment-to-tei", "version": "1",
                           "callable": "_convert", "implementation_path": CONVERTER.as_posix(),
                           "implementation_sha256": _sha((root / CONVERTER).read_bytes())}
    record["validator"] = {"id": "ocd-lib054-edwards-enclosing-volume-oracle", "version": "1",
                           "callable": "_oracle", "implementation_path": ORACLE.as_posix(),
                           "implementation_sha256": _sha((root / ORACLE).read_bytes()),
                           "import_closure_sha256": _import_closure_sha256(root)}
    return (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for work_id in VOLUMES:
        path = ROOT / FAMILY / "work-bindings" / work_id / "lib054-edwards-fragment.source-manifest.json"
        content = manifest_bytes(ROOT, work_id)
        if args.check:
            if path.read_bytes() != content:
                raise ValueError(f"Edwards fragment manifest stale: {work_id}")
        else:
            path.write_bytes(content)
        print(f"{work_id}: {_sha(content)}")


if __name__ == "__main__":
    main()
