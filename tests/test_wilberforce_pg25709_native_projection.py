"""Source-bound native projection checks for the retained PG25709 TEI envelope."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from lxml import etree
import pytest

from build.tools import stage_wilberforce_pg25709_acceptance as stage
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header


NS = {"t": "http://www.tei-c.org/ns/1.0"}
IDENTITY = stage.IDENTITY
KW = dict(identity={key: IDENTITY[key] for key in ("work_id", "textual_form_id", "edition_id")},
          language="en", representation_revision="wilberforce-pg25709-test-v1",
          edition_title="Project Gutenberg PG #25709 electronic witness",
          category="prose", _allow_acceptance_metadata=True)


@pytest.fixture(scope="module")
def accepted_bytes() -> bytes:
    original = _io_path(stage.CANDIDATE / "package/content.tei.xml").read_bytes()
    assert sha256(original).hexdigest() == stage.ORIGINAL_TEI_SHA
    acquisition = json.loads(_io_path(stage.ROOT / stage.ACQUISITION).read_bytes())
    source = _io_path(stage.ROOT / stage.SOURCE).read_bytes()
    assert sha256(source).hexdigest() == stage.SOURCE_SHA
    declared = acquisition["retained_files"][0]["scope"]
    return bind_reviewed_header(
        original, expected_sha256=stage.ORIGINAL_TEI_SHA, identity=IDENTITY,
        source=dict(source_path=stage.SOURCE.as_posix(), source_sha256=stage.SOURCE_SHA,
                    source_bytes=len(source), source_scope=declared),
        source_url=acquisition["url"], declared_scope=declared,
        revision=dict(id=KW["representation_revision"], date="2026-09-27",
                      note="Test-only accepted-header binding for exact PG25709 source."),
    )


@pytest.fixture(scope="module")
def baseline(accepted_bytes: bytes, tmp_path_factory: pytest.TempPathFactory) -> tuple[list, dict]:
    path = tmp_path_factory.mktemp("wilberforce-native") / "master.tei.xml"
    path.write_bytes(accepted_bytes)
    projected = project_document(path, **KW)
    assert len(projected["rows"]) == 1
    assert verify_document(path, projected["rows"], projected["receipt"], **KW) == []
    assert projected["receipt"]["master_sha256"] == sha256(accepted_bytes).hexdigest()
    return projected["rows"], projected["receipt"]


@pytest.mark.parametrize("carrier,attribute,value", [
    ("group", "type", "changed"),
    ("space", "quantity", "2"),
    ("head", "subtype", "3"),
])
def test_source_carrier_mutations_fail_both_projection_paths(
    accepted_bytes: bytes, baseline: tuple[list, dict], tmp_path: Path,
    carrier: str, attribute: str, value: str,
) -> None:
    tree = etree.fromstring(accepted_bytes)
    if carrier == "head":
        nodes = tree.xpath("//t:body//t:head[@type='source-located-heading']", namespaces=NS)
    else:
        nodes = tree.xpath(f"//t:{carrier}", namespaces=NS)
    assert nodes
    nodes[0].set(attribute, value)
    path = tmp_path / "mutated.tei.xml"
    path.write_bytes(etree.tostring(tree, encoding="utf-8"))
    with pytest.raises(PipelineError):
        project_document(path, **KW)
    rows, receipt = baseline
    assert verify_document(path, rows, receipt, **KW)
