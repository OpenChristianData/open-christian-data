"""Extract the two complete, separately acquired Vita Lupi electronic editions."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

from lxml import etree

from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "vita-sancti-lupi-trecensis"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
CONTRACT = "ocd-openmgh-vita-lupi-dual-exact-div-v1"
WITNESSES = {
    "bsb00000750": {
        "source_sha256": "a88f93a090b6fd452a05b3cbc39a50f7bd7059cd94547f3cd712a4937243f0fc",
        "package_sha256": "71542cfb4f7372efd3908996848052cdf3fcc2a0d7c14348dc16fa407338a22c",
        "receipt_sha256": "fae4db8f39ebf080e3a9b499a7bd29b5c26ceef277fb360191753cb5fd7aab5d",
        "work_div_index": 10, "volume_work_count": 39,
        "work_div_n": "Vita Lupi ep. Trecensis",
        "preceding_work_n": "Vita Aniani ep. Aurel.",
        "following_work_n": "Vita patrum Iurensium Romani, Lupicini, Eugendi",
        "first_id": "bsb00000750_00128_9", "last_id": "bsb00000750_00132_12",
    },
    "bsb00000754": {
        "source_sha256": "3349fbef5e7e957e964433d097e94a4a35d84addcbd6a314a88819e6a53039ff",
        "package_sha256": "f25422ac5fb447be60d9d6fcc99509a546144224ac68b370c220b89df0a715fe",
        "receipt_sha256": "67f23305c57ba40d40f351393c3dd7408b36bbcdaeef27113fb6bd2b7ee0eeb2",
        "work_div_index": 9, "volume_work_count": 20,
        "work_div_n": "Vita Lupi",
        "preceding_work_n": "Vita Germani", "following_work_n": "Vita Sollemnis",
        "first_id": "bsb00000754_00305_15", "last_id": "bsb00000754_00312_14",
    },
}


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def paths(code: str) -> tuple[Path, Path, Path]:
    if code not in WITNESSES:
        raise ValueError(f"unselected Vita Lupi source: {code}")
    home = Path("raw/openmgh") / code
    return home / "tei" / f"{code}.xml", home / f"{code}.zip", home / "acquisition-receipt.json"


def source_div(code: str) -> tuple[bytes, etree._Element, etree._Element]:
    spec = WITNESSES[code]
    source_path, package_path, receipt_path = paths(code)
    raw = _io_path(ROOT / source_path).read_bytes()
    archive = _io_path(ROOT / package_path).read_bytes()
    if (_sha(raw) != spec["source_sha256"] or _sha(archive) != spec["package_sha256"]
            or _sha(_io_path(ROOT / receipt_path).read_bytes()) != spec["receipt_sha256"]):
        raise ValueError(f"{code} retained source, package, or receipt changed")
    with ZipFile(_io_path(ROOT / package_path)) as package:
        if package.namelist() != [f"{code}.xml"] or package.read(f"{code}.xml") != raw:
            raise ValueError(f"{code} package member differs from extracted XML")
    root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True,
                                                 remove_comments=False, huge_tree=True))
    if root.tag != TEI + "TEI" or root.getroottree().docinfo.doctype:
        raise ValueError(f"{code} source envelope changed")
    text = root.find(TEI + "text")
    body = text.find(TEI + "body") if text is not None else None
    if (text is None or body is None or list(text) != [body] or len(body) != 1
            or body[0].tag != TEI + "div" or body[0].get("type") != "volume"
            or any((node.text or "").strip() for node in (text, body, body[0]))
            or len(body[0]) != spec["volume_work_count"]
            or any(child.tag != TEI + "div" or child.get("type") != "work"
                   or (child.tail or "").strip() for child in body[0])):
        raise ValueError(f"{code} volume envelope or work partition changed")
    volume = body[0]
    index = spec["work_div_index"]
    selected = volume[index]
    if (selected.get("n") != spec["work_div_n"]
            or volume[index - 1].get("n") != spec["preceding_work_n"]
            or volume[index + 1].get("n") != spec["following_work_n"]
            or len(selected) != 1 or selected[0].tag != TEI + "ab"):
        raise ValueError(f"{code} Vita Lupi division boundary changed")
    ids = [node.get(XML_ID) for node in selected.iter() if node.get(XML_ID)]
    first, last = spec["first_id"], spec["last_id"]
    if (ids.count(first) != 1 or ids.count(last) != 1 or ids.index(first) >= ids.index(last)
            or sum(node.get(XML_ID) == first for node in root.iter()) != 1
            or sum(node.get(XML_ID) == last for node in root.iter()) != 1
            or not any(node.get(XML_ID) == last for node in selected[-1])):
        raise ValueError(f"{code} catalog locators do not bind complete Vita Lupi division")
    selected_ids = set(ids)
    for node in selected.iter():
        for attribute in ("target", "corresp"):
            value = node.get(attribute)
            if value and any(not ref.startswith("#") or ref[1:] not in selected_ids
                             for ref in value.split()):
                raise ValueError(f"{code} fragment reference leaves Vita Lupi")
    return raw, root, selected


def convert(code: str) -> tuple[bytes, dict]:
    raw, source, selected = source_div(code)
    work = json.loads(_io_path(ROOT / "library/works" / WORK_ID / "work.json").read_bytes())
    if work["work_id"] != WORK_ID or len(work["textual_forms"]) != 1:
        raise ValueError("Vita Lupi work identity changed")
    editions = work["textual_forms"][0]["editions"]
    if len(editions) != 2 or {e["edition_id"].split("-")[-2] for e in editions} != set(WITNESSES):
        raise ValueError("Vita Lupi has changed editions")
    edition = next(e for e in editions if e["edition_id"].endswith(f"{code}-electronic"))
    source_path, _, _ = paths(code)
    expected_locator = "; ".join(f"{source_path.as_posix()}#{WITNESSES[code][key]}"
                                  for key in ("first_id", "last_id"))
    if edition["containing_source"]["locator"] != expected_locator:
        raise ValueError(f"{code} edition locator differs")
    result = etree.Element(TEI + "TEI", nsmap=source.nsmap)
    result.set(XML_ID, f"ocd-{WORK_ID}-{code}-v1")
    result.append(deepcopy(source.find(TEI + "teiHeader")))
    body = etree.SubElement(etree.SubElement(result, TEI + "text"), TEI + "body")
    body.append(deepcopy(selected))
    content = etree.tostring(result, encoding="UTF-8", xml_declaration=True)
    return content, {
        "contract": CONTRACT, "work_id": WORK_ID, "edition_id": edition["edition_id"],
        "source_path": source_path.as_posix(), "source_sha256": _sha(raw),
        "source_bytes": len(raw), "work_div_index": WITNESSES[code]["work_div_index"],
        "work_div_n": selected.get("n"), "volume_work_count": WITNESSES[code]["volume_work_count"],
        "first_id": WITNESSES[code]["first_id"], "last_id": WITNESSES[code]["last_id"],
        "source_div_c14n_sha256": _sha(etree.tostring(selected, method="c14n", with_comments=True)),
        "candidate_sha256": _sha(content), "candidate_bytes": len(content),
        "other_work_divisions": WITNESSES[code]["volume_work_count"] - 1,
    }
