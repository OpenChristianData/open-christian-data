"""Generate exact one-work source manifests for LIB-054 readable candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build.tei.lib054_work_local_oracle import _import_closure_sha256

FAMILY = Path("sources/structured-text/lib054-ccel-puritan")
PROFILE = FAMILY / "lib054.reconstruction-profile.json"
POLICY = FAMILY / "lib054-work-local.validation-policy.json"
SCHEMA = Path("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json")
XSD = Path("ocd_kernel/tei/vendor/xsd/tei_all.xsd")
CONVERTER = Path("build/tei/lib054_work_local.py")
CONVERTER_SUPPORT = Path("build/tei/lib031_reconstruction.py")
ORACLE = Path("build/tei/lib054_work_local_oracle.py")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _authority(root: Path, name: str, path: Path, role: str) -> dict[str, object]:
    content = (root / path).read_bytes()
    return {"name": name, "path": path.as_posix(), "role": role, "bytes": len(content), "sha256": _sha(content)}


def manifest_bytes(root: Path, work_id: str) -> bytes:
    profile = json.loads((root / PROFILE).read_bytes())
    matches = [item for item in profile["works"] if item["work_id"] == work_id]
    if len(matches) != 1:
        raise ValueError(f"unknown LIB-054 work: {work_id}")
    work = matches[0]
    source = Path(str(work["source_path"]))
    config = FAMILY / "work-bindings" / work_id / "config.json"
    authorities = [
        _authority(root, str(work["authority_name"]), source, "primary-source"),
        _authority(root, "work-identity-config", config, "work-identity-config"),
        _authority(root, "reconstruction-profile", PROFILE, "complete-source-feature-profile"),
        _authority(root, "validation-policy", POLICY, "independent-validation-policy"),
        _authority(root, "tei-p5-xsd", XSD, "tei-validation-schema"),
        _authority(root, "candidate-package-schema", SCHEMA, "candidate-package-schema"),
        _authority(root, "family-converter-support", CONVERTER_SUPPORT, "converter-support"),
    ]
    if (authorities[0]["bytes"], authorities[0]["sha256"]) != (work["bytes"], work["sha256"]):
        raise ValueError(f"retained LIB-054 source drifted: {work_id}")
    config_value = json.loads((root / config).read_bytes())
    if config_value.get("work_id") != work_id:
        raise ValueError(f"LIB-054 identity config drifted: {work_id}")
    record = {
        "contract": "ocd-source-manifest-v1",
        "work_id": work_id,
        "source_id": "ccel-lib054-work-" + work_id,
        "authorities": authorities,
        "converter": {"id": "ocd-lib054-work-local-thml-to-tei", "version": "1", "callable": "_convert", "implementation_path": CONVERTER.as_posix(), "implementation_sha256": _sha((root / CONVERTER).read_bytes())},
        "validator": {"id": "ocd-lib054-work-local-source-oracle", "version": "1", "callable": "_oracle", "implementation_path": ORACLE.as_posix(), "implementation_sha256": _sha((root / ORACLE).read_bytes()), "import_closure_sha256": _import_closure_sha256(root)},
        "package_schema": {"path": SCHEMA.as_posix(), "sha256": _sha((root / SCHEMA).read_bytes())},
    }
    return _json(record)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--work", action="append")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    profile = json.loads((root / PROFILE).read_bytes())
    works = args.work or [str(item["work_id"]) for item in profile["works"]]
    for work_id in works:
        content = manifest_bytes(root, work_id)
        destination = root / FAMILY / "work-bindings" / work_id / "lib054-work.source-manifest.json"
        if args.check:
            if destination.read_bytes() != content:
                raise ValueError(f"LIB-054 work manifest stale: {work_id}")
        else:
            destination.write_bytes(content)
        print(f"{work_id}: {_sha(content)}")


if __name__ == "__main__":
    main()
