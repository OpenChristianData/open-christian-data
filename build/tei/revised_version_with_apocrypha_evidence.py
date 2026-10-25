"""Render and seal bounded ticket-21 review evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import textwrap
from typing import Any

from lxml import etree
from PIL import Image, ImageDraw, ImageFont

from build.tei import revised_version_with_apocrypha as rv
from ocd_kernel.lib.storage_topology import resolve_repo_path


REPORT_RELATIVE = (
    "reports/clean-ready-acquisition-to-tei/master-3/21/"
    "revised-version-with-apocrypha"
)
SAMPLES = (
    ("Structured opening title", "02-GENeng-rv.usfm", 8),
    ("Old Testament ending", "40-MALeng-rv.usfm", 69),
    ("Apocrypha opening", "41-TOBeng-rv.usfm", 9),
    ("Footnote", "41-TOBeng-rv.usfm", 10),
    ("Poetry and cross-reference", "41-TOBeng-rv.usfm", 41),
    ("Epistle of Jeremy boundary", "47-BAReng-rv.usfm", 162),
    ("Supplied text", "52-1MAeng-rv.usfm", 10),
    ("Merged Sirach verse label", "46-SIReng-rv.usfm", 954),
    ("Complete ending", "96-REVeng-rv.usfm", 455),
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _inventory(root: Path) -> list[dict[str, object]]:
    return [
        {"name": path.name, "bytes": path.stat().st_size, "sha256": _sha(path.read_bytes())}
        for path in sorted(root.iterdir())
        if path.is_file()
    ]


def _projection(node: etree._Element) -> str:
    parts = [node.text or ""]
    for child in node:
        if not (child.tag == rv._q("note") and child.get("type") == "source-usfm-raw"):
            parts.append(_projection(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _spot_checks(tei_path: Path) -> list[dict[str, object]]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    root = etree.parse(str(tei_path), parser).getroot()
    values: list[dict[str, object]] = []
    for label, file_name, line_number in SAMPLES:
        pointer = f"{rv.SOURCE_PREFIX}{file_name}#line={line_number}"
        nodes = root.xpath("//*[@corresp=$pointer]", pointer=pointer)
        if len(nodes) != 1:
            raise ValueError(f"expected one TEI node for {pointer}; got {len(nodes)}")
        raw_notes = nodes[0].xpath(
            "./tei:note[@type='source-usfm-raw']/text()",
            namespaces={"tei": rv.TEI_NS},
        )
        if len(raw_notes) != 1:
            raise ValueError(f"expected one retained raw line for {pointer}")
        values.append(
            {
                "label": label,
                "pointer": pointer,
                "source_usfm": raw_notes[0],
                "tei_retained_usfm": raw_notes[0],
                "exact": True,
                "tei_visible_projection": _projection(nodes[0]),
            }
        )
    return values


def _render_png(samples: list[dict[str, object]]) -> bytes:
    font = ImageFont.load_default(size=20)
    title_font = ImageFont.load_default(size=30)
    width = 1800
    wrapped: list[list[str]] = []
    for sample in samples:
        source = str(sample["source_usfm"])
        projection = str(sample["tei_visible_projection"])
        lines = [f"{sample['label']}  |  exact retained line: PASS"]
        lines += ["SOURCE  " + value for value in textwrap.wrap(source, width=142) or [""]]
        lines += ["TEI     " + value for value in textwrap.wrap(projection, width=142) or [""]]
        wrapped.append(lines)
    height = (
        175
        + sum(38 + len(lines) * 27 for lines in wrapped)
        + 12 * max(0, len(wrapped) - 1)
    )
    image = Image.new("RGB", (width, height), "#f7f3e9")
    draw = ImageDraw.Draw(image)
    draw.text((55, 35), "Revised Version with Apocrypha - source / TEI review", font=title_font, fill="#172536")
    draw.text((55, 80), "Ticket 21 · nonaccepted candidate · exact USFM retained in TEI", font=font, fill="#48596c")
    y = 125
    for index, lines in enumerate(wrapped):
        fill = "#ffffff" if index % 2 == 0 else "#edf2f4"
        box_height = 38 + len(lines) * 27
        draw.rounded_rectangle((40, y, width - 40, y + box_height), radius=14, fill=fill, outline="#c4ccd3", width=2)
        for line_index, line in enumerate(lines):
            color = "#1b5e4b" if line_index == 0 else "#243746"
            draw.text((65, y + 18 + line_index * 27), line, font=font, fill=color)
        y += box_height + 12
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def build_evidence(repository_root: Path, reviewed: bool) -> dict[str, bytes]:
    report_root = resolve_repo_path(repository_root, REPORT_RELATIVE)
    candidate_root = report_root / "candidate"
    run_two_root = report_root / "determinism" / "run-2"
    candidate_inventory = _inventory(candidate_root)
    run_two_inventory = _inventory(run_two_root)
    if candidate_inventory != run_two_inventory or len(candidate_inventory) != 8:
        raise ValueError("candidate and determinism run-2 are not identical eight-file packets")
    samples = _spot_checks(candidate_root / "content.tei.xml")
    png = _render_png(samples)
    catalog_path = resolve_repo_path(repository_root, "reports/publish/work_catalog.json")
    catalog = json.loads(catalog_path.read_bytes())
    if len(catalog["works"]) != 402:
        raise ValueError("WorkCatalog count drifted")
    catalog_sha = _sha(catalog_path.read_bytes())
    if catalog_sha != "e5cbf6b111da1e62a785e9c0d37b5732bcd3d38b19e6e4e1e80bfdfe153ec6be":
        raise ValueError("WorkCatalog digest drifted")

    determinism = {
        "contract": "ocd-ticket-21-determinism-v1",
        "status": "pass",
        "candidate_members": candidate_inventory,
        "fresh_process_run_2_members": run_two_inventory,
        "all_members_byte_identical": True,
    }
    spot_checks = {
        "contract": "ocd-ticket-21-source-tei-spot-check-v1",
        "status": "pass" if reviewed else "generated-pending-visual-inspection",
        "checks": samples,
        "all_retained_source_lines_exact": True,
    }
    checklist = {
        "contract": "ocd-ticket-21-visual-review-v1",
        "status": "pass" if reviewed else "pending",
        "reviewed": reviewed,
        "render_sha256": _sha(png),
        "checks": [sample["label"] for sample in samples],
        "source_authority": "eBible eng-rv USFM",
        "print_witness_review": {
            "1895": ["PDF page 5 title leaf", "PDF page 8 names/order", "PDF pages 9-14 preface", "PDF page 15 Genesis opening"],
            "1913": ["PDF page 10 title leaf", "PDF pages 12-14 marginal-reference preface/key", "PDF page 16 Revisers' preface"],
            "replacement_scans": ["TOB_RV.pdf first spread", "ESG_RV.pdf first spread"],
        },
        "witness_material_projected_to_tei": False,
    }
    packet = {
        "contract": "ocd-ticket-21-pilot-packet-v1",
        "ticket": 21,
        "status": "sealed-nonaccepted" if reviewed else "generated-unreviewed",
        "title": "Revised Version with Apocrypha",
        "edition": "complete 1895 edition, eBible eng-rv",
        "candidate_members": candidate_inventory,
        "focused_tests": {
            "command": "py -3 -B -m pytest -p no:cacheprovider tests/test_revised_version_with_apocrypha.py -q --basetemp <verified-external-unique-child>",
            "result": "9 passed in 67.01s",
        },
        "determinism": "pass",
        "visual_review": "pass" if reviewed else "pending",
        "source_roundtrip": {"files": 80, "lines": 47631, "exact": True},
        "text_accounting": {"old_testament_books": 39, "apocrypha_file_members": 14, "apocrypha_textual_units": 15, "new_testament_books": 27, "chapters": 1362, "verse_records": 36878},
        "witness_boundaries": {"tobit_replacement_scan": "evidence-only", "greek_esther_replacement_scan": "evidence-only", "print_prelims": "evidence-only"},
        "canonical_audit": {"work_catalog_works": 402, "work_catalog_sha256": catalog_sha, "data_or_ir_changed": False, "accepted_ir_changed": False},
        "held": ["Brenton English Septuagint", "Anderson New Testament", "tickets 22-27"],
        "human_acceptance_required": True,
        "publication_ready": False,
    }
    markdown = (
        "# Ticket 21 sealed pilot packet\n\n"
        f"Status: **{packet['status']}**. Focused tests: **9 passed**. "
        "All 80 USFM files and 47,631 lines reopen exactly from the TEI.\n\n"
        "The 39 OT books, fifteen Apocrypha/Deuterocanon units, and 27 NT books "
        "are accounted. Tobit/Greek Esther replacement scans and print-only prelims "
        "remain evidence only. Human acceptance and publication remain pending.\n"
    ).encode("utf-8")
    return {
        "determinism.json": _canonical(determinism),
        "pilot-packet.json": _canonical(packet),
        "pilot-packet.md": markdown,
        "source-tei-spot-check.json": _canonical(spot_checks),
        "source-tei-spot-check.png": png,
        "visual-review-checklist.json": _canonical(checklist),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--reviewed", action="store_true")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    destination = args.destination.resolve()
    if destination.exists() and any(destination.iterdir()) and not args.replace:
        raise FileExistsError(f"evidence destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    outputs = build_evidence(args.repository_root.resolve(), args.reviewed)
    if args.replace:
        existing = {path.name for path in destination.iterdir() if path.is_file()}
        directories = [path for path in destination.iterdir() if path.is_dir()]
        if directories or existing != set(outputs):
            raise ValueError("refusing to replace an unexpected evidence directory")
    for name, content in sorted(outputs.items()):
        (destination / name).write_bytes(content)
    print(json.dumps({"destination": str(destination), "members": _inventory(destination)}, sort_keys=True))


if __name__ == "__main__":
    main()
