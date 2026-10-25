"""Isolation and fidelity checks for the three LIB-071 proofread routes."""

from __future__ import annotations

import ast
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from types import ModuleType
from typing import Callable

import pytest
from lxml import etree

from ocd_kernel.lib.path_io import resolve_path
from ocd_kernel.reconstruction import contract


ROOT = Path(__file__).resolve().parents[1]
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
SOURCE_CASES = (
    {
        "ticket_id": "37c-094",
        "work_id": "carey-enquiry",
        "source_id": "gutenberg-37c-094-pg11449",
        "source_path": "raw/gutenberg/pg11449.txt",
        "manifest_path": "sources/structured-text/lib071-gutenberg-evangelical/work-bindings/carey-enquiry/37c-094-tables-v4.source-manifest.json",
        "builder_path": "build/tei/gutenberg_evangelical_lib071_selected_reconstruction.py",
    },
    {
        "ticket_id": "37c-135",
        "work_id": "drummond-greatest-thing",
        "source_id": "gutenberg-37c-135-pg16739",
        "source_path": "raw/gutenberg/pg16739.txt",
        "manifest_path": "sources/structured-text/lib071-gutenberg-evangelical/work-bindings/drummond-greatest-thing/37c-135-source-underscore-emphasis-v2.source-manifest.json",
        "builder_path": "build/tei/gutenberg_evangelical_lib071_selected_reconstruction.py",
    },
    {
        "ticket_id": "37c-136",
        "work_id": "drummond-natural-law",
        "source_id": "gutenberg-37c-136-pg23334",
        "source_path": "raw/gutenberg/pg23334.txt",
        "manifest_path": "sources/structured-text/lib071-gutenberg-evangelical/work-bindings/drummond-natural-law/37c-136.source-manifest.json",
        "builder_path": "build/tei/gutenberg_evangelical_lib071_selected_reconstruction.py",
    },
)
ORACLE_PATH = "build/tei/gutenberg_proofread_selected_oracle.py"
ALLOWED_SOURCE_PATHS = {case["source_path"] for case in SOURCE_CASES} | {
    "raw/gutenberg/pg25709.txt"
}


def _load_module(relative_path: str, module_name: str) -> ModuleType:
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _is_raw_path(path: Path) -> bool:
    normalized = path.resolve(strict=False).as_posix().casefold()
    return "/raw/" in f"/{normalized.strip('/')}/"


def _sealed_mutation(
    package: contract.CandidatePackage,
    destination: Path,
    mutate: Callable[[etree._Element], None],
) -> contract.CandidatePackage:
    destination.mkdir()
    for member_name in package.member_names:
        (destination / member_name).write_bytes(package.member_bytes(member_name))

    tei_path = destination / "content.tei.xml"
    root = etree.fromstring(tei_path.read_bytes())
    mutate(root)
    tei_bytes = etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )
    tei_path.write_bytes(tei_bytes)

    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes().decode("utf-8"))
    tei_member = next(
        item for item in manifest["members"] if item["name"] == "content.tei.xml"
    )
    tei_member["bytes"] = len(tei_bytes)
    tei_member["sha256"] = hashlib.sha256(tei_bytes).hexdigest()
    manifest_path.write_bytes(_canonical(manifest))
    return contract.CandidatePackage.load(destination)


def _sealed_json_mutation(
    package: contract.CandidatePackage,
    destination: Path,
    member_name: str,
    mutate: Callable[[dict[str, object]], None],
) -> contract.CandidatePackage:
    destination.mkdir()
    for name in package.member_names:
        (destination / name).write_bytes(package.member_bytes(name))

    member_path = destination / member_name
    value = json.loads(member_path.read_bytes().decode("utf-8"))
    mutate(value)
    member_bytes = _canonical(value)
    member_path.write_bytes(member_bytes)

    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes().decode("utf-8"))
    member = next(item for item in manifest["members"] if item["name"] == member_name)
    member["bytes"] = len(member_bytes)
    member["sha256"] = hashlib.sha256(member_bytes).hexdigest()
    manifest_path.write_bytes(_canonical(manifest))
    return contract.CandidatePackage.load(destination)


def _run_clean_process(
    case: dict[str, str], destination: Path
) -> dict[str, str]:
    script = """
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[4])
from ocd_kernel.reconstruction import contract

root = Path(sys.argv[1])
case = json.loads(sys.argv[2])
destination = Path(sys.argv[3])
sys.path.insert(0, str(root))

def load_module(relative_path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, root / relative_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {relative_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

manifest = contract.SourceManifest.load(root / case["manifest_path"], repository_root=root)
converter = load_module(manifest.record["converter"]["implementation_path"], "clean_process_converter")
oracle = load_module(manifest.record["validator"]["implementation_path"], "clean_process_oracle")
candidate = contract.reconstruct(manifest, destination, converter._convert)
report = contract.validate(manifest, candidate, oracle._oracle)
print(json.dumps({"candidate_sha256": candidate.sha256, "report_sha256": report.sha256}, sort_keys=True))
"""
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            script,
            str(ROOT),
            json.dumps(case, sort_keys=True),
            str(destination),
            str(Path(__file__).resolve().parents[1]),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(result.stdout)
    assert set(value) == {"candidate_sha256", "report_sha256"}
    return value


def _generic_37c136_inputs() -> tuple[bytes, dict[str, object], list[tuple[str, bytes]]]:
    """Read the exact retained generic generation without changing the later note route."""
    code_root = Path(__file__).resolve().parents[1]
    home = code_root / "tests/fixtures/reconstruction-runtime/authorities"
    raw = (home / "37c136-generic-source-manifest.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "39ab061259762023e2aa0a8d2f49bcb52d6a2163c3eb160cd5119d828128683a"
    record = json.loads(raw)
    assert record["ticket_id"] == "37c-136" and record["work_id"] == "drummond-natural-law"
    assert len(record["authorities"]) == 13
    frozen = {"ticket-scope": "37c136-generic-ticket.md", "validation-policy": "37c136-generic-policy.json"}
    payloads = []
    for authority in record["authorities"]:
        origin = (home / frozen[authority["name"]]
                  if authority["name"] in frozen else code_root / authority["path"])
        payload = origin.read_bytes()
        assert len(payload) == authority["bytes"]
        assert hashlib.sha256(payload).hexdigest() == authority["sha256"], authority["path"]
        payloads.append((authority["path"], payload))
    return raw, record, payloads


def _generic_37c136_root(case: dict[str, str], tmp_path: Path) -> Path:
    raw, record, payloads = _generic_37c136_inputs()
    current_manifest = ROOT / case["manifest_path"]
    current_bytes = current_manifest.read_bytes()
    replay = tmp_path / "generic-37c136-replay"
    for relative, payload in payloads:
        target = replay / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    target = replay / case["manifest_path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    assert target.read_bytes() == raw and json.loads(target.read_bytes()) == record
    assert current_manifest.read_bytes() == current_bytes
    return replay


@pytest.mark.parametrize("case", SOURCE_CASES, ids=[item["ticket_id"] for item in SOURCE_CASES])
def test_ticket_candidate_isolated_deterministic_and_mutation_sensitive(
    case: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if case["ticket_id"] == "37c-136":
        monkeypatch.setitem(globals(), "ROOT", _generic_37c136_root(case, tmp_path))
    builder = _load_module(case["builder_path"], f"builder_{case['work_id']}")
    source_path = resolve_path(ROOT / case["source_path"], strict=True)
    source_manifest_path = ROOT / case["manifest_path"]
    observed_raw_reads: set[Path] = set()
    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path: Path) -> bytes:
        resolved = resolve_path(path, strict=False)
        if _is_raw_path(resolved):
            if resolved != source_path:
                raise AssertionError("selected-source route read an excluded raw member")
            observed_raw_reads.add(resolved)
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    source_manifest = contract.SourceManifest.load(
        source_manifest_path,
        repository_root=ROOT,
    )
    converter = _load_module(
        source_manifest.record["converter"]["implementation_path"],
        "selected_proofread_converter",
    )
    oracle = _load_module(
        source_manifest.record["validator"]["implementation_path"],
        "selected_proofread_oracle",
    )
    assert source_manifest.record["ticket_id"] == case["ticket_id"]
    assert source_manifest.record["work_id"] == case["work_id"]
    assert source_manifest.record["source_id"] == case["source_id"]
    profile, work = builder._select(source_manifest)
    assert work["source_form"] == "human-proofread Project Gutenberg plain text"
    assert profile["source_correction_attestation"] == (
        "The ticket-bound retained Project Gutenberg member was positively identified as human-proofread and carries Distributed Proofreaders attribution. This technical reconstruction does not independently audit the provider's individual corrections."
    )
    raw_authorities = [
        item
        for item in source_manifest.record["authorities"]
        if _is_raw_path(ROOT / str(item["path"]))
    ]
    assert len(raw_authorities) == 1
    assert raw_authorities[0]["role"] == "primary-source"
    assert raw_authorities[0]["path"] == case["source_path"]

    first = contract.reconstruct(
        source_manifest,
        tmp_path / "first-package",
        converter._convert,
    )
    first_report = contract.validate(source_manifest, first, oracle._oracle)
    second = contract.reconstruct(
        source_manifest,
        tmp_path / "second-package",
        converter._convert,
    )
    second_report = contract.validate(source_manifest, second, oracle._oracle)

    assert first.sha256 == second.sha256
    assert first_report.sha256 == second_report.sha256
    assert first_report.status == second_report.status == "pass"
    assert first.manifest["status"] == second.manifest["status"] == "nonaccepted"
    assert {"content.tei.xml", "source-accountability.json", "README.source.md"} <= set(
        first.member_names
    )

    candidate_root = etree.fromstring(first.member_bytes("content.tei.xml"))
    expected_heading_lines = {
        int(item["line_number"]) for item in work["heading_map"]
    }
    observed_heading_lines = {
        int(item.get("n", "0"))
        for item in candidate_root.findall(
            f".//{{{TEI_NS}}}head[@type='source-located-heading']"
        )
    }
    assert observed_heading_lines == expected_heading_lines
    expected_title_lines = {
        int(item["attached_title_lines"][0]["line_number"])
        for item in work["heading_map"]
        if item["attached_title_lines"]
    }
    observed_title_lines = {
        int(item.get("n", "0"))
        for item in candidate_root.findall(
            f".//{{{TEI_NS}}}head[@type='source-attached-title']"
        )
    }
    assert observed_title_lines == expected_title_lines

    if case["ticket_id"] == "37c-094":
        expected_tables = (
            ("europe", 819, 930, 5, 112),
            ("asia", 935, 1034, 5, 100),
            ("africa", 1039, 1080, 5, 42),
            ("america", 1085, 1182, 6, 98),
        )
        table_nodes = candidate_root.findall(f".//{{{TEI_NS}}}table")
        assert [
            (
                node.get("n"),
                int(node[0].get("n", "0")),
                int(node[-1].get("n", "0")),
                int(node.get("cols", "0")),
                len(node),
            )
            for node in table_nodes
        ] == list(expected_tables)
        accounting = json.loads(first.member_bytes("source-accountability.json"))
        table_ledger = accounting["works"][0]["source_tables"]
        assert [
            (
                table["table_id"],
                table["start_line"],
                table["end_line"],
                table["row_count"],
                sum(row["continuation_owner_line"] is not None for row in table["rows"]),
                sum(row["group_owner_line"] is not None for row in table["rows"]),
                sum(row["note_role"] is not None for row in table["rows"]),
            )
            for table in table_ledger
        ] == [
            ("europe", 819, 930, 112, 19, 0, 2),
            ("asia", 935, 1034, 100, 16, 15, 9),
            ("africa", 1039, 1080, 42, 4, 0, 0),
            ("america", 1085, 1182, 98, 26, 43, 5),
        ]
        assert candidate_root.find(
            f".//{{{TEI_NS}}}table[@n='america']/{{{TEI_NS}}}row[@n='1086']/{{{TEI_NS}}}cell[@role='population']"
        ).get("cols") == "2"
        assert candidate_root.find(
            f".//{{{TEI_NS}}}table[@n='america']/{{{TEI_NS}}}row[@n='1170']/{{{TEI_NS}}}cell[@role='white_population']"
        ) is not None
        assert candidate_root.find(
            f".//{{{TEI_NS}}}table[@n='europe']/{{{TEI_NS}}}row[@n='824']"
        ).get("corresp") == "#carey-enquiry-row-00823"
        assert "#carey-enquiry-row-00991" in candidate_root.find(
            f".//{{{TEI_NS}}}table[@n='asia']/{{{TEI_NS}}}row[@n='999']"
        ).get("ana")
        assert candidate_root.find(
            f".//{{{TEI_NS}}}table[@n='europe']/{{{TEI_NS}}}row[@n='861']//{{{TEI_NS}}}ref"
        ).get("target") == "#carey-enquiry-row-00929"
        assert candidate_root.find(
            f".//{{{TEI_NS}}}table[@n='europe']/{{{TEI_NS}}}row[@n='890']/{{{TEI_NS}}}cell[@rend='source-qualifier']"
        ) is not None

    clean_process = _run_clean_process(case, tmp_path / "clean-process-package")
    assert clean_process == {
        "candidate_sha256": first.sha256,
        "report_sha256": first_report.sha256,
    }

    adjacent_path = next(path for path in ALLOWED_SOURCE_PATHS if path != case["source_path"])
    adjacent_record = dict(source_manifest.record)
    adjacent_authority = dict(raw_authorities[0])
    adjacent_authority.update(
        {
            "name": "adjacent-retained-source",
            "path": adjacent_path,
            "role": "adjacent-retained-source",
        }
    )
    adjacent_record["authorities"] = (
        *source_manifest.record["authorities"],
        adjacent_authority,
    )
    adjacent_manifest = replace(source_manifest, _record=adjacent_record)
    with pytest.raises(ValueError, match="may bind only"):
        builder._select(adjacent_manifest)
    with pytest.raises(ValueError, match="may bind only"):
        oracle._oracle(adjacent_manifest, first)

    def delete_first_line(root: etree._Element) -> None:
        first_line = root.find(f".//{{{TEI_NS}}}seg")
        assert first_line is not None and first_line.getparent() is not None
        first_line.getparent().remove(first_line)

    def reorder_two_line_values(root: etree._Element) -> None:
        lines = root.findall(f".//{{{TEI_NS}}}seg")
        assert len(lines) >= 2
        lines[0].text, lines[1].text = lines[1].text, lines[0].text

    def remove_explicit_section_head(root: etree._Element) -> None:
        sections = root.findall(
            f".//{{{TEI_NS}}}div[@type='source-heading-section']"
        )
        assert sections
        head = sections[0].find(f"{{{TEI_NS}}}head")
        assert head is not None
        sections[0].remove(head)

    def remove_outer_language(root: etree._Element) -> None:
        outer_text = root.find(f"{{{TEI_NS}}}text")
        assert outer_text is not None and outer_text.get(XML_LANG) == "en"
        del outer_text.attrib[XML_LANG]

    def change_outer_language(root: etree._Element) -> None:
        outer_text = root.find(f"{{{TEI_NS}}}text")
        assert outer_text is not None and outer_text.get(XML_LANG) == "en"
        outer_text.set(XML_LANG, "fr")

    def alter_first_mapped_heading(root: etree._Element) -> None:
        heading = root.find(
            f".//{{{TEI_NS}}}head[@type='source-located-heading']"
        )
        assert heading is not None
        line = heading.find(f"{{{TEI_NS}}}seg")
        assert line is not None and line.text
        line.text += " [altered]"

    def detach_first_attached_title(root: etree._Element) -> None:
        title = root.find(
            f".//{{{TEI_NS}}}head[@type='source-attached-title']"
        )
        assert title is not None and title.get("corresp")
        title.set("corresp", f"#{case['work_id']}-heading-00000")

    def change_source_reference(root: etree._Element) -> None:
        reference = root.find(f".//{{{TEI_NS}}}sourceDesc/{{{TEI_NS}}}bibl/{{{TEI_NS}}}ref")
        assert reference is not None and reference.get("target")
        reference.set("target", str(reference.get("target")) + "?changed=1")

    def change_source_reference_text(root: etree._Element) -> None:
        reference = root.find(f".//{{{TEI_NS}}}sourceDesc/{{{TEI_NS}}}bibl/{{{TEI_NS}}}ref")
        assert reference is not None and reference.text
        reference.text += ".changed"

    def change_source_correction_attestation(root: etree._Element) -> None:
        note = root.find(
            f".//{{{TEI_NS}}}sourceDesc/{{{TEI_NS}}}bibl/{{{TEI_NS}}}note[@type='source-correction-attestation']"
        )
        assert note is not None and note.text
        note.text += " Corrections audited."

    def change_witness_description(root: etree._Element) -> None:
        note = root.find(
            f".//{{{TEI_NS}}}sourceDesc/{{{TEI_NS}}}bibl/{{{TEI_NS}}}note[@type='witness-description']"
        )
        assert note is not None and note.text
        note.text += " Edition boundaries resolved."

    def change_human_acceptance_disclaimer(root: etree._Element) -> None:
        paragraph = root.find(f".//{{{TEI_NS}}}availability/{{{TEI_NS}}}p")
        assert paragraph is not None and paragraph.text
        paragraph.text = paragraph.text.replace(
            "human acceptance", "human acceptance has occurred"
        )

    def change_rights_disclaimer(root: etree._Element) -> None:
        paragraph = root.find(f".//{{{TEI_NS}}}availability/{{{TEI_NS}}}p")
        assert paragraph is not None and paragraph.text
        paragraph.text = paragraph.text.replace(
            "Rights clearance", "Rights clearance has been completed"
        )

    def delete_first_blank_delimiter(root: etree._Element) -> None:
        blank = root.find(
            f".//{{{TEI_NS}}}space[@type='source-blank-line']"
        )
        assert blank is not None and blank.getparent() is not None
        blank.getparent().remove(blank)

    def alter_first_line_ending(root: etree._Element) -> None:
        line = next(
            (
                item
                for item in root.findall(f".//{{{TEI_NS}}}seg[@type='source-line']")
                if item.get("subtype") in {"crlf", "lf", "cr"}
            ),
            None,
        )
        assert line is not None
        line.set("subtype", "lf" if line.get("subtype") != "lf" else "crlf")

    def drift_provenance_rights(value: dict[str, object]) -> None:
        rights = value.get("rights")
        assert isinstance(rights, dict)
        rights["clearance"] = "cleared"

    def change_table_cell_span(root: etree._Element) -> None:
        cell = root.find(
            f".//{{{TEI_NS}}}table[@n='america']/{{{TEI_NS}}}row[@n='1086']/{{{TEI_NS}}}cell[@role='population']"
        )
        assert cell is not None and cell.get("cols") == "2"
        cell.set("cols", "3")

    def detach_table_continuation(root: etree._Element) -> None:
        row = root.find(f".//{{{TEI_NS}}}table[@n='europe']/{{{TEI_NS}}}row[@n='824']")
        assert row is not None and row.get("corresp") == "#carey-enquiry-row-00823"
        row.set("corresp", "#carey-enquiry-row-00822")

    def detach_table_group(root: etree._Element) -> None:
        row = root.find(f".//{{{TEI_NS}}}table[@n='asia']/{{{TEI_NS}}}row[@n='992']")
        assert row is not None and row.get("ana")
        analysis = str(row.get("ana")).split()
        assert "#carey-enquiry-row-00991" in analysis
        row.set("ana", " ".join(value for value in analysis if value != "#carey-enquiry-row-00991"))

    def detach_table_note(root: etree._Element) -> None:
        row = root.find(f".//{{{TEI_NS}}}table[@n='asia']/{{{TEI_NS}}}row[@n='999']")
        assert row is not None and row.get("ana")
        analysis = str(row.get("ana")).split()
        assert "#carey-enquiry-row-00991" in analysis
        row.set("ana", " ".join(value for value in analysis if value != "#carey-enquiry-row-00991"))

    def detach_table_footnote(root: etree._Element) -> None:
        reference = root.find(
            f".//{{{TEI_NS}}}table[@n='europe']/{{{TEI_NS}}}row[@n='861']//{{{TEI_NS}}}ref"
        )
        assert reference is not None and reference.get("target") == "#carey-enquiry-row-00929"
        reference.set("target", "#carey-enquiry-row-00930")

    def delete_table_blank_row(root: etree._Element) -> None:
        row = root.find(f".//{{{TEI_NS}}}table[@n='europe']/{{{TEI_NS}}}row[@n='822']")
        assert row is not None and row.get("role") == "source-blank-line"
        row.getparent().remove(row)

    def delete_table_blank_marker(root: etree._Element) -> None:
        marker = root.find(
            f".//{{{TEI_NS}}}table[@n='europe']/{{{TEI_NS}}}row[@n='822']/{{{TEI_NS}}}cell/{{{TEI_NS}}}space"
        )
        assert marker is not None and marker.get("type") == "source-blank-line"
        marker.getparent().remove(marker)

    def alter_table_cell_text(root: etree._Element) -> None:
        segment = root.find(
            f".//{{{TEI_NS}}}table[@n='europe']/{{{TEI_NS}}}row[@n='823']/{{{TEI_NS}}}cell[@role='country']/{{{TEI_NS}}}seg"
        )
        assert segment is not None and segment.text
        segment.text += " altered"

    def drift_table_accounting(value: dict[str, object]) -> None:
        works = value.get("works")
        assert isinstance(works, list) and works
        tables = works[0].get("source_tables")
        assert isinstance(tables, list) and tables
        row = next(item for item in tables[0]["rows"] if item["line_number"] == 824)
        row["continuation_owner_line"] = 822

    false_positive_lines = {
        "carey-enquiry": ((493, "part of Macedonia"),),
        "drummond-greatest-thing": (
            (190, "chapter we have Love"),
            (213, "part."),
        ),
        "drummond-natural-law": ((1424, "Book of Euclid applies"),),
    }

    def inject_false_positive_heading(
        root: etree._Element, line_number: int, expected_excerpt: str
    ) -> None:
        line = root.find(
            f".//{{{TEI_NS}}}seg[@type='source-line'][@n='{line_number}']"
        )
        assert line is not None and expected_excerpt in str(line.text)
        paragraph = line.getparent()
        assert paragraph is not None and paragraph.tag == f"{{{TEI_NS}}}p"
        paragraph.tag = f"{{{TEI_NS}}}head"
        paragraph.attrib.clear()
        paragraph.set("type", "source-located-heading")
        paragraph.set("n", str(line_number))
        paragraph.set("subtype", "1")
        paragraph.set(
            "{http://www.w3.org/XML/1998/namespace}id",
            f"{case['work_id']}-heading-{line_number:05d}",
        )

    deleted = _sealed_mutation(first, tmp_path / "deleted-line", delete_first_line)
    reordered = _sealed_mutation(first, tmp_path / "reordered-lines", reorder_two_line_values)
    headless_section = _sealed_mutation(
        first, tmp_path / "missing-section-head", remove_explicit_section_head
    )
    missing_outer_language = _sealed_mutation(
        first, tmp_path / "missing-outer-language", remove_outer_language
    )
    wrong_outer_language = _sealed_mutation(
        first, tmp_path / "wrong-outer-language", change_outer_language
    )
    altered_heading = _sealed_mutation(
        first, tmp_path / "altered-heading", alter_first_mapped_heading
    )
    detached_title = _sealed_mutation(
        first, tmp_path / "detached-title", detach_first_attached_title
    )
    missing_blank = _sealed_mutation(
        first, tmp_path / "missing-blank-delimiter", delete_first_blank_delimiter
    )
    changed_ending = _sealed_mutation(
        first, tmp_path / "changed-line-ending", alter_first_line_ending
    )
    with pytest.raises(ValueError, match="candidate TEI"):
        oracle._oracle(source_manifest, deleted)
    with pytest.raises(ValueError, match="candidate TEI"):
        oracle._oracle(source_manifest, reordered)
    with pytest.raises(ValueError, match="candidate TEI"):
        oracle._oracle(source_manifest, headless_section)
    with pytest.raises(ValueError, match="candidate TEI"):
        oracle._oracle(source_manifest, altered_heading)
    with pytest.raises(ValueError, match="candidate TEI"):
        oracle._oracle(source_manifest, detached_title)
    with pytest.raises(ValueError, match="candidate TEI"):
        oracle._oracle(source_manifest, missing_blank)
    with pytest.raises(ValueError, match="candidate TEI"):
        oracle._oracle(source_manifest, changed_ending)
    with pytest.raises(ValueError, match="outer text language"):
        oracle._oracle(source_manifest, missing_outer_language)
    with pytest.raises(ValueError, match="outer text language"):
        oracle._oracle(source_manifest, wrong_outer_language)

    if case["ticket_id"] == "37c-094":
        for mutation_name, mutation in (
            ("table-cell-span-drift", change_table_cell_span),
            ("table-continuation-detachment", detach_table_continuation),
            ("table-group-detachment", detach_table_group),
            ("table-note-detachment", detach_table_note),
            ("table-footnote-detachment", detach_table_footnote),
            ("table-blank-row-deletion", delete_table_blank_row),
            ("table-blank-marker-deletion", delete_table_blank_marker),
            ("table-cell-text-drift", alter_table_cell_text),
        ):
            corrupted_table = _sealed_mutation(first, tmp_path / mutation_name, mutation)
            with pytest.raises(ValueError, match="candidate TEI"):
                oracle._oracle(source_manifest, corrupted_table)
        corrupted_table_account = _sealed_json_mutation(
            first,
            tmp_path / "table-accountability-drift",
            "source-accountability.json",
            drift_table_accounting,
        )
        with pytest.raises(ValueError, match="source-accountability"):
            oracle._oracle(source_manifest, corrupted_table_account)

    for mutation_index, (line_number, excerpt) in enumerate(
        false_positive_lines.get(case["work_id"], ())
    ):
        false_heading = _sealed_mutation(
            first,
            tmp_path / f"false-positive-heading-{mutation_index}",
            lambda root, line_number=line_number, excerpt=excerpt: inject_false_positive_heading(
                root, line_number, excerpt
            ),
        )
        with pytest.raises(ValueError, match="candidate TEI"):
            oracle._oracle(source_manifest, false_heading)

    if case["work_id"] == "drummond-greatest-thing":
        source_reference_drift = _sealed_mutation(
            first, tmp_path / "source-reference-target-drift", change_source_reference
        )
        source_path_drift = _sealed_mutation(
            first, tmp_path / "source-reference-path-drift", change_source_reference_text
        )
        correction_attestation_drift = _sealed_mutation(
            first,
            tmp_path / "source-correction-attestation-drift",
            change_source_correction_attestation,
        )
        witness_description_drift = _sealed_mutation(
            first, tmp_path / "witness-description-drift", change_witness_description
        )
        human_acceptance_drift = _sealed_mutation(
            first,
            tmp_path / "human-acceptance-disclaimer-drift",
            change_human_acceptance_disclaimer,
        )
        rights_disclaimer_drift = _sealed_mutation(
            first,
            tmp_path / "rights-disclaimer-drift",
            change_rights_disclaimer,
        )
        provenance_rights_drift = _sealed_json_mutation(
            first,
            tmp_path / "provenance-rights-drift",
            "provenance.json",
            drift_provenance_rights,
        )
        with pytest.raises(ValueError, match="sourceDesc/reference"):
            oracle._oracle(source_manifest, source_reference_drift)
        with pytest.raises(ValueError, match="sourceDesc/reference"):
            oracle._oracle(source_manifest, source_path_drift)
        with pytest.raises(ValueError, match="source correction attestation"):
            oracle._oracle(source_manifest, correction_attestation_drift)
        with pytest.raises(ValueError, match="sourceDesc witness description"):
            oracle._oracle(source_manifest, witness_description_drift)
        with pytest.raises(ValueError, match="availability disclaimer"):
            oracle._oracle(source_manifest, human_acceptance_drift)
        with pytest.raises(ValueError, match="availability disclaimer"):
            oracle._oracle(source_manifest, rights_disclaimer_drift)
        with pytest.raises(ValueError, match="provenance or nonacceptance"):
            oracle._oracle(source_manifest, provenance_rights_drift)

    assert observed_raw_reads == {source_path}


def test_selected_code_has_no_source_directory_discovery() -> None:
    paths = {
        "build/tei/gutenberg_evangelical_lib071_selected_reconstruction.py",
        "build/tei/gutenberg_evangelical_lib072_selected_reconstruction.py",
        ORACLE_PATH,
    }
    forbidden_calls = {"glob", "rglob", "iterdir", "walk", "scandir", "listdir"}
    observed_source_paths: set[str] = set()
    for relative_path in paths:
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=relative_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr not in forbidden_calls, relative_path
            if isinstance(node, ast.Name):
                assert node.id not in forbidden_calls, relative_path
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if re.fullmatch(r"raw/gutenberg/pg\d+\.txt", node.value):
                    observed_source_paths.add(node.value)
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "gutenberg_evangelical_reconstruction" not in node.module
                assert "aggregate" not in node.module.casefold()
    assert observed_source_paths == ALLOWED_SOURCE_PATHS


def test_37c136_generic_replay_preserves_exact_record_and_current_authorities() -> None:
    raw, record, payloads = _generic_37c136_inputs()
    assert json.loads(raw) == record
    assert len(payloads) == len(record["authorities"]) == 13
    authorities = {item["name"]: item for item in record["authorities"]}
    assert authorities["ticket-scope"]["sha256"] == "edaf5b0776b9d0e50a6206dd7fe2aeda153774c9972f4e54c774ddcab380fa42"
    assert authorities["validation-policy"]["sha256"] == "b91b20e855cfb3ea50d16e6d7fd8cdf9196b6dbca1d1679fe2e80aead783430c"
    assert record["converter"]["implementation_sha256"] == authorities["converter-implementation"]["sha256"]
    assert record["validator"]["implementation_sha256"] == authorities["oracle-implementation"]["sha256"]
    own = authorities["oracle-implementation"]
    assert hashlib.sha256(_canonical([{"path": own["path"], "sha256": own["sha256"]}])).hexdigest() == record["validator"]["import_closure_sha256"]
    # The production source remains the later source-bound one-hundred-note route.
    case = next(item for item in SOURCE_CASES if item["ticket_id"] == "37c-136")
    current = json.loads((ROOT / case["manifest_path"]).read_bytes())
    assert current["converter"]["implementation_path"].endswith("37c-136.note-reconstruction.py")
    assert current["validator"]["implementation_path"].endswith("37c-136.note-oracle.py")
    assert next(item for item in current["authorities"] if item["name"] == "primary-source") == authorities["primary-source"]


def _specialized_37c136_inputs() -> tuple[bytes, dict[str, object], list[tuple[str, bytes]]]:
    code_root = Path(__file__).resolve().parents[1]
    case = next(item for item in SOURCE_CASES if item["ticket_id"] == "37c-136")
    raw = (code_root / case["manifest_path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "c8e882b58f02bf4a085eda5d8d223448a9f83541158039583916549fe6c9a62b"
    record = json.loads(raw)
    assert len(record["authorities"]) == 16
    home = code_root / "tests/fixtures/reconstruction-runtime/authorities"
    frozen = {"ticket-scope": "37c136-generic-ticket.md", "validation-policy": "37c136-specialized-note-policy.json"}
    payloads = []
    for authority in record["authorities"]:
        origin = home / frozen[authority["name"]] if authority["name"] in frozen else code_root / authority["path"]
        payload = origin.read_bytes()
        assert len(payload) == authority["bytes"]
        assert hashlib.sha256(payload).hexdigest() == authority["sha256"], authority["path"]
        payloads.append((authority["path"], payload))
    own = record["validator"]
    assert hashlib.sha256(_canonical([{"path": own["implementation_path"], "sha256": own["implementation_sha256"]}])).hexdigest() == own["import_closure_sha256"]
    return raw, record, payloads


def test_37c136_specialized_record_preserves_all_sixteen_exact_authorities() -> None:
    raw, record, payloads = _specialized_37c136_inputs()
    assert json.loads(raw) == record
    assert len(payloads) == len(record["authorities"]) == 16
    assert record["converter"]["implementation_path"].endswith("37c-136.note-reconstruction.py")
    assert record["validator"]["implementation_path"].endswith("37c-136.note-oracle.py")


def test_37c136_current_specialized_notes_reproduce_and_reject_original_four_mutants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw, record, payloads = _specialized_37c136_inputs()
    case = next(item for item in SOURCE_CASES if item["ticket_id"] == "37c-136")
    current_manifest = ROOT / case["manifest_path"]
    original_current = current_manifest.read_bytes()
    mirror = tmp_path / "specialized-37c136"
    for relative, payload in payloads:
        target = mirror / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    manifest_path = mirror / case["manifest_path"]
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(raw)
    monkeypatch.setitem(globals(), "ROOT", mirror)
    manifest = contract.SourceManifest.load(manifest_path, repository_root=mirror)
    assert manifest.sha256 == hashlib.sha256(raw).hexdigest()
    converter = _load_module(record["converter"]["implementation_path"], "specialized_136_converter")
    oracle = _load_module(record["validator"]["implementation_path"], "specialized_136_oracle")
    first = contract.reconstruct(manifest, tmp_path / "specialized-first", converter._convert)
    second = contract.reconstruct(manifest, tmp_path / "specialized-second", converter._convert)
    first_report = contract.validate(manifest, first, oracle._oracle)
    second_report = contract.validate(manifest, second, oracle._oracle)
    assert first_report.status == second_report.status == "pass"
    assert first.sha256 == second.sha256
    assert first_report.sha256 == second_report.sha256
    assert first.manifest["status"] == second.manifest["status"] == "nonaccepted"
    document = etree.fromstring(first.member_bytes("content.tei.xml"))
    assert len(document.findall(f".//{{{TEI_NS}}}ref[@type='source-footnote-call']")) == 100
    assert len(document.findall(f".//{{{TEI_NS}}}note[@type='source-footnote']")) == 100
    assert len(document.xpath(".//t:div[@type='source-block' and starts-with(@corresp, '#drummond-natural-law-note-')]", namespaces={"t": TEI_NS})) == 9
    assert _run_clean_process(case, tmp_path / "specialized-clean-process") == {
        "candidate_sha256": first.sha256, "report_sha256": first_report.sha256,
    }

    def wrong_call_target(root: etree._Element) -> None:
        call = root.find(f".//{{{TEI_NS}}}ref[@type='source-footnote-call']")
        assert call is not None
        call.set("target", "#wrong-note")

    def wrong_section_owner(root: etree._Element) -> None:
        note = root.find(f".//{{{TEI_NS}}}note[@type='source-footnote']")
        assert note is not None
        note.set("corresp", "#wrong-section")

    def wrong_continuation_target(root: etree._Element) -> None:
        block = root.xpath(".//t:div[@type='source-block' and starts-with(@corresp, '#drummond-natural-law-note-')]", namespaces={"t": TEI_NS})[0]
        block.set("corresp", "#wrong-note")

    def foreign_carey_policy(root: etree._Element) -> None:
        paragraph = root.find(f".//{{{TEI_NS}}}projectDesc/{{{TEI_NS}}}p")
        assert paragraph is not None
        paragraph.text = "Carey foreign encoding policy"

    mutations = (
        (wrong_call_target, "identity or link differs from source"),
        (wrong_section_owner, "identity or link differs from source"),
        (wrong_continuation_target, "note continuation block count differs"),
        (foreign_carey_policy, "encoding policy is unrelated or incomplete"),
    )
    for index, (mutate, expected_guard) in enumerate(mutations):
        changed = _sealed_mutation(first, tmp_path / f"specialized-mutant-{index}", mutate)
        with pytest.raises(ValueError, match=expected_guard):
            contract.validate(manifest, changed, oracle._oracle)
    assert current_manifest.read_bytes() == original_current == raw
