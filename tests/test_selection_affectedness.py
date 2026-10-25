"""Bounded reporting uses real candidate bindings and verified retained sources."""

import hashlib

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.selection_affectedness import report_selection_affectedness
from tests.test_wu03_collection_fixture import _accounting
from tests.test_wu03_collection_fixture import shared_collection as _shared_collection

shared_collection = _shared_collection


def _report(fixture, outputs=None):
    root, children, _ = fixture
    if outputs is None:
        outputs = {name: [child["package"].path / "content.tei.xml"]
                   for name, child in children.items()}
    return report_selection_affectedness(
        root=root, children=list(children.values()),
        carrier_accounting=_accounting(), outputs=outputs,
    )


def test_shared_context_counted_once_with_both_relationships(shared_collection):
    report = _report(shared_collection)
    assert len(report["coverage"]) == 5
    assert [row["position"] for row in report["coverage"]] == list(range(5))
    assert len(report["shared_dependencies"]) == 1
    assert report["shared_dependencies"][0]["dependents"] == [
        {"work_id": "child-a", "purpose": "source-credit"},
        {"work_id": "child-b", "purpose": "source-credit"},
    ]
    assert [row["status"] for row in report["outputs"]] == ["binding-current"] * 2
    assert all(row["requires_check"] for row in report["outputs"])


@pytest.mark.parametrize("old,new", [(b"Alpha.", b"Revised alpha."),
                                     (b"Shared context.", b"Revised context.")])
def test_correction_invalidates_all_whole_member_bindings(shared_collection, old, new):
    root, children, member = shared_collection
    previous = {name: child["package"].member_bytes("content.tei.xml")
                for name, child in children.items()}
    source = root / member["path"]
    raw = source.read_bytes().replace(old, new)
    source.write_bytes(raw)
    member.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    for child in children.values():
        acquisition = child["acquisition"]
        acquisition.update(source_bytes=len(raw), source_sha256=member["sha256"])
        if old == b"Shared context.":
            acquisition["source_selection"]["dependencies"][0]["text_sha256"] = hashlib.sha256(new).hexdigest()
    report = _report(shared_collection)
    assert [row["status"] for row in report["outputs"]] == ["stale"] * 2
    assert all("source_sha256 differs" in row["reasons"] for row in report["outputs"])
    for name, child in children.items():
        assert child["package"].member_bytes("content.tei.xml") == previous[name]


def test_missing_outputs_preserve_unknowns(shared_collection, tmp_path):
    report = _report(shared_collection, {"child-a": [tmp_path / "missing.xml"]})
    assert [row["status"] for row in report["outputs"]] == ["unknown"] * 2
    assert [row["reasons"] for row in report["outputs"]] == [["output missing"], ["no supplied output"]]


@pytest.mark.parametrize("payload", [b"bad XML", b"<TEI/>"])
def test_invalid_or_unbound_output_is_unknown(shared_collection, tmp_path, payload):
    path = tmp_path / "unbound.xml"
    path.write_bytes(payload)
    report = _report(shared_collection, {"child-a": [path]})
    assert report["outputs"][0]["status"] == "unknown"
    assert report["outputs"][0]["requires_check"]


def test_unknown_work_rejected(shared_collection):
    with pytest.raises(PipelineError, match="outside bounded"):
        _report(shared_collection, {"unknown": []})


def test_stale_source_declaration_fails_closed(shared_collection):
    root, _, member = shared_collection
    (root / member["path"]).write_bytes(b"changed")
    with pytest.raises(PipelineError, match="retained member binding differs"):
        _report(shared_collection)


def test_duplicate_output_rejected(shared_collection):
    _, children, _ = shared_collection
    path = children["child-a"]["package"].path / "content.tei.xml"
    with pytest.raises(PipelineError, match="duplicate output"):
        _report(shared_collection, {"child-a": [path, path]})


def test_empty_duplicate_binding_is_unknown(shared_collection, tmp_path):
    _, children, _ = shared_collection
    raw = children["child-a"]["package"].member_bytes("content.tei.xml")
    raw = raw.replace(b'</bibl>', b'<idno type="work_id"/></bibl>')
    path = tmp_path / "duplicate.xml"
    path.write_bytes(raw)
    report = _report(shared_collection, {"child-a": [path]})
    assert report["outputs"][0]["status"] == "unknown"
    assert "missing or ambiguous work_id" in report["outputs"][0]["reasons"]


def test_wrong_work_binding_is_stale(shared_collection):
    _, children, _ = shared_collection
    path = children["child-b"]["package"].path / "content.tei.xml"
    report = _report(shared_collection, {"child-a": [path]})
    assert report["outputs"][0]["status"] == "stale"
    assert "work_id differs" in report["outputs"][0]["reasons"]
