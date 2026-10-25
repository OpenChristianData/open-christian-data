"""Focused full-edition and adversarial checks for Gutenberg eBook 38326."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

from lxml import etree
import pytest

from ocd_kernel.reconstruction.contract import SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "sources/bede-ecclesiastical-history-of-england"
NS = {"t": "http://www.tei-c.org/ns/1.0"}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _ChangedCandidate:
    def __init__(self, baseline, content: bytes):
        self.baseline = baseline
        self.content = content
        self.manifest = baseline.manifest
        self.sha256 = baseline.sha256
        self.account = json.loads(baseline.member_bytes("source-accountability.json"))
        self.account["candidate_sha256"] = hashlib.sha256(content).hexdigest()

    def verify_integrity(self) -> None:
        # The mutation changes only the candidate's TEI and matching accounting
        # hash. The source oracle must reject the altered readable structure.
        pass

    def member_bytes(self, name: str) -> bytes:
        if name == "content.tei.xml":
            return self.content
        if name == "source-accountability.json":
            return (json.dumps(self.account, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        return self.baseline.member_bytes(name)


@pytest.fixture(scope="module")
def route(tmp_path_factory, historical_bede_mirror):
    root = historical_bede_mirror
    base = root / "sources/bede-ecclesiastical-history-of-england"
    original = base / "bede.source-manifest.json"
    original_raw = original.read_bytes()
    retained = json.loads(original_raw)
    producer = _load("bede_producer_test", base / "reconstruct.py")
    checker = _load("bede_checker_test", base / "oracle.py")
    current = json.loads((ROOT / "tests/fixtures/reconstruction-runtime/bede-ecclesiastical-history-of-england-current.source-manifest.json").read_bytes())
    assert current["validator"]["import_closure_sha256"] == checker._closure_digest()
    restored = deepcopy(current)
    restored["validator"]["import_closure_sha256"] = retained["validator"]["import_closure_sha256"]
    assert restored == retained
    runtime_path = base / "bede.current-runtime.source-manifest.json"
    runtime_path.write_bytes((json.dumps(current, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    manifest = SourceManifest.load(runtime_path, repository_root=root)
    candidate = reconstruct(manifest, tmp_path_factory.mktemp("bede38326") / "package", producer._convert)
    assert original.read_bytes() == original_raw
    return manifest, candidate, checker._oracle


def test_complete_bede_candidate_passes_source_oracle(route):
    manifest, candidate, oracle = route
    report = validate(manifest, candidate, oracle)
    assert report.status == "pass"
    assert tuple(report.attestation["findings"]) == ()


def test_bede_oracle_rejects_wording_target_note_and_order_mutations(route):
    manifest, candidate, oracle = route
    original = candidate.member_bytes("content.tei.xml")

    def changed_tree(edit):
        root = etree.fromstring(original)
        edit(root)
        return etree.tostring(root, encoding="UTF-8", xml_declaration=True)

    def omit_note(root):
        note = root.xpath("/t:TEI/t:text/t:back//t:note", namespaces=NS)[0]
        note.getparent().remove(note)

    def move_continuation(root):
        body = root.xpath("/t:TEI/t:text/t:body", namespaces=NS)[0]
        continuation = root.xpath("/t:TEI/t:text/t:body//t:div[@type='continuation']", namespaces=NS)[0]
        body.insert(0, continuation)

    mutations = (
        ("wording", original.replace(b"Britain, an\n          island", b"Britain, a\n          continent", 1), "direct text order"),
        ("wrong valid link target", original.replace(b'target="#toc1"', b'target="#toc3"', 1), "link target"),
        ("omitted footnote", changed_tree(omit_note), "note item attachment"),
        ("moved Continuation", changed_tree(move_continuation), "carrier kind"),
    )
    for label, altered, reason in mutations:
        assert altered != original, label
        with pytest.raises(ValueError, match=reason):
            oracle(manifest, _ChangedCandidate(candidate, altered))


@pytest.fixture(scope="module")
def historical_bede_mirror(tmp_path_factory):
    from tests.vendored_schema_mirrors import copy_vendored_schema_imports
    original_path = BASE / "bede.source-manifest.json"
    original_raw = original_path.read_bytes()
    assert hashlib.sha256(original_raw).hexdigest() == "ea35c36d076d59427747857946c9ee4b0846a8918e24d97a63497aa1399aaa3b"
    record = json.loads(original_raw)
    work_logical = Path("library/works/bede-ecclesiastical-history-of-england/work.json")
    current_work_raw = (ROOT / work_logical).read_bytes()
    held = ROOT / "tests/fixtures/reconstruction-runtime/authorities/bede-original-work.json"
    historical_work_raw = held.read_bytes()
    assert hashlib.sha256(historical_work_raw).hexdigest() == "4989d74995a5a44b1e22055ff7e0a065f12b70da517ff1a92dd2a2e9d40b79f6"
    assert len(historical_work_raw) == 648
    mirror = tmp_path_factory.mktemp("bede-original")
    payloads = {}
    for authority in record["authorities"]:
        relative = Path(authority["path"])
        assert not relative.is_absolute() and ".." not in relative.parts
        if authority["name"] == "work-sidecar":
            assert relative == work_logical
            payload = historical_work_raw
        else:
            payload = (ROOT / relative).read_bytes()
        assert len(payload) == authority["bytes"]
        assert hashlib.sha256(payload).hexdigest() == authority["sha256"], relative
        payloads[relative] = payload
    for key in ("converter", "validator"):
        implementation = record[key]
        relative = Path(implementation["implementation_path"])
        assert not relative.is_absolute() and ".." not in relative.parts
        payload = (ROOT / relative).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == implementation["implementation_sha256"]
        payloads[relative] = payload
    payloads[original_path.relative_to(ROOT)] = original_raw
    for relative, payload in payloads.items():
        target = mirror / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        assert target.read_bytes() == payload
    copy_vendored_schema_imports(ROOT, mirror)
    manifest = SourceManifest.load(mirror / original_path.relative_to(ROOT), repository_root=mirror)
    assert manifest.sha256 == hashlib.sha256(original_raw).hexdigest()
    assert json.loads(json.dumps(manifest.record, default=dict)) == record
    try:
        yield mirror
    finally:
        assert original_path.read_bytes() == original_raw
        assert (ROOT / work_logical).read_bytes() == current_work_raw
        assert held.read_bytes() == historical_work_raw


def test_historical_bede_mirror_preserves_complete_original_record_and_work_authority(historical_bede_mirror):
    original_raw = (BASE / "bede.source-manifest.json").read_bytes()
    manifest_path = historical_bede_mirror / "sources/bede-ecclesiastical-history-of-england/bede.source-manifest.json"
    assert manifest_path.read_bytes() == original_raw
    loaded = SourceManifest.load(manifest_path, repository_root=historical_bede_mirror)
    assert loaded.sha256 == hashlib.sha256(original_raw).hexdigest()
    assert json.loads(json.dumps(loaded.record, default=dict)) == json.loads(original_raw)
    held = (ROOT / "tests/fixtures/reconstruction-runtime/authorities/bede-original-work.json").read_bytes()
    assert len(held) == 648
    assert hashlib.sha256(held).hexdigest() == "4989d74995a5a44b1e22055ff7e0a065f12b70da517ff1a92dd2a2e9d40b79f6"
    assert loaded.authority_path("work-sidecar").read_bytes() == held
    assert "category" not in json.loads(held)["textual_forms"][0]["editions"][0]
