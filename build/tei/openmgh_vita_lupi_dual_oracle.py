"""Independent full-tree source oracle for both Vita Lupi electronic editions."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path

from lxml import etree

from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
EXPECTED = {
    "bsb00000750": ("a88f93a090b6fd452a05b3cbc39a50f7bd7059cd94547f3cd712a4937243f0fc",
                    39, 10, "Vita Lupi ep. Trecensis", "Vita Aniani ep. Aurel.",
                    "Vita patrum Iurensium Romani, Lupicini, Eugendi",
                    "bsb00000750_00128_9", "bsb00000750_00132_12"),
    "bsb00000754": ("3349fbef5e7e957e964433d097e94a4a35d84addcbd6a314a88819e6a53039ff",
                    20, 9, "Vita Lupi", "Vita Germani", "Vita Sollemnis",
                    "bsb00000754_00305_15", "bsb00000754_00312_14"),
}


def _same(original: etree._Element, actual: etree._Element, *, outer: bool = False) -> bool:
    if (original.tag != actual.tag or dict(original.attrib) != dict(actual.attrib)
            or original.text != actual.text or len(original) != len(actual)
            or not outer and original.tail != actual.tail):
        return False
    return all(_same(a, b) for a, b in zip(original, actual, strict=True))


def check(code: str, candidate_bytes: bytes) -> dict:
    if code not in EXPECTED:
        raise ValueError(f"unselected Vita Lupi witness: {code}")
    digest, volume_count, index, label, before, after, first, last = EXPECTED[code]
    path = Path("raw/openmgh") / code / "tei" / f"{code}.xml"
    original_bytes = _io_path(ROOT / path).read_bytes()
    if sha256(original_bytes).hexdigest() != digest:
        raise ValueError(f"{code} source XML changed")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True)
    original = etree.fromstring(original_bytes, parser)
    candidate = etree.fromstring(candidate_bytes, parser)
    if (original.tag != TEI + "TEI" or candidate.tag != TEI + "TEI"
            or original.getroottree().docinfo.doctype or candidate.getroottree().docinfo.doctype):
        raise ValueError("source or candidate TEI envelope differs")
    original_header = original.find(TEI + "teiHeader")
    candidate_header = candidate.find(TEI + "teiHeader")
    if original_header is None or candidate_header is None or not _same(original_header, candidate_header, outer=True):
        raise ValueError(f"{code} electronic source header, rights, or bibliography differs")
    source_text = original.find(TEI + "text")
    source_body = source_text.find(TEI + "body") if source_text is not None else None
    target_text = candidate.find(TEI + "text")
    target_body = target_text.find(TEI + "body") if target_text is not None else None
    if (source_body is None or len(source_body) != 1 or len(source_body[0]) != volume_count
            or source_body[0].tag != TEI + "div" or source_body[0].get("type") != "volume"
            or target_body is None or list(candidate) != [candidate_header, target_text]
            or list(target_text) != [target_body] or len(target_body) != 1
            or any((node.text or "").strip() for node in (source_text, source_body, source_body[0]))
            or any(node.tag != TEI + "div" or node.get("type") != "work"
                   or (node.tail or "").strip() for node in source_body[0])):
        raise ValueError(f"{code} volume or candidate work partition differs")
    volume = source_body[0]
    selected = volume[index]
    if (selected.get("n") != label or volume[index - 1].get("n") != before
            or volume[index + 1].get("n") != after or len(selected) != 1
            or selected[0].tag != TEI + "ab" or not _same(selected, target_body[0], outer=True)):
        raise ValueError(f"{code} full Vita Lupi tree or boundary differs")
    counts = Counter(node.get(XML_ID) for node in original.iter() if node.get(XML_ID))
    ids = [node.get(XML_ID) for node in selected.iter() if node.get(XML_ID)]
    if (counts[first] != 1 or counts[last] != 1 or ids.count(first) != 1 or ids.count(last) != 1
            or ids.index(first) >= ids.index(last) or selected[0][-1].get(XML_ID) != last):
        raise ValueError(f"{code} complete source locator span differs")
    selected_ids = set(ids)
    for node in selected.iter():
        for attribute in ("target", "corresp"):
            value = node.get(attribute)
            if value and any(not ref.startswith("#") or ref[1:] not in selected_ids
                             for ref in value.split()):
                raise ValueError(f"{code} fragment reference leaves selected work")
    return {
        "contract": "ocd-openmgh-vita-lupi-dual-source-oracle-v1", "source_path": path.as_posix(),
        "source_sha256": digest, "candidate_sha256": sha256(candidate_bytes).hexdigest(),
        "work_div_index": index, "volume_work_count": volume_count,
        "source_div_c14n_sha256": sha256(etree.tostring(selected, method="c14n", with_comments=True)).hexdigest(),
        "first_id": first, "last_id": last, "selected_xml_id_count": len(ids),
        "other_work_divisions": volume_count - 1, "full_tree": "pass", "header": "pass",
    }
