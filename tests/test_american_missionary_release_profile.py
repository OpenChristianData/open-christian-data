"""Bounded American Missionary native issue carrier checks."""

from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection import native_content
from ocd_kernel.projection.native_content_check import observe_content
from ocd_kernel.projection.categories import native_documents, prose

ROOT = Path(__file__).resolve().parents[1]
TEI = "{http://www.tei-c.org/ns/1.0}"
PROFILE = native_documents.AMERICAN_MISSIONARY_PROFILE


def _both(xml: bytes):
    return (
        lambda: native_content.project_content(ET.fromstring(xml), source_profile=PROFILE),
        lambda: observe_content(xml, source_profile=PROFILE)[0],
    )


def test_monthly_table_cell_source_number_is_literal_and_source_bound():
    valid = f'<row xmlns="{TEI[1:-1]}"><cell role="data" n="4" xml:id="amv36-I01-B00004" xmlns:xml="http://www.w3.org/XML/1998/namespace">One</cell><cell role="data">Two</cell></row>'.encode()
    produced, observed = (operation() for operation in _both(valid))
    assert produced == observed
    assert produced["content"][0]["attributes"]["number"] == "4"
    assert produced["content"][0]["attributes"]["source_role"] == "data"
    assert "xml:id" not in produced["content"][0]["attributes"]
    assert produced["content"][1]["attributes"] == {"source_role": "data"}

    changed = (
        valid.replace(b'n="4"', b'n="0"'),
        valid.replace(b'n="4"', b'n="x"'),
        valid.replace(b'B00004', b'B00005'),
        valid.replace(b'role="data"', b'role="head"', 1),
        valid.replace(b'</cell><cell', b'</cell><cell n="4" xml:id="amv36-I02-B00004"'),
    )
    for xml in changed:
        for operation in _both(xml):
            with pytest.raises((PipelineError, ValueError)):
                operation()
    outside = f'<cell xmlns="{TEI[1:-1]}" role="data" n="4" xml:id="amv36-I01-B00004" xmlns:xml="http://www.w3.org/XML/1998/namespace">One</cell>'.encode()
    for operation in _both(outside):
        with pytest.raises((PipelineError, ValueError)):
            operation()


def test_monthly_source_block_roles_remain_visible_and_unknown_role_fails():
    for kind in ("direct-text", "html-span", "html-a", "html-em", "html-b", "html-i", "html-cite"):
        xml = f'<ab xmlns="{TEI[1:-1]}" type="{kind}">Text</ab>'.encode()
        produced, observed = (operation() for operation in _both(xml))
        assert produced == observed
        assert produced["attributes"]["type"] == kind
    unknown = f'<ab xmlns="{TEI[1:-1]}" type="html-script">Text</ab>'.encode()
    for operation in _both(unknown):
        with pytest.raises((PipelineError, ValueError)):
            operation()


def test_monthly_profile_admission_is_exact_identity_and_master():
    identity = {
        "work_id": "american-missionary",
        "textual_form_id": "american-missionary-gutenberg-retained-en",
        "edition_id": "american-missionary-volume-36-1882-gutenberg-electronic",
    }
    with pytest.raises(PipelineError, match="master differs"):
        native_documents._american_missionary_profile(
            identity, b"changed master", language="en", category="prose", collection=False,
            projection_profile=PROFILE, allow_acceptance_metadata=True,
        )
    unrelated = {**identity, "work_id": "another-work"}
    with pytest.raises(PipelineError, match="exact accepted profile"):
        native_documents._american_missionary_profile(
            unrelated, b"changed master", language="en", category="prose", collection=False,
            projection_profile=PROFILE, allow_acceptance_metadata=True,
        )
    assert prose._american_missionary_profile(ROOT, {"identity": unrelated}) is None
    with pytest.raises(PipelineError, match="identity or master differs"):
        prose._american_missionary_profile(ROOT, {
            "identity": identity,
            "authority": {"master": {"sha256": "0" * 64}},
            "accepted": {"identity": {**identity, "acquisition_id": identity["edition_id"] + "-acquired"}},
            "language": "en",
        })
