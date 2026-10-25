"""Focused independent NPNF113 child-root source and mutation checks."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tei.npnf113_work_oracle import _oracle
from build.tei import npnf113_work_oracle as oracle_module
from build.tei.npnf113_work_reconstruction import _convert
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "sources/structured-text/chrysostom-npnf113-lib041/work-bindings"
WORK = "chrysostom-commentary-on-galatians"
SOURCE_SHA = "d62c7c82b262c738739090ffaf5473aa5a76dbadf62ebee0dccac8c4a7db4762"
TEI = "{http://www.tei-c.org/ns/1.0}"


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _reseal(path: Path) -> CandidatePackage:
    manifest = json.loads((path / "manifest.json").read_bytes())
    for member in manifest["members"]:
        content = (path / member["name"]).read_bytes()
        member["bytes"] = len(content)
        member["sha256"] = sha256(content).hexdigest()
    (path / "manifest.json").write_bytes(_json(manifest))
    return CandidatePackage.load(path)


def test_ten_child_bindings_are_distinct_and_source_attested() -> None:
    volume = json.loads((ROOT / "sources/structured-text/chrysostom-npnf113-lib041/npnf113-lib041.reconstruction-profile.json").read_bytes())
    expected = {(root_id, work_id) for root_id, work_id in volume["assigned"]}
    observed = set()
    for root_id, work_id in volume["assigned"]:
        manifest = SourceManifest.load(HOME / work_id / "source-manifest.json", repository_root=ROOT)
        binding = json.loads(manifest.authority_path("work-binding").read_bytes())
        observed.add((binding["source_root_id"], binding["work_id"]))
        assert binding["source_root_id"] == root_id
        assert binding["source_sha256"] == SOURCE_SHA
        assert binding["shared_apparatus_ids"] == [f"{binding['source_parent_id']}.i", f"{binding['source_parent_id']}.ii"]
    assert len(observed) == 10
    assert observed == expected


def test_child_source_oracle_rejects_missing_note_and_changed_title(tmp_path: Path, exact_bound_work) -> None:
    manifest = SourceManifest.load(ROOT / "tests/fixtures/reconstruction-runtime/chrysostom-commentary-on-galatians.npnf113.source-manifest.json", repository_root=ROOT)
    package = reconstruct(manifest, tmp_path / "original", _convert)
    report = validate(manifest, package, _oracle)
    assert report.status == "pass" and not report.findings
    for mutation in ("missing-note", "changed-title"):
        altered = tmp_path / mutation
        shutil.copytree(package.path, altered)
        tei_path = altered / "content.tei.xml"
        tree = etree.parse(str(tei_path))
        if mutation == "missing-note":
            notes = tree.findall(f".//{TEI}note")
            assert notes
            notes[0].getparent().remove(notes[0])
        else:
            title = tree.find(f".//{TEI}titleStmt/{TEI}title")
            assert title is not None
            title.text = "Changed title"
        tei_path.write_bytes(etree.tostring(tree, encoding="UTF-8", xml_declaration=True))
        candidate = _reseal(altered)
        with pytest.raises(ValueError):
            _oracle(manifest, candidate)


BOUND_WORK_FIXTURE = Path("tests/fixtures/reconstruction-runtime/authorities/npnf113-galatians-original-bound-work.json")
BOUND_WORK_SHA = "f9f360df47ddeb1bbffb6eb5ae67a821d1e9e3bab80498c2dea7ca6b515cdc45"


@pytest.fixture
def exact_bound_work(tmp_path, monkeypatch):
    """Replay only the exact metadata bytes required by the original source binding."""
    manifest_raw = (ROOT / "tests/fixtures/reconstruction-runtime/chrysostom-commentary-on-galatians.npnf113.source-manifest.json").read_bytes()
    assert sha256(manifest_raw).hexdigest() == "c34f41ba172831ce400860ae12c786509eada4ed2360b154733ebe68d3ab23bd"
    manifest_record = json.loads(manifest_raw)
    row = next(item for item in manifest_record["authorities"] if item["name"] == "work-binding")
    binding_raw = (ROOT / row["path"]).read_bytes()
    assert sha256(binding_raw).hexdigest() == row["sha256"]
    binding = json.loads(binding_raw)
    source_path = ROOT / binding["work_path"]
    current_raw = source_path.read_bytes()
    raw = (ROOT / BOUND_WORK_FIXTURE).read_bytes()
    assert sha256(raw).hexdigest() == binding["work_sha256"] == BOUND_WORK_SHA
    assert sha256((ROOT / binding["acquisition_path"]).read_bytes()).hexdigest() == binding["acquisition_sha256"]
    replay = tmp_path / "original-bound-work.json"
    replay.write_bytes(raw)
    actual_io_path = oracle_module._io_path

    def historical_work_io(path):
        # Every other authority and all producer/oracle code use the real current route.
        return actual_io_path(replay if Path(path) == source_path else path)

    monkeypatch.setattr(oracle_module, "_io_path", historical_work_io)
    yield
    assert source_path.read_bytes() == current_raw
    assert (ROOT / "tests/fixtures/reconstruction-runtime/chrysostom-commentary-on-galatians.npnf113.source-manifest.json").read_bytes() == manifest_raw


def test_original_bound_work_fixture_preserves_complete_record():
    raw = (ROOT / BOUND_WORK_FIXTURE).read_bytes()
    assert sha256(raw).hexdigest() == BOUND_WORK_SHA
    assert json.loads(raw)["work_id"] == WORK
