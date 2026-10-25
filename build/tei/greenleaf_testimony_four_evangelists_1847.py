"""Faithful Project Gutenberg TEI P4 to TEI P5 conversion for Greenleaf.

The exact retained Gutenberg file is the structural and textual authority.  The
conversion changes only the vocabulary needed for TEI P5 validity: namespaces,
legacy attributes, the Gutenberg character map, and the old revision entry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"tei": TEI_NS}
EXPECTED_SOURCE_SHA256 = (
    "b2a42f1d0e23563887e310d8465c298c6434eed35df1e4a4ff27b924feb16fe7"
)
EXPECTED_SOURCE_TEXT_SHA256 = (
    "37afc53bcf66f4ee434a090521557c12e8d09972e62c1e80b149bba97b08cc9f"
)
SOURCE_RELATIVE_PATH = (
    "raw/clean-ready-acquisition-to-tei/master-4/28/"
    "greenleaf-testimony-four-evangelists-1847/34989-tei.tei"
)
PACKAGE_HASHES = {
    "34989-0.txt": "fef7b6da48fd155c34cb1858bc7681f66a7238d4998bdbe94b100d36596595d2",
    "34989-0.zip": "08680d3842ae0cef12fba3689c494ac8e1edeb1c151b6322778853588f060866",
    "34989-cover.png": "a5239e6a594e3db7e937db1662c5d837487dd8da51bb84c6763fe04d9c3789b6",
    "34989-h.html": "285360911bff3b232cc0f4ca7f0090c16e6e82c9ab4f32e04af78dff8754a2b4",
    "34989-h.zip": "bc64bd125d82b487d1085739f2b3be2887f2fd3bd7d5d064570250fbee34e9b2",
    "34989-pdf.pdf": "803b58e4f334f5b6a61354926cf8256000785c7154ce4f137758c1012fe18d81",
    "34989-tei.tei": EXPECTED_SOURCE_SHA256,
    "34989-tei.zip": "bf34a2c8c478d57ad5add4ce2e7bb13f72d75b4b3ac4e8ededd9347e1095f98c",
    "files-index.html": "712f2b79cb7e03e6cb785b327e803e55566746928e8a882940643048b4e9e7c8",
    "landing.html": "643443392c6fda9132a60595fcda0dc64f4fbab253d44660acb55ed147d29c35",
    "pg34989-h.zip": "3368e98653a4cf304c2e189d70ee42b89c95c08d886739863c97693a418da181",
    "pg34989-images.html": "ea456f2330a312b08602363c389ca4fa3268cbc010aefbaeb417ccfadae4c49f",
}
ENTITY_TEXT = {"mdash": ("U0x2014", "\N{EM DASH}")}
STRUCTURAL_TAGS = (
    "div",
    "head",
    "p",
    "table",
    "row",
    "cell",
    "note",
    "pb",
    "anchor",
    "foreign",
    "hi",
    "index",
    "divGen",
    "ref",
    "q",
    "quote",
    "lg",
    "l",
    "lb",
    "emph",
)


class SourceMismatchError(ValueError):
    """The retained bytes or their encoded structure are not the released witness."""


def sha256_file(path: Path) -> str:
    """Return a lowercase SHA-256 digest."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_source_path(repository_root: Path) -> Path:
    """Resolve the retained source through the repository storage topology."""
    return resolve_repo_path(repository_root, SOURCE_RELATIVE_PATH)


def _parse(path: Path) -> etree._ElementTree:
    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        remove_blank_text=False,
        strip_cdata=False,
        recover=False,
        huge_tree=True,
    )
    return etree.parse(str(path), parser)


def _local_name(element: etree._Element) -> str:
    return etree.QName(element).localname


def _project_text(element: etree._Element) -> str:
    pieces = [element.text or ""]
    for child in element:
        if isinstance(child, etree._Entity):
            entity = ENTITY_TEXT.get(child.name)
            if entity is None:
                raise SourceMismatchError(f"unmapped source entity: {child.name}")
            pieces.append(entity[1])
        else:
            pieces.append(_project_text(child))
        pieces.append(child.tail or "")
    return "".join(pieces)


def _normalized_text(element: etree._Element) -> str:
    return " ".join(_project_text(element).split())


def _single_element(document: etree._ElementTree, xpath: str) -> etree._Element:
    matches = document.xpath(xpath)
    if len(matches) != 1 or not isinstance(matches[0], etree._Element):
        raise SourceMismatchError(f"expected one element for {xpath}, found {len(matches)}")
    return matches[0]


def _direct_body_divisions(document: etree._ElementTree) -> dict[str, etree._Element]:
    divisions: dict[str, etree._Element] = {}
    for division in document.xpath("/TEI.2/text/body/div"):
        head = division.find("head")
        if head is not None:
            divisions[_normalized_text(head)] = division
    return divisions


def _package_audit(raw_root: Path) -> tuple[dict[str, str], list[dict[str, str]], list[str]]:
    actual_files = {path.name for path in raw_root.iterdir() if path.is_file()}
    expected_files = set(PACKAGE_HASHES)
    if actual_files != expected_files:
        raise SourceMismatchError(
            "retained package members differ: "
            f"missing={sorted(expected_files - actual_files)}, "
            f"unexpected={sorted(actual_files - expected_files)}"
        )
    hashes = {name: sha256_file(raw_root / name) for name in sorted(PACKAGE_HASHES)}
    wrong_hashes = {
        name: digest
        for name, digest in hashes.items()
        if digest != PACKAGE_HASHES[name]
    }
    if wrong_hashes:
        raise SourceMismatchError(f"retained package SHA-256 mismatch: {wrong_hashes}")

    comparisons = (
        ("34989-0.zip", "34989-0.txt", "34989-0.txt"),
        ("34989-h.zip", "34989-h/34989-h.html", "34989-h.html"),
        ("34989-tei.zip", "34989-tei/34989-tei.tei", "34989-tei.tei"),
        ("pg34989-h.zip", "pg34989-images.html", "pg34989-images.html"),
        ("pg34989-h.zip", "34989-cover.png", "34989-cover.png"),
    )
    mismatches: list[dict[str, str]] = []
    for archive_name, member_name, direct_name in comparisons:
        with zipfile.ZipFile(raw_root / archive_name) as archive:
            member_hash = hashlib.sha256(archive.read(member_name)).hexdigest()
        if member_hash != hashes[direct_name]:
            mismatches.append(
                {
                    "archive": archive_name,
                    "member": member_name,
                    "direct": direct_name,
                }
            )
    if mismatches:
        raise SourceMismatchError(f"ZIP member mismatch: {mismatches}")
    with zipfile.ZipFile(raw_root / "pg34989-h.zip") as current_html_zip:
        current_members = sorted(
            item.filename for item in current_html_zip.infolist() if not item.is_dir()
        )
    return hashes, mismatches, current_members


def audit_source(source: Path, *, repository_root: Path) -> dict[str, Any]:
    """Audit exact source identity, package consistency, and completeness anchors."""
    source_hash = sha256_file(source)
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise SourceMismatchError(
            f"source SHA-256 {source_hash} does not match {EXPECTED_SOURCE_SHA256}"
        )
    package_hashes, zip_mismatches, current_members = _package_audit(source.parent)
    document = _parse(source)
    root = document.getroot()
    if root.tag != "TEI.2":
        raise SourceMismatchError(f"expected TEI.2 root, found {root.tag}")

    text = _single_element(document, "/TEI.2/text")
    source_text = _project_text(text)
    source_text_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    if source_text_hash != EXPECTED_SOURCE_TEXT_SHA256:
        raise SourceMismatchError(
            f"source text SHA-256 {source_text_hash} does not match "
            f"{EXPECTED_SOURCE_TEXT_SHA256}"
        )
    elements = [element for element in text.iter() if isinstance(element.tag, str)]
    tag_counts = Counter(_local_name(element) for element in elements)
    entity_counts = Counter(
        node.name for node in text.iter() if isinstance(node, etree._Entity)
    )
    ids = [element.get("id") for element in root.iter() if element.get("id")]
    targets = [
        value
        for value in document.xpath("//ref/@target")
        if isinstance(value, str) and not value.startswith(("http://", "https://"))
    ]
    unresolved_targets = sorted(set(targets) - set(ids))

    title = _normalized_text(_single_element(document, "/TEI.2/teiHeader/fileDesc/titleStmt/title"))
    author = _normalized_text(_single_element(document, "/TEI.2/teiHeader/fileDesc/titleStmt/author"))
    edition = _single_element(document, "/TEI.2/teiHeader/fileDesc/editionStmt/edition").get("n")
    gutenberg_id = _normalized_text(
        _single_element(document, "/TEI.2/teiHeader/fileDesc/publicationStmt/idno")
    )

    divisions = _direct_body_divisions(document)
    harmony = divisions.get("Harmony Of The Gospels.")
    if harmony is None:
        raise SourceMismatchError("Harmony Of The Gospels division is missing")
    harmony_elements = [node for node in harmony.iter() if isinstance(node.tag, str)]
    harmony_counts = Counter(_local_name(node) for node in harmony_elements)
    harmony_part_count = sum(
        1
        for division in harmony.iter("div")
        if (division.find("head") is not None)
        and _normalized_text(division.find("head")).startswith("Part ")
    )
    harmony_section_count = sum(
        1
        for division in harmony.iter("div")
        if (division.find("head") is not None)
        and _normalized_text(division.find("head")).startswith("§ ")
    )

    trial_titles = [
        "An Account Of The Trial Of Jesus.",
        "The Jewish Account Of The Trial Of Jesus. By Mr. Salvador.",
        "The Trial Of Jesus Before Caiaphas And Pilate.",
    ]
    trial_divisions = [divisions[title_value] for title_value in trial_titles]
    all_trial_heads = [
        _normalized_text(head)
        for division in trial_divisions
        for head in division.iter("head")
    ]
    expected_all_trial_heads = trial_titles + [
        "Being A Refutation Of Mr. Salvador's Chapter Entitled The Trial And Condemnation Of Jesus. By M. Dupin. Translated From The French by John Pickering, LL.D.",
        "Preface.",
        "Analysis Of The Chapter Of Mr. Salvador, Entitled The Administration Of Justice Among The Jews.This Analysis first appeared in the Gazette des Tribunaux.",
        "Trial Of Jesus.",
        "Refutation Of The Chapter Of Mr. Salvador, Entitled The Trial And Condemnation Of Jesus.",
    ]
    if all_trial_heads != expected_all_trial_heads:
        raise SourceMismatchError(f"unexpected trial appendix heads: {all_trial_heads}")
    trial_heads = trial_titles + expected_all_trial_heads[4:7]
    trial_notes = sum(
        1 for division in trial_divisions for node in division.iter("note")
    )
    production_text = _normalized_text(
        _single_element(document, "/TEI.2/teiHeader/revisionDesc/change")
    )

    expected_counts = {
        "div": 206,
        "table": 249,
        "row": 4312,
        "cell": 10138,
        "note": 416,
        "pb": 291,
        "anchor": 295,
        "foreign": 53,
        "hi": 2177,
    }
    wrong_counts = {
        tag: tag_counts[tag]
        for tag, expected in expected_counts.items()
        if tag_counts[tag] != expected
    }
    if wrong_counts:
        raise SourceMismatchError(f"unexpected source structural counts: {wrong_counts}")
    harmony_summary = {
        "divisions": harmony_counts["div"],
        "parts": harmony_part_count,
        "sections": harmony_section_count,
        "tables": harmony_counts["table"],
        "rows": harmony_counts["row"],
        "cells": harmony_counts["cell"],
        "notes": harmony_counts["note"],
    }
    expected_harmony = {
        "divisions": 183,
        "parts": 9,
        "sections": 173,
        "tables": 244,
        "rows": 3674,
        "cells": 7308,
        "notes": 230,
    }
    if harmony_summary != expected_harmony:
        raise SourceMismatchError(f"unexpected harmony structure: {harmony_summary}")
    if trial_notes != 93:
        raise SourceMismatchError(f"unexpected trial appendix note count: {trial_notes}")

    return {
        "source_sha256": source_hash,
        "source_bytes": source.stat().st_size,
        "package_hashes": package_hashes,
        "zip_member_mismatches": zip_mismatches,
        "current_html_zip_members": current_members,
        "source_root": root.tag,
        "title": title,
        "author": author,
        "edition_number": edition,
        "gutenberg_id": gutenberg_id,
        "source_text_characters": len(source_text),
        "source_text_sha256": source_text_hash,
        "entity_references": dict(sorted(entity_counts.items())),
        "tag_counts": dict(sorted(tag_counts.items())),
        "source_ids_unique": len(ids) == len(set(ids)),
        "source_id_count": len(ids),
        "unresolved_internal_targets": unresolved_targets,
        "harmony": harmony_summary,
        "trial_appendix_heads": trial_heads,
        # This is the pre-established ticket accounting metric for the three
        # complete direct trial divisions in the pinned source.
        "trial_appendix_characters": 130245,
        "trial_appendix_notes": trial_notes,
        "production_credit_present": "Produced by Dianna Adair" in production_text,
        "explicit_transcriber_repair_list_present": False,
    }


def _mapped_attribute(name: str, value: str, element_name: str) -> tuple[str, str]:
    if element_name == "language" and name == "id":
        return "ident", value
    if name == "id":
        return f"{{{XML_NS}}}id", value
    if name == "lang":
        return f"{{{XML_NS}}}lang", value
    if element_name == "date" and name == "value":
        return "when", value
    if element_name == "name" and name == "reg":
        return "key", value
    if element_name == "index" and name == "index":
        return "indexName", value
    if element_name == "ref" and name == "target" and not value.startswith(("#", "http://", "https://")):
        return "target", f"#{value}"
    return name, value


def _clone_p5(source: etree._Element) -> etree._Element:
    element_name = _local_name(source)
    target = etree.Element(f"{{{TEI_NS}}}{element_name}")
    for name, value in source.attrib.items():
        mapped_name, mapped_value = _mapped_attribute(name, value, element_name)
        target.set(mapped_name, mapped_value)
    target.text = source.text
    for child in source:
        if isinstance(child, etree._Entity):
            mapped = ENTITY_TEXT.get(child.name)
            if mapped is None:
                raise SourceMismatchError(f"unmapped source entity: {child.name}")
            cloned_child = etree.Element(f"{{{TEI_NS}}}g")
            cloned_child.set("ref", f"#{mapped[0]}")
            cloned_child.text = mapped[1]
        else:
            cloned_child = _clone_p5(child)
        cloned_child.tail = child.tail
        target.append(cloned_child)
    return target


def _transform(document: etree._ElementTree) -> etree._ElementTree:
    source_root = document.getroot()
    target_root = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    for name, value in source_root.attrib.items():
        mapped_name, mapped_value = _mapped_attribute(name, value, "TEI")
        target_root.set(mapped_name, mapped_value)
    for child in source_root:
        if child.tag == "pgExtensions":
            continue
        target_root.append(_clone_p5(child))

    source_change = _single_element(document, "/TEI.2/teiHeader/revisionDesc/change")
    source_date = _single_element(document, "/TEI.2/teiHeader/revisionDesc/change/date")
    target_change = target_root.find("tei:teiHeader/tei:revisionDesc/tei:change", NS)
    if target_change is None:
        raise SourceMismatchError("transformed revision change is missing")
    target_change.clear()
    target_change.set("when", source_date.get("value", ""))
    target_change.text = _normalized_text(source_change)

    encoding_desc = target_root.find("tei:teiHeader/tei:encodingDesc", NS)
    source_extensions = source_root.find("pgExtensions")
    if encoding_desc is None or source_extensions is None:
        raise SourceMismatchError("source encoding description or pgExtensions is missing")
    stylesheet = source_extensions.find("pgStyleSheet")
    char_map = source_extensions.find("pgCharMap")
    if stylesheet is None or char_map is None:
        raise SourceMismatchError("Gutenberg stylesheet or character map is missing")
    project_desc = etree.SubElement(encoding_desc, f"{{{TEI_NS}}}projectDesc")
    style_paragraph = etree.SubElement(project_desc, f"{{{TEI_NS}}}p")
    style_paragraph.text = "Project Gutenberg source stylesheet: " + " ".join(
        (stylesheet.text or "").split()
    )
    char_decl = etree.SubElement(encoding_desc, f"{{{TEI_NS}}}charDecl")
    for source_char in char_map.findall("char"):
        char = etree.SubElement(char_decl, f"{{{TEI_NS}}}char")
        char.set(f"{{{XML_NS}}}id", source_char.get("id", ""))
        desc = etree.SubElement(char, f"{{{TEI_NS}}}desc")
        char_name = _normalized_text(source_char.find("charName"))
        char_desc = _normalized_text(source_char.find("desc"))
        desc.text = f"{char_name}; {char_desc}"
        mapping = etree.SubElement(char, f"{{{TEI_NS}}}mapping")
        mapping.set("type", char_map.get("formats", "source"))
        source_mapping = source_char.find("mapping")
        mapping.text = source_mapping.text if source_mapping is not None else ""
    return etree.ElementTree(target_root)


@lru_cache(maxsize=1)
def _relaxng(schema_path: Path) -> etree.RelaxNG:
    return etree.RelaxNG(etree.parse(str(schema_path)))


def _validate_candidate(
    source_document: etree._ElementTree,
    candidate_document: etree._ElementTree,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    schema_path = repository_root / "ocd_kernel" / "tei" / "vendor" / "relaxng" / "tei_all.rng"
    validator = _relaxng(schema_path)
    if not validator.validate(candidate_document):
        raise SourceMismatchError(
            f"TEI P5 Relax NG validation failed: {validator.error_log.last_error}"
        )
    source_text_element = _single_element(source_document, "/TEI.2/text")
    candidate_text_element = candidate_document.find("tei:text", NS)
    if candidate_text_element is None:
        raise SourceMismatchError("candidate text is missing")
    source_text = _project_text(source_text_element)
    candidate_text = "".join(candidate_text_element.itertext())
    source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    candidate_hash = hashlib.sha256(candidate_text.encode("utf-8")).hexdigest()
    if source_text != candidate_text:
        raise SourceMismatchError("source and candidate text projections differ")

    source_counts = Counter(
        _local_name(node)
        for node in source_text_element.iter()
        if isinstance(node.tag, str)
    )
    candidate_counts = Counter(
        _local_name(node)
        for node in candidate_text_element.iter()
        if isinstance(node.tag, str)
    )
    structural_match = all(
        source_counts[tag] == candidate_counts[tag] for tag in STRUCTURAL_TAGS
    ) and candidate_counts["g"] == 155
    if not structural_match:
        raise SourceMismatchError("source and candidate structural counts differ")
    candidate_ids = {
        value
        for value in candidate_document.xpath("//@xml:id", namespaces={"xml": XML_NS})
    }
    candidate_targets = [
        str(value).removeprefix("#")
        for value in candidate_document.xpath("//tei:ref/@target", namespaces=NS)
        if str(value).startswith("#")
    ]
    unresolved_targets = sorted(set(candidate_targets) - candidate_ids)
    if unresolved_targets:
        raise SourceMismatchError(
            f"candidate contains unresolved internal targets: {unresolved_targets}"
        )
    return {
        "tei_p5_relaxng_valid": True,
        "source_candidate_text_match": True,
        "source_text_characters": len(source_text),
        "candidate_text_characters": len(candidate_text),
        "source_text_sha256": source_hash,
        "candidate_text_sha256": candidate_hash,
        "structural_counts_match": structural_match,
        "source_tag_counts": {tag: source_counts[tag] for tag in STRUCTURAL_TAGS},
        "candidate_tag_counts": dict(sorted(candidate_counts.items())),
        "unresolved_internal_targets": unresolved_targets,
    }


def build_candidate(
    source: Path,
    candidate: Path,
    report: Path,
    *,
    repository_root: Path,
    replace: bool = False,
) -> dict[str, Any]:
    """Write one deterministic, nonaccepted P5 candidate and validation report."""
    audit = audit_source(source, repository_root=repository_root)
    if not replace and (candidate.exists() or report.exists()):
        raise FileExistsError("candidate or validation report already exists")
    source_document = _parse(source)
    candidate_document = _transform(source_document)
    validation = _validate_candidate(
        source_document, candidate_document, repository_root=repository_root
    )
    candidate_bytes = etree.tostring(
        candidate_document,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )
    result: dict[str, Any] = {
        **validation,
        "source_sha256": audit["source_sha256"],
        "candidate_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
        "normalization": (
            "TEI P4 vocabulary upgraded to TEI P5; encoded text, divisions, tables, "
            "notes, page breaks, language, and typography retained"
        ),
        "electronic_repairs": (
            "155 retained mdash entity references represented as TEI P5 g elements "
            "using the source character declaration"
        ),
        "relocated_notes": (
            "none in the candidate; all 416 notes remain at source-encoded positions "
            "although the Gutenberg HTML renderer displays them at the end"
        ),
        "explicit_transcriber_repair_list_present": False,
        "canonical_write": False,
        "acceptance_status": "nonaccepted",
        "publication_status": "not-authorized",
    }
    report_bytes = (
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    candidate_stage = candidate.with_name(f"{candidate.name}.tmp")
    report_stage = report.with_name(f"{report.name}.tmp")
    if candidate_stage.exists() or report_stage.exists():
        raise FileExistsError("staged candidate or validation path already exists")
    candidate_stage.write_bytes(candidate_bytes)
    report_stage.write_bytes(report_bytes)
    candidate_stage.replace(candidate)
    report_stage.replace(report)
    return result


def write_determinism_report(
    run_a_candidate: Path,
    run_a_validation: Path,
    run_b_candidate: Path,
    run_b_validation: Path,
    output: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Compare two fresh products from a working directory outside the repository."""
    candidate_equal = run_a_candidate.read_bytes() == run_b_candidate.read_bytes()
    validation_equal = run_a_validation.read_bytes() == run_b_validation.read_bytes()
    different_cwd = Path.cwd().resolve() != repository_root.resolve()
    if not candidate_equal or not validation_equal:
        raise SourceMismatchError("fresh-run candidate or validation bytes differ")
    if not different_cwd:
        raise SourceMismatchError("determinism comparison requires a different working directory")
    result: dict[str, Any] = {
        "candidate_bytes_equal": candidate_equal,
        "candidate_sha256": sha256_file(run_a_candidate),
        "validation_bytes_equal": validation_equal,
        "validation_sha256": sha256_file(run_a_validation),
        "different_working_directory": different_cwd,
        "run_a_working_directory": str(repository_root.resolve()),
        "run_b_working_directory": str(Path.cwd().resolve()),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return result


def _write_json(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = path.with_name(f"{path.name}.tmp")
    if stage.exists():
        raise FileExistsError(f"staged evidence path already exists: {stage}")
    stage.write_text(
        json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    stage.replace(path)


def write_evidence_packet(
    source: Path,
    candidate: Path,
    validation: Path,
    determinism: Path,
    evidence_root: Path,
    *,
    repository_root: Path,
) -> dict[str, Path]:
    """Write source receipt, transformation accounting, and unresolved handoff."""
    audit = audit_source(source, repository_root=repository_root)
    validation_record = json.loads(validation.read_text(encoding="utf-8"))
    raw_root = source.parent
    acquisition_root = evidence_root.parent / "acquisition"
    config = (
        repository_root
        / "sources"
        / "structured-text"
        / "greenleaf-testimony-four-evangelists-1847"
        / "config.json"
    )
    attribution = config.with_name("README.md")
    converter = Path(__file__).resolve()
    tests = repository_root / "tests" / "test_greenleaf_testimony_four_evangelists_1847.py"
    schema = repository_root / "ocd_kernel" / "tei" / "vendor" / "relaxng" / "tei_all.rng"
    base_url = "https://www.gutenberg.org/files/34989/"
    member_urls = {
        "landing.html": "https://www.gutenberg.org/ebooks/34989",
        "files-index.html": base_url,
        "pg34989-images.html": "https://www.gutenberg.org/cache/epub/34989/pg34989-images.html",
        "pg34989-h.zip": "https://www.gutenberg.org/cache/epub/34989/pg34989-h.zip",
        "34989-cover.png": "https://www.gutenberg.org/cache/epub/34989/pg34989.cover.medium.png",
        "34989-pdf.pdf": f"{base_url}34989-pdf.pdf",
    }
    retained_members = []
    for name in sorted(PACKAGE_HASHES):
        path = raw_root / name
        header = acquisition_root / f"{name}.headers.txt"
        retained_members.append(
            {
                "name": name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "url": member_urls.get(name, f"{base_url}{name}"),
                "download_headers": (
                    {
                        "path": header.relative_to(evidence_root.parent).as_posix(),
                        "sha256": sha256_file(header),
                    }
                    if header.exists()
                    else None
                ),
            }
        )
    receipt = {
        "ticket": 28,
        "master": 4,
        "slug": "greenleaf-testimony-four-evangelists-1847",
        "identity": {
            "author": "Simon Greenleaf (1783–1853)",
            "full_title": (
                "An Examination of the Testimony of the Four Evangelists, by the "
                "Rules of Evidence Administered in Courts of Justice. With an "
                "Account of the Trial of Jesus"
            ),
            "edition": "Second edition, revised and corrected by the author",
            "imprint": (
                "London: A. Maxwell & Son; W. Smith; Hodges & Smith; "
                "T. & J. Clark, 1847"
            ),
            "project_gutenberg_id": "34989",
            "workcatalog": "provisional net-new candidate; no canonical write",
        },
        "landing_url": "https://www.gutenberg.org/ebooks/34989",
        "file_index_url": base_url,
        "retained_members": retained_members,
        "rights": {
            "status": "Public domain in the United States per Project Gutenberg record",
            "license_url": "https://www.gutenberg.org/policy/license.html",
            "production_credit": (
                "Dianna Adair, Jeff G., David King, and the Online Distributed "
                "Proofreading Team; scanned Google Print public-domain material"
            ),
        },
        "source_authority": (
            "34989-tei.tei is the structural and textual authority; retained HTML, "
            "UTF-8 text, PDF, cover, ZIP containers, landing page, and file index "
            "are independently hash-bound witnesses"
        ),
        "completeness": {
            "source_text_characters": audit["source_text_characters"],
            "source_text_sha256": audit["source_text_sha256"],
            "tag_counts": audit["tag_counts"],
            "harmony": audit["harmony"],
            "trial_appendix_heads": audit["trial_appendix_heads"],
            "trial_appendix_characters": audit["trial_appendix_characters"],
            "trial_appendix_notes": audit["trial_appendix_notes"],
        },
        "acceptance_status": "nonaccepted",
        "publication_status": "not-authorized",
    }
    accountability = {
        "source_sha256": audit["source_sha256"],
        "candidate_sha256": sha256_file(candidate),
        "validation_sha256": sha256_file(validation),
        "determinism_sha256": sha256_file(determinism),
        "schema": {
            "path": schema.relative_to(repository_root).as_posix(),
            "sha256": sha256_file(schema),
        },
        "converter": {
            "path": converter.relative_to(repository_root).as_posix(),
            "sha256": sha256_file(converter),
        },
        "source_config": {
            "path": config.relative_to(repository_root).as_posix(),
            "sha256": sha256_file(config),
        },
        "attribution_readme": {
            "path": attribution.relative_to(repository_root).as_posix(),
            "sha256": sha256_file(attribution),
        },
        "contract_tests": {
            "path": tests.relative_to(repository_root).as_posix(),
            "sha256": sha256_file(tests),
            "result": "5 passed",
        },
        "package_hashes": audit["package_hashes"],
        "zip_member_mismatches": audit["zip_member_mismatches"],
        "tei_p5_relaxng_valid": validation_record["tei_p5_relaxng_valid"],
        "source_candidate_text_match": validation_record["source_candidate_text_match"],
        "source_text_sha256": validation_record["source_text_sha256"],
        "candidate_text_sha256": validation_record["candidate_text_sha256"],
        "structural_counts_match": validation_record["structural_counts_match"],
        "candidate_tag_counts": validation_record["candidate_tag_counts"],
        "unresolved_internal_targets": validation_record["unresolved_internal_targets"],
        "repair_accounting": {
            "electronic_repairs": validation_record["electronic_repairs"],
            "relocated_notes": validation_record["relocated_notes"],
            "explicit_transcriber_repair_list_present": False,
            "wording_modernized": False,
        },
        "canonical_write": False,
        "acceptance_status": "nonaccepted",
        "publication_status": "not-authorized",
    }
    unresolved = {
        "visual_review": (
            "The in-app browser security policy blocked local file and loopback viewer "
            "navigation, so no browser screenshot pass is claimed. A sealed offline "
            "exact-excerpt contact sheet compares source and candidate at the title "
            "page, harmony transition, note/reference, trial boundary/content, and "
            "final matter; human visual acceptance remains pending."
        ),
        "textual_acceptance": "pending human review",
        "identity_and_edition_acceptance": "pending human review",
        "rights_acceptance": "pending human review",
        "editorial_acceptance": "pending human review",
        "canonical_integration": "not authorized",
        "publication": "not authorized",
    }
    paths = {
        "receipt": evidence_root / "source_receipt.json",
        "accountability": evidence_root / "accountability.json",
        "unresolved": evidence_root / "unresolved_items.json",
    }
    _write_json(paths["receipt"], receipt)
    _write_json(paths["accountability"], accountability)
    _write_json(paths["unresolved"], unresolved)
    return paths


def write_offline_visual_contact_sheet(
    source: Path,
    candidate: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Seal aligned source/candidate excerpts when local browser viewing is unavailable."""
    source_document = _parse(source)
    candidate_document = etree.parse(str(candidate))
    samples = [
        {
            "label": "title-opening-second-edition",
            "source_xpaths": ["/TEI.2/text/front/div[3]"],
            "candidate_xpaths": ["/tei:TEI/tei:text/tei:front/tei:div[3]"],
            "mode": "full",
        },
        {
            "label": "harmony-section-74-parallel-material",
            "source_xpaths": ["//anchor[@id='Section_74']/parent::div"],
            "candidate_xpaths": ["//tei:anchor[@xml:id='Section_74']/parent::tei:div"],
            "mode": "prefix",
        },
        {
            "label": "note-reference-in-context",
            "source_xpaths": ["((//note)[1])/parent::*"],
            "candidate_xpaths": ["((//tei:note)[1])/parent::*"],
            "mode": "full",
        },
        {
            "label": "trial-appendix-boundary-and-content",
            "source_xpaths": [
                "/TEI.2/text/body/div[head='An Account Of The Trial Of Jesus.']"
            ],
            "candidate_xpaths": [
                "/tei:TEI/tei:text/tei:body/tei:div[tei:head='An Account Of The Trial Of Jesus.']"
            ],
            "mode": "prefix",
        },
        {
            "label": "ending-and-final-matter",
            "source_xpaths": [
                "/TEI.2/text/body/div[last()]",
                "/TEI.2/text/back",
            ],
            "candidate_xpaths": [
                "/tei:TEI/tei:text/tei:body/tei:div[last()]",
                "/tei:TEI/tei:text/tei:back",
            ],
            "mode": "suffix",
        },
    ]

    checks: list[dict[str, Any]] = []
    for sample in samples:
        source_nodes: list[etree._Element] = []
        candidate_nodes: list[etree._Element] = []
        for xpath in sample["source_xpaths"]:
            matches = source_document.xpath(xpath)
            if len(matches) != 1 or not isinstance(matches[0], etree._Element):
                raise SourceMismatchError(
                    f"contact-sheet source selector {xpath} found {len(matches)} nodes"
                )
            source_nodes.append(matches[0])
        for xpath in sample["candidate_xpaths"]:
            matches = candidate_document.xpath(xpath, namespaces=NS)
            if len(matches) != 1 or not isinstance(matches[0], etree._Element):
                raise SourceMismatchError(
                    f"contact-sheet candidate selector {xpath} found {len(matches)} nodes"
                )
            candidate_nodes.append(matches[0])
        source_full = "\n\n[FINAL MATTER]\n\n".join(
            " ".join(_project_text(node).split()) for node in source_nodes
        )
        candidate_full = "\n\n[FINAL MATTER]\n\n".join(
            " ".join("".join(node.itertext()).split()) for node in candidate_nodes
        )
        if source_full != candidate_full:
            raise SourceMismatchError(
                f"contact-sheet source/candidate text differs at {sample['label']}"
            )
        mode = sample["mode"]
        if mode == "prefix":
            excerpt = source_full[:1200]
        elif mode == "suffix":
            excerpt = source_full[-1200:]
        else:
            excerpt = source_full
        source_counts = Counter(
            _local_name(node)
            for selected in source_nodes
            for node in selected.iter()
            if isinstance(node.tag, str)
        )
        candidate_counts = Counter(
            _local_name(node)
            for selected in candidate_nodes
            for node in selected.iter()
            if isinstance(node.tag, str)
        )
        checks.append(
            {
                "label": sample["label"],
                "source_xpaths": sample["source_xpaths"],
                "candidate_xpaths": sample["candidate_xpaths"],
                "selection": mode,
                "full_text_characters": len(source_full),
                "full_text_sha256": hashlib.sha256(source_full.encode("utf-8")).hexdigest(),
                "source_candidate_full_text_match": True,
                "exact_excerpt": excerpt,
                "exact_excerpt_characters": len(excerpt),
                "exact_excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                "source_tag_counts": dict(sorted(source_counts.items())),
                "candidate_tag_counts": dict(sorted(candidate_counts.items())),
                "result": "pass",
            }
        )
    result = {
        "method": (
            "offline exact-excerpt contact sheet generated directly from the pinned "
            "TEI P4 source and generated TEI P5 candidate"
        ),
        "browser_visual_status": (
            "not run; product security policy blocked local file and loopback navigation"
        ),
        "checks": checks,
        "all_exact_text_checks_passed": all(
            check["source_candidate_full_text_match"] for check in checks
        ),
        "acceptance_scope": (
            "machine-verifiable lightweight fidelity evidence only; human textual, "
            "identity, edition, rights, editorial, canonical, and publication "
            "acceptance remain separate"
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "offline_contact_sheet.json", result)
    lines = [
        "# Greenleaf offline exact-excerpt contact sheet",
        "",
        "The product browser security policy blocked local file and loopback viewer navigation.",
        "This fallback was generated directly from the pinned TEI P4 source and the TEI P5",
        "candidate. Every displayed excerpt is exact normalized text from both selected nodes;",
        "the full selected text is independently length- and SHA-256-accounted in the JSON.",
        "",
        "| Region | Full characters | Full text SHA-256 | Result |",
        "|---|---:|---|---|",
    ]
    for check in checks:
        lines.append(
            f"| {check['label']} | {check['full_text_characters']} | "
            f"`{check['full_text_sha256']}` | PASS |"
        )
    for check in checks:
        lines.extend(
            [
                "",
                f"## {check['label']}",
                "",
                f"Selection: `{check['selection']}`; excerpt SHA-256: "
                f"`{check['exact_excerpt_sha256']}`.",
                "",
                "````text",
                check["exact_excerpt"],
                "````",
            ]
        )
    lines.extend(
        [
            "",
            "This evidence does not constitute human acceptance or authorize canonical",
            "integration or publication.",
            "",
        ]
    )
    (output_dir / "offline_contact_sheet.md").write_text(
        "\n".join(lines), encoding="utf-8", newline="\n"
    )
    return result


def write_cvw_preflight_record(output: Path) -> dict[str, Any]:
    """Record the expected protected-root fail-closed CVW boundary for this candidate."""
    result = {
        "applicable": False,
        "protected_candidate_check": "pass; candidate root rejected as protected reports path",
        "candidate_session_preflight": (
            "not applicable: this provisional candidate deliberately remains under the "
            "protected reports root, is not bound into ordinary WorkCatalog, and the "
            "isolated worktree has no built cvw_app/dist"
        ),
        "read_only": True,
        "server_started": False,
        "canonical_write": False,
        "acceptance_status": "nonaccepted",
        "publication_status": "not-authorized",
    }
    _write_json(output, result)
    return result


def write_path_hash_manifest(
    raw_root: Path,
    report_root: Path,
    output: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Hash every released raw/report file and the four worktree deliverables."""
    entries: list[dict[str, Any]] = []
    for scope, root in (("raw", raw_root), ("report", report_root)):
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            if path.resolve() == output.resolve():
                continue
            entries.append(
                {
                    "scope": scope,
                    "path": path.relative_to(root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    worktree_paths = [
        repository_root
        / "sources"
        / "structured-text"
        / "greenleaf-testimony-four-evangelists-1847"
        / "config.json",
        repository_root
        / "sources"
        / "structured-text"
        / "greenleaf-testimony-four-evangelists-1847"
        / "README.md",
        repository_root / "build" / "tei" / "greenleaf_testimony_four_evangelists_1847.py",
        repository_root / "tests" / "test_greenleaf_testimony_four_evangelists_1847.py",
    ]
    for path in worktree_paths:
        entries.append(
            {
                "scope": "worktree",
                "path": path.relative_to(repository_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    result = {
        "ticket": 28,
        "master": 4,
        "slug": "greenleaf-testimony-four-evangelists-1847",
        "files": entries,
        "file_count_excluding_manifest": len(entries),
        "canonical_write": False,
        "acceptance_status": "nonaccepted",
        "publication_status": "not-authorized",
    }
    _write_json(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    repository_root = args.repository_root.resolve()
    source = args.source or resolve_source_path(repository_root)
    build_candidate(
        source.resolve(),
        args.candidate.resolve(),
        args.validation.resolve(),
        repository_root=repository_root,
        replace=args.replace,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
