import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools.render_review_html import render_resource_html  # noqa: E402


def _block(**overrides: object) -> dict:
    block = {
        "block_id": "slot8-affordance-block",
        "block_id_history": [],
        "block_type": "paragraph",
        "language": "en",
        "language_confidence": 0.99,
        "language_alternates": [],
        "language_segments": [],
        "original_text": "The colour spelling is attested.",
        "modern_text": "The color spelling is attested.",
        "annotations": {},
        "source_pages": [],
        "attested_by": ["ia/r"],
        "disagreements": [],
        "structural_disagreements": [],
        "modernisations": [],
    }
    block.update(overrides)
    return block


def _record(
    block: dict,
    *,
    schema_type: str = "reconciled_record",
    extra_meta: dict | None = None,
) -> dict:
    meta = {
        "id": "sample-work-edition",
        "title": "Sample Work",
        "author_slug": "sample-author",
        "author_display_name": "Sample Author",
        "author_birth_year": None,
        "author_death_year": None,
        "original_publication_year": 1900,
        "language": "en",
        "tradition": ["reformed"],
        "license": "public-domain",
        "schema_type": schema_type,
        "schema_version": "3.0.0",
        "resource_type": "encyclopedia",
        "edition": "1900",
        "pd_anchor": "ccel/schaff/encyclopedia/1908-1914/thml",
        "modernisation_ruleset_version": None,
        "attestation_summary": {
            "block_count": 1,
            "fully_attested_blocks": 1,
            "blocks_with_disagreements": 0,
            "blocks_with_structural_disagreements": 0,
        },
    }
    if schema_type == "modernised_record":
        meta["modernisation_ruleset_version"] = "en@1.0.0"
        meta["paired_with"] = "data/reference/sample/work/1900/original/record.json"
    if extra_meta:
        meta.update(extra_meta)
    return {
        "meta": meta,
        "blocks": [block],
        "match_explanations": [],
        "data": [
            {
                "entry_id": block["block_id"],
                "term": "Sample",
                "alt_terms": [],
                "definition_blocks": [{"type": block["block_type"], "text": block["original_text"]}],
                "related_terms": [],
            }
        ],
    }


def test_disagreement_adjudication_affordance():
    block = _block(
        disagreements=[
            {
                "reading_a": "colour",
                "reading_b": "color",
                "kind": "spelling_variant",
                "attested_by": ["ia/r"],
            }
        ]
    )
    html = render_resource_html(_record(block))
    assert 'class="reading"' in html

    clean_html = render_resource_html(_record(_block(disagreements=[])))
    assert 'class="reading"' not in clean_html


def test_structural_disagreement_split_merge_interactions():
    block = _block(
        structural_disagreements=[
            {
                "kind": "split_in_attestor",
                "anchor_block_id": "abc123",
                "attestor_rendering_id": "ia/r",
            }
        ]
    )
    html = render_resource_html(_record(block))
    assert 'data-action="split"' in html
    assert 'data-action="merge"' in html

    clean_html = render_resource_html(_record(_block(structural_disagreements=[])))
    assert 'data-action="split"' not in clean_html
    assert 'data-action="merge"' not in clean_html


def test_modernisation_accept_override_per_token():
    block = _block(
        modernisations=[
            {
                "rule_id": "eth_rule",
                "original": "hath",
                "modern": "has",
                "offset": 0,
                "length": 4,
            }
        ]
    )
    html = render_resource_html(_record(block, schema_type="modernised_record"))
    assert 'data-rule-id="eth_rule"' in html

    clean_html = render_resource_html(_record(_block(modernisations=[]), schema_type="modernised_record"))
    assert "data-rule-id" not in clean_html


def test_catalog_management_promote_demote():
    block = _block()
    catalog = {
        "renderings": [
            {
                "rendering_id": "ia/schaff/encyclopedia/1908-1914/ocr",
                "role": "pending",
            },
            {
                "rendering_id": "ccel/schaff/encyclopedia/1908-1914/thml",
                "role": "pd_anchor",
            },
        ]
    }
    record = _record(
        block,
        extra_meta={"pd_anchor": "ccel/schaff/encyclopedia/1908-1914/thml"},
    )

    html = render_resource_html(record, catalog=catalog)

    assert 'data-rendering-id="ia/schaff/encyclopedia/1908-1914/ocr"' in html
    assert 'data-action="promote"' in html
    anchor_fragment = html.split('data-rendering-id="ccel/schaff/encyclopedia/1908-1914/thml"', 1)[1]
    assert 'data-action="promote"' not in anchor_fragment.split("</", 1)[0]
