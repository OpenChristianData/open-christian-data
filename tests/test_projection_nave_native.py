"""Focused closed Nave grammar/reading and saved-output negatives.

Actual retained-candidate tests skip explicitly when source evidence is absent.
Portable grammar tests do not require local library payloads.
"""

from copy import deepcopy
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

from lxml import etree
import pytest

from build.tei import nave_native_projection_proposal as profile
from ocd_kernel.library._common import PipelineError


ROOT = Path(__file__).resolve().parents[1]
NS = profile.NS
CONTEXT = {"identity": profile.IDENTITY, "language": "en", "representation_revision": "nave-retained-native-technical-v1", "edition_title": profile.TITLE}


def test_literal_nested_list_rendering():
    node = ET.fromstring(f'<def xmlns="{NS[1:-1]}"> Lead  <lb/>line\n<list><item>Parent <ref type="osisRef" target="Gen.1.1">1:1</ref><list><item>Child  value</item></list> parent tail</item><item>Next</item></list> End </def>')
    assert profile._render_et(node) == " Lead  \nline\n\n  Parent 1:1\n    Child  value parent tail\n  Next End "


@pytest.mark.parametrize("fragment", [
    '<def unexpected="x">text</def>',
    '<def><p>text</p></def>',
    '<def><lb>text</lb></def>',
    '<def><list><ref target="x">x</ref></list></def>',
    '<def><ref type="scripture" target="Gen.1.1">1</ref></def>',
    '<def><ref target="x"><item>x</item></ref></def>',
    '<def><ref>x</ref></def>',
])
def test_closed_definition_grammar(fragment):
    node = ET.fromstring(fragment.replace('<def', f'<def xmlns="{NS[1:-1]}"', 1))
    with pytest.raises(PipelineError, match="unsupported-visible: Nave"):
        profile._render_et(node)


@pytest.mark.parametrize("field,value", [("work_id", "other"), ("edition_id", "other"), ("textual_form_id", "other")])
def test_profile_identity_is_closed(field, value):
    identity = dict(profile.IDENTITY, **{field: value})
    with pytest.raises(PipelineError, match="exact native identity"):
        profile.project_nave_native(Path("not-read.xml"), **dict(CONTEXT, identity=identity))
    assert profile.verify_nave_native(Path("not-read.xml"), [], {}, **dict(CONTEXT, identity=identity)) == ["unsupported-visible: Nave checker identity/context"]


@pytest.fixture(scope="module")
def retained():
    default = ROOT / "library/works/naves-topical-bible/integration/nave-current-v2/candidate.tei.xml"
    candidate = Path(os.environ.get("OCD_NAVE_CANDIDATE", str(default)))
    saved = Path(os.environ.get("OCD_NAVE_PROJECTION", str(ROOT / "reports/_logs/naves-topical-bible-current-reconciliation-20261002-v1/native-support-proposal-v2/actual-projection.json")))
    if not candidate.is_file() or not saved.is_file():
        pytest.skip("Retained Nave candidate/projection evidence unavailable; configure OCD_NAVE_CANDIDATE/OCD_NAVE_PROJECTION.")
    return candidate.read_bytes(), json.loads(saved.read_bytes())


@pytest.mark.parametrize("kind,expected", [
    ("entry-omission", "complete body"),
    ("source-attribute", "mixed attribute"),
    ("reference-role", "reference"),
    ("foreign-namespace", "namespace"),
    ("header-scope-attribute", "header grammar"),
    ("entry-order", "entry/order"),
])
def test_source_shape_negatives_require_specific_checker_reason(retained, tmp_path, kind, expected):
    raw, saved = retained
    root = etree.fromstring(raw); body = root[1][0]; definition = body[0][1]
    if kind == "entry-omission": body.remove(body[-1])
    elif kind == "source-attribute": definition.set("unexpected", "x")
    elif kind == "reference-role": next(definition.iter(NS + "ref")).set("type", "scripture")
    elif kind == "foreign-namespace": next(definition.iter(NS + "lb")).tag = "{urn:foreign}lb"
    elif kind == "header-scope-attribute": root[0][0].set("unexpected", "x")
    else: body.insert(0, body[1])
    mutated = etree.tostring(root)
    assert mutated != raw
    path = tmp_path / "mutated.xml"; path.write_bytes(mutated)
    with pytest.raises((PipelineError, ET.ParseError)):
        profile.project_nave_native(path, **CONTEXT)
    errors = profile.verify_nave_native(path, saved["rows"], saved["receipt"], **CONTEXT)
    assert len(errors) == 1 and "unsupported-visible: Nave checker" in errors[0] and expected in errors[0], errors


@pytest.mark.parametrize("kind", ["omitted-row", "changed-literal-reference", "duplicate-row"])
def test_saved_output_mutations_fail_with_producer_disabled(retained, tmp_path, monkeypatch, kind):
    raw, saved = retained
    rows = deepcopy(saved["rows"])
    if kind == "omitted-row": rows.pop()
    elif kind == "duplicate-row": rows[-1] = deepcopy(rows[0])
    else: rows[0]["items"][0]["references"][0]["target"] += "-invented"
    assert rows != saved["rows"]
    path = tmp_path / "unchanged-master.xml"; path.write_bytes(raw)
    monkeypatch.setattr(profile, "project_nave_native", lambda *a, **k: pytest.fail("Producer called by checker"))
    errors = profile.verify_nave_native(path, rows, saved["receipt"], **CONTEXT)
    assert "Nave rows differ from independent native traversal" in errors
