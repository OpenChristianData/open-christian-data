"""Exact historical NPNF generations with the actual current installer oracle."""
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
from tests.npnf_install_runtime_fixture import current_npnf_work_install_context
from ocd_kernel.tei.install_accepted import _files, _io_path


def _case(root, work_id):
    cases = []
    for name in ("npnf-four-install-before.json", "npnf-late-install-before.json"):
        cases.extend(json.loads((root / "tests/fixtures/reconstruction-runtime" / name).read_bytes()))
    assert len({row["work_id"] for row in cases}) == len(cases)
    matches = [row for row in cases if row["work_id"] == work_id]
    assert len(matches) == 1
    return matches[0]


def four_work_install_fixture(input_root, destination, work_id):
    case = _case(input_root, work_id)
    before = destination / "preserved-before"
    work = Path("library/works") / work_id
    for item in case["preserved_before"]:
        payload = (input_root / item["fixture"]).read_bytes()
        assert sha256(payload).hexdigest() == item["sha256"] and len(payload) == item["bytes"]
        relative = Path(item["repository_path"])
        if relative.is_relative_to(work):
            target = before / "work" / relative.relative_to(work)
        elif relative.as_posix() == case["manifest_path"]:
            target = before / "manifest-before.json"
        else:
            assert relative.as_posix() == case["profile_path"]
            target = before / "profile-before.json"
        _io_path(target).parent.mkdir(parents=True, exist_ok=True)
        _io_path(target).write_bytes(payload)
    return current_npnf_work_install_context(input_root, destination,
        receipt_path=Path(case["original_receipt"]), receipt_sha256=case["original_receipt_sha256"],
        preserved_before=before.resolve(strict=True), runtime_fields=case["runtime_fields"],
        npnf113_aggregate=case["npnf113_aggregate"])


@contextmanager
def current_npnf_generation_is_preserved(input_root, work_id):
    case = _case(input_root, work_id)
    receipt = Path(case["original_receipt"])
    raw = receipt.read_bytes()
    assert sha256(raw).hexdigest() == case["original_receipt_sha256"]
    original = json.loads(raw)
    work = Path("library/works") / work_id
    before = _files(input_root / work)
    sidecars = {key: _io_path(input_root / case[key]).read_bytes() for key in ("manifest_path", "profile_path")}
    try:
        yield
    finally:
        assert _files(input_root / work) == before
        assert receipt.read_bytes() == raw
        assert _files(Path(original["stage_root"]) / work) == original["after"]
        for key, payload in sidecars.items():
            assert _io_path(input_root / case[key]).read_bytes() == payload


def current_generation_receipt(input_root, destination, work_id):
    case = _case(input_root, work_id)
    raw = Path(case["original_receipt"]).read_bytes()
    assert sha256(raw).hexdigest() == case["original_receipt_sha256"]
    original = json.loads(raw)
    current = dict(original, canonical_root=input_root.as_posix())
    restored = dict(current, canonical_root=original["canonical_root"])
    assert restored == original
    destination.write_bytes((json.dumps(current, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
    return destination


def historical_child_manifest(input_root, manifest, destination):
    """Verify held child boundaries with their exact pre-corpus sidecars."""
    from ocd_kernel.reconstruction import SourceManifest
    from tests.vendored_schema_mirrors import copy_vendored_schema_imports
    binding = json.loads(manifest.authority_path("work-binding").read_bytes())
    work_id = binding["work_id"]
    assert work_id in {"chrysostom-letters-to-olympias", "chrysostom-correspondence-with-rome"}
    case = _case(input_root, work_id)
    original = manifest.path.read_bytes()
    payloads = {Path(row["path"]): manifest.authority_path(row["name"]).read_bytes()
                for row in manifest.record["authorities"]}
    for key in ("converter", "validator"):
        row = manifest.record[key]
        payload = (input_root / row["implementation_path"]).read_bytes()
        assert sha256(payload).hexdigest() == row["implementation_sha256"]
        payloads[Path(row["implementation_path"])] = payload
    payloads[manifest.path.relative_to(input_root)] = original
    for label in ("work", "acquisition"):
        relative = binding[label + "_path"]
        matched = [row for row in case["preserved_before"] if row["repository_path"] == relative]
        assert len(matched) == 1
        row = matched[0]
        payload = (input_root / row["fixture"]).read_bytes()
        assert len(payload) == row["bytes"]
        assert sha256(payload).hexdigest() == row["sha256"] == binding[label + "_sha256"]
        payloads[Path(relative)] = payload
    for relative, payload in payloads.items():
        assert not relative.is_absolute() and ".." not in relative.parts
        target = _io_path(destination / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    copy_vendored_schema_imports(input_root, destination)
    result = SourceManifest.load(destination / manifest.path.relative_to(input_root), repository_root=destination)
    assert result.sha256 == manifest.sha256 and result.record == manifest.record
    assert manifest.path.read_bytes() == original
    return result
