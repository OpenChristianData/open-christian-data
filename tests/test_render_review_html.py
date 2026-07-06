import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools.render_review_html import (  # noqa: E402
    build_review_queue,
    build_output_path,
    render_commentary_html,
    render_commentary_review,
    render_resource_html,
)


TEST_TMP = REPO_ROOT / "tests" / "_tmp_render_review_html"


def _case_dir(name: str) -> Path:
    path = TEST_TMP / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _commentary_payload() -> dict:
    return {
        "meta": {
            "id": "sample-commentary",
            "title": "Sample Commentary",
            "author": "Test Author",
            "license": "public-domain",
            "schema_type": "commentary",
            "schema_version": "2.2.0",
            "provenance": {
                "source_url": "https://example.test/source",
                "source_format": "HTML",
                "source_edition": "Sample edition",
                "processing_method": "automated",
                "processing_script_version": "parser@v1",
                "processing_date": "2026-05-06",
            },
        },
        "data": [
            {
                "entry_id": "sample.Gen.1.intro",
                "book": "Genesis",
                "book_osis": "Gen",
                "chapter": 1,
                "verse_range": "intro",
                "verse_range_osis": None,
                "verse_text": None,
                "commentary_text": "Chapter heading\n\nFirst paragraph with <old> spelling.",
                "cross_references": ["Gen.1.1"],
                "word_count": 7,
            },
            {
                "entry_id": "sample.Gen.1.1",
                "book": "Genesis",
                "book_osis": "Gen",
                "chapter": 1,
                "verse_range": "1",
                "verse_range_osis": "Gen.1.1",
                "verse_text": "In the beginning God created the heavens and the earth.",
                "commentary_text": "Verse note line one.\nVerse note line two.",
                "cross_references": [],
                "word_count": 7,
            },
        ],
    }


def test_render_commentary_html_shows_metadata_labels_and_escaped_text():
    html = render_commentary_html(
        _commentary_payload(),
        source_path=Path("data/commentaries/sample/genesis.json"),
    )

    assert "<!doctype html>" in html
    assert "Sample Commentary" in html
    assert "Test Author" in html
    assert "sample.Gen.1.intro" in html
    assert "Entry type: intro" in html
    assert "Entry type: verse" in html
    assert "Verse text" in html
    assert "In the beginning God created" in html
    assert "&lt;old&gt;" in html
    assert "Raw entry JSON" in html
    assert "Review warnings" in html


def test_render_commentary_html_warns_about_duplicate_entry_ids():
    payload = _commentary_payload()
    payload["data"][1]["entry_id"] = payload["data"][0]["entry_id"]

    html = render_commentary_html(
        payload,
        source_path=Path("data/commentaries/sample/genesis.json"),
    )

    assert "Duplicate entry_id: sample.Gen.1.intro" in html
    assert "duplicate_entry_id" in html
    assert "error" in html


def test_render_commentary_html_uses_shared_warning_logic():
    payload = _commentary_payload()
    payload["data"][0]["commentary_text"] = "The king-\n dom came."
    payload["data"][0]["word_count"] = 4

    html = render_commentary_html(
        payload,
        source_path=Path("data/commentaries/sample/genesis.json"),
    )

    assert "possible_broken_hyphenation" in html
    assert "possible broken hyphenation" in html


def test_build_output_path_preserves_commentary_source_structure():
    output = build_output_path(
        source_path=Path("data/commentaries/adam-clarke/2-john.json"),
        data_root=Path("data"),
        output_root=Path("review"),
    )

    assert output == Path("review/commentaries/adam-clarke/2-john/index.html")


def test_build_output_path_handles_relative_source_with_absolute_data_root():
    output = build_output_path(
        source_path=Path("data/commentaries/adam-clarke/2-john.json"),
        data_root=REPO_ROOT / "data",
        output_root=Path("review"),
    )

    assert output == Path("review/commentaries/adam-clarke/2-john/index.html")


def test_render_commentary_review_writes_html():
    root = _case_dir("writes_html")
    source = root / "data" / "commentaries" / "sample" / "genesis.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(json.dumps(_commentary_payload()), encoding="utf-8")

    output = render_commentary_review(
        source_path=source,
        data_root=root / "data",
        output_root=root / "review",
    )

    assert output == root / "review" / "commentaries" / "sample" / "genesis" / "index.html"
    assert output.exists()
    assert "Sample Commentary" in output.read_text(encoding="utf-8")


def test_render_commentary_review_writes_queue_json():
    root = _case_dir("writes_queue_json")
    source = root / "data" / "commentaries" / "sample" / "genesis.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(json.dumps(_commentary_payload()), encoding="utf-8")
    queue_json = root / "review" / "commentaries" / "sample" / "genesis" / "review-queue.json"

    render_commentary_review(
        source_path=source,
        data_root=root / "data",
        output_root=root / "review",
        queue_json=queue_json,
    )

    queue = json.loads(queue_json.read_text(encoding="utf-8"))
    assert queue["source_file"] == str(source)
    assert queue["total_entries"] == 2
    assert set(queue["warning_counts_by_severity"]) == {"info", "warning", "error"}
    assert isinstance(queue["warnings"], list)


def test_review_queue_timestamp_is_timezone_aware():
    queue = build_review_queue(
        _commentary_payload(),
        source_path=Path("data/commentaries/sample/genesis.json"),
    )

    assert queue["generated_at"].endswith("+00:00")


def test_render_commentary_html_rejects_unsupported_payload():
    with pytest.raises(ValueError, match="Unknown meta.schema_type|at least one data entry"):
        render_commentary_html({"meta": {"schema_type": "sermon"}, "data": []})


def _slot8_block(**overrides: object) -> dict:
    block = {
        "block_id": "slot8-block-1",
        "block_id_history": [],
        "block_type": "paragraph",
        "language": "en",
        "language_confidence": 0.99,
        "language_alternates": [],
        "language_segments": [],
        "original_text": "The source text is ready for review.",
        "modern_text": "",
        "annotations": {},
        "source_pages": [],
        "attested_by": ["ccel/sample/work/1900/thml"],
        "disagreements": [],
        "structural_disagreements": [],
        "modernisations": [],
    }
    block.update(overrides)
    return block


def _slot8_record(
    *,
    schema_type: str = "reconciled_record",
    resource_type: str | None = "encyclopedia",
    blocks: list[dict] | None = None,
) -> dict:
    blocks = blocks or [_slot8_block()]
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
        "schema_version": "3.0.0" if schema_type != "commentary" else "2.2.0",
        "edition": "1900",
        "pd_anchor": "ccel/sample/work/1900/thml",
        "modernisation_ruleset_version": None,
        "attestation_summary": {
            "block_count": len(blocks),
            "fully_attested_blocks": len(blocks),
            "blocks_with_disagreements": 0,
            "blocks_with_structural_disagreements": 0,
        },
    }
    if resource_type is not None:
        meta["resource_type"] = resource_type
    if schema_type == "commentary":
        meta = {
            "id": "sample-commentary",
            "title": "Sample Commentary",
            "author": "Sample Author",
            "license": "public-domain",
            "schema_type": "commentary",
            "schema_version": "2.2.0",
            "resource_type": "commentary",
            "provenance": {},
        }
        data = [
            {
                "entry_id": "sample.Gen.1.1",
                "book": "Genesis",
                "book_osis": "Gen",
                "chapter": 1,
                "verse_range": "1",
                "verse_range_osis": "Gen.1.1",
                "verse_text": None,
                "commentary_text": blocks[0]["original_text"],
                "cross_references": [],
                "word_count": len(str(blocks[0]["original_text"]).split()),
            }
        ]
    else:
        data = [
            {
                "entry_id": block["block_id"],
                "term": block["block_id"],
                "alt_terms": [],
                "definition_blocks": [{"type": block["block_type"], "text": block["original_text"]}],
                "related_terms": [],
            }
            for block in blocks
        ]
    return {"meta": meta, "blocks": blocks, "match_explanations": [], "data": data}


def test_render_review_html_emits_split_pane():
    html = render_resource_html(_slot8_record())
    assert 'class="split-pane"' in html

    commentary_html = render_resource_html(_slot8_record(schema_type="commentary"))
    assert 'class="split-pane"' not in commentary_html


def test_render_review_html_loads_scan_via_webp_derivative():
    block = _slot8_block(
        source_pages=[
            {
                "rendering_id": "ia/schaff/encyclopedia/1908-1914/ocr",
                "page_number": 1,
            }
        ]
    )
    html = render_resource_html(_slot8_record(blocks=[block]))
    assert '<img' in html
    assert 'src="scans-derived/ia/schaff/encyclopedia/1908-1914/ocr/p1.webp"' in html

    no_page_block = _slot8_block(
        source_pages=[
            {
                "rendering_id": "ia/schaff/encyclopedia/1908-1914/ocr",
                "page_number": None,
            }
        ]
    )
    no_page_html = render_resource_html(_slot8_record(blocks=[no_page_block]))
    assert 'src="scans-derived/ia/schaff/encyclopedia/1908-1914/ocr/p1.webp"' not in no_page_html
