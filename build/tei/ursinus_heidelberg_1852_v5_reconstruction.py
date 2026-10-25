"""Declared-candidate wrapper for the retained 1852 Ursinus IA source."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Mapping

from ocd_kernel.reconstruction.contract import SourceManifest
from build.tei import ursinus_heidelberg_1852_v5 as legacy


CONVERTER_ID = "ocd-ursinus-1852-retained-members-to-tei-v9"
CONVERTER_VERSION = "9"
WORK_ID = "ursinus-commentary-heidelberg-catechism-1852"
EDITION_ID = "commdrza00ursi-1852"
ACQUISITION_ID = "ia-commdrza00ursi-second-american-1852"
SOURCE_ID = "ia-commdrza00ursi-second-american-1852"
SOURCE_MEMBERS = {
    "scan.pdf": "c04a2ef0e88fa4970fd29386c086e528ff249f1d9e3d321fdd51cb3c14a31b52",
    "ocr.txt": "b992748facfcf8c7268783cc497e195bdd22849f52aa0a94d4ebadae5b3a86c5",
    "ocr.xml": "44d5f752ac2fd60e7864134eb818951c842329b8393565ae5f5cdb9449f78d98",
    "page-numbers.json": "cbb1c407e254dcbdb9a577014e4c38e18135a7a492d0b750ae1ac8def06140f6",
    "scandata.xml": "b1ddaeaa58e9b90c120eb8dacc801c162736c938fe007ec1fe7792e41c634b09",
}
ENVELOPE_HASHES = {
    **SOURCE_MEMBERS,
    "metadata.json": "b12ca6fcfc47a1c02a2a1207e71a83f0db96c5339999c44a3a7d5e94faed7edf",
    "acquisition-receipt.json": "ee903821197d0ccfe82bd854deac5e65e39794073d594d860ac27b6d1c2d589a",
    "member-inventory.tsv": "e8b2cbbb638db2ad2ecaf39ed449e9bcb1f91b0031be3c388c365b6cb45ddd9c",
}


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _authority_map(manifest: SourceManifest) -> dict[str, Mapping[str, object]]:
    authorities = manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("source manifest authority list is invalid")
    return {str(row["name"]): row for row in authorities}


def _load_json(path: Path, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not readable UTF-8 JSON") from error


def _verify_binding(manifest: SourceManifest) -> tuple[dict[str, Mapping[str, object]], Path, dict[str, object], dict[str, object]]:
    root = manifest.repository_root
    if manifest.record.get("source_id") != SOURCE_ID or manifest.record.get("work_id") != WORK_ID:
        raise ValueError("source manifest work or source identity differs")
    authorities = _authority_map(manifest)
    by_role: dict[str, list[Mapping[str, object]]] = {}
    for row in authorities.values():
        by_role.setdefault(str(row.get("role")), []).append(row)
    primary = {Path(str(row["path"])).name: row for row in by_role.get("primary-source", [])}
    if set(primary) != set(SOURCE_MEMBERS):
        raise ValueError("primary source authority set differs from retained acquisition members")
    source_dir = manifest.authority_path("source-ocr-xml").parent
    for name, expected in SOURCE_MEMBERS.items():
        authority = primary[name]
        if authority.get("sha256") != expected or manifest.authority_path(str(authority["name"])) != (source_dir / name).resolve(strict=True):
            raise ValueError(f"primary source authority identity differs: {name}")
    if set(ENVELOPE_HASHES) != {path.name for path in source_dir.iterdir() if path.is_file()}:
        raise ValueError("retained source envelope file names differ")
    for name, expected in ENVELOPE_HASHES.items():
        observed = _sha((source_dir / name).read_bytes())
        if observed != expected:
            raise ValueError(f"retained source envelope hash differs: {name}")
    work = _load_json(manifest.authority_path("work-identity"), "work identity")
    acquisition = _load_json(manifest.authority_path("acquisition-selection"), "acquisition sidecar")
    if not isinstance(work, dict) or work.get("work_id") != WORK_ID:
        raise ValueError("work identity authority differs")
    if not isinstance(acquisition, dict) or acquisition.get("acquisition_id") != ACQUISITION_ID or acquisition.get("edition_id") != EDITION_ID:
        raise ValueError("acquisition authority differs")
    member_set_path = manifest.authority_path("acquisition-member-set")
    if acquisition.get("source_path") != member_set_path.relative_to(root).as_posix():
        raise ValueError("acquisition source path does not bind its ordered member-set authority")
    expected_member_set = _canonical({
        "contract": "ocd-retained-source-member-set-v1",
        "acquisition_id": ACQUISITION_ID,
        "edition_id": EDITION_ID,
        "scope": acquisition.get("source_scope"),
        "members": [dict(member, position=index) for index, member in enumerate(acquisition.get("retained_files", []), 1)],
    })
    if member_set_path.read_bytes() != expected_member_set or len(expected_member_set) != acquisition.get("source_bytes") or _sha(expected_member_set) != acquisition.get("source_sha256"):
        raise ValueError("ordered acquisition member-set manifest is not canonical")
    retained = {
        Path(str(row["path"])).name: (row.get("path"), row.get("bytes"), row.get("sha256"))
        for row in acquisition.get("retained_files", [])
    }
    expected_retained = {
        name: (str(primary[name]["path"]), int(primary[name]["bytes"]), SOURCE_MEMBERS[name])
        for name in SOURCE_MEMBERS
    }
    if retained != expected_retained:
        raise ValueError("primary authorities do not equal the acquisition retained_files member set")
    builder = manifest.authority_path("route-builder")
    if _sha(builder.read_bytes()) != _sha(Path(legacy.__file__).read_bytes()):
        raise ValueError("bound legacy reconstruction builder differs")
    return authorities, source_dir, work, acquisition


def convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    authorities, source_dir, work, acquisition = _verify_binding(source_manifest)
    root = source_manifest.repository_root
    library = Path(_load_json(root / ".ocd-storage.json", "storage configuration")["library_root"]).resolve(strict=True)
    review_root = library / "candidate-reviews"
    if not review_root.is_dir():
        raise ValueError("durable candidate-review root is unavailable")

    # The declared package and every replay use this same relative depth from raw/.
    with tempfile.TemporaryDirectory(prefix="ursinus-declared-build-", dir=review_root) as temp_name:
        build_root = Path(temp_name) / "package"
        legacy.build(root, build_root)
        source_accounting = json.loads((build_root / "source-accounting.json").read_text(encoding="utf-8"))
        row_map = json.loads((build_root / "contents-row-map.json").read_text(encoding="utf-8"))
        tei_bytes = (build_root / "candidate.xml").read_bytes()
        if len(source_accounting["leaves"]) != 720 or source_accounting["ocr_paragraphs"] != 6005 or source_accounting["ocr_lines"] != 34726 or source_accounting["contents_row_count"] != 436:
            raise ValueError("retained-source accounting totals differ")

    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_text(encoding="utf-8"))
    policy = json.loads(source_manifest.authority_path("validation-policy").read_text(encoding="utf-8"))
    unresolved_rows = policy.get("unresolved_fidelity_gaps")
    if not isinstance(unresolved_rows, list) or len(unresolved_rows) < 1:
        raise ValueError("validation policy lacks the unresolved fidelity ledger")
    rows = row_map.get("rows")
    if not isinstance(rows, list) or len(rows) != 436:
        raise ValueError("scan-derived contents row map is incomplete")

    parsed_root = legacy.etree.fromstring(tei_bytes)
    text_nodes = parsed_root.findall("{http://www.tei-c.org/ns/1.0}text")
    body_nodes = parsed_root.findall("./{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body")
    body_divisions = body_nodes[0].findall("./{http://www.tei-c.org/ns/1.0}div") if len(body_nodes) == 1 else []
    if parsed_root.tag != "{http://www.tei-c.org/ns/1.0}TEI" or len(text_nodes) != 1 or len(body_nodes) != 1 or len(body_divisions) != 1:
        raise ValueError("one-work/one-TEI root, text, or body division count differs")

    source_member_hashes = dict(ENVELOPE_HASHES)
    authority_rows = [
        {key: row[key] for key in ("name", "path", "role", "bytes", "sha256")}
        for row in sorted(authorities.values(), key=lambda item: str(item["name"]))
    ]
    accountability = {
        "contract": "ocd-ursinus-source-accountability-v2",
        "work_id": WORK_ID,
        "edition_id": EDITION_ID,
        "acquisition_id": ACQUISITION_ID,
        "source_identity": profile["source_identity"],
        "one_work_one_tei": {
            "source_attested_complete_work_count": 1,
            "candidate_tei_count": 1,
            "manifest_rows": ["L427", "L468"],
            "title_anchor": profile["work_boundary"]["title_anchor"],
            "manifest_row_relationship": profile["work_boundary"]["manifest_row_relationship"],
        },
        "source_authorities": authority_rows,
        "source_member_hashes": source_member_hashes,
        "provider_retained_members": source_accounting["provider_retained_members"],
        "provider_inventory_members": source_accounting["provider_inventory_members"],
        "source_roles": source_accounting["source_roles"],
        "candidate_facsimile_target": source_accounting["candidate_facsimile_target"],
        "scan_envelope": {
            "access_pdf_pages": 720,
            "ocr_pages": 720,
            "scandata_leaves": 722,
            "empty_ocr_pages": sum(1 for row in source_accounting["leaves"] if row["paragraphs"] == 0),
            "excluded_scan_leaves": source_accounting["excluded_scan_leaves"],
        },
        "leaves": source_accounting["leaves"],
        "contents_row_count": source_accounting["contents_row_count"],
        "contents_rows_by_leaf": source_accounting["contents_rows_by_leaf"],
        "contents_row_map_method": row_map["method"],
        "contents_row_map": rows,
        "image_preserved_structures": source_accounting["image_preserved_structures"],
        "source_layout_hierarchies": source_accounting["source_layout_hierarchies"],
        "diagram_scan_leaves": source_accounting["diagram_scan_leaves"],
        "source_layout_scan_leaves": source_accounting["source_layout_scan_leaves"],
        "source_layout_page_crosswalk": source_accounting["source_layout_page_crosswalk"],
        "headings": source_accounting["headings"],
        "ocr_words": source_accounting["ocr_words"],
        "ocr_lines": source_accounting["ocr_lines"],
        "ocr_paragraphs": source_accounting["ocr_paragraphs"],
        "ocr_text_normalized_sha256": source_accounting["ocr_text_normalized_sha256"],
        "mapping_policy": source_accounting["mapping_policy"],
        "candidate_tei": {
            "member": "content.tei.xml",
            "bytes": len(tei_bytes),
            "sha256": _sha(tei_bytes),
            "root_count": 1,
            "text_count": 1,
            "body_division_count": 1,
        },
        "unresolved_fidelity_gaps": unresolved_rows,
        "candidate_status": "nonaccepted technical review candidate",
    }

    authority_digests = {str(row["name"]): str(row["sha256"]) for row in authority_rows}
    provenance = {
        "contract": "ocd-ursinus-provenance-v2",
        "source_manifest_sha256": source_manifest.sha256,
        "authorities": authority_digests,
        "converter": dict(source_manifest.record["converter"]),
        "work_id": WORK_ID,
        "edition_id": EDITION_ID,
        "acquisition_id": ACQUISITION_ID,
        "source_id": SOURCE_ID,
        "source_identity": profile["source_identity"],
        "work_boundary": profile["work_boundary"],
        "retained_source_envelope": sorted(source_member_hashes),
        "candidate_member": "content.tei.xml",
        "candidate_sha256": _sha(tei_bytes),
        "candidate_status": "nonaccepted",
        "mapping_summary": "One source-titled commentary is represented by exactly one candidate TEI with all 720 PDF/OCR pages and seven retained scan-linked layouts, each structurally mapped without changing OCR readings.",
    }
    readme = source_manifest.authority_path("source-attribution-readme").read_bytes()
    outputs = {
        "README.source.md": readme,
        "content.tei.xml": tei_bytes,
        "provenance.json": _canonical(provenance),
        "source-accountability.json": _canonical(accountability),
        "unresolved.jsonl": b"".join(_canonical(row) for row in unresolved_rows),
    }
    return outputs


convert.converter_id = CONVERTER_ID
convert.converter_version = CONVERTER_VERSION
