"""Arnulf's CVW package must reproduce the accepted source-derived TEI."""

from copy import deepcopy
import json
import pytest
from hashlib import sha256
from pathlib import Path

from build.tei.arnulf_bsb830_cvw_oracle import _oracle
from build.tei.arnulf_bsb830_cvw_reconstruction import _convert
from ocd_kernel.reconstruction import SourceManifest, reconstruct, validate
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[1]
WORK_ID = "arnulf-of-sees-invective-to-geoffrey-of-chartres"
ORIGINAL_MANIFEST = ROOT / "sources" / "openmgh-exclusive" / WORK_ID / "source-manifest.json"
MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/arnulf-bsb830-current-cvw.source-manifest.json"
MASTER = ROOT / "library" / "works" / WORK_ID / "forms" / (
    WORK_ID + "-openmgh-retained"
) / "editions" / (WORK_ID + "-openmgh-electronic") / "master.tei.xml"


def test_runner_contract_reproduces_accepted_arnulf_from_retained_source(tmp_path: Path) -> None:
    source_manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate = reconstruct(source_manifest, tmp_path / "package", _convert)
    report = validate(source_manifest, candidate, _oracle)

    accepted = Path(_io_path(MASTER)).read_bytes()
    assert candidate.member_bytes("content.tei.xml") == accepted
    assert sha256(accepted).hexdigest() == "ea0a68291595046132841824ceb0589a8307b4321117d86d5f143627822636f4"
    assert report.status == "pass"
    assert report.findings == ()


def test_runtime_arnulf_manifest_preserves_complete_original_and_actual_current_closure():
    from build.tei import arnulf_bsb830_cvw_oracle as current_oracle
    original_raw = ORIGINAL_MANIFEST.read_bytes()
    assert sha256(original_raw).hexdigest() == "46c8d408ee0d6d957e22fb8e90a06cf9d843ae92d9d903020293cfa7147e4ad2"
    original = json.loads(original_raw)
    runtime = json.loads(MANIFEST.read_bytes())
    policy_row = next(row for row in original["authorities"] if row["name"] == "validation-policy")
    policy_raw = (ROOT / policy_row["path"]).read_bytes()
    assert len(policy_raw) == policy_row["bytes"] and sha256(policy_raw).hexdigest() == policy_row["sha256"]
    closure = current_oracle._sha(current_oracle._json([
        {"path": path, "sha256": current_oracle._sha((ROOT / path).read_bytes())}
        for path in json.loads(policy_raw)["closure_inputs"]
    ]))
    assert runtime["validator"]["import_closure_sha256"] == closure
    assert closure != original["validator"]["import_closure_sha256"]
    restored = deepcopy(runtime)
    restored["validator"]["import_closure_sha256"] = original["validator"]["import_closure_sha256"]
    assert restored == original
    loaded = SourceManifest.load(MANIFEST, repository_root=ROOT)
    assert loaded.sha256 == sha256(MANIFEST.read_bytes()).hexdigest()
    assert json.loads(json.dumps(loaded.record, default=dict)) == runtime
    assert ORIGINAL_MANIFEST.read_bytes() == original_raw


def test_original_arnulf_closure_is_rejected_by_actual_current_oracle(tmp_path: Path):
    original_raw = ORIGINAL_MANIFEST.read_bytes()
    historical = SourceManifest.load(ORIGINAL_MANIFEST, repository_root=ROOT)
    candidate = reconstruct(historical, tmp_path / "historical-binding-package", _convert)
    accepted = Path(_io_path(MASTER)).read_bytes()
    assert candidate.member_bytes("content.tei.xml") == accepted
    assert sha256(accepted).hexdigest() == "ea0a68291595046132841824ceb0589a8307b4321117d86d5f143627822636f4"
    attestation = _oracle(historical, candidate)
    assert attestation["import_closure_sha256"] == json.loads(MANIFEST.read_bytes())["validator"]["import_closure_sha256"]
    assert attestation["import_closure_sha256"] != historical.record["validator"]["import_closure_sha256"]
    with pytest.raises(ValueError, match="oracle import-closure binding mismatch"):
        validate(historical, candidate, _oracle)
    assert ORIGINAL_MANIFEST.read_bytes() == original_raw


# Exact original SourceManifest work authority; production current work is preserved.
HISTORICAL_ARNULF_WORK = b'{"creators":[{"evidence":["raw/openmgh/bsb00000830/tei/bsb00000830.xml#bsb00000830_00093_16"],"name":"Arnulf of Sees","role":"author"}],"evidence":["raw/openmgh/bsb00000830/tei/bsb00000830.xml#bsb00000830_00093_16","raw/openmgh/bsb00000830/tei/bsb00000830.xml#bsb00000830_00116_9","raw/openmgh/bsb00000830/bsb00000830.zip","raw/openmgh/bsb00000830/acquisition-receipt.json","research/MANIFEST.md#L590"],"schema_version":"2.0","textual_forms":[{"editions":[{"acquisition_ids":["arnulf-of-sees-invective-to-geoffrey-of-chartres-openmgh-acquired"],"category":"prose","containing_source":{"evidence":["raw/openmgh/bsb00000830/acquisition-receipt.json","raw/openmgh/bsb00000830/bsb00000830.zip","raw/openmgh/bsb00000830/tei/bsb00000830.xml#bsb00000830_00093_16","raw/openmgh/bsb00000830/tei/bsb00000830.xml#bsb00000830_00116_9"],"locator":"raw/openmgh/bsb00000830/tei/bsb00000830.xml#bsb00000830_00093_16; raw/openmgh/bsb00000830/tei/bsb00000830.xml#bsb00000830_00116_9","title":"Libelli de lite imperatorum et pontificum (MGH Ldl 3)"},"edition_id":"arnulf-of-sees-invective-to-geoffrey-of-chartres-openmgh-electronic","language":"la","title":"Retained openMGH electronic witness in Libelli de lite imperatorum et pontificum (MGH Ldl 3)"}],"textual_form_id":"arnulf-of-sees-invective-to-geoffrey-of-chartres-openmgh-retained"}],"title":"Arnulf of Sees, Invective against Girard of Angouleme","work_id":"arnulf-of-sees-invective-to-geoffrey-of-chartres"}\n'

@pytest.fixture(scope="module", autouse=True)
def private_historical_arnulf_context(tmp_path_factory):
    import importlib.util
    from tests.vendored_schema_mirrors import copy_vendored_schema_imports
    from build.tei import arnulf_bsb830_cvw_oracle as current_oracle

    code_root = Path(__file__).resolve().parents[1]
    original_logical = Path("sources/openmgh-exclusive/arnulf-of-sees-invective-to-geoffrey-of-chartres/source-manifest.json")
    runtime_logical = Path("tests/fixtures/reconstruction-runtime/arnulf-bsb830-current-cvw.source-manifest.json")
    original_raw = (code_root / original_logical).read_bytes()
    assert sha256(original_raw).hexdigest() == "46c8d408ee0d6d957e22fb8e90a06cf9d843ae92d9d903020293cfa7147e4ad2"
    original = json.loads(original_raw)
    runtime_raw = (code_root / runtime_logical).read_bytes()
    assert sha256(runtime_raw).hexdigest() == "158992d1cb3c9d769af2bcd9440c157a6ebbf59f589dba96573f62b7a03b956c"
    baseline = json.loads(runtime_raw)
    restored = deepcopy(baseline)
    restored["validator"]["import_closure_sha256"] = original["validator"]["import_closure_sha256"]
    assert restored == original
    work_logical = Path("library/works/arnulf-of-sees-invective-to-geoffrey-of-chartres/work.json")
    current_work_raw = (code_root / work_logical).read_bytes()
    assert len(HISTORICAL_ARNULF_WORK) == 1449
    assert sha256(HISTORICAL_ARNULF_WORK).hexdigest() == "234930fd7264559752f3ba5d155f1c4bd51771e0766b2b9edea81fc764c88204"
    mirror = tmp_path_factory.mktemp("arnulf-historical")
    payloads = {}
    for authority in original["authorities"]:
        relative = Path(authority["path"])
        assert not relative.is_absolute() and ".." not in relative.parts
        payload = HISTORICAL_ARNULF_WORK if authority["name"] == "work-sidecar" else (code_root / relative).read_bytes()
        if authority["name"] == "work-sidecar":
            assert relative == work_logical
        assert len(payload) == authority["bytes"]
        assert sha256(payload).hexdigest() == authority["sha256"], relative
        payloads[relative] = payload
    for key in ("converter", "validator"):
        row = original[key]
        relative = Path(row["implementation_path"])
        payload = (code_root / relative).read_bytes()
        assert sha256(payload).hexdigest() == row["implementation_sha256"]
        payloads[relative] = payload
    profile_row = next(row for row in original["authorities"] if row["name"] == "reconstruction-profile")
    profile = json.loads(payloads[Path(profile_row["path"])])
    master_logical = Path(profile["accepted_master_path"])
    accepted = (code_root / master_logical).read_bytes()
    assert sha256(accepted).hexdigest() == profile["accepted_master_sha256"] == "ea0a68291595046132841824ceb0589a8307b4321117d86d5f143627822636f4"
    payloads[master_logical] = accepted
    policy_row = next(row for row in original["authorities"] if row["name"] == "validation-policy")
    policy = json.loads(payloads[Path(policy_row["path"])])
    closure_entries = []
    for name in policy["closure_inputs"]:
        relative = Path(name)
        assert not relative.is_absolute() and ".." not in relative.parts
        payload = (code_root / relative).read_bytes()
        if relative in payloads:
            assert payloads[relative] == payload
        payloads[relative] = payload
        closure_entries.append({"path": name, "sha256": current_oracle._sha(payload)})
    private_runtime = deepcopy(baseline)
    private_runtime["validator"]["import_closure_sha256"] = current_oracle._sha(current_oracle._json(closure_entries))
    inverse = deepcopy(private_runtime)
    inverse["validator"]["import_closure_sha256"] = baseline["validator"]["import_closure_sha256"]
    assert inverse == baseline
    payloads[original_logical] = original_raw
    payloads[runtime_logical] = current_oracle._json(private_runtime)
    for relative, payload in payloads.items():
        target = mirror / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        assert target.read_bytes() == payload
    copy_vendored_schema_imports(code_root, mirror)

    def load(row, label):
        path = mirror / row["implementation_path"]
        spec = importlib.util.spec_from_file_location(label, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert sha256(path.read_bytes()).hexdigest() == row["implementation_sha256"]
        return module

    producer = load(private_runtime["converter"], "arnulf_private_current_producer")
    oracle = load(private_runtime["validator"], "arnulf_private_current_oracle")
    loaded = SourceManifest.load(mirror / runtime_logical, repository_root=mirror)
    assert loaded.sha256 == sha256((mirror / runtime_logical).read_bytes()).hexdigest()
    assert json.loads(json.dumps(loaded.record, default=dict)) == private_runtime
    with pytest.MonkeyPatch.context() as patch:
        for name, value in {
            "ROOT": mirror, "ORIGINAL_MANIFEST": mirror / original_logical,
            "MANIFEST": mirror / runtime_logical, "MASTER": mirror / master_logical,
            "_convert": producer._convert, "_oracle": oracle._oracle,
        }.items():
            patch.setitem(globals(), name, value)
        yield
    assert (code_root / work_logical).read_bytes() == current_work_raw
    assert (code_root / original_logical).read_bytes() == original_raw
    assert (code_root / runtime_logical).read_bytes() == runtime_raw
    assert (code_root / master_logical).read_bytes() == accepted
