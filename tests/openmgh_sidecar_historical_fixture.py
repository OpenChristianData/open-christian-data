"""Build exact before-generation contexts for historical MGH sidecar transactions."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
from ocd_kernel.tei.install_accepted import _files, _io_path


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def historical_mgh_sidecar_root(input_root: Path, destination: Path, receipt_path: Path,
                                expected_receipt_sha256: str | None = None) -> tuple[Path, Path, dict]:
    raw = _io_path(receipt_path).read_bytes()
    if expected_receipt_sha256 is not None:
        assert sha256(raw).hexdigest() == expected_receipt_sha256
    record = json.loads(raw)
    assert record["status"] == "staged-only" and record["installation"] == "not-performed"
    work = Path("library/works") / record["work_id"]
    stage = Path(record["stage_root"])
    assert _files(stage / work) == record["after"]
    assert destination.is_dir() and not _files(destination)
    # These are the same bounded dependencies present in the original stage,
    # never a current canonical code or metadata overlay.
    prefix = work.as_posix() + "/"
    for relative, digest in _files(stage).items():
        if relative.startswith(prefix):
            continue
        payload = _io_path(stage / relative).read_bytes()
        assert sha256(payload).hexdigest() == digest
        target = _io_path(destination / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    retained_before = stage.parent / "fixture"
    assert len(record["before"]) == 3
    for relative, digest in record["before"].items():
        payload = _io_path(retained_before / work / relative).read_bytes()
        assert sha256(payload).hexdigest() == digest
        target = _io_path(destination / work / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    assert _files(destination / work) == record["before"]
    history = stage / work / "integration/openmgh-language-rebind-v1"
    historical_manifest = json.loads(_io_path(history / "historical-source-manifest.json").read_bytes())
    historical_manifest["validator"]["import_closure_sha256"] = record["historical_oracle_closure_sha256"]
    manifest_raw = _json(historical_manifest)
    assert sha256(manifest_raw).hexdigest() == record["source_manifest_before_sha256"]
    profile_raw = _io_path(history / "historical-reconstruction-profile.json").read_bytes()
    assert sha256(profile_raw).hexdigest() == record["profile_before_sha256"]
    for logical, payload in ((record["manifest_path"], manifest_raw), (record["profile_path"], profile_raw)):
        target = _io_path(destination / logical)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    inspection = Path(record["original_inspection_receipt"])
    payload = _io_path(input_root / inspection).read_bytes()
    assert sha256(payload).hexdigest() == record["original_inspection_receipt_sha256"]
    target = _io_path(destination / inspection)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    context = dict(record, canonical_root=destination.as_posix())
    assert dict(context, canonical_root=record["canonical_root"]) == record
    derived = destination / "fixture-stage-receipt.json"
    derived.write_bytes(_json(context))
    return destination, derived, context
