from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from lxml import etree

from build.tools.count_dataset_records import collect_work_catalog
from build.tei.ylt_oracle import oracle
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/ylt.source-manifest.json'
SOURCE = ROOT / "raw/bible_databases/formats/json/YLT.json"
SOURCE_SHA256 = "d55ef42dae715c4fc5d00049011b818a42a99e0ff419f5f08bc37cea0b4f12e3"
SOURCE_BYTES = 8_382_339
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data: bytes) -> object:
    return json.loads(data.decode("utf-8"))


def _run_candidate(destination: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "build.tools.reconstruct_candidate",
            "--manifest",
            MANIFEST.relative_to(ROOT).as_posix(),
            "--destination",
            str(destination),
            "--repository-root",
            str(ROOT),
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )


@pytest.fixture(scope="module")
def route_run():
    with tempfile.TemporaryDirectory(prefix="ocd-ylt-37c323-") as temporary:
        destination = Path(temporary) / "candidate"
        completed = _run_candidate(destination)
        assert completed.returncode == 0, completed.stderr
        yield destination, json.loads(completed.stdout)


def test_manifest_binds_exact_ylt_source_and_complete_selector() -> None:
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    manifest.verify()
    record = manifest.record
    authorities = {row["name"]: row for row in record["authorities"]}
    assert record["source_id"] == "ylt-retained-json"
    assert record["work_id"] == "ylt"
    assert record["source_selection"] == {
        "authority": "ylt-source",
        "json_pointer": "",
        "selected_root_fields": ("/translation", "/books"),
        "selection": "the complete single retained JSON document",
    }
    assert authorities["ylt-source"]["path"] == SOURCE.relative_to(ROOT).as_posix()
    assert authorities["ylt-source"]["bytes"] == SOURCE_BYTES
    assert authorities["ylt-source"]["sha256"] == SOURCE_SHA256
    assert authorities["ylt-config"]["path"] == "sources/bible-text/ylt/config.json"
    assert authorities["ylt-profile"]["role"] == "complete-source-feature-profile"
    assert authorities["ylt-policy"]["role"] == "independent-validation-policy"
    assert authorities["ylt-accountability-schema"]["role"] == "source-accountability-schema"
    assert record["converter"]["implementation_path"] == "build/tei/ylt_reconstruction.py"
    assert record["validator"]["implementation_path"] == "build/tei/ylt_oracle.py"


def test_candidate_is_nonaccepted_and_accounts_every_source_carrier(route_run) -> None:
    destination, summary = route_run
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate = CandidatePackage.load(destination / "package")
    assert summary["status"] == "pass"
    assert summary["acceptance_status"] == "nonaccepted"
    assert summary["publication_status"] == "not-authorized"
    assert candidate.manifest["status"] == "nonaccepted"
    assert candidate.manifest["source_manifest"]["sha256"] == manifest.sha256
    accounting = _json(candidate.member_bytes("source-accountability.json"))
    assert accounting["source_member"] == {
        "path": "raw/bible_databases/formats/json/YLT.json",
        "bytes": SOURCE_BYTES,
        "sha256": SOURCE_SHA256,
    }
    assert accounting["counts"] == {
        "source_members": 1,
        "books": 66,
        "chapters": 1189,
        "verse_carriers": 31102,
        "nonempty_text_values": 31102,
        "empty_text_values": 0,
        "missing_text_fields": 0,
        "null_text_fields": 0,
        "unknown_object_keys": 0,
        "scalar_fields": 63460,
        "ordered_arrays": 1256,
        "leading_whitespace_text_values": 0,
        "trailing_ascii_space_text_values": 0,
    }
    assert len(accounting["book_inventory"]) == 66
    assert len(accounting["chapter_inventory"]) == 1189
    assert len(accounting["verse_carriers"]) == 31102
    assert accounting["empty_text_carriers"] == []
    assert accounting["excluded"] == []


def test_tei_preserves_opening_midpoint_ending_and_all_66_books(route_run) -> None:
    destination, _ = route_run
    source = _json(SOURCE.read_bytes())
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    root = etree.fromstring(CandidatePackage.load(destination / "package").member_bytes("content.tei.xml"), parser)
    q = lambda local: f"{{{TEI}}}{local}"
    body = root.find(f"{q('text')}/{q('body')}")
    assert body is not None
    books = list(body)
    assert len(books) == 66
    chapter_total = verse_total = 0
    for position, (book, book_node) in enumerate(zip(source["books"], books, strict=True), 1):
        assert book_node.get("n") == str(position)
        assert book_node.find(q("head")).text == book["name"]
        chapter_nodes = list(book_node)[1:]
        assert len(chapter_nodes) == len(book["chapters"])
        for chapter, chapter_node in zip(book["chapters"], chapter_nodes, strict=True):
            assert chapter_node.get("n") == str(chapter["chapter"])
            verse_nodes = list(chapter_node)
            assert len(verse_nodes) == len(chapter["verses"])
            chapter_total += 1
            for verse, verse_node in zip(chapter["verses"], verse_nodes, strict=True):
                assert verse_node.get("n") == str(verse["verse"])
                assert verse_node.get(f"{{{XML}}}space") == "preserve"
                assert (verse_node.text or "") == verse["text"]
                verse_total += 1
    assert (chapter_total, verse_total) == (1189, 31102)
    refs = [("Genesis", 1, 1), ("Psalms", 119, 176), ("Revelation of John", 22, 21)]
    for book_name, chapter_number, verse_number in refs:
        source_book = next(book for book in source["books"] if book["name"] == book_name)
        source_chapter = next(ch for ch in source_book["chapters"] if ch["chapter"] == chapter_number)
        source_verse = next(v for v in source_chapter["verses"] if v["verse"] == verse_number)
        book_node = next(node for node in books if node.find(q("head")).text == book_name)
        chapter_node = next(node for node in list(book_node)[1:] if node.get("n") == str(chapter_number))
        verse_node = next(node for node in chapter_node if node.get("n") == str(verse_number))
        assert (verse_node.text or "") == source_verse["text"]


@pytest.mark.parametrize("mutation", ["omission", "reordering", "invention"])
def test_independent_oracle_rejects_structural_mutations(route_run, tmp_path: Path, mutation: str) -> None:
    destination, _ = route_run
    package = tmp_path / mutation
    shutil.copytree(destination / "package", package)
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    content_path = package / "content.tei.xml"
    tree = etree.parse(str(content_path), parser)
    q = lambda local: f"{{{TEI}}}{local}"
    chapter = tree.xpath(".//tei:div[@type='book'][@n='1']/tei:div[@type='chapter'][@n='1']", namespaces={"tei": TEI})[0]
    verses = list(chapter)
    if mutation == "omission":
        chapter.remove(verses[0])
    elif mutation == "reordering":
        chapter.remove(verses[1])
        chapter.insert(0, verses[1])
    else:
        invented = etree.Element(q("ab"), {"type": "verse", "n": "999", f"{{{XML}}}id": "ylt-invented", f"{{{XML}}}space": "preserve"})
        invented.text = "Invented verse content."
        chapter.append(invented)
    content_path.write_bytes(etree.tostring(tree, encoding="utf-8", xml_declaration=True) + b"\n")
    descriptor_path = package / "manifest.json"
    descriptor = json.loads(descriptor_path.read_bytes())
    member = next(row for row in descriptor["members"] if row["name"] == "content.tei.xml")
    member["bytes"] = content_path.stat().st_size
    member["sha256"] = _sha(content_path.read_bytes())
    descriptor_path.write_text(json.dumps(descriptor, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="verse carrier|order/identity|order/value"):
        oracle(SourceManifest.load(MANIFEST, repository_root=ROOT), CandidatePackage.load(package))


def test_fresh_process_reproduction_is_byte_identical(route_run, tmp_path: Path) -> None:
    first, summary = route_run
    with tempfile.TemporaryDirectory(prefix="ocd-ylt-37c323-repeat-") as temporary:
        second = Path(temporary) / "second"
        completed = _run_candidate(second)
        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout) == summary
        first_files = {p.relative_to(first).as_posix(): p.read_bytes() for p in first.rglob("*") if p.is_file()}
        second_files = {p.relative_to(second).as_posix(): p.read_bytes() for p in second.rglob("*") if p.is_file()}
        assert first_files == second_files


def test_subject_scoped_metadata_and_bounded_workcatalog_route(route_run, monkeypatch) -> None:
    from tests.test_runtime_manifest_binding_boundaries import allow_runtime_manifest_selection

    allow_runtime_manifest_selection(monkeypatch, MANIFEST)
    destination, _ = route_run
    metadata = _json((ROOT / "metadata/source-evidence/catalog/ylt.json").read_bytes())
    assert metadata["subject"] == {"id": "ylt", "kind": "catalog"}
    # The retained source is current, but the legacy YLT projection carries a
    # stale source hash.  Exercise the supported source-only admission path
    # without reading that generated projection as current route evidence.
    paths = ["data/topical-reference/naves/naves-topical-bible.json"]
    catalog = collect_work_catalog(
        ROOT / "data",
        reconstruction_evidence={
            ("ylt-retained-json", "ylt"): (destination / "package", destination / "validation.json")
        },
        source_manifest_allowlist=[MANIFEST.relative_to(ROOT).as_posix()],
        data_resource_allowlist=paths,
    )
    rows = [work for work in catalog.works if work["work_id"] == "ylt"]
    assert len(rows) == 1
    row = rows[0]
    assert row["audit_flags"] == ["runtime_source_admission"]
    assert row["file_count"] == 0
    assert row["top_level_records"] == 0
    assert row["reconstruction_state"]["routes"] == [{
        "association": "runtime_source_admission",
        "manifest": 'tests/fixtures/reconstruction-runtime/ylt.source-manifest.json',
        "scope": "work",
        "source_id": "ylt-retained-json",
        "verification": "verified",
        "candidate_verification": "verified",
        "validation_verification": "verified",
    }]
