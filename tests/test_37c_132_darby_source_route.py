from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest
from lxml import etree

from build.tei.darby_oracle import oracle
from build.tei.darby_reconstruction import convert
from ocd_kernel.reconstruction.contract import SourceManifest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_RELATIVE = Path('tests/fixtures/reconstruction-runtime/darby.source-manifest.json')
SOURCE_RELATIVE = Path("raw/bible_databases/formats/json/Darby.json")
SOURCE_BYTES = 8_515_465
SOURCE_SHA256 = "6e5c9816b945fa5adef7c1ba419f4ddbca5fff3f77263284697e928a0841f806"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
EMPTY_REFERENCES = {
    ("Matthew", 23, 14): (40, "/books/39/chapters/22/verses/13"),
    ("Acts", 8, 37): (44, "/books/43/chapters/7/verses/36"),
    ("Acts", 15, 34): (44, "/books/43/chapters/14/verses/33"),
}
MEMBER_NAMES = {
    "README.source.md",
    "content.tei.xml",
    "provenance.json",
    "source-accountability.json",
    "unresolved.jsonl",
}


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _strict_json(content: bytes) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(content.decode("utf-8"), object_pairs_hook=reject_duplicates)


class InMemoryCandidateView:
    """Oracle test adapter; candidate members remain in memory, never packaged."""

    def __init__(self, source_manifest: SourceManifest, members: dict[str, bytes]):
        self._members = dict(members)
        converter = _plain(source_manifest.record["converter"])
        package_schema = _plain(source_manifest.record["package_schema"])
        member_rows = [
            {
                "name": name,
                "bytes": len(content),
                "sha256": _sha256(content),
            }
            for name, content in sorted(self._members.items())
        ]
        self.manifest = {
            "contract": "ocd-candidate-package-v1",
            "status": "nonaccepted",
            "source_id": source_manifest.record["source_id"],
            "source_manifest": {
                "path": source_manifest.path.relative_to(
                    source_manifest.repository_root
                ).as_posix(),
                "sha256": source_manifest.sha256,
            },
            "converter": converter,
            "package_schema": package_schema,
            "members": member_rows,
        }
        self.sha256 = _sha256(_canonical(self.manifest))

    def member_bytes(self, name: str) -> bytes:
        return self._members[name]

    def verify_integrity(self) -> None:
        if set(self._members) != MEMBER_NAMES:
            raise ValueError("in-memory candidate member inventory differs")
        observed_rows = [
            {
                "name": name,
                "bytes": len(content),
                "sha256": _sha256(content),
            }
            for name, content in sorted(self._members.items())
        ]
        if self.manifest["members"] != observed_rows:
            raise ValueError("in-memory candidate member digest differs")
        if self.sha256 != _sha256(_canonical(self.manifest)):
            raise ValueError("in-memory candidate descriptor digest differs")


def _new_memory_candidate(
    source_manifest: SourceManifest, members: dict[str, bytes]
) -> InMemoryCandidateView:
    return InMemoryCandidateView(source_manifest, members)


def _xml_root(content: bytes):
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        remove_blank_text=False,
    )
    return etree.fromstring(content, parser)


def _xml_bytes(root) -> bytes:
    return etree.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


@pytest.fixture(scope="module")
def route_run():
    manifest = SourceManifest.load(
        REPOSITORY_ROOT / MANIFEST_RELATIVE,
        repository_root=REPOSITORY_ROOT,
    )
    members = convert(manifest)
    candidate = _new_memory_candidate(manifest, members)
    result = oracle(manifest, candidate)
    return manifest, members, candidate, result


def test_manifest_binds_only_the_exact_darby_source_route(route_run):
    manifest, _, _, _ = route_run
    authorities = {
        authority["name"]: authority for authority in manifest.record["authorities"]
    }

    assert manifest.record["contract"] == "ocd-source-manifest-v1"
    assert manifest.record["source_id"] == "darby-retained-json"
    assert manifest.record["work_id"] == "darby"
    assert manifest.record["source_selection"] == {
        "authority": "darby-source",
        "json_pointer": "",
        "selected_root_fields": ("/translation", "/books"),
        "selection": "the complete single retained JSON document",
    }
    assert authorities["darby-source"]["path"] == SOURCE_RELATIVE.as_posix()
    assert authorities["darby-source"]["role"] == "primary-source"
    assert authorities["darby-source"]["bytes"] == SOURCE_BYTES
    assert authorities["darby-source"]["sha256"] == SOURCE_SHA256
    assert authorities["darby-profile"]["role"] == (
        "complete-source-feature-profile"
    )
    assert authorities["darby-policy"]["role"] == (
        "independent-validation-policy"
    )
    assert authorities["darby-accountability-schema"]["path"] == (
        "sources/bible-text/darby/darby.source-accountability.schema.json"
    )
    assert authorities["candidate-package-schema"]["path"] == (
        "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"
    )
    assert not any(
        "data/bible-text/darby" in authority["path"]
        or authority["path"] == "sources/bible-text/darby/config.json"
        for authority in authorities.values()
    )

    policy = _strict_json(manifest.authority_path("darby-policy").read_bytes())
    profile = _strict_json(manifest.authority_path("darby-profile").read_bytes())
    assert isinstance(policy, dict)
    assert isinstance(profile, dict)
    assert profile["downstream_segmentation_diagnostic_only"][
        "observed_per_book_json_file_count"
    ] == 66
    assert profile["downstream_segmentation_diagnostic_only"][
        "observed_total_bytes"
    ] == 8_107_066
    assert profile["downstream_segmentation_diagnostic_only"][
        "observed_verse_rows"
    ] == 31_099
    assert profile["downstream_segmentation_diagnostic_only"][
        "observed_files_claiming_completeness_full"
    ] == 66
    assert "diagnostic observation only" in profile[
        "downstream_segmentation_diagnostic_only"
    ]["role"]
    assert "must not read" in profile["downstream_segmentation_diagnostic_only"][
        "route_use"
    ]
    assert policy["downstream_segmentation"]["role"].startswith(
        "diagnostic only"
    )
    assert policy["downstream_segmentation"]["observed_file_count"] == 66
    assert policy["downstream_segmentation"]["observed_row_count"] == 31_099
    assert policy["downstream_segmentation"]["observed_total_bytes"] == 8_107_066

    oracle_ast = ast.parse(
        (REPOSITORY_ROOT / "build/tei/darby_oracle.py").read_text(encoding="utf-8")
    )
    imported_modules = {
        node.module
        for node in ast.walk(oracle_ast)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_names = {
        alias.name
        for node in ast.walk(oracle_ast)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "build.tei.darby_reconstruction" not in imported_modules
    assert "darby_reconstruction" not in imported_names


def test_independent_oracle_accounts_all_ordered_carriers_and_exact_values(route_run):
    manifest, members, candidate, result = route_run
    source_bytes = manifest.authority_path("darby-source").read_bytes()
    source = _strict_json(source_bytes)
    accounting = _strict_json(members["source-accountability.json"])
    tei = _xml_root(members["content.tei.xml"])

    assert isinstance(source, dict)
    assert isinstance(accounting, dict)
    assert _sha256(source_bytes) == SOURCE_SHA256
    assert len(source_bytes) == SOURCE_BYTES
    assert list(source) == ["translation", "books"]
    assert source["translation"] == "Darby: Darby Bible (1889)"
    assert result["status"] == "pass"
    assert result["oracle_id"] == "ocd-lib023-darby-independent-oracle"
    assert result["findings"] == []
    assert set(members) == MEMBER_NAMES

    expected_counts = {
        "source_members": 1,
        "books": 66,
        "chapters": 1189,
        "verse_carriers": 31102,
        "nonempty_text_values": 31099,
        "empty_text_values": 3,
        "missing_text_fields": 0,
        "null_text_fields": 0,
        "unknown_object_keys": 0,
        "scalar_fields": 63460,
        "ordered_arrays": 1256,
        "leading_whitespace_text_values": 2427,
        "trailing_ascii_space_text_values": 31102 - 3,
    }
    assert accounting["counts"] == expected_counts
    assert len(accounting["book_inventory"]) == 66
    assert len(accounting["chapter_inventory"]) == 1189
    assert len(accounting["verse_carriers"]) == 31102
    assert accounting["translation_field"] == {
        "json_pointer": "/translation",
        "value": source["translation"],
        "field_state": "present_nonempty_string",
        "value_sha256": _sha256(source["translation"].encode("utf-8")),
    }
    assert accounting["excluded"] == []

    def q(local: str) -> str:
        return f"{{{TEI_NS}}}{local}"

    body = tei.find(f".//{q('body')}")
    assert body is not None
    source_books = source["books"]
    tei_books = list(body)
    assert len(tei_books) == len(source_books) == 66
    empty_tei_nodes = {}
    total_chapters = 0
    total_verses = 0
    for book_position, (book, book_node) in enumerate(
        zip(source_books, tei_books, strict=True), start=1
    ):
        assert book_node.get("type") == "book"
        assert book_node.get("n") == str(book_position)
        children = list(book_node)
        assert children[0].tag == q("head")
        assert children[0].text == book["name"]
        chapters = book["chapters"]
        chapter_nodes = children[1:]
        assert len(chapter_nodes) == len(chapters)
        for chapter, chapter_node in zip(chapters, chapter_nodes, strict=True):
            assert chapter_node.tag == q("div")
            assert chapter_node.get("type") == "chapter"
            assert chapter_node.get("n") == str(chapter["chapter"])
            verses = chapter["verses"]
            verse_nodes = list(chapter_node)
            assert len(verse_nodes) == len(verses)
            total_chapters += 1
            for verse, verse_node in zip(verses, verse_nodes, strict=True):
                assert verse_node.tag == q("ab")
                assert verse_node.get("type") == "verse"
                assert verse_node.get("n") == str(verse["verse"])
                assert verse_node.get(f"{{{XML_NS}}}space") == "preserve"
                assert (verse_node.text or "") == verse["text"]
                reference = (book["name"], chapter["chapter"], verse["verse"])
                if reference in EMPTY_REFERENCES:
                    empty_tei_nodes[reference] = verse_node
                total_verses += 1

    assert total_chapters == 1189
    assert total_verses == 31102
    assert len(empty_tei_nodes) == 3
    genesis_one = tei.xpath(
        ".//tei:div[@type='book'][@n='1']/tei:div[@type='chapter'][@n='1']/tei:ab[@n='1']",
        namespaces={"tei": TEI_NS},
    )
    assert len(genesis_one) == 1
    assert genesis_one[0].text == "In the beginningGod created the heavens and the earth. "

    empty_rows = accounting["empty_text_carriers"]
    assert len(empty_rows) == 3
    for (book, chapter, verse), (book_position, pointer) in EMPTY_REFERENCES.items():
        row = next(
            item
            for item in empty_rows
            if item["reference"] == f"{book} {chapter}:{verse}"
        )
        assert row["book_position"] == book_position
        assert row["json_pointer"] == pointer
        assert row["carrier_state"] == "present"
        assert row["text_field_state"] == "present"
        assert row["text_value_state"] == "empty_string"
        assert row["text_value_sha256"] == _sha256(b"")
        assert row["json_pointer"] == next(
            item["json_pointer"]
            for item in accounting["verse_carriers"]
            if item["identity"]
            == {
                "book_position": book_position,
                "book": book,
                "chapter": chapter,
                "verse": verse,
            }
        )
        assert (empty_tei_nodes[(book, chapter, verse)].text or "") == ""


def test_oracle_rejects_an_omitted_present_empty_carrier(route_run):
    manifest, members, _, _ = route_run
    mutated = dict(members)
    root = _xml_root(mutated["content.tei.xml"])
    chapter = root.xpath(
        ".//tei:div[@type='book'][@n='40']/tei:div[@type='chapter'][@n='23']",
        namespaces={"tei": TEI_NS},
    )[0]
    verse = chapter.xpath("./tei:ab[@type='verse'][@n='14']", namespaces={"tei": TEI_NS})[
        0
    ]
    chapter.remove(verse)
    mutated["content.tei.xml"] = _xml_bytes(root)

    with pytest.raises(ValueError, match="verse carrier count mismatch"):
        oracle(manifest, _new_memory_candidate(manifest, mutated))


def test_oracle_rejects_reordered_carriers_and_trimmed_source_text(route_run):
    manifest, members, _, _ = route_run
    reordered = dict(members)
    root = _xml_root(reordered["content.tei.xml"])
    chapter = root.xpath(
        ".//tei:div[@type='book'][@n='44']/tei:div[@type='chapter'][@n='8']",
        namespaces={"tei": TEI_NS},
    )[0]
    first = list(chapter)[0]
    chapter.remove(first)
    chapter.insert(1, first)
    reordered["content.tei.xml"] = _xml_bytes(root)
    with pytest.raises(ValueError, match="verse carrier/order/value mismatch"):
        oracle(manifest, _new_memory_candidate(manifest, reordered))

    trimmed = dict(members)
    root = _xml_root(trimmed["content.tei.xml"])
    genesis = root.xpath(
        ".//tei:div[@type='book'][@n='1']/tei:div[@type='chapter'][@n='1']/tei:ab[@n='1']",
        namespaces={"tei": TEI_NS},
    )[0]
    assert genesis.text.endswith(" ")
    genesis.text = genesis.text[:-1]
    trimmed["content.tei.xml"] = _xml_bytes(root)
    with pytest.raises(ValueError, match="verse carrier/order/value mismatch"):
        oracle(manifest, _new_memory_candidate(manifest, trimmed))


def test_oracle_rejects_translation_or_accountability_state_drift(route_run):
    manifest, members, _, _ = route_run
    altered_label = dict(members)
    root = _xml_root(altered_label["content.tei.xml"])
    label = root.xpath(
        ".//tei:sourceDesc/tei:bibl", namespaces={"tei": TEI_NS}
    )[0]
    label.text = "Darby Bible"
    altered_label["content.tei.xml"] = _xml_bytes(root)
    with pytest.raises(ValueError, match="retained translation label mismatch"):
        oracle(manifest, _new_memory_candidate(manifest, altered_label))

    altered_accountability = dict(members)
    account = _strict_json(altered_accountability["source-accountability.json"])
    account["empty_text_carriers"][0]["text_field_state"] = "missing"
    altered_accountability["source-accountability.json"] = _canonical(account)
    with pytest.raises(ValueError, match="accountability schema failure"):
        oracle(manifest, _new_memory_candidate(manifest, altered_accountability))


def test_conversion_is_deterministic_in_a_fresh_process(route_run):
    manifest, members, _, _ = route_run
    expected = {
        name: {"bytes": len(content), "sha256": _sha256(content)}
        for name, content in sorted(members.items())
    }
    script = "\n".join(
        (
            "import hashlib, json",
            "from pathlib import Path",
            "from build.tei.darby_reconstruction import convert",
            "from ocd_kernel.reconstruction.contract import SourceManifest",
            "root = Path.cwd()",
            "manifest = SourceManifest.load(root / 'tests/fixtures/reconstruction-runtime/darby.source-manifest.json', repository_root=root)",
            "members = convert(manifest)",
            "result = {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()} for name, data in sorted(members.items())}",
            "print(json.dumps(result, sort_keys=True, separators=(',', ':'))) ",
        )
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    assert json.loads(completed.stdout) == expected


def test_route_never_reads_downstream_diagnostic_directory(route_run, monkeypatch):
    manifest, members, _, _ = route_run
    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path: Path) -> bytes:
        if "data/bible-text/darby" in path.as_posix():
            raise AssertionError("Darby route attempted a downstream diagnostic read")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    candidate_members = convert(manifest)
    candidate = _new_memory_candidate(manifest, candidate_members)
    assert set(candidate_members) == set(members)
    assert oracle(manifest, candidate)["status"] == "pass"
