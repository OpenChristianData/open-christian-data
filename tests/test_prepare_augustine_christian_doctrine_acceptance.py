"""Public acceptance contract for the pinned Augustine On Christian Doctrine route."""

import json
import shutil
from pathlib import Path

from lxml import etree
import pytest

from tests.retained_handoff_runtime_fixture import (
    assert_original_handoff_is_currently_rejected, current_handoff_context,
)

from build.tools import prepare_augustine_christian_doctrine_acceptance as helper
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.acceptance import make_file_binding, validate_acceptance, write_acceptance


NS = {"t": "http://www.tei-c.org/ns/1.0"}


def test_pinned_acceptance_preserves_source_navigation_type_scripture_and_titles(tmp_path, current_handoff):
    stage = Path("\\\\?\\" + str(tmp_path / "stage"))
    try:
        acceptance = helper.prepare(helper.ROOT, stage)
        record = validate_acceptance(acceptance, root=stage)
        assert record["decision"]["agent_assessment"]["status"] == "accepted"
        assert record["promotion"]["status"] == "pending"

        source = etree.fromstring((stage / helper.SOURCE).read_bytes())
        selected = source.find("ThML.body/div1[@id='v']")
        assert selected is not None and selected.get("next") == "v.i"
        assert selected.find("div2[@id='v.iv']").get("type") == "Book"
        assert selected.xpath(".//scripRef[@version]")
        assert selected.get("title") == "On Christian Doctrine"
        assert "On Christian Doctrine" in " ".join("".join(selected.find("p").itertext()).split())

        # The two native v.IV_1 links have no source anchor. This test checks
        # sensitivity to changes in the pinned mapping, not its editorial disposition.
        missing_anchor_links = [
            (node, relation)
            for node in selected.iter()
            for relation in ("prev", "next")
            if node.get(relation) == "v.IV_1"
        ]
        assert len(missing_anchor_links) == 2
        assert not source.xpath("//*[@id='v.IV_1']")

        candidate = stage / helper.WORK / "integration/selected-thml-agent-handoff/candidate.tei.xml"
        master = stage / helper.MASTER
        master_baseline = master.read_bytes()
        assert master_baseline == (helper.ROOT / helper.MASTER).read_bytes()
        assert master != candidate
        baseline = candidate.read_bytes()
        tree = etree.fromstring(baseline)
        selected_tei = tree.xpath("/t:TEI/t:text/t:body/t:div", namespaces=NS)[0]
        assert selected_tei.get("next")
        assert tree.xpath("//t:div[@type='Book']", namespaces=NS)
        assert tree.xpath("//t:ref[@source]", namespaces=NS)
        assert not tree.xpath("//t:head", namespaces=NS)
        pinned_fallback = "https://www.ccel.org/ccel/schaff/npnf102.html#v.IV_1"
        mapped_missing_anchor_links = [
            (node, relation)
            for node in tree.xpath("//t:div", namespaces=NS)
            for relation in ("prev", "next")
            if node.get(relation) == pinned_fallback
        ]
        assert len(mapped_missing_anchor_links) == len(missing_anchor_links)

        mutations = (
            ("navigation", "attribute mapping differs"),
            ("pinned missing-anchor link", "attribute mapping differs"),
            ("division type", "attribute mapping differs"),
            ("scripture source", "attribute mapping differs"),
            ("invented heading", "hierarchy or attachment differs"),
        )
        original_record = json.loads(acceptance.read_text(encoding="utf-8"))
        for change, expected in mutations:
            changed = etree.fromstring(baseline)
            if change == "navigation":
                changed.xpath("/t:TEI/t:text/t:body/t:div", namespaces=NS)[0].set("next", "#src-1")
            elif change == "pinned missing-anchor link":
                changed_links = [
                    (node, relation)
                    for node in changed.xpath("//t:div", namespaces=NS)
                    for relation in ("prev", "next")
                    if node.get(relation) == pinned_fallback
                ]
                assert len(changed_links) == 2
                node, relation = changed_links[0]
                node.set(relation, pinned_fallback + "-changed")
            elif change == "division type":
                changed.xpath("//t:div[@type='Book']", namespaces=NS)[0].set("type", "Invented")
            elif change == "scripture source":
                changed.xpath("//t:ref[@source]", namespaces=NS)[0].set("source", "Invented")
            else:
                root = changed.xpath("/t:TEI/t:text/t:body/t:div", namespaces=NS)[0]
                heading = etree.Element("{http://www.tei-c.org/ns/1.0}head")
                heading.text = selected.get("title")
                root.insert(0, heading)
            mutated = etree.tostring(changed, encoding="utf-8", xml_declaration=True)
            assert mutated != baseline
            candidate.write_bytes(mutated)
            resealed = json.loads(json.dumps(original_record))
            resealed["technical"]["candidate"] = make_file_binding(stage, candidate)
            write_acceptance(acceptance, resealed)
            with pytest.raises(PipelineError, match=expected):
                validate_acceptance(acceptance, root=stage)
            assert master.read_bytes() == master_baseline
        candidate.write_bytes(baseline)
        write_acceptance(acceptance, original_record)
        validate_acceptance(acceptance, root=stage)
    finally:
        if stage.exists():
            shutil.rmtree(stage)




@pytest.fixture
def current_handoff(tmp_path, monkeypatch):
    with current_handoff_context(helper, 'augustine-on-christian-doctrine', tmp_path / "runtime", monkeypatch):
        yield


def test_original_handoff_remains_conserved_and_currently_rejected(tmp_path):
    assert_original_handoff_is_currently_rejected(helper, 'augustine-on-christian-doctrine', tmp_path / "original-stage")
