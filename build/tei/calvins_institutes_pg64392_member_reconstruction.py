"""Bounded pg64392 member producer built on the tested Calvin rendering seam."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Mapping

from lxml import etree

from build.tei.calvins_institutes_reconstruction import (
    _blocks,
    _build_tei,
    _canonical,
    _classify,
    _closure,
    _digest,
    _el,
    _inventory,
    _line_records,
    _sha,
)
from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-calvins-institutes-pg64392-member-gutenberg-to-tei"
CONVERTER_VERSION = "1"
_PROFILE_ID = "calvins-institutes-pg64392-member-source-v1"
_MEMBER_NAME = "retained-volume-2"
_MEMBER_PATH = "raw/gutenberg/pg64392.txt"
_LINE_COUNT = 38723
_SOURCE_BYTES = 2134850
_NOTE_COUNT = 1490
_PRINCIPAL_START = 32957
_PRINCIPAL_END = 33423
_SCRIPTURE_START = 33424
_SCRIPTURE_END = 38372
_TEI = "http://www.tei-c.org/ns/1.0"


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _member_authority(source_manifest: SourceManifest) -> Mapping[str, object]:
    authorities = [
        item
        for item in source_manifest.record["authorities"]
        if item.get("role") == "primary-source"
    ]
    if len(authorities) != 1:
        raise ValueError("Calvin pg64392 member route requires exactly one primary source")
    authority = authorities[0]
    if authority.get("name") != _MEMBER_NAME or authority.get("path") != _MEMBER_PATH:
        raise ValueError("Calvin pg64392 member route has the wrong primary source")
    return authority


def _member_model_digests(model: Mapping[str, object]) -> tuple[dict[str, int], dict[str, str]]:
    physical_books = model["physical_books"]
    chapters = model["chapters"]
    front = model["front_blocks"]
    arguments = model["argument_blocks"]
    body = model["body_blocks"]
    indexes = model["indexes"]
    anchors = model["anchors"][2]
    notes = model["notes"][2]
    emphasis = model["emphasis"]
    structural = [
        {"kind": "volume", "volume": 2, "line": 1},
        *(
            {
                "kind": "book",
                **{
                    key: item[key]
                    for key in ("volume", "book", "start_line", "end_line", "heading_sha256")
                },
            }
            for item in physical_books
        ),
        *(
            {
                "kind": "chapter",
                **{
                    key: item[key]
                    for key in ("volume", "book", "chapter", "start_line", "end_line", "heading_sha256")
                },
            }
            for item in chapters
        ),
    ]
    index_fields = ("id", "start_line", "end_line", "text_sha256")
    anchor_fields = ("volume", "occurrence", "number", "label", "book", "chapter", "block_id", "line", "column")
    note_fields = ("volume", "number", "label", "book", "chapter", "label_block_id", "block_ids", "start_line", "end_line")
    emphasis_fields = ("occurrence", "id", "volume", "block_id", "start_line", "start_column", "end_line", "end_column", "value", "value_sha256")
    counts = {
        "logical_books": len({int(item["book"]) for item in physical_books}),
        "physical_book_headings": len(physical_books),
        "chapters": len(chapters),
        "volume_2_chapters": len(chapters),
        "front_blocks": len(front),
        "argument_blocks": len(arguments),
        "chapter_body_blocks": len(body),
        "principal_index_lines": _PRINCIPAL_END - _PRINCIPAL_START + 1,
        "principal_index_blocks": len(indexes["principal-matters"]),
        "scripture_index_lines": _SCRIPTURE_END - _SCRIPTURE_START + 1,
        "scripture_index_blocks": len(indexes["scripture"]),
        "volume_2_anchors": len(anchors),
        "volume_2_notes": len(notes),
        "emphasis_carriers": len(emphasis),
    }
    digests = {
        "structural_events_sha256": _digest(structural),
        "front_blocks_sha256": _digest(_inventory(front, index_fields)),
        "argument_blocks_sha256": _digest(_inventory(arguments, index_fields)),
        "chapter_body_blocks_sha256": _digest(_inventory(body, index_fields)),
        "principal_index_blocks_sha256": _digest(_inventory(indexes["principal-matters"], index_fields)),
        "scripture_index_blocks_sha256": _digest(_inventory(indexes["scripture"], index_fields)),
        "anchors_sha256": _digest(_inventory(anchors, anchor_fields)),
        "notes_sha256": _digest(_inventory(notes, note_fields)),
        "attachments_sha256": _digest(model["pairs"]),
        "emphasis_sha256": _digest(_inventory(emphasis, emphasis_fields)),
    }
    return counts, digests


def _member_header(policy: Mapping[str, object], source_sha256: str) -> etree._Element:
    header = _el("teiHeader")
    file_desc = _el("fileDesc")
    title_stmt = _el("titleStmt")
    title_stmt.append(
        _el(
            "title",
            text="Institutes of the Christian Religion, retained Project Gutenberg volume II member candidate",
        )
    )
    title_stmt.append(
        _el(
            "author",
            {"ana": "#source-name-conflict"},
            "Jean Calvin (Gutenberg metadata); John Calvin (retained title page)",
        )
    )
    resp = _el("respStmt")
    resp.append(_el("resp", text="Translator named by the retained volume"))
    resp.append(_el("name", text="John Allen"))
    title_stmt.append(resp)
    file_desc.append(title_stmt)
    publication = _el("publicationStmt")
    publication.append(_el("publisher", text="Open Christian Data"))
    availability = _el("availability", {"status": "unknown"})
    availability.append(_el("p", text=str(policy["rights_statement"])))
    publication.append(availability)
    file_desc.append(publication)
    source_desc = _el("sourceDesc")
    bibl = _el("bibl")
    bibl.append(
        _el(
            "title",
            text="Institutes of the Christian Religion, Project Gutenberg volume II",
        )
    )
    bibl.append(_el("idno", {"type": "sha256"}, source_sha256))
    bibl.append(
        _el(
            "note",
            text="Exact Project Gutenberg eBook #64392 retained bytes; wrapper, license, credits, release, and update evidence remain visible but distinct from represented work and index content.",
        )
    )
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    encoding = _el("encodingDesc")
    encoding.append(
        _el(
            "p",
            text="This partial member candidate represents physical volume II only: Book III from chapter XIV onward, Book IV, the retained notes, and both appended indexes. It is not a whole-work acceptance claim.",
        )
    )
    header.append(encoding)
    return header


def _expected_unresolved() -> list[dict[str, str]]:
    return [
        {
            "id": "calvin-author-name",
            "status": "unresolved",
            "detail": "Project Gutenberg metadata says Jean Calvin; the retained title page says John Calvin.",
        },
        {
            "id": "calvin-edition-identity",
            "status": "unresolved",
            "detail": "The title page states Sixth American Edition, revised and corrected, Philadelphia, Presbyterian Board of Publication, 1813; this package does not normalize the claim.",
        },
        {
            "id": "calvin-scripture-index-identity",
            "status": "unresolved",
            "detail": "The appended Scripture Index identifies S. T. Livermore, the Presbyterian Board of Publication, the University of Rochester, and MDCCCLII (1852).",
        },
        {
            "id": "calvin-project-gutenberg-record",
            "status": "unresolved",
            "detail": "The retained Gutenberg wrapper carries its release, update, credit, and Internet Archive image-production records; these remain evidence, not a synthesized edition claim.",
        },
        {
            "id": "calvin-rights-jurisdiction-and-terms",
            "status": "unresolved",
            "detail": "The source asserts a United States public-domain basis, warns users to check local law, and imposes Project Gutenberg license and trademark terms; validation is not rights clearance.",
        },
        {
            "id": "calvin-human-acceptance",
            "status": "unresolved",
            "detail": "This deterministic member candidate is explicitly nonaccepted and has not received human textual, identity, or rights acceptance.",
        },
    ]


def _expected_readme() -> bytes:
    return (
        "# Calvin Institutes volume II retained-member candidate\n\n"
        "This package-only README accompanies a nonaccepted reconstruction of the exact retained Project Gutenberg volume II text, eBook #64392.\n\n"
        "The represented boundary begins with Book III chapter XIV and continues through Book IV, the chapter notes, the principal-matters index, the Scripture Index, and the retained wrapper and license evidence. This is an explicitly partial member candidate, not a whole-work acceptance claim.\n\n"
        "Rights are deliberately split: the retained file states a United States public-domain basis, warns users outside the United States to check their jurisdiction, and retains Project Gutenberg redistribution and trademark conditions. Review the [Project Gutenberg License](https://www.gutenberg.org/license/) before redistribution. This package does not claim unconditional availability, worldwide public-domain status, human acceptance, or publication authorization.\n\n"
        "John Allen, Jean/John Calvin identity evidence, the Sixth American Edition title-page claim, the volume-II release/update records, Distributed Proofreaders credits, Internet Archive image evidence, S. T. Livermore, the Presbyterian Board of Publication, and the University of Rochester evidence remain visible.\n"
    ).encode("utf-8")


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    authority = _member_authority(source_manifest)
    profile = _strict_json(
        source_manifest.authority_path("reconstruction-profile").read_bytes(),
        "Calvin pg64392 member reconstruction profile",
    )
    policy = _strict_json(
        source_manifest.authority_path("validation-policy").read_bytes(),
        "Calvin pg64392 member validation policy",
    )
    if profile.get("contract") != "ocd-calvins-institutes-pg64392-member-reconstruction-profile-v1" or profile.get("profile_id") != _PROFILE_ID:
        raise ValueError("Calvin pg64392 member profile identity mismatch")
    if policy.get("contract") != "ocd-calvins-institutes-pg64392-member-validation-policy-v1":
        raise ValueError("Calvin pg64392 member validation policy identity mismatch")
    source = source_manifest.authority_path(_MEMBER_NAME).read_bytes()
    member = {
        "path": authority["path"],
        "bytes": len(source),
        "sha256": _sha(source),
    }
    scope = profile.get("source_scope")
    if not isinstance(scope, dict) or scope.get("members") != [member] or scope.get("bytes") != _SOURCE_BYTES or scope.get("physical_lines") != _LINE_COUNT:
        raise ValueError("Calvin pg64392 member source scope drifted")
    rows = _line_records(2, str(authority["path"]), source)
    if len(rows) != _LINE_COUNT:
        raise ValueError("Calvin pg64392 member line count drifted")
    exact_inventory = [
        {
            key: row[key]
            for key in ("volume", "member", "line", "byte_start", "byte_end", "terminator", "record_sha256")
        }
        for row in rows
    ]
    exact_line_sha = _digest(exact_inventory)
    if exact_line_sha != scope.get("derived_exact_line_inventory_sha256"):
        raise ValueError("Calvin pg64392 member exact-line inventory drifted")
    blocks = _blocks(rows)
    model = _classify([[], blocks], included_volumes=(2,))
    counts, digests = _member_model_digests(model)
    if counts != profile.get("required_counts") or digests != profile.get("derived_inventory_digests"):
        raise ValueError("Calvin pg64392 member source-derived inventory drifted")
    root = source_manifest.repository_root
    closure = _closure(root, Path(__file__))
    closure_sha = _digest(closure)
    if closure_sha != profile.get("producer_import_closure_sha256"):
        raise ValueError("Calvin pg64392 member producer import closure drifted")
    loaded = {
        "converter": Path(__file__).resolve().relative_to(root.resolve()).as_posix(),
        "shared_renderer": (root / "build/tei/calvins_institutes_reconstruction.py").resolve().relative_to(root.resolve()).as_posix(),
        "contract": Path(sys.modules["ocd_kernel.reconstruction.contract"].__file__).resolve().relative_to(root.resolve()).as_posix(),
    }
    tei_bytes = _build_tei(
        [blocks],
        model,
        policy,
        str(member["sha256"]),
        volume_numbers=(2,),
        header_builder=_member_header,
        tei_xml_id="calvins-institutes-gutenberg-pg64392-member-candidate",
    )
    line_to_block = {
        (2, line): block
        for block in blocks
        for line in range(int(block["start_line"]), int(block["end_line"]) + 1)
    }
    lines = []
    for row in rows:
        block = line_to_block[(2, int(row["line"]))]
        lines.append(
            {
                **row,
                "feature_id": f"calvin-v2-line-{int(row['line']):05d}",
                "block_id": block["id"],
                "category": block["category"],
                "disposition": block["disposition"],
                "tei_selector": f"#calvin-v2-line-{int(row['line']):05d}",
            }
        )
    represented = sum(item["disposition"] == "represented" for item in lines)
    accountability = {
        "contract": "ocd-calvins-institutes-pg64392-member-source-accountability-v1",
        "schema": "calvins-institutes-pg64392-member.source-accountability.schema.json",
        "source_members": [member],
        "source_bytes": len(source),
        "physical_line_count": len(lines),
        "represented_line_count": represented,
        "evidence_only_line_count": len(lines) - represented,
        "omitted_line_count": 0,
        "duplicate_line_count": 0,
        "derived_member_set_sha256": member["sha256"],
        "derived_exact_line_inventory_sha256": exact_line_sha,
        "inventory_digests": digests,
        "required_counts": profile["required_counts"],
        "lines": lines,
        "structural_events": [
            {"kind": "volume", "volume": 2, "line": 1},
            *model["physical_books"],
            *model["chapters"],
        ],
        "note_attachments": model["pairs"],
        "emphasis_carriers": model["emphasis"],
    }
    authorities = {
        str(item["name"]): {
            key: item[key] for key in ("path", "role", "bytes", "sha256")
        }
        for item in source_manifest.record["authorities"]
    }
    provenance = {
        "contract": "ocd-calvins-institutes-pg64392-member-candidate-provenance-v1",
        "status": "nonaccepted",
        "authorities": authorities,
        "loaded_module_paths": loaded,
        "producer_import_closure": closure,
        "producer_import_closure_sha256": closure_sha,
        "source_member_set_sha256": member["sha256"],
        "identity_conflicts": profile["identity_conflicts"],
        "rights": profile["rights"],
        "source_bytes_embedded_in_candidate": False,
    }
    return {
        "content.tei.xml": tei_bytes,
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in _expected_unresolved()),
        "README.source.md": _expected_readme(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
