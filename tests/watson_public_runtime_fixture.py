"""Current installed Watson acceptance mirrors with real source-bound reconstruction."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from build.tools.reconstruct_candidate import _bound_callable
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei import acceptance as public
from ocd_kernel.tei.install_accepted import _io_path

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "watson-divine-contentment": {"prefix": "DIVINE_CONTENTMENT"},
    "watson-beatitudes": {"prefix": "BEATITUDES_ACCEPTANCE"},
}


def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def current_installed_acceptance(route, destination, patch):
    work_id = route.WORK.name
    case = CASES[work_id]
    prefix = case["prefix"]
    historical_prefix = "DIVINE_CONTENTMENT_HISTORICAL" if work_id == "watson-divine-contentment" else "BEATITUDES_HISTORICAL"
    current_manifest_path = getattr(public, prefix + "_MANIFEST")
    original_manifest_sha = getattr(public, prefix + "_MANIFEST_SHA")
    evidence = getattr(public, prefix + "_EVIDENCE")
    original_package_sha = getattr(public, prefix + "_PACKAGE_SHA")
    # Replay the installed proof with its exact declared implementation bytes.
    # Mirror those exact declared records; historical reconstruction tests use their
    # separate held-work fixtures without replacing this installed proof.
    runtime_path = ROOT / current_manifest_path
    runtime_raw = runtime_path.read_bytes()
    assert sha256(runtime_raw).hexdigest() == original_manifest_sha
    original_raw = runtime_raw
    current_record = json.loads(runtime_raw)
    retained = CandidatePackage.load(ROOT / evidence)
    assert retained.sha256 == original_package_sha
    assert retained.manifest["source_manifest"]["sha256"] == original_manifest_sha
    destination.mkdir()
    copied = {}

    def put(relative, expected_sha=None):
        relative = Path(relative)
        assert not relative.is_absolute() and ".." not in relative.parts
        target = destination / relative
        if target.exists() and expected_sha is None:
            return target.read_bytes()
        raw = _io_path(resolve_repo_path(ROOT, relative.as_posix())).read_bytes()
        if relative.as_posix() == "ocd_kernel/library/acquisitions.py" and expected_sha == "281ae80f19c1b0021d7e05b20dcd3f5eef4a6e29c1bea58f62cd094bbd60d08d":
            raw = (ROOT / "tests/fixtures/reconstruction-runtime/authorities/watson-installed-acquisitions.py.bin").read_bytes()
            assert sha256(raw).hexdigest() == expected_sha
        if expected_sha and sha256(raw).hexdigest() != expected_sha:
            # Only a complete bound historical metadata preimage can select an EOL variant.
            assert relative.parts[0] not in {"raw", "reports", "exports"} and relative.suffix != ".py"
            lf = raw.replace(b"\r\n", b"\n")
            matches = [b for b in (lf, lf.replace(b"\n", b"\r\n")) if sha256(b).hexdigest() == expected_sha]
            assert matches, relative
            raw = matches[0]
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            assert target.read_bytes() == raw, relative
        else:
            target.write_bytes(raw)
        copied[relative.as_posix()] = raw
        return raw

    # Public acceptance and every schema-bound technical/review/source file stay exact.
    accepted_path = route.EDITION / "acceptance.json"
    original_acceptance_raw = (ROOT / accepted_path).read_bytes()
    supplement_path = Path("sources/structured-text") / work_id / "runtime-supplement-20261025-main.json"
    pinned_supplement = put(supplement_path, public.RUNTIME_SUPPLEMENTS[work_id])
    assert sha256(pinned_supplement).hexdigest() == public.RUNTIME_SUPPLEMENTS[work_id]
    supplement = json.loads(pinned_supplement)
    assert supplement["acceptance"]["path"] == accepted_path.as_posix()
    accepted_raw = put(accepted_path, supplement["acceptance"]["sha256"])
    accepted = json.loads(accepted_raw)
    put(route.WORK / "work.json")
    state_raw = put(route.WORK / "state.json")
    def bound_references(value):
        if isinstance(value, dict):
            if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
                put(value["path"], value["sha256"])
            for child in value.values():
                bound_references(child)
        elif isinstance(value, list):
            for child in value:
                bound_references(child)
    bound_references(accepted)
    supplement_path = Path("sources/structured-text") / work_id / "runtime-supplement-20261025-main.json"
    supplement_raw = put(supplement_path, public.RUNTIME_SUPPLEMENTS[work_id])
    supplement = json.loads(supplement_raw)
    assert supplement["work_id"] == work_id
    bound_references(supplement)
    for row in current_record["authorities"]:
        put(row["path"], row["sha256"])
    for target in json.loads(state_raw)["targets"]:
        for relative in target.get("evidence", []):
            put(relative)
    for relative in (route.HISTORICAL_MANIFEST, route.CURRENT_MANIFEST, route.EVIDENCE / "candidate.tei.xml"):
        put(relative)
    # Historical private package/validation/acceptance and CVW receipts retain their full fixed hashes.
    for suffix in ("EVIDENCE", "VALIDATION", "ACCEPTANCE"):
        relative = getattr(public, historical_prefix + "_" + suffix)
        if suffix == "EVIDENCE":
            package = CandidatePackage.load(ROOT / relative)
            assert package.sha256 == getattr(public, historical_prefix + "_PACKAGE_SHA")
            for name in package.member_names:
                put(Path(relative) / name)
        else:
            put(relative, getattr(public, historical_prefix + "_" + suffix + "_SHA"))
    if work_id == "watson-divine-contentment":
        cvw = route.HISTORICAL_EVIDENCE / "inputs/cvw/session-receipt.json"
        put(cvw, public.DIVINE_CONTENTMENT_HISTORICAL_CVW_SHA)
        put(public.DIVINE_CONTENTMENT_HISTORICAL_MANIFEST, public.DIVINE_CONTENTMENT_HISTORICAL_MANIFEST_SHA)
    else:
        # The exact original8598 is retained separately from the newer live5011 authority.
        historical = (ROOT / "tests/fixtures/reconstruction-runtime/authorities/watson-beatitudes-original-source-manifest.json").read_bytes()
        assert sha256(historical).hexdigest() == public.BEATITUDES_HISTORICAL_MANIFEST_SHA
        for relative in (route.HISTORICAL_MANIFEST, public.BEATITUDES_HISTORICAL_MANIFEST):
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(historical)
    schema_relative = public.SCHEMA_PATH.relative_to(ROOT)
    put(schema_relative)
    for relative in ("ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd", "ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd"):
        put(relative)
    for role in ("converter", "validator"):
        row = current_record[role]
        put(row["implementation_path"], row["implementation_sha256"])
    # Only the named current-runtime authority changes in the private mirror.
    manifest_path = destination / current_manifest_path
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(runtime_raw)
    manifest = SourceManifest.load(manifest_path, repository_root=destination)
    fresh = destination.parent / (destination.name + "-source-candidate")
    result = subprocess.run(
        [sys.executable, "-m", "build.tools.reconstruct_candidate", "--repository-root", str(destination),
         "--manifest", current_manifest_path, "--destination", str(fresh)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "pass"
    package = CandidatePackage.load(fresh / "package")
    assert package.member_names == retained.member_names
    for name in package.member_names:
        if name != "manifest.json":
            assert package.member_bytes(name) == retained.member_bytes(name), name
    expected_package = json.loads(retained.member_bytes("manifest.json"))
    expected_package["source_manifest"]["sha256"] = manifest.sha256
    assert json.loads(package.member_bytes("manifest.json")) == expected_package
    oracle = _bound_callable(destination, manifest.record["validator"], role="validator")
    report = validate(manifest, package, oracle)
    assert report.status == "pass" and not report.findings
    for name in package.member_names:
        target = destination / evidence / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(package.member_bytes(name))
    patch.setattr(public, "SCHEMA_PATH", destination / schema_relative)
    patch.setattr(public, prefix + "_MANIFEST_SHA", manifest.sha256)
    patch.setattr(public, prefix + "_PACKAGE_SHA", package.sha256)
    if work_id == "watson-divine-contentment":
        from build.tei import watson_divine_contentment_oracle as module
        patch.setattr(module, "_oracle", oracle)
        validation_path = destination / Path(evidence).parent / "validation.json"
        assert sha256(validation_path.read_bytes()).hexdigest() == public.DIVINE_CONTENTMENT_VALIDATION_SHA
        patch.setattr(public, "DIVINE_CONTENTMENT_VALIDATION_SHA", sha256(validation_path.read_bytes()).hexdigest())
    acceptance = destination / accepted_path
    assert acceptance.read_bytes() == accepted_raw
    # Ensure no source, master, acceptance, or historical evidence was changed in the real repository.
    assert (ROOT / current_manifest_path).read_bytes() == original_raw
    assert (ROOT / accepted_path).read_bytes() == original_acceptance_raw
    assert (ROOT / runtime_path.relative_to(ROOT)).read_bytes() == runtime_raw
    return acceptance
