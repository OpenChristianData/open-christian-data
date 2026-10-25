from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.original_douay_rheims import (
    APPENDIX_BOOKS,
    CANONICAL_NT,
    CANONICAL_OT,
    CONFIG_RELATIVE,
    SOURCE_PREFIX,
    _build_candidate,
    _source_markup,
    _tei,
    _verify_text_events,
)
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.tei.validate import compiled_schema


pytestmark = [pytest.mark.slow, pytest.mark.requires_local_artifacts]
ROOT = Path(__file__).resolve().parents[1]
NS = {"tei": "http://www.tei-c.org/ns/1.0"}


@pytest.fixture(scope="module")
def config() -> dict[str, object]:
    return json.loads((ROOT / CONFIG_RELATIVE).read_bytes())


@pytest.fixture(scope="module")
def source_root(config: dict[str, object]) -> Path:
    return resolve_repo_path(ROOT, str(config["source_root"]))


@pytest.fixture(scope="module")
def built() -> dict[str, bytes]:
    return _build_candidate(ROOT)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_config_pins_original_release_without_challoner_identity(config: dict[str, object]) -> None:
    assert config["resource_id"] == "original-douay-rheims"
    assert config["source_tag"] == "v1.0"
    assert config["source_revision"] == "5f48879740a3280e2bf679b2d1c0d6f835c992aa"
    assert config["candidate_status"] == "nonaccepted"
    assert "not the Challoner revision" in str(config["notes"])


def test_receipt_binds_archive_and_every_extracted_member(built: dict[str, bytes]) -> None:
    receipt = json.loads(built["source-receipt.json"])
    assert receipt["archive"] == {
        "path": "raw/clean-ready-acquisition-to-tei/master-3/21/original-douay-rheims/archive/original-douay-rheims-v1.0.zip",
        "bytes": 8108226,
        "sha256": "df1e9fe1580a9e6767c6587846c4bbe6bddec788fee0dce3bced05a6e9e48a6c",
    }
    assert len(receipt["extracted_members"]) == 654
    assert len(receipt["transformation_authority_members"]) == 500
    assert receipt["rights"]["license"] == "CC0 1.0 Universal"
    assert receipt["rights"]["attribution_required"] is False
    assert receipt["explicit_omissions"] and receipt["unresolved_questions"]


def test_complete_candidate_is_schema_valid_and_accounted(built: dict[str, bytes]) -> None:
    tei = etree.fromstring(built["content.tei.xml"])
    assert compiled_schema().validate(tei)
    accountability = json.loads(built["source-accountability.json"])
    assert accountability["member_counts"] == {
        "archive_containers": 1,
        "extracted_files": 654,
        "tagged_book_members": 77,
        "canonical_books_rendered": 73,
        "appendix_books_rendered": 3,
        "exact_duplicate_tagged_members": 1,
        "annotation_files": 394,
        "reference_files": 26,
        "raw_derivative_book_files_retained": 77,
        "usfm_derivative_book_files_retained": 77,
    }
    assert accountability["text_counts"] == {
        "reference_documents": 26,
        "chapters": 1361,
        "verses": 37181,
        "inline_notes": 8452,
        "cross_references": 1989,
        "annotations": 1659,
        "annotation_subnotes": 3544,
        "duplicate_verse_addresses": 1,
        "canonical_books": 73,
        "appendix_books": 3,
    }
    assert accountability["text_events"] == 61868
    assert accountability["omitted_transformation_authority_members"] == 0
    assert accountability["candidate_status"] == "nonaccepted"
    assert accountability["human_review_required"] is True
    assert accountability["work_catalog_changed"] is False
    assert accountability["publication_ready"] is False
    manifest = json.loads(built["manifest.json"])
    assert manifest["status"] == "nonaccepted"
    for member in manifest["members"]:
        content = built[member["name"]]
        assert member["bytes"] == len(content)
        assert member["sha256"] == _sha(content)


def test_source_member_discrepancy_is_preserved_not_silently_dropped(
    built: dict[str, bytes], source_root: Path
) -> None:
    tagged = source_root / "bible" / "tagged"
    assert len(list(tagged.glob("*.json"))) == 77
    assert (tagged / "prayer-of-manasseh.json").read_bytes() == (tagged / "prayer-of-manasses.json").read_bytes()
    unresolved = json.loads(built["unresolved.json"])
    disposition = unresolved["source_member_disposition"]
    assert len(disposition["canonical"]) == len(CANONICAL_OT) + len(CANONICAL_NT) == 73
    assert disposition["source_appendix"] == list(APPENDIX_BOOKS)
    assert disposition["exact_duplicate_not_rendered_twice"] == "prayer-of-manasseh"


def test_json_null_text_field_uses_its_json_lexeme(built: dict[str, bytes], source_root: Path) -> None:
    source_path = source_root / "bible" / "tagged" / "1-corinthians.json"
    source_book = json.loads(source_path.read_bytes())
    assert source_book["hebrew_title"] is None

    root = etree.fromstring(built["content.tei.xml"])
    pointer = SOURCE_PREFIX + "bible/tagged/1-corinthians.json#/hebrew_title"
    nodes = root.xpath("//*[@corresp=$pointer]", pointer=pointer)
    assert len(nodes) == 1
    assert "".join(nodes[0].itertext()) == "null"
    assert "None" not in "".join(nodes[0].itertext())

def test_every_source_text_event_and_inline_marker_round_trips_exactly(
    config: dict[str, object], source_root: Path
) -> None:
    tei_bytes, _, events = _tei(source_root, config)
    evidence = _verify_text_events(tei_bytes, events)
    assert evidence["text_events"] == 61868
    assert evidence["exact_source_markup_roundtrip"] is True
    root = etree.fromstring(tei_bytes)
    assert len(root.xpath(f"//*[@corresp and starts-with(@corresp, '{SOURCE_PREFIX}')]")) == len(events)


def test_opening_middle_ending_and_unusual_source_features_are_present(built: dict[str, bytes]) -> None:
    root = etree.fromstring(built["content.tei.xml"])
    ot_title = root.xpath("//tei:div[@type='reference-document' and @subtype='old-testament'][@n='title-page']/tei:head", namespaces=NS)
    nt_title = root.xpath("//tei:div[@type='reference-document' and @subtype='new-testament'][@n='title-page']/tei:head", namespaces=NS)
    assert ot_title and "HOLY BIBLE" in "".join(ot_title[0].itertext())
    assert nt_title and "NEW TESTAMENT" in "".join(nt_title[0].itertext())
    psalms = root.xpath("//tei:div[@xml:id='odr-book-psalms']", namespaces={**NS, "xml": "http://www.w3.org/XML/1998/namespace"})[0]
    proverbs = root.xpath("//tei:div[@xml:id='odr-book-proverbs']", namespaces={**NS, "xml": "http://www.w3.org/XML/1998/namespace"})[0]
    assert psalms.getnext() is proverbs
    ending = root.xpath("//tei:div[@xml:id='odr-apocalypse-22-21']/tei:ab[@type='verse-text']", namespaces={**NS, "xml": "http://www.w3.org/XML/1998/namespace"})[0]
    assert "grace of our Lord Jesus Christ" in "".join(ending.itertext())
    assert root.xpath("//tei:seg[@type='column-left']", namespaces=NS)
    assert root.xpath("//tei:seg[@type='column-right']", namespaces=NS)
    assert root.xpath("//tei:seg[@type='alternate-reading']", namespaces=NS)
    assert root.xpath("//tei:lb[@type='source-br']", namespaces=NS)
    assert root.xpath("//tei:hi[@rend='ref-title-sub']", namespaces=NS)
    assert root.xpath("//*[@ana='#source-unclosed-markup']")


def test_exact_event_check_rejects_mutated_candidate(
    config: dict[str, object], source_root: Path
) -> None:
    tei_bytes, _, events = _tei(source_root, config)
    root = etree.fromstring(tei_bytes)
    target = root.xpath("//tei:div[@xml:id='odr-genesis-1-1']/tei:ab", namespaces={**NS, "xml": "http://www.w3.org/XML/1998/namespace"})[0]
    target.text = "Invented text"
    mutated = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    with pytest.raises(ValueError, match="text event drift"):
        _verify_text_events(mutated, events)


def test_fresh_process_different_cwd_outputs_are_byte_identical(tmp_path: Path) -> None:
    script = (
        "from pathlib import Path;import sys;"
        "from build.tei.original_douay_rheims import write_candidate;"
        "write_candidate(Path(sys.argv[1]),Path(sys.argv[2]))"
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT)
    destinations = [tmp_path / "first", tmp_path / "second"]
    for destination in destinations:
        subprocess.run(
            [sys.executable, "-B", "-c", script, str(ROOT), str(destination)],
            cwd=tmp_path,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
    first_names = sorted(path.name for path in destinations[0].iterdir())
    second_names = sorted(path.name for path in destinations[1].iterdir())
    assert first_names == second_names
    for name in first_names:
        assert (destinations[0] / name).read_bytes() == (destinations[1] / name).read_bytes()


def test_source_markup_projection_preserves_the_unclosed_source_marker(built: dict[str, bytes]) -> None:
    root = etree.fromstring(built["content.tei.xml"])
    node = root.xpath("//*[@ana='#source-unclosed-markup']/ancestor-or-self::*[@corresp][1]")[0]
    assert _source_markup(node).count("<i>") > _source_markup(node).count("</i>")
