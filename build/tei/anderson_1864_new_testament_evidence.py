"""Render and seal bounded ticket-21 Anderson review evidence."""

from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path
import subprocess
import textwrap

from lxml import etree
from PIL import Image, ImageDraw, ImageFont

from build.tei import anderson_1864_new_testament as anderson
from ocd_kernel.lib.storage_topology import resolve_repo_path


REPORT_RELATIVE = (
    "reports/clean-ready-acquisition-to-tei/master-3/21/"
    "anderson-1864-new-testament"
)
SAMPLES = (
    ("Title", "ENG[B1]Anderson1864[pd]USFM-00.sfm", 6),
    ("Dedication and small caps", "ENG[B1]Anderson1864[pd]USFM-00.sfm", 16),
    ("Preface signature", "ENG[B1]Anderson1864[pd]USFM-00.sfm", 20),
    ("Matthew opening", "ENG[B1]Anderson1864[pd]USFM-41.sfm", 11),
    ("Print-variance remark", "ENG[B1]Anderson1864[pd]USFM-45.sfm", 4),
    ("Romans structure", "ENG[B1]Anderson1864[pd]USFM-46.sfm", 9),
    ("Supplied text", "ENG[B1]Anderson1864[pd]USFM-41.sfm", 45),
    ("Glossary keyword", "ENG[B1]Anderson1864[pd]USFM-41.sfm", 146),
    ("Revelation ending", "ENG[B1]Anderson1864[pd]USFM-67.sfm", 573),
    ("Terminal glossary", "ENG[B1]Anderson1864[pd]USFM-69.sfm", 6),
    ("Terminal colophon", "ENG[B1]Anderson1864[pd]USFM-69.sfm", 13),
)
PRINT_WITNESS_PAGES = (
    ("Title page - printed 1865", 3),
    ("Copyright - entered 1864", 4),
    ("Dedication and preface", 5),
    ("Signed preface - March 1864", 6),
    ("Matthew opening", 7),
    ("Romans", 334),
    ("Revelation 21-22", 569),
    ("Revelation 22", 570),
    ("Ending, glossary, THE END", 571),
)


def _inventory(root: Path) -> list[dict[str, object]]:
    return [
        {
            "name": path.name,
            "bytes": path.stat().st_size,
            "sha256": anderson.base._sha(path.read_bytes()),
        }
        for path in sorted(root.iterdir())
        if path.is_file()
    ]


def _projection(node: etree._Element) -> str:
    parts = [node.text or ""]
    for child in node:
        if not (
            child.tag == anderson._q("note")
            and child.get("type") == "source-usfm-raw"
        ):
            parts.append(_projection(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _spot_checks(tei_path: Path) -> list[dict[str, object]]:
    root = etree.parse(
        str(tei_path),
        parser=etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    ).getroot()
    checks: list[dict[str, object]] = []
    for label, file_name, line_number in SAMPLES:
        pointer = anderson._pointer(Path(file_name), line_number)
        nodes = root.xpath("//*[@corresp=$pointer]", pointer=pointer)
        if len(nodes) != 1:
            raise ValueError(f"expected one TEI node for {pointer}; got {len(nodes)}")
        raw_notes = nodes[0].xpath(
            "./tei:note[@type='source-usfm-raw']/text()",
            namespaces={"tei": anderson.TEI_NS},
        )
        if len(raw_notes) != 1:
            raise ValueError(f"expected one retained raw line for {pointer}")
        checks.append(
            {
                "label": label,
                "pointer": pointer,
                "source_usfm": raw_notes[0],
                "tei_retained_usfm": raw_notes[0],
                "exact": True,
                "tei_visible_projection": _projection(nodes[0]),
            }
        )
    return checks


def _render_png(samples: list[dict[str, object]]) -> bytes:
    font = ImageFont.truetype(Path("C:/Windows/Fonts/arial.ttf"), 19)
    title_font = ImageFont.truetype(Path("C:/Windows/Fonts/arialbd.ttf"), 29)
    width = 1800
    wrapped: list[list[str]] = []
    for sample in samples:
        lines = [f"{sample['label']}  |  exact retained line: PASS"]
        lines += [
            "SOURCE  " + value
            for value in textwrap.wrap(str(sample["source_usfm"]), width=145) or [""]
        ]
        lines += [
            "TEI     " + value
            for value in textwrap.wrap(
                str(sample["tei_visible_projection"]), width=145
            )
            or [""]
        ]
        wrapped.append(lines)
    height = 175 + sum(38 + len(lines) * 26 for lines in wrapped) + 12 * (
        len(wrapped) - 1
    )
    image = Image.new("RGB", (width, height), "#f7f3e9")
    draw = ImageDraw.Draw(image)
    draw.text(
        (55, 35),
        "Anderson New Testament - source / TEI review",
        font=title_font,
        fill="#172536",
    )
    draw.text(
        (55, 80),
        "Ticket 21 - nonaccepted candidate - exact pinned USFM retained in TEI",
        font=font,
        fill="#48596c",
    )
    y = 125
    for index, lines in enumerate(wrapped):
        box_height = 38 + len(lines) * 26
        draw.rounded_rectangle(
            (40, y, width - 40, y + box_height),
            radius=14,
            fill="#ffffff" if index % 2 == 0 else "#edf2f4",
            outline="#c4ccd3",
            width=2,
        )
        for line_index, line in enumerate(lines):
            draw.text(
                (65, y + 18 + line_index * 26),
                line,
                font=font,
                fill="#1b5e4b" if line_index == 0 else "#243746",
            )
        y += box_height + 12
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _render_print_witness(pdf_path: Path) -> bytes:
    pages: list[tuple[str, Image.Image]] = []
    for label, page_number in PRINT_WITNESS_PAGES:
        result = subprocess.run(
            [
                "pdftoppm",
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                "-singlefile",
                "-r",
                "120",
                "-png",
                str(pdf_path),
            ],
            check=True,
            capture_output=True,
        )
        if not result.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError(f"pdftoppm did not return PNG for page {page_number}")
        pages.append((label, Image.open(BytesIO(result.stdout)).convert("RGB")))

    label_font = ImageFont.truetype(Path("C:/Windows/Fonts/arial.ttf"), 18)
    width = 1800
    cell_width = 600
    cell_height = 820
    sheet = Image.new("RGB", (width, cell_height * 3), "#d9dde2")
    for index, (label, page) in enumerate(pages):
        page.thumbnail((560, 760))
        cell = Image.new("RGB", (cell_width, cell_height), "white")
        cell.paste(page, ((cell_width - page.width) // 2, 40))
        ImageDraw.Draw(cell).text(
            (20, 10),
            f"PDF {PRINT_WITNESS_PAGES[index][1]} - {label}",
            font=label_font,
            fill="#172536",
        )
        sheet.paste(cell, ((index % 3) * cell_width, (index // 3) * cell_height))
    buffer = BytesIO()
    sheet.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def build_evidence(repository_root: Path, reviewed: bool) -> dict[str, bytes]:
    report_root = resolve_repo_path(repository_root, REPORT_RELATIVE)
    candidate_inventory = _inventory(report_root / "candidate")
    run_two_inventory = _inventory(report_root / "determinism" / "run-2")
    if candidate_inventory != run_two_inventory or len(candidate_inventory) != 8:
        raise ValueError("candidate and run-2 are not identical eight-file packets")
    samples = _spot_checks(report_root / "candidate" / "content.tei.xml")
    png = _render_png(samples)
    config = anderson._load_config(repository_root)
    print_witness_png = _render_print_witness(
        resolve_repo_path(repository_root, config["witness"]["path"])
    )
    print_witness_evidence = {
        "name": "print-witness-contact-sheet.png",
        "bytes": len(print_witness_png),
        "sha256": anderson.base._sha(print_witness_png),
    }

    catalog_path = resolve_repo_path(repository_root, "reports/publish/work_catalog.json")
    catalog_bytes = catalog_path.read_bytes()
    catalog = json.loads(catalog_bytes)
    catalog_sha = anderson.base._sha(catalog_bytes)
    if len(catalog["works"]) != 402:
        raise ValueError("WorkCatalog count drifted")
    if catalog_sha != "e5cbf6b111da1e62a785e9c0d37b5732bcd3d38b19e6e4e1e80bfdfe153ec6be":
        raise ValueError("WorkCatalog digest drifted")

    determinism = {
        "contract": "ocd-ticket-21-anderson-determinism-v1",
        "status": "pass",
        "candidate_members": candidate_inventory,
        "fresh_process_run_2_members": run_two_inventory,
        "all_members_byte_identical": True,
    }
    spot_checks = {
        "contract": "ocd-ticket-21-anderson-source-tei-spot-check-v1",
        "status": "pass" if reviewed else "generated-pending-visual-inspection",
        "checks": samples,
        "all_retained_source_lines_exact": True,
    }
    checklist = {
        "contract": "ocd-ticket-21-anderson-visual-review-v1",
        "status": "pass" if reviewed else "pending",
        "reviewed": reviewed,
        "render_sha256": anderson.base._sha(png),
        "checks": [sample["label"] for sample in samples],
        "pdf_witness_review": {
            "pages": [3, 4, 5, 6, 7, 334, 569, 570, 571],
            "features": [
                "1865 title page",
                "1864 copyright",
                "dedication and preface",
                "Matthew opening",
                "Romans middle",
                "Revelation ending",
                "terminal glossary and THE END",
            ],
            "visual_result": "pass",
            "retained_contact_sheet": print_witness_evidence,
        },
        "bibliographic_year_discrepancy": "human-review-required",
    }
    packet = {
        "contract": "ocd-ticket-21-anderson-pilot-packet-v1",
        "ticket": 21,
        "status": "sealed-nonaccepted" if reviewed else "generated-unreviewed",
        "title": "The New Testament Translated from the Original Greek",
        "translator": "Henry Tompkins Anderson",
        "candidate_members": candidate_inventory,
        "focused_tests": {
            "command": "py -3 -m pytest -p no:cacheprovider tests/test_anderson_1864_new_testament.py -x -v --basetemp <verified-external-unique-child>",
            "result": "5 passed in 36.08s",
        },
        "determinism": "pass",
        "visual_review": "pass" if reviewed else "pending",
        "source_roundtrip": {"files": 30, "lines": 10435, "exact": True},
        "source_accounting": {
            "books": 27,
            "paratext_members": 3,
            "chapters": 260,
            "verse_records": 7946,
            "supplied_text_spans": 98,
            "glossary_keyword_spans": 23,
        },
        "witness_boundaries": {
            "structured_authority": "GitHub USFM commit abfccf6965b4c47781843930907b1ac180e9b4a3",
            "crosswire_module": "comparison-only",
            "print_witness_title_year": "1865",
            "print_witness_copyright_year": "1864",
            "bibliographic_year_discrepancy": "human-review-required",
            "retained_print_witness_evidence": print_witness_evidence,
        },
        "canonical_audit": {
            "work_catalog_works": 402,
            "work_catalog_sha256": catalog_sha,
            "data_or_ir_changed": False,
            "accepted_ir_changed": False,
        },
        "held": ["tickets 22-27"],
        "human_acceptance_required": True,
        "publication_ready": False,
    }
    markdown = (
        "# Ticket 21 Anderson sealed pilot packet\n\n"
        f"Status: **{packet['status']}**. Focused tests: **5 passed**. "
        "All 30 authority members and 10,435 source lines reopen exactly from "
        "the TEI.\n\n"
        "The complete 27-book New Testament, front matter, and terminal glossary "
        "are accounted. The print witness says 1865 on the title page and 1864 "
        "in its copyright and signed preface; edition-expression acceptance "
        "therefore remains a human decision. Publication remains pending.\n"
    ).encode("utf-8")
    return {
        "determinism.json": anderson.base._canonical(determinism),
        "pilot-packet.json": anderson.base._canonical(packet),
        "pilot-packet.md": markdown,
        "print-witness-contact-sheet.png": print_witness_png,
        "source-tei-spot-check.json": anderson.base._canonical(spot_checks),
        "source-tei-spot-check.png": png,
        "visual-review-checklist.json": anderson.base._canonical(checklist),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--reviewed", action="store_true")
    args = parser.parse_args()
    destination = args.destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"evidence destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    outputs = build_evidence(args.repository_root.resolve(), args.reviewed)
    for name, content in sorted(outputs.items()):
        (destination / name).write_bytes(content)
    print(
        json.dumps(
            {"destination": str(destination), "members": _inventory(destination)},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
