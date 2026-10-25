"""Focused source-carrier and frozen-stage guards for Strong PG44035."""

from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from lxml import etree
import pytest

from build.tei import strong_vol1_pg44035_native as native
from build.tei import strong_vol1_pg44035_native_oracle as oracle
from build.tools import install_strong_vol1_pg44035 as installer
from ocd_kernel.library._common import PipelineError
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.reconstruction.decision import _load_bound_validator
from ocd_kernel.reconstruction.contract import _runtime_binding
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[1]
RETAINED_MANIFEST = ROOT / "sources/structured-text/strong-systematic-theology-vol-1/strong-systematic-theology-vol-1.source-manifest.json"
RUNTIME_MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/strong-vol1.source-manifest.json"
RUNTIME_PROFILE = ROOT / "tests/fixtures/reconstruction-runtime/strong-vol1.reconstruction-profile.json"
RETAINED_PROFILE = ROOT / "sources/structured-text/strong-systematic-theology-vol-1/strong-systematic-theology-vol-1.reconstruction-profile.json"


def test_runtime_copy_preserves_complete_original_strong_records():
    raw = RETAINED_MANIFEST.read_bytes()
    assert sha256(raw).hexdigest() == "1ddc4949c28010e98f4a936e2285c04d92f372aa0c6cf5720ed593aeb2367654"
    original_profile = RETAINED_PROFILE.read_bytes()
    assert sha256(original_profile).hexdigest() == "b8c7c276c2f67945042050c0d12aa8c6bcea2dc60d11db3b59fb61bf73b1a30a"
    expected = json.loads(raw)
    source = SourceManifest.load(RUNTIME_MANIFEST, repository_root=ROOT)
    reader = _load_bound_validator(source)
    namespace = reader.__globals__
    policy = json.loads(source.authority_path("validation-policy").read_bytes())
    closure = namespace["_import_closure"]
    stable = namespace["_stable_json"]
    producer = closure(ROOT, ROOT / expected["converter"]["implementation_path"],
                       tuple(policy["producer_forbidden_import_prefixes"]))
    validator = closure(ROOT, ROOT / expected["validator"]["implementation_path"],
                        tuple(policy["forbidden_import_prefixes"]))
    profile = json.loads(original_profile)
    profile["producer_import_closure_sha256"] = sha256(stable(producer)).hexdigest()
    profile_bytes = RUNTIME_PROFILE.read_bytes()
    assert json.loads(profile_bytes) == profile
    expected["validator"]["import_closure_sha256"] = sha256(stable(validator)).hexdigest()
    binding = next(b for b in expected["authorities"] if b["name"] == "reconstruction-profile")
    binding.update(path=RUNTIME_PROFILE.relative_to(ROOT).as_posix(),
                   bytes=len(profile_bytes), sha256=sha256(profile_bytes).hexdigest())
    assert json.loads(RUNTIME_MANIFEST.read_bytes()) == expected


@pytest.fixture(scope="module", autouse=True)
def current_source_bound_package(tmp_path_factory):
    retained = CandidatePackage.load(oracle.PACKAGE)
    assert retained.sha256 == "61f708236bf39b25dadb5873f64473dcd676577d522919ad29db3e23084330a8"
    source = SourceManifest.load(RUNTIME_MANIFEST, repository_root=ROOT)
    destination = tmp_path_factory.mktemp("strong-v1-current") / "candidate"
    completed = subprocess.run([
        sys.executable, str(ROOT / "build/tools/reconstruct_candidate.py"),
        "--manifest", RUNTIME_MANIFEST.relative_to(ROOT).as_posix(),
        "--destination", str(destination), "--repository-root", str(ROOT),
    ], cwd=ROOT, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(completed.stdout)["status"] == "pass"
    current = CandidatePackage.load(destination / "package")
    for name in retained.member_names:
        if name not in {"manifest.json", "provenance.json"}:
            assert current.member_bytes(name) == retained.member_bytes(name)
    assert sha256(current.member_bytes("content.tei.xml")).hexdigest() == native.DIRECT_SHA256
    expected = deepcopy(json.loads(retained.member_bytes("provenance.json")))
    namespace = _load_bound_validator(source).__globals__
    policy = json.loads(source.authority_path("validation-policy").read_bytes())
    producer = namespace["_import_closure"](
        ROOT, ROOT / source.record["converter"]["implementation_path"],
        tuple(policy["producer_forbidden_import_prefixes"]))
    expected.update(runtime=_runtime_binding(), source_manifest_sha256=source.sha256, producer_import_closure=list(producer),
                    producer_import_closure_sha256=sha256(namespace["_stable_json"](producer)).hexdigest())
    assert json.loads(current.member_bytes("provenance.json")) == expected
    historical = SourceManifest.load(RETAINED_MANIFEST, repository_root=ROOT)
    with pytest.raises(ValueError, match="Strong provenance, profile, or producer closure drifted"):
        validate(historical, retained, _load_bound_validator(historical))
    assert retained.sha256 == "61f708236bf39b25dadb5873f64473dcd676577d522919ad29db3e23084330a8"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(oracle, "MANIFEST", RUNTIME_MANIFEST)
        patch.setattr(oracle, "PACKAGE", current.path)
        yield


def _roots() -> tuple[etree._Element, etree._Element]:
    direct = native.direct_candidate()
    adapted, counts = native.adapt(direct)
    assert counts == native.EXPECTED
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    return etree.fromstring(direct, parser), etree.fromstring(adapted, parser)


def test_complete_witness_and_master_validate() -> None:
    direct = native.direct_candidate()
    adapted, counts = native.adapt(direct)
    result = oracle.check(adapted)
    assert result["source_oracle_status"] == "pass"
    assert result["carrier_counts"] == counts == native.EXPECTED
    assert validate_file(_io_path(installer.STAGE / installer.EDITION / "master.tei.xml")) == []


@pytest.mark.parametrize(
    ("tag", "original_subtype", "mutated_subtype"),
    [
        ("ab", "title-page-line", "wrong-title-page-line"),
        ("seg", "xml-space-preserve", "wrong-whitespace"),
    ],
)
def test_independent_carrier_check_rejects_mutation(
    tag: str, original_subtype: str, mutated_subtype: str
) -> None:
    before, after = _roots()
    matches = [node for node in after.iter(native.TEI + tag)
               if node.get("subtype") == original_subtype]
    assert matches
    matches[0].set("subtype", mutated_subtype)
    with pytest.raises(ValueError, match="changed source node"):
        oracle._match(before, after, Counter())


def test_direct_digest_and_frozen_receipt_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(native, "DIRECT_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="source-bound TEI differs"):
        native.direct_candidate()
    monkeypatch.setattr(installer, "RECEIPT_SHA256", "0" * 64)
    with pytest.raises(PipelineError, match="frozen stage path or receipt differs"):
        installer.preflight()
