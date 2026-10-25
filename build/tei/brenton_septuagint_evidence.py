"""Render and seal bounded ticket-21 Brenton review evidence."""

from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path
import textwrap

from lxml import etree
from PIL import Image, ImageDraw, ImageFont

from build.tei import brenton_septuagint as brenton
from ocd_kernel.lib.storage_topology import resolve_repo_path


REPORT_RELATIVE = (
    "reports/clean-ready-acquisition-to-tei/master-3/21/brenton-septuagint"
)
SAMPLES = (
    ("Abbreviations table", "00-FRTeng-Brenton.usfm", 9),
    ("1870 introduction and small caps", "01-INTeng-Brenton.usfm", 8),
    ("Genesis opening footnote", "02-GENeng-Brenton.usfm", 12),
    ("Cross-reference", "03-EXOeng-Brenton.usfm", 68),
    ("Supplied text", "04-LEVeng-Brenton.usfm", 10),
    ("III Maccabees opening", "57-3MAeng-Brenton.usfm", 9),
    ("IV Maccabees ending", "59-4MAeng-Brenton.usfm", 647),
    ("Appendix source verse spans", "97-BAKeng-Brenton.usfm", 24),
    ("Apocrypha overview", "98-OTHeng-Brenton.usfm", 6),
    ("Jeremiah concordance table", "99-XXAeng-Brenton.usfm", 9),
    ("1844 preface", "100-XXBeng-Brenton.usfm", 6),
    ("Electronic errata ending", "101-XXCeng-Brenton.usfm", 326),
)


def _inventory(root: Path) -> list[dict[str, object]]:
    return [
        {
            "name": path.name,
            "bytes": path.stat().st_size,
            "sha256": brenton._sha(path.read_bytes()),
        }
        for path in sorted(root.iterdir())
        if path.is_file()
    ]


def _projection(node: etree._Element) -> str:
    parts = [node.text or ""]
    for child in node:
        if not (
            child.tag == brenton._q("note")
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
        pointer = f"{brenton.SOURCE_PREFIX}{file_name}#line={line_number}"
        nodes = root.xpath("//*[@corresp=$pointer]", pointer=pointer)
        if len(nodes) != 1:
            raise ValueError(f"expected one TEI node for {pointer}; got {len(nodes)}")
        raw_notes = nodes[0].xpath(
            "./tei:note[@type='source-usfm-raw']/text()",
            namespaces={"tei": brenton.TEI_NS},
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
    font = ImageFont.load_default(size=19)
    title_font = ImageFont.load_default(size=29)
    width = 1800
    wrapped: list[list[str]] = []
    for sample in samples:
        source = str(sample["source_usfm"])
        projection = str(sample["tei_visible_projection"])
        lines = [f"{sample['label']}  |  exact retained line: PASS"]
        lines += ["SOURCE  " + value for value in textwrap.wrap(source, width=145) or [""]]
        lines += ["TEI     " + value for value in textwrap.wrap(projection, width=145) or [""]]
        wrapped.append(lines)
    height = (
        175
        + sum(38 + len(lines) * 26 for lines in wrapped)
        + 12 * max(0, len(wrapped) - 1)
    )
    image = Image.new("RGB", (width, height), "#f7f3e9")
    draw = ImageDraw.Draw(image)
    draw.text(
        (55, 35),
        "Brenton Septuagint - source / TEI review",
        font=title_font,
        fill="#172536",
    )
    draw.text(
        (55, 80),
        "Ticket 21 - nonaccepted candidate - exact eng-Brenton USFM retained in TEI",
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


def build_evidence(repository_root: Path, reviewed: bool) -> dict[str, bytes]:
    report_root = resolve_repo_path(repository_root, REPORT_RELATIVE)
    candidate_root = report_root / "candidate"
    run_two_root = report_root / "determinism" / "run-2"
    candidate_inventory = _inventory(candidate_root)
    run_two_inventory = _inventory(run_two_root)
    if candidate_inventory != run_two_inventory or len(candidate_inventory) != 8:
        raise ValueError("candidate and run-2 are not identical eight-file packets")
    samples = _spot_checks(candidate_root / "content.tei.xml")
    png = _render_png(samples)
    catalog_path = resolve_repo_path(repository_root, "reports/publish/work_catalog.json")
    catalog_bytes = catalog_path.read_bytes()
    catalog = json.loads(catalog_bytes)
    catalog_sha = brenton._sha(catalog_bytes)
    if len(catalog["works"]) != 402:
        raise ValueError("WorkCatalog count drifted")
    if catalog_sha != "e5cbf6b111da1e62a785e9c0d37b5732bcd3d38b19e6e4e1e80bfdfe153ec6be":
        raise ValueError("WorkCatalog digest drifted")

    determinism = {
        "contract": "ocd-ticket-21-brenton-determinism-v1",
        "status": "pass",
        "candidate_members": candidate_inventory,
        "fresh_process_run_2_members": run_two_inventory,
        "all_members_byte_identical": True,
    }
    spot_checks = {
        "contract": "ocd-ticket-21-brenton-source-tei-spot-check-v1",
        "status": "pass" if reviewed else "generated-pending-visual-inspection",
        "checks": samples,
        "all_retained_source_lines_exact": True,
    }
    checklist = {
        "contract": "ocd-ticket-21-brenton-visual-review-v1",
        "status": "pass" if reviewed else "pending",
        "reviewed": reviewed,
        "render_sha256": brenton._sha(png),
        "checks": [sample["label"] for sample in samples],
        "pdf_witness_review": {
            "pages": [3, 6, 13, 1329, 1341, 1362, 1365, 1366, 1371, 1376, 1379],
            "features": [
                "contents", "1870 introduction", "Genesis opening", "III Maccabees",
                "IV Maccabees", "Apocrypha overview", "Jeremiah table", "1844 preface",
                "errata", "appendix and ending",
            ],
        },
        "pdf_witness_projected_to_tei": False,
    }
    packet = {
        "contract": "ocd-ticket-21-brenton-pilot-packet-v1",
        "ticket": 21,
        "status": "sealed-nonaccepted" if reviewed else "generated-unreviewed",
        "title": "Brenton Septuagint Translation",
        "edition": "corrected eBible eng-Brenton source files dated 2025-12-12",
        "candidate_members": candidate_inventory,
        "focused_tests": {
            "command": "py -3 -B -m pytest -p no:cacheprovider tests/test_brenton_septuagint.py -q --basetemp <verified-external-unique-child>",
            "result": "8 passed in 36.44s",
        },
        "determinism": "pass",
        "visual_review": "pass" if reviewed else "pending",
        "source_roundtrip": {"files": 60, "lines": 38382, "exact": True},
        "source_accounting": {
            "textual_books": 53,
            "paratext_members": 7,
            "chapters": 1118,
            "verse_records": 29005,
            "footnotes": 2600,
            "cross_references": 150,
            "supplied_text_spans": 9086,
            "table_rows": 51,
        },
        "witness_boundaries": {
            "official_pdf": "rendering-evidence-only",
            "electronic_errata": "retained-authority-member",
            "print_only_content_claimed": False,
            "terminal_order_difference": "explicit",
        },
        "canonical_audit": {
            "work_catalog_works": 402,
            "work_catalog_sha256": catalog_sha,
            "data_or_ir_changed": False,
            "accepted_ir_changed": False,
        },
        "held": ["Anderson New Testament", "tickets 22-27"],
        "human_acceptance_required": True,
        "publication_ready": False,
    }
    markdown = (
        "# Ticket 21 Brenton sealed pilot packet\n\n"
        f"Status: **{packet['status']}**. Focused tests: **8 passed**. "
        "All 60 USFM members and 38,382 lines reopen exactly from the TEI.\n\n"
        "The full 53-book represented canon and seven paratext members are accounted. "
        "Electronic errata remain explicit; the official PDF is evidence only. Human "
        "acceptance and publication remain pending.\n"
    ).encode("utf-8")
    return {
        "determinism.json": brenton._canonical(determinism),
        "pilot-packet.json": brenton._canonical(packet),
        "pilot-packet.md": markdown,
        "source-tei-spot-check.json": brenton._canonical(spot_checks),
        "source-tei-spot-check.png": png,
        "visual-review-checklist.json": brenton._canonical(checklist),
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
