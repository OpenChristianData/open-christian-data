"""Freeze eight Goffridus stage roots, receipts, and technical dependencies."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tools import prepare_openmgh_bsb829_gof_parts as parts
from build.tools.run_openmgh_bsb829_gof_parts_stages import PACKAGES, RECEIPTS, ROOT, STAGES
from ocd_kernel.tei.install_accepted import _files, _io_path


OUTPUT = ROOT / RECEIPTS / "freeze.json"
DIRECT = Path(r"D:\Library\Open Christian Data\candidate-reviews\openmgh-bsb829-gof-parts-20260926\receipt.json")
SHARED = (
    "ocd_kernel/library/acquisitions.py",
    "ocd_kernel/library/identities.py",
    "ocd_kernel/library/state.py",
    "ocd_kernel/lib/atomic_io.py",
    "ocd_kernel/projection/categories/native_documents.py",
    "ocd_kernel/projection/categories/prose.py",
    "ocd_kernel/reconstruction/contract.py",
    "ocd_kernel/tei/acceptance.py",
    "ocd_kernel/tei/install_accepted.py",
    "ocd_kernel/tei/reviewed_integration.py",
    "ocd_kernel/tei/validate.py",
)
PARTS_CODE = (
    "build/tei/openmgh_bsb829_gof_parts_oracle.py",
    "build/tools/prepare_openmgh_bsb829_gof_parts.py",
    "build/tools/prepare_openmgh_bsb829_gof_parts_manifests.py",
    "build/tools/stage_openmgh_bsb829_gof_parts_acceptance.py",
    "build/tools/preflight_openmgh_bsb829_gof_parts.py",
    "build/tools/install_openmgh_bsb829_gof_parts.py",
    "build/tools/run_openmgh_bsb829_gof_parts_stages.py",
    "build/tools/freeze_openmgh_bsb829_gof_parts.py",
    "tests/test_openmgh_bsb829_gof_parts.py",
    "tests/test_openmgh_bsb829_gof_parts_install.py",
)


def _read(path: Path) -> bytes:
    return Path(_io_path(path)).read_bytes()


def _sha(path: Path) -> str:
    return sha256(_read(path)).hexdigest()


def _json(path: Path) -> dict:
    value = json.loads(_read(path))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def freeze() -> dict:
    aggregate_path = ROOT / RECEIPTS / "receipt.json"
    aggregate = _json(aggregate_path)
    packages = _json(PACKAGES)
    direct = _json(DIRECT)
    if (aggregate.get("contract") != "ocd-openmgh-bsb829-gof-parts-stages-v1"
            or packages.get("contract") != "ocd-openmgh-bsb829-gof-parts-packages-v1"
            or direct.get("contract") != "ocd-openmgh-bsb829-gof-parts-candidates-v1"
            or len(aggregate["stages"]) != 8 or len(packages["works"]) != 8
            or len(direct["candidates"]) != 8):
        raise ValueError("expected exact eight-stage source chain")
    dependencies = {Path(path) for path in (*SHARED, *PARTS_CODE, parts.SOURCE,
                                          parts.RECEIPT, parts.BATCH)}
    stages = []
    for row in aggregate["stages"]:
        receipt_path = ROOT / row["receipt_path"]
        record = _json(receipt_path)
        stage = Path(record["stage_root"])
        work = Path("library/works") / row["work_id"]
        if (record["work_id"] != row["work_id"]
                or _sha(receipt_path) != row["receipt_sha256"]
                or not stage.is_relative_to(STAGES)
                or _files(stage / work) != record["after"]
                or _files(ROOT / work) != record["before"]
                or _sha(stage / record["manifest_path"]) != record["source_manifest_after_sha256"]
                or _sha(stage / record["profile_path"]) != record["profile_after_sha256"]):
            raise ValueError(f"stage/root/receipt changed: {row['work_id']}")
        manifest = _json(ROOT / record["manifest_path"])
        dependencies.update(Path(item["path"]) for item in manifest["authorities"])
        dependencies.update(Path(manifest[key]["implementation_path"])
                            for key in ("converter", "validator"))
        dependencies.add(Path(manifest["package_schema"]["path"]))
        policy = _json(ROOT / parts.SIDE_HOME / "validation-policy.json")
        dependencies.update(Path(path) for path in policy["closure_inputs"])
        edition = work / "forms" / f"{row['work_id']}-openmgh-retained" / "editions" / f"{row['work_id']}-openmgh-electronic"
        if Path(_io_path(ROOT / edition / "master.tei.xml")).exists():
            raise ValueError(f"canonical master already installed: {row['work_id']}")
        stages.append({"work_id": row["work_id"], "stage_root": stage.as_posix(),
                       "stage_receipt": row["receipt_path"],
                       "stage_receipt_sha256": row["receipt_sha256"],
                       "accepted_master_sha256": row["accepted_master_sha256"]})
    if len({row["stage_root"] for row in stages}) != 8:
        raise ValueError("stage roots are not distinct")
    return {"contract": "ocd-openmgh-bsb829-gof-parts-freeze-v1", "status": "staged-only",
            "canonical_install": "not-performed", "corpus_refresh": "not-performed",
            "source_sha256": _sha(ROOT / parts.SOURCE),
            "frozen_batch_sha256": _sha(ROOT / parts.BATCH),
            "acquisition_receipt_sha256": _sha(ROOT / parts.RECEIPT),
            "direct_receipt": DIRECT.as_posix(), "direct_receipt_sha256": _sha(DIRECT),
            "package_receipt": PACKAGES.as_posix(), "package_receipt_sha256": _sha(PACKAGES),
            "stage_aggregate_receipt": (RECEIPTS / "receipt.json").as_posix(),
            "stage_aggregate_receipt_sha256": _sha(aggregate_path),
            "dependencies": [{"path": path.as_posix(), "sha256": _sha(ROOT / path)}
                             for path in sorted(dependencies)],
            "stages": stages}


def main() -> int:
    result = freeze()
    content = (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if Path(_io_path(OUTPUT)).exists() and _read(OUTPUT) != content:
        raise ValueError("existing exact freeze differs")
    Path(_io_path(OUTPUT)).write_bytes(content)
    print(json.dumps({"stages": len(result["stages"]),
                      "dependencies": len(result["dependencies"]),
                      "receipt": OUTPUT.as_posix(), "sha256": _sha(OUTPUT)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
