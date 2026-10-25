"""Select the source-attested first examination from retained TCP A22076."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


TEI = "{http://www.tei-c.org/ns/1.0}"
SOURCE_SHA = "211a2c0d5029ca1dc6622b419fea356a0bba0ee28a363bd8c4e28331b3b6f92a"
CONVERTER_ID = "ocd-anne-a22076-first-scoped"
CONVERTER_VERSION = "1"


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    if manifest.record.get("source_id") != "tcp-A22076" or manifest.record.get("work_id") != "anne-askew-first-examinacyon":
        raise ValueError("A22076 first-work identity differs")
    source = manifest.authority_path("retained-tei-p5").read_bytes()
    if _sha(source) != SOURCE_SHA:
        raise ValueError("A22076 retained source changed")
    policy = json.loads(manifest.authority_path("validation-policy").read_text(encoding="utf-8"))
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_text(encoding="utf-8"))
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True)
    root = etree.fromstring(source, parser)
    group = root.find(f"{TEI}text/{TEI}group")
    if group is None or len(group) != 2 or [child.tag for child in group] != [TEI + "text", TEI + "text"]:
        raise ValueError("A22076 retained two-text envelope changed")
    first, second = group
    if not first.find(f"{TEI}body/{TEI}trailer") is not None:
        raise ValueError("first examination trailer is absent")
    if second.find(f"{TEI}front/{TEI}div[@type='preface']") is None:
        raise ValueError("out-of-work preface boundary changed")
    source_header = root.find(TEI + "teiHeader")
    outer = root.find(TEI + "text")
    if source_header is None or outer is None or profile.get("source_sha256") != SOURCE_SHA:
        raise ValueError("A22076 source profile/header differs")
    root.remove(outer)
    root.append(deepcopy(first))
    candidate = etree.tostring(root, encoding="utf-8", xml_declaration=True, pretty_print=False)
    account = {
        "contract": "ocd-anne-a22076-work-scope-v1",
        "source_path": "raw/tcp/high-range/A22076/A22076.xml",
        "source_sha256": SOURCE_SHA,
        "source_bytes": len(source),
        "candidate_sha256": _sha(candidate),
        "candidate_bytes": len(candidate),
        "header": "retained in candidate without editorial replacement",
        "included": {
            "selector": "/TEI/text/group/text[1]",
            "work_id": "anne-askew-first-examinacyon",
            "source_tree_sha256": profile["first_text_tree_sha256"],
            "page_breaks": profile["first_page_breaks"],
            "disposition": "direct TEI/text child; all front, body, trailer, and back matter retained",
        },
        "excluded": {
            "selector": "/TEI/text/group/text[2]",
            "source_tree_sha256": profile["second_text_tree_sha256"],
            "page_breaks": profile["second_page_breaks"],
            "disposition": "accounted out-of-work source matter; retained A22076 bytes remain unchanged",
            "physical_placement": "unverified",
        },
        "acquisition_receipt_sha256": _sha(manifest.authority_path("acquisition-receipt").read_bytes()),
        "member_inventory_sha256": _sha(manifest.authority_path("member-inventory").read_bytes()),
    }
    return {
        "README.source.md": manifest.authority_path("source-local-attribution-readme").read_bytes(),
        "content.tei.xml": candidate,
        "provenance.json": _json(policy["provenance"]),
        "source-accountability.json": _json(account),
        "unresolved.jsonl": b"".join(_json(item) for item in policy["unresolved"]),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
