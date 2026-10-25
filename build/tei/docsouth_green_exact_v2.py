"""Account for the exact electronic and title-page titles in L763 Green TEI."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from build.tei.docsouth_l761_l762 import _migrate, _read
from ocd_kernel.reconstruction.contract import SourceManifest

TEI = "http://www.tei-c.org/ns/1.0"
T = "{" + TEI + "}"
CONVERTER_ID = "ocd-docsouth-green-exact-v2-title-accounting-to-p5"
CONVERTER_VERSION = "2"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _title_records(title_stmt: etree._Element | None, *, candidate: bool) -> list[dict[str, object]]:
    if title_stmt is None:
        return []
    records = []
    for position, node in enumerate(title_stmt.findall("title") if not candidate else title_stmt.findall(T + "title"), 1):
        title_type = node.get("type")
        if candidate and title_type is not None:
            title_type = "-".join(title_type.split())
        records.append(
            {
                "position": position,
                "type": title_type,
                "text": " ".join("".join(node.itertext()).split()),
            }
        )
    return records


def _title_inventory(root: etree._Element, *, candidate: bool) -> dict[str, list[dict[str, object]]]:
    prefix = T if candidate else ""
    file_desc = root.find(prefix + "teiHeader/" + prefix + "fileDesc")
    if file_desc is None:
        return {"electronic_edition": [], "source_title_page": []}
    return {
        "electronic_edition": _title_records(
            file_desc.find(prefix + "titleStmt"), candidate=candidate
        ),
        "source_title_page": _title_records(
            file_desc.find(prefix + "sourceDesc/" + prefix + "biblFull/" + prefix + "titleStmt"),
            candidate=candidate,
        ),
    }


def _candidate_title_inventory(
    source_inventory: dict[str, list[dict[str, object]]]
) -> dict[str, list[dict[str, object]]]:
    return {
        slot: [
            {
                **record,
                "type": "-".join(record["type"].split())
                if record["type"] is not None
                else None,
            }
            for record in records
        ]
        for slot, records in source_inventory.items()
    }


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    receipt, profile, source, entities = _read(manifest)
    stylesheet = manifest.authority_path("p4-to-p5-stylesheet").read_bytes()
    output = _migrate(source, stylesheet, entities, receipt["source_url"])
    source_titles = _title_inventory(source, candidate=False)
    candidate_titles = _title_inventory(output, candidate=True)
    if source_titles != profile.get("title_inventory"):
        raise ValueError("source title inventory differs from the bound profile")
    if candidate_titles != _candidate_title_inventory(source_titles):
        raise ValueError("migrated title inventory differs from source roles, wording, or order")

    content = etree.tostring(
        output, encoding="UTF-8", xml_declaration=True, pretty_print=True
    )
    policy = json.loads(manifest.authority_path("policy").read_bytes())
    profile_bytes = manifest.authority_path("profile").read_bytes()
    account = {
        "contract": "ocd-docsouth-green-accountability-v2",
        "source_id": receipt["source_id"],
        "work_id": manifest.record["work_id"],
        "source_sha256": receipt["member"]["sha256"],
        "profile_sha256": _sha(profile_bytes),
        "source_envelope": profile["envelope"],
        "title_inventory": source_titles,
        "page_markers": profile["page_markers"],
        "image_entities": profile["image_entities"],
        "tei_sha256": _sha(content),
        "tei_bytes": len(content),
    }
    return {
        "README.source.md": manifest.authority_path("readme").read_bytes(),
        "content.tei.xml": content,
        "provenance.json": _json(policy["provenance"]),
        "source-accountability.json": _json(account),
        "unresolved.jsonl": b"".join(_json(item) for item in policy["unresolved"]),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
