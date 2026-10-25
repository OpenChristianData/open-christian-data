from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from lxml import etree

from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    validate,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_RELATIVE = Path('tests/fixtures/reconstruction-runtime/kjva.source-manifest.json')
SOURCE_RELATIVE = Path("raw/bible_databases/formats/json/KJVA.json")
SOURCE_SHA256 = "b927f4a0601de39b1636ebb71162ab1bf8ddbad66a55f50603011697e46060d5"
SOURCE_BYTES = 10_082_833
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _strict_json(content: bytes):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(content.decode("utf-8"), object_pairs_hook=unique_object)


def _run_candidate_cli(destination: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "build.tools.reconstruct_candidate",
            "--manifest",
            MANIFEST_RELATIVE.as_posix(),
            "--destination",
            str(destination),
            "--repository-root",
            str(REPOSITORY_ROOT),
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )


@pytest.fixture(scope="module")
def candidate_run(tmp_path_factory):
    destination = tmp_path_factory.mktemp("kjva-cli") / "candidate"
    completed = _run_candidate_cli(destination)
    assert completed.returncode == 0, completed.stderr
    return destination, json.loads(completed.stdout)


def test_public_manifest_binds_exact_source_and_route_dependencies():
    manifest_path = REPOSITORY_ROOT / MANIFEST_RELATIVE
    manifest = SourceManifest.load(manifest_path, repository_root=REPOSITORY_ROOT)
    record = manifest.record
    authorities = {entry["name"]: entry for entry in record["authorities"]}

    assert record["contract"] == "ocd-source-manifest-v1"
    assert record["source_id"] == "kjva-retained-json"
    assert record["work_id"] == "kjva"
    assert authorities["kjva-source"]["path"] == SOURCE_RELATIVE.as_posix()
    # The shared manifest contract requires one primary-source member for its
    # source digest; this mechanical role does not settle edition-level identity.
    assert authorities["kjva-source"]["role"] == "primary-source"
    assert authorities["kjva-source"]["bytes"] == SOURCE_BYTES
    assert authorities["kjva-source"]["sha256"] == SOURCE_SHA256
    assert authorities["kjva-config"]["path"] == "sources/bible-text/kjva/config.json"
    assert authorities["kjva-profile"]["path"] == (
        "sources/bible-text/kjva/kjva.reconstruction-profile.json"
    )
    assert authorities["kjva-policy"]["path"] == (
        "sources/bible-text/kjva/kjva.validation-policy.json"
    )
    assert authorities["tei-p5-xsd"]["path"] == "ocd_kernel/tei/vendor/xsd/tei_all.xsd"
    assert authorities["tei-xml-xsd"]["path"] == (
        "ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd"
    )
    assert authorities["tei-teix-xsd"]["path"] == (
        "ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd"
    )
    assert authorities["candidate-package-schema"]["path"] == (
        "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"
    )
    assert authorities["candidate-cli"]["path"] == "build/tools/reconstruct_candidate.py"
    assert authorities["build-package-init"]["path"] == "build/__init__.py"
    assert authorities["reconstruction-contract"]["path"] == (
        "ocd_kernel/reconstruction/contract.py"
    )
    assert authorities["reconstruction-verifier"]["path"] == (
        "ocd_kernel/reconstruction/verifier.py"
    )
    assert authorities["destination-policy"]["path"] == (
        "ocd_kernel/reconstruction/destination_policy.py"
    )
    assert authorities["kernel-init"]["path"] == "ocd_kernel/__init__.py"
    assert authorities["reconstruction-init"]["path"] == (
        "ocd_kernel/reconstruction/__init__.py"
    )
    assert set(authorities) == {
        "kjva-source",
        "kjva-config",
        "kjva-profile",
        "kjva-policy",
        "tei-p5-xsd",
        "tei-xml-xsd",
        "tei-teix-xsd",
        "candidate-package-schema",
        "candidate-cli",
        "build-package-init",
        "reconstruction-contract",
        "reconstruction-verifier",
        "destination-policy",
        "kernel-init",
        "reconstruction-init",
    }

    converter = record["converter"]
    validator_binding = record["validator"]
    assert converter["implementation_path"] == "build/tei/kjva_reconstruction.py"
    assert validator_binding["implementation_path"] == "build/tei/kjva_oracle.py"
    assert len(validator_binding["import_closure_sha256"]) == 64
    assert record["package_schema"] == {
        "path": authorities["candidate-package-schema"]["path"],
        "sha256": authorities["candidate-package-schema"]["sha256"],
    }
    manifest.verify()


def test_supported_cli_generates_complete_source_ordered_schema_valid_tei(candidate_run):
    destination, summary = candidate_run
    manifest = SourceManifest.load(
        REPOSITORY_ROOT / MANIFEST_RELATIVE,
        repository_root=REPOSITORY_ROOT,
    )
    candidate = CandidatePackage.load(destination / "package")
    source_bytes = (REPOSITORY_ROOT / SOURCE_RELATIVE).read_bytes()
    source = _strict_json(source_bytes)
    profile = _strict_json(manifest.authority_path("kjva-profile").read_bytes())
    accounting = _strict_json(candidate.member_bytes("source-accountability.json"))

    assert _sha256(source_bytes) == SOURCE_SHA256
    assert list(source) == ["translation", "books"]
    assert summary["status"] == "pass"
    assert summary["acceptance_status"] == "nonaccepted"
    assert summary["publication_status"] == "not-authorized"
    assert summary["digests"]["source_manifest"] == manifest.sha256
    assert summary["digests"]["candidate"] == candidate.sha256
    validation = json.loads((destination / "validation.json").read_bytes())
    assert validation["status"] == "pass"
    assert validation["candidate_sha256"] == candidate.sha256
    assert validation["source_manifest_sha256"] == manifest.sha256
    assert validation["attestation"]["findings"] == []

    book_inventory = [
        {
            "position": position,
            "name": book["name"],
            "chapters": len(book["chapters"]),
            "verses": sum(len(chapter["verses"]) for chapter in book["chapters"]),
        }
        for position, book in enumerate(source["books"], start=1)
    ]
    assert book_inventory == profile["ordered_book_envelope"]
    assert len(book_inventory) == 80
    assert book_inventory[39]["name"] == "I Esdras"
    assert book_inventory[52]["name"] == "II Maccabees"
    assert profile["book_partitions"] == {
        "kjv_portion_positions": [[1, 39], [54, 80]],
        "kjv_portion_books": 66,
        "apocrypha_positions": [[40, 53]],
        "apocrypha_books": 14,
    }
    assert profile["edition_and_publication_dates"] == "unresolved"
    assert profile["print_edition_completeness"] == "unassessed"
    assert profile["source_member"] == {
        "path": SOURCE_RELATIVE.as_posix(),
        "bytes": SOURCE_BYTES,
        "sha256": SOURCE_SHA256,
    }

    assert accounting["contract"] == "ocd-kjva-accounting-v1"
    assert accounting["source_member"] == {
        "path": SOURCE_RELATIVE.as_posix(),
        "bytes": SOURCE_BYTES,
        "sha256": SOURCE_SHA256,
    }
    assert accounting["counts"] == {
        "members": 1,
        "books": 80,
        "chapters": 1371,
        "verses": 36819,
        "carriers": 38270,
        "scalar_fields": 75090,
        "ordered_arrays": 1452,
    }
    assert accounting["field_states"] == {
        "missing": 0,
        "null": 0,
        "empty_string": 0,
        "zero_integer": 0,
        "false_boolean": 0,
        "empty_array": 0,
    }
    assert accounting["book_inventory"] == book_inventory
    assert len(accounting["carriers"]) == 38270
    assert accounting["object_key_orders"] == profile["object_key_orders"]
    assert accounting["root_fields"] == [
        {
            "name": "translation",
            "state": "nonempty_string",
            "value_sha256": _sha256(
                json.dumps(
                    source["translation"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                + b"\n"
            ),
        },
        {"name": "books", "state": "nonempty_array", "length": 80},
    ]
    carrier_signatures = [
        {
            "kind": carrier["kind"],
            "pointer": carrier["pointer"],
            "parent": carrier["parent"],
            "identity": carrier["identity"],
        }
        for carrier in accounting["carriers"]
    ]
    expected_carriers = []
    for book_position, book in enumerate(source["books"], 1):
        book_pointer = f"/books/{book_position - 1}"
        expected_carriers.append(
            {
                "kind": "book",
                "pointer": book_pointer,
                "parent": "/books",
                "identity": {"position": book_position, "book": book["name"]},
            }
        )
        for chapter_position, chapter in enumerate(book["chapters"], 1):
            chapter_pointer = f"{book_pointer}/chapters/{chapter_position - 1}"
            expected_carriers.append(
                {
                    "kind": "chapter",
                    "pointer": chapter_pointer,
                    "parent": f"{book_pointer}/chapters",
                    "identity": {"book": book["name"], "chapter": chapter_position},
                }
            )
            for verse_position, _verse in enumerate(chapter["verses"], 1):
                verse_pointer = f"{chapter_pointer}/verses/{verse_position - 1}"
                expected_carriers.append(
                    {
                        "kind": "verse",
                        "pointer": verse_pointer,
                        "parent": f"{chapter_pointer}/verses",
                        "identity": {
                            "book": book["name"],
                            "chapter": chapter_position,
                            "verse": verse_position,
                        },
                    }
                )
    assert carrier_signatures == expected_carriers
    assert [
        sum(carrier["kind"] == kind for carrier in accounting["carriers"])
        for kind in ("book", "chapter", "verse")
    ] == [80, 1371, 36819]
    for carrier in accounting["carriers"]:
        assert carrier["fields"]
        assert all(field["state"] in {"nonempty_string", "nonempty_array", "positive_integer"} for field in carrier["fields"])
    assert accounting["carriers"][0]["identity"] == {
        "position": 1,
        "book": "Genesis",
    }
    assert accounting["carriers"][0]["parent"] == "/books"
    assert accounting["carriers"][-1]["identity"] == {
        "book": "Revelation of John",
        "chapter": 22,
        "verse": 21,
    }
    assert accounting["excluded"] == []

    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        remove_blank_text=False,
    )
    tree = etree.fromstring(candidate.member_bytes("content.tei.xml"), parser)
    q = lambda local: f"{{{TEI_NS}}}{local}"
    xml_id = f"{{{XML_NS}}}id"
    xml_space = f"{{{XML_NS}}}space"
    assert tree.tag == q("TEI")
    assert tree.get(xml_id) == "kjva"
    assert [node.tag for node in tree] == [q("teiHeader"), q("text")]
    assert tree.find(f".//{q('titleStmt')}/{q('title')}").text == (
        "King James Version with Apocrypha"
    )
    body = tree.find(f"{q('text')}/{q('body')}")
    assert body is not None
    book_nodes = list(body)
    assert len(book_nodes) == len(source["books"]) == 80

    chapter_total = 0
    verse_total = 0
    for book_position, (source_book, book_node) in enumerate(
        zip(source["books"], book_nodes, strict=True),
        start=1,
    ):
        book_id = f"kjva-book-{book_position:03d}"
        assert book_node.tag == q("div")
        assert dict(book_node.attrib) == {
            "type": "book",
            "n": str(book_position),
            xml_id: book_id,
        }
        children = list(book_node)
        assert children[0].tag == q("head")
        assert children[0].text == source_book["name"]
        assert children[0].get(xml_id) == f"{book_id}-title"
        chapter_nodes = children[1:]
        assert len(chapter_nodes) == len(source_book["chapters"])
        for chapter_source, chapter_node in zip(
            source_book["chapters"],
            chapter_nodes,
            strict=True,
        ):
            chapter_number = chapter_source["chapter"]
            chapter_id = f"{book_id}-chapter-{chapter_number:03d}"
            assert chapter_node.tag == q("div")
            assert dict(chapter_node.attrib) == {
                "type": "chapter",
                "n": str(chapter_number),
                xml_id: chapter_id,
            }
            verse_nodes = list(chapter_node)
            assert len(verse_nodes) == len(chapter_source["verses"])
            chapter_total += 1
            for verse_source, verse_node in zip(
                chapter_source["verses"],
                verse_nodes,
                strict=True,
            ):
                verse_number = verse_source["verse"]
                assert verse_node.tag == q("ab")
                assert dict(verse_node.attrib) == {
                    "type": "verse",
                    "n": str(verse_number),
                    xml_id: (
                        f"{chapter_id}-verse-{verse_number:03d}"
                    ),
                    xml_space: "preserve",
                }
                assert verse_node.text == verse_source["text"]
                assert len(verse_node) == 0
                verse_total += 1

    assert chapter_total == 1371
    assert verse_total == 36819

    def source_verse(book_name: str, chapter_number: int, verse_number: int) -> str:
        book = next(item for item in source["books"] if item["name"] == book_name)
        chapter = next(
            item for item in book["chapters"] if item["chapter"] == chapter_number
        )
        return next(
            item["text"] for item in chapter["verses"] if item["verse"] == verse_number
        )

    assert source_verse("Genesis", 1, 1) == (
        "In the beginning God created the heaven and the earth."
    )
    assert source_verse("Additions to Esther", 10, 4).startswith(" </title>")
    assert source_verse("I John", 2, 23).find("[but]") >= 0
    assert source_verse("Psalms", 119, 176).endswith(" ")

    def tei_verse(book_name: str, chapter_number: int, verse_number: int) -> str:
        book_node = next(
            node for node in book_nodes if node.find(q("head")).text == book_name
        )
        chapter_node = next(
            node
            for node in list(book_node)[1:]
            if node.get("n") == str(chapter_number)
        )
        verse_node = next(
            node for node in chapter_node if node.get("n") == str(verse_number)
        )
        return verse_node.text

    assert tei_verse("Genesis", 1, 1) == "In the beginning God created the heaven and the earth."
    assert tei_verse("Additions to Esther", 10, 4).startswith(" </title>")
    assert "[but]" in tei_verse("I John", 2, 23)
    assert tei_verse("Psalms", 119, 176).endswith(" ")

    schema = etree.XMLSchema(
        etree.parse(str(REPOSITORY_ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))
    )
    schema.assertValid(tree)


def test_supported_cli_reproduces_complete_candidate_bytes(candidate_run, tmp_path):
    first_destination, first_summary = candidate_run
    second_destination = tmp_path / "second-candidate"
    completed = _run_candidate_cli(second_destination)
    assert completed.returncode == 0, completed.stderr
    second_summary = json.loads(completed.stdout)

    first_files = {
        path.relative_to(first_destination).as_posix(): path.read_bytes()
        for path in first_destination.rglob("*")
        if path.is_file()
    }
    second_files = {
        path.relative_to(second_destination).as_posix(): path.read_bytes()
        for path in second_destination.rglob("*")
        if path.is_file()
    }
    assert first_summary == second_summary
    assert first_files.keys() == second_files.keys()
    assert first_files == second_files


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("omission", "source order/parent/omission"),
        ("reordering", "source order/parent/omission"),
        ("invention", "source order/parent/omission"),
    ],
)
def test_manifest_bound_oracle_rejects_candidate_mutations(
    candidate_run,
    tmp_path,
    mutation,
    expected_error,
):
    destination, _ = candidate_run
    mutated_package = tmp_path / "mutated-package"
    shutil.copytree(destination / "package", mutated_package)
    content_path = mutated_package / "content.tei.xml"
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        remove_blank_text=False,
    )
    tree = etree.parse(str(content_path), parser)
    q = lambda local: f"{{{TEI_NS}}}{local}"
    body = tree.find(f"{q('text')}/{q('body')}")
    assert body is not None
    first_book = body[0]
    first_chapter = first_book[1]
    verses = list(first_chapter)
    assert len(verses) >= 2

    if mutation == "omission":
        first_chapter.remove(verses[0])
    elif mutation == "reordering":
        first_chapter.remove(verses[1])
        first_chapter.insert(0, verses[1])
    else:
        invented = etree.Element(q("ab"))
        invented.set("type", "verse")
        invented.set("n", "999")
        invented.set(f"{{{XML_NS}}}id", "kjva-invented-verse")
        invented.set(f"{{{XML_NS}}}space", "preserve")
        invented.text = "Invented verse content."
        first_chapter.append(invented)

    content_path.write_bytes(
        etree.tostring(
            tree,
            encoding="utf-8",
            xml_declaration=True,
        )
        + b"\n"
    )
    package_manifest_path = mutated_package / "manifest.json"
    package_manifest = json.loads(package_manifest_path.read_bytes())
    content_record = next(
        member
        for member in package_manifest["members"]
        if member["name"] == "content.tei.xml"
    )
    mutated_bytes = content_path.read_bytes()
    content_record["bytes"] = len(mutated_bytes)
    content_record["sha256"] = _sha256(mutated_bytes)
    package_manifest_path.write_text(
        json.dumps(
            package_manifest,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    source_manifest = SourceManifest.load(
        REPOSITORY_ROOT / MANIFEST_RELATIVE,
        repository_root=REPOSITORY_ROOT,
    )
    candidate = CandidatePackage.load(mutated_package)
    oracle = importlib.import_module("build.tei.kjva_oracle").oracle
    with pytest.raises(ValueError, match=expected_error):
        validate(source_manifest, candidate, oracle)
