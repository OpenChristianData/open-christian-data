"""Focused exact accepted WEB Classic line/continuation projection proof."""

import copy
import json
from pathlib import Path

import pytest

from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories import bible, web_classic_native_bible
from ocd_kernel.projection.categories.web_classic_native_bible_check import check_document
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release.public_rows import public_rows_with_omissions
from ocd_kernel.release.work_metadata import compose_work_metadata


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "library/works/world-english-bible-classic/forms/world-english-bible-classic-retained-en/editions/world-english-bible-classic-electronic/acceptance.json"
LICENSE = "public-domain"
ITEM = "world-english-bible-classic--world-english-bible-classic-electronic"


@pytest.fixture(scope="module")
def real_projection():
    with cached_edition_lookups():
        metadata = web_classic_native_bible._context(ROOT, ACCEPTANCE)
        result = bible.project_accepted_bible(ROOT, acceptance_path=ACCEPTANCE)
    return metadata, result


def test_all_source_lines_and_verse_continuations_are_accounted(real_projection):
    metadata, result = real_projection
    inventory = result["inventory"]
    assert len(result["rows"]) == 38058
    assert inventory["source_members"] == 83
    assert inventory["source_lines"] == 74297
    assert inventory["word_annotations"] == 677690
    assert inventory["inline_tags"] == {"term": 94, "title": 47}
    assert inventory["continuation_blocks"] == 15501
    assert inventory["blank_note_verses"] == 29
    assert inventory["note_boundary_spaces"] == 2
    assert inventory["nonverse_carriers"]["sirach-51-opening-caption"] == 1
    assert inventory["note_types"]["source-usfm-raw"] == 74297
    assert json.loads(json.dumps(result["receipt"])) == result["receipt"]
    assert check_document(metadata["master_path"], result["rows"], result["receipt"], metadata=metadata) == []
    composed, _ = compose_work_metadata(ROOT, [dict(row, license=LICENSE) for row in result["rows"]], result["receipt"])
    public, omissions = public_rows_with_omissions(composed, item_id=ITEM)
    assert omissions is None and len(public) == 38058
    assert _scan(public, "WEB Classic public rows") == []


@pytest.mark.parametrize("kind", ["text", "continuation-inventory"])
def test_independent_observer_rejects_lost_text_or_private_ledger(real_projection, kind):
    metadata, result = real_projection
    rows = copy.deepcopy(result["rows"])
    receipt = copy.deepcopy(result["receipt"])
    if kind == "text":
        rows[0]["text"] = "A changed verse"
    else:
        receipt["inventory"]["continuation_blocks"] -= 1
    assert check_document(metadata["master_path"], rows, receipt, metadata=metadata)
