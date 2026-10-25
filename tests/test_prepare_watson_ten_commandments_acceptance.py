"""Focused Watson v2 acceptance seam without staging or promotion."""

import hashlib
import json
from pathlib import Path

from lxml import etree
import pytest

from build.tools import prepare_watson_ten_commandments_acceptance as helper
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei import acceptance as acceptance_module


@pytest.fixture
def historical_root(tmp_path: Path):
    root = tmp_path / "watson-v2-original-input"
    root.mkdir()
    (root / ".ocd-storage.json").write_bytes((helper.ROOT / ".ocd-storage.json").read_bytes())
    original = helper.ROOT / "tests/fixtures/reconstruction-runtime/authorities/watson-ten-commandments-acceptance-v2.source-manifest.json"
    assert hashlib.sha256(original.read_bytes()).hexdigest() == helper.MANIFEST_SHA
    for relative in (helper.MANIFEST, helper.ACQUISITION, helper.RECEIPT, helper.TICKET, helper.REPORT):
        source = original if relative == helper.MANIFEST else helper.ROOT / relative
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    return root


def test_current_successor_manifest_rejects_old_v2_handoff():
    with pytest.raises(PipelineError, match="Watson evidence SHA-256 mismatch"):
        helper._preflight(helper.ROOT)


def _acquisition() -> dict:
    return json.loads((helper.ROOT / helper.ACQUISITION).read_bytes())


def _work() -> dict:
    return json.loads((helper.ROOT / helper.WORK / "work.json").read_bytes())


def test_exact_v2_handoff_inputs_are_bound(historical_root):
    receipt, acquisition, files, source = helper._preflight(historical_root)
    assert receipt["current_binding"]["candidate_manifest_sha256"] == helper.PACKAGE_SHA
    assert acquisition["acquisition_id"] == helper.IDENTITY["acquisition_id"]
    assert hashlib.sha256(source).hexdigest() == helper.SOURCE_SHA
    assert set(helper.FRAMES) == {"tenth-commandment-h3", "law-sin-h3"}
    assert all(f"cvw/{name}/frame.png" in files for name in helper.FRAMES)
    assert "cvw/tenth-commandment-h3/capture.json" in files
    assert hashlib.sha256(files["source-manifest.json"]).hexdigest() == helper.MANIFEST_SHA


def test_exact_v2_route_passes_and_duplicate_heading_fails(tmp_path):
    content = helper.CANDIDATE / "package/content.tei.xml"
    acceptance_module._check_selected_thml_for_acceptance(
        helper.ROOT, _acquisition(), _work(), content, helper.IDENTITY
    )

    tree = etree.parse(str(content))
    division = tree.xpath(
        "//*[@xml:id='src-2195']",
        namespaces={"xml": "http://www.w3.org/XML/1998/namespace"},
    )[0]
    duplicate = etree.Element("{http://www.tei-c.org/ns/1.0}head")
    duplicate.text = "2.10 The Tenth Commandment"
    division.insert(0, duplicate)
    mutated = tmp_path / "watson-duplicate.tei.xml"
    mutated.write_bytes(etree.tostring(tree, encoding="utf-8", xml_declaration=True))
    with pytest.raises(PipelineError, match="navigation title is duplicated"):
        acceptance_module._check_selected_thml_for_acceptance(
            helper.ROOT, _acquisition(), _work(), mutated, helper.IDENTITY
        )


def test_changed_v2_source_heading_is_rejected(tmp_path):
    content = helper.CANDIDATE / "package/content.tei.xml"
    tree = etree.parse(str(content))
    heading = tree.xpath(
        "//*[@xml:id='src-2196']",
        namespaces={"xml": "http://www.w3.org/XML/1998/namespace"},
    )[0]
    heading.text = "Changed Tenth Commandment"
    mutated = tmp_path / "watson-changed-heading.tei.xml"
    mutated.write_bytes(etree.tostring(tree, encoding="utf-8", xml_declaration=True))
    with pytest.raises(PipelineError, match="selected ThML text or tail differs"):
        acceptance_module._check_selected_thml_for_acceptance(
            helper.ROOT, _acquisition(), _work(), mutated, helper.IDENTITY
        )

def test_watson_route_misbinding_fails_closed():
    acquisition = _acquisition()
    acquisition["source_selection"]["selection_id"] = "untrusted-route"
    with pytest.raises(PipelineError, match="exact acquisition binding"):
        acceptance_module._check_selected_thml_for_acceptance(
            helper.ROOT, acquisition, _work(),
            helper.CANDIDATE / "package/content.tei.xml", helper.IDENTITY
        )


def test_watson_cannot_skip_checker_by_dropping_selection():
    acquisition = _acquisition()
    acquisition.pop("source_selection")
    with pytest.raises(PipelineError, match="exact acquisition binding"):
        acceptance_module._validate_tei(
            {}, helper.ROOT, helper.CANDIDATE / "package/content.tei.xml",
            helper.IDENTITY, acquisition,
        )

def test_other_selected_thml_routes_keep_generic_checker(monkeypatch, tmp_path):
    calls = []
    from ocd_kernel.tei import selected_thml_check

    def generic(root, acquisition, work, candidate):
        calls.append((root, acquisition, work, candidate))

    monkeypatch.setattr(selected_thml_check, "check_selected_thml", generic)
    identity = {"work_id": "other-work"}
    acquisition = {"source_selection": {"selection_id": "other-selection"}}
    work = {"work_id": "other-work"}
    candidate = tmp_path / "other.tei.xml"
    acceptance_module._check_selected_thml_for_acceptance(
        helper.ROOT, acquisition, work, candidate, identity
    )
    assert calls == [(helper.ROOT, acquisition, work, candidate)]
