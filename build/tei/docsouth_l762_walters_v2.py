"""Single-work DocSouth converter with retained image accounting for Walters."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from build.tei.docsouth_l761_l762 import _convert as _convert_base
from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-docsouth-l762-walters-single-work-retained-assets"
CONVERTER_VERSION = "2"
TEI = "http://www.tei-c.org/ns/1.0"
T = "{" + TEI + "}"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    """Reuse the faithful P4-to-P5 map and bind current support members."""
    if manifest.record.get("source_id") != "docsouth-walters":
        raise ValueError("Walters converter requires the exact DocSouth source ID")

    produced = dict(_convert_base(manifest))
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    receipt_bytes = manifest.authority_path("acquisition-receipt").read_bytes()
    inventory_bytes = manifest.authority_path("member-inventory").read_bytes()
    content = etree.fromstring(
        produced["content.tei.xml"],
        parser=etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    body = content.find(T + "text/" + T + "body")
    units = [
        unit
        for unit in profile["constituent_units"]
        if unit["role"] != "shared-front"
    ]
    if content.tag != T + "TEI" or body is None or len(units) != 1:
        raise ValueError("Walters must map to one titled TEI and one source work unit")
    unit = units[0]
    wrapper = etree.Element(T + "div", type="source-constituent", n=unit["tei_xml_id"])
    wrapper.text = body.text
    body.text = None
    for node in list(body):
        body.remove(node)
        wrapper.append(node)
    body.append(wrapper)
    content_bytes = etree.tostring(
        content,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )
    produced["content.tei.xml"] = content_bytes
    account = json.loads(produced["source-accountability.json"])
    account.update(
        {
            "retained_support_members": profile["retained_support_members"],
            "acquisition_receipt_sha256": _sha(receipt_bytes),
            "member_inventory_sha256": _sha(inventory_bytes),
            "one_root": True,
            "source_constituent_order": [unit["tei_xml_id"]],
            "tei_sha256": _sha(content_bytes),
            "tei_bytes": len(content_bytes),
            "top_level_titled_work": profile["top_level_titled_work"],
        }
    )
    produced["source-accountability.json"] = _json(account)
    return produced


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
