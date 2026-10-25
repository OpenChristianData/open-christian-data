from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.wilberforce_practical_view_37c322_reconstruction import (
    _convert,
    _scan_emphasis,
)
from build.tei.wilberforce_practical_view_37c322_oracle import (
    _closure_digest,
    _oracle,
    _literal_underscore_census,
    _source_rows,
    _source_units,
    _underscore_census,
)
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
ROUTE_DIR = ROOT / "sources/structured-text/lib072-gutenberg-evangelical/work-bindings/wilberforce-practical-view"
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/wilberforce-practical-view-37c322.source-manifest.json'
SOURCE = ROOT / "raw/gutenberg/pg25709.txt"
TEI = {"tei": "http://www.tei-c.org/ns/1.0"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
LONG_SPAN_SHA256 = "b18fd07c3bf00c17a218f5978852211c638e787329382a8b8e3ed1a60506bf70"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


@pytest.fixture(scope="module")
def validated_candidate(tmp_path_factory: pytest.TempPathFactory):
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate_dir = tmp_path_factory.mktemp("37c-322-candidate") / "candidate"
    candidate = reconstruct(
        source,
        candidate_dir,
        _convert,
    )
    report = validate(source, candidate, _oracle)
    return source, candidate, report


def _reseal_member(candidate_dir: Path, member_name: str) -> CandidatePackage:
    manifest_path = candidate_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    member_record = next(row for row in manifest["members"] if row["name"] == member_name)
    content = (candidate_dir / member_name).read_bytes()
    member_record.update(bytes=len(content), sha256=_sha(content))
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(candidate_dir)


def test_source_marker_census_is_exact_and_independently_reproduced() -> None:
    content = SOURCE.read_bytes()
    producer_spans, producer_literals, producer_marker_count = _scan_emphasis(content)
    oracle_rows = _source_rows(content)
    oracle_units = _source_units(oracle_rows)
    oracle_spans = _underscore_census(content, oracle_rows, oracle_units)
    oracle_literals = _literal_underscore_census(oracle_rows, oracle_units)
    assert len(oracle_rows) == 10_820
    assert producer_spans == oracle_spans
    assert producer_literals == oracle_literals == []
    assert producer_marker_count == 1_304
    assert len(producer_spans) == 652
    assert sum(str(row["text"]).count("_") for row in oracle_rows) == 1_304
    longest = max(producer_spans, key=lambda span: int(span["interior_character_count"]))
    assert longest["start_line"] == 9_177
    assert longest["start_column"] == 18
    assert longest["end_line"] == 9_185
    assert longest["end_column"] == 23
    assert longest["interior_character_count"] == 566
    assert longest["physical_byte_count"] == 576
    assert longest["source_sha256"] == LONG_SPAN_SHA256
    assert len(longest["fragments"]) == 9
    assert longest["opening_delimiter"] == {
        "line_number": 9_177,
        "column": 18,
        "byte_offset": longest["source_slice_byte_start"],
        "character": "_",
        "sha256": _sha(b"_"),
    }
    assert longest["closing_delimiter"]["line_number"] == 9_185
    assert longest["closing_delimiter"]["column"] == 23
    assert longest["closing_delimiter"]["byte_offset"] == longest["source_slice_byte_end"] - 1


def test_literal_snake_case_underscores_are_preserved_before_pairing() -> None:
    spans, literal_markers, marker_count = _scan_emphasis(
        b"snake_case remains literal\r\n"
    )
    assert spans == []
    assert marker_count == 1
    assert literal_markers == [
        {
            "line_number": 1,
            "column": 6,
            "byte_offset": 5,
            "character": "_",
            "sha256": _sha(b"_"),
        }
    ]

    spans, literal_markers, marker_count = _scan_emphasis(b"_snake_case_\n")
    assert marker_count == 3
    assert spans[0]["start_column"] == 1
    assert spans[0]["end_column"] == 12
    assert spans[0]["fragments"][0]["text_sha256"] == _sha(b"snake_case")
    assert literal_markers[0]["column"] == 7


def test_unmatched_and_ambiguous_markers_fail_closed() -> None:
    with pytest.raises(ValueError, match="unmatched .*delimiter"):
        _scan_emphasis(b"text_\n")
    with pytest.raises(ValueError, match="ambiguous"):
        _scan_emphasis(b"__\n")
    for malformed in (b"text_\n", b"__\n"):
        rows = _source_rows(malformed)
        with pytest.raises(ValueError, match="unmatched source underscore|adjacent underscore"):
            _underscore_census(malformed, rows, _source_units(rows))


def test_manifest_binds_ticket_local_independent_oracle_and_current_closure() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    oracle_path = ROOT / "build/tei/wilberforce_practical_view_37c322_oracle.py"
    converter_path = ROOT / "build/tei/wilberforce_practical_view_37c322_reconstruction.py"
    parsed = ast.parse(oracle_path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(parsed)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(parsed)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "build.tei.gutenberg_evangelical_lib072_selected_reconstruction" not in imported
    assert "build.tei.gutenberg_proofread_selected_oracle" not in imported
    assert "build.tei.wilberforce_practical_view_37c322_reconstruction" not in imported
    policy = json.loads(source.authority_path("validation-policy").read_bytes())
    assert source.record["validator"]["implementation_path"] == oracle_path.relative_to(ROOT).as_posix()
    assert source.record["converter"]["implementation_path"] == converter_path.relative_to(ROOT).as_posix()
    assert _closure_digest(ROOT, policy) == source.record["validator"]["import_closure_sha256"]


def test_candidate_accountability_and_exact_tei_wrapper_projection(
    validated_candidate,
) -> None:
    _source, candidate, report = validated_candidate
    assert report.status == "pass"
    assert candidate.manifest["status"] == "nonaccepted"
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    work = accountability["works"][0]
    markup = work["source_underscore_markup"]
    assert markup["marker_count"] == 1_304
    assert markup["delimiter_count"] == 1_304
    assert markup["literal_underscore_count"] == 0
    assert markup["literal_markers"] == []
    assert markup["span_count"] == 652
    assert len(markup["spans"]) == 652

    document = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    long_span = next(row for row in markup["spans"] if row["source_sha256"] == LONG_SPAN_SHA256)
    opener = document.xpath(
        ".//tei:hi[@xml:id=$span_id]",
        namespaces=TEI,
        span_id=long_span["span_id"],
    )
    assert len(opener) == 1
    pieces = [opener[0]] + document.xpath(
        ".//tei:hi[@corresp=$target]",
        namespaces=TEI,
        target=f"#{long_span['span_id']}",
    )
    assert len(pieces) == 9
    assert all(piece.get("rend") == "italic" for piece in pieces)
    assert not pieces[0].text.startswith("_")
    assert not pieces[-1].text.endswith("_")
    source_rows = _source_rows(SOURCE.read_bytes())
    source_by_line = {row["line_number"]: row for row in source_rows}
    for fragment in long_span["fragments"]:
        line = document.xpath(
            ".//tei:seg[@type='source-line'][@n=$line]",
            namespaces=TEI,
            line=str(fragment["line_number"]),
        )[0]
        matching = [
            child
            for child in line
            if child.get(XML_ID) == long_span["span_id"]
            or child.get("corresp") == f"#{long_span['span_id']}"
        ]
        assert len(matching) == 1
        source_text = str(source_by_line[int(fragment["line_number"])]["text"])
        assert matching[0].text == source_text[
            int(fragment["start_column"]) - 1 : int(fragment["end_column"])
        ]
    long_source_slice = SOURCE.read_bytes()[
        int(long_span["source_slice_byte_start"]) : int(long_span["source_slice_byte_end"])
    ]
    assert _sha(long_source_slice) == long_span["source_sha256"] == LONG_SPAN_SHA256
    assert long_source_slice.startswith(b"_") and long_source_slice.endswith(b"_")


@pytest.mark.parametrize(
    "mutation",
    [
        "remove-visible-text",
        "change-rend",
        "break-continuation",
        "restore-delimiter",
        "change-accountability",
    ],
)
def test_candidate_isolation_mutation_sensitivity(
    validated_candidate,
    tmp_path: Path,
    mutation: str,
) -> None:
    source, original, _ = validated_candidate
    target = tmp_path / mutation
    shutil.copytree(original.path, target)
    if mutation in {"remove-visible-text", "change-rend", "break-continuation", "restore-delimiter"}:
        tei_path = target / "content.tei.xml"
        document = etree.fromstring(tei_path.read_bytes())
        wrappers = document.xpath(".//tei:hi[@rend='italic']", namespaces=TEI)
        if mutation == "remove-visible-text":
            wrappers[0].text = (wrappers[0].text or "")[1:]
        elif mutation == "change-rend":
            wrappers[0].set("rend", "source-underscore")
        elif mutation == "restore-delimiter":
            wrappers[0].text = "_" + (wrappers[0].text or "")
        else:
            continuation = document.xpath(
                ".//tei:hi[@corresp]",
                namespaces=TEI,
            )[0]
            continuation.set("corresp", "#wrong-span")
        tei_path.write_bytes(etree.tostring(document, encoding="UTF-8", xml_declaration=True))
        candidate = _reseal_member(target, "content.tei.xml")
    else:
        accountability_path = target / "source-accountability.json"
        accountability = json.loads(accountability_path.read_bytes())
        accountability["works"][0]["source_underscore_markup"]["spans"][0]["start_column"] += 1
        accountability_path.write_bytes(_canonical(accountability))
        candidate = _reseal_member(target, "source-accountability.json")
    with pytest.raises(ValueError):
        validate(source, candidate, _oracle)


def test_candidate_isolated_and_deterministic_in_fresh_processes(
    tmp_path: Path,
) -> None:
    first = tmp_path / "candidate-a"
    second = tmp_path / "candidate-b"
    command_base = [
        sys.executable,
        str(ROOT / "build/tools/reconstruct_candidate.py"),
        "--manifest",
        MANIFEST.relative_to(ROOT).as_posix(),
    ]
    results = []
    for destination in (first, second):
        completed = subprocess.run(
            [*command_base, "--destination", str(destination)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        results.append(json.loads(completed.stdout))
    assert results[0] == results[1]
    assert (first / "package" / "manifest.json").read_bytes() == (
        second / "package" / "manifest.json"
    ).read_bytes()
    for member in (
        "README.source.md",
        "content.tei.xml",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    ):
        assert _sha((first / "package" / member).read_bytes()) == _sha(
            (second / "package" / member).read_bytes()
        )
