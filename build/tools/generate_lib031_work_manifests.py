"""Generate exact one-work LIB-031 source manifests for the standard handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build.tei.lib031_work_local_oracle import _import_closure_sha256

SOURCE_SET = Path("sources/structured-text/bounds-essentials-of-prayer/lib031-retained-source-set.json")
PROFILE = Path("sources/structured-text/bounds-essentials-of-prayer/lib031.reconstruction-profile.json")
POLICY = Path("sources/structured-text/bounds-essentials-of-prayer/lib031-work-local.validation-policy.json")
SCHEMA = Path("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json")
XSD = Path("ocd_kernel/tei/vendor/xsd/tei_all.xsd")
CONVERTER = Path("build/tei/lib031_work_local.py")
CONVERTER_SUPPORT = Path("build/tei/lib031_reconstruction.py")
ORACLE = Path("build/tei/lib031_work_local_oracle.py")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _authority(root: Path, name: str, path: Path, role: str) -> dict[str, object]:
    content = (root / path).read_bytes()
    return {"name": name, "path": path.as_posix(), "role": role, "bytes": len(content), "sha256": _sha(content)}


def manifest_bytes(root: Path, work_id: str) -> bytes:
    source_set = json.loads((root / SOURCE_SET).read_bytes())
    members = [item for item in source_set["members"] if item["work_id"] == work_id]
    if len(members) != 1 or members[0]["disposition"] != "include":
        raise ValueError(f"unknown LIB-031 member: {work_id}")
    source = Path("raw") / members[0]["logical_path"]
    config = Path("sources/structured-text") / work_id / "config.json"
    authorities = [
        _authority(root, work_id + "-source", source, "primary-source"),
        _authority(root, "work-identity-config", config, "work-identity-config"),
        _authority(root, "retained-source-set", SOURCE_SET, "source-member-census"),
        _authority(root, "reconstruction-profile", PROFILE, "complete-source-feature-profile"),
        _authority(root, "validation-policy", POLICY, "independent-validation-policy"),
        _authority(root, "tei-p5-xsd", XSD, "tei-validation-schema"),
        _authority(root, "candidate-package-schema", SCHEMA, "candidate-package-schema"),
        _authority(root, "family-converter-support", CONVERTER_SUPPORT, "converter-support"),
    ]
    if authorities[0]["sha256"] != members[0]["sha256"] or authorities[0]["bytes"] != members[0]["bytes"]:
        raise ValueError(f"retained source set drifted: {work_id}")
    record = {
        "contract": "ocd-source-manifest-v1",
        "work_id": work_id,
        "source_id": "ccel-lib031-work-" + work_id,
        "authorities": authorities,
        "converter": {"id": "ocd-lib031-work-local-thml-to-tei", "version": "1", "callable": "_convert", "implementation_path": CONVERTER.as_posix(), "implementation_sha256": _sha((root / CONVERTER).read_bytes())},
        "validator": {"id": "ocd-lib031-work-local-source-oracle", "version": "1", "callable": "_oracle", "implementation_path": ORACLE.as_posix(), "implementation_sha256": _sha((root / ORACLE).read_bytes()), "import_closure_sha256": _import_closure_sha256(root)},
        "package_schema": {"path": SCHEMA.as_posix(), "sha256": _sha((root / SCHEMA).read_bytes())},
    }
    return _canonical(record)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--work", action="append", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    for work_id in args.work:
        expected = manifest_bytes(root, work_id)
        destination = root / "sources" / "structured-text" / work_id / "lib031-work.source-manifest.json"
        if args.check:
            if destination.read_bytes() != expected:
                raise ValueError(f"work-local manifest stale: {work_id}")
        else:
            destination.write_bytes(expected)
        print(f"{work_id}: {_sha(expected)}")


if __name__ == "__main__":
    main()
