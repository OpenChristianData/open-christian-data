"""Independent full-source and structural check of the PG16739 native adaptation."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path

from lxml import etree

from build.tei.drummond_greatest_thing_37c135_oracle import _oracle
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "sources/structured-text/lib071-gutenberg-evangelical/work-bindings/drummond-greatest-thing/37c-135-source-underscore-emphasis-v2.source-manifest.json"
PACKAGE = Path("D:/Library/Open Christian Data/candidate-reviews/drummond-pg16739-native-prep-20260928/package/package")
TEI = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"


def _match(before: etree._Element, after: etree._Element, counts: Counter[str]) -> None:
    name = before.tag.removeprefix(TEI)
    expected_tag = before.tag
    expected_attributes = dict(before.attrib)
    if name == "space" and before.get("type") == "source-blank-line":
        expected_tag = TEI + "div"
        expected_attributes = {
            "type": "source-blank-line", "subtype": "crlf", "n": before.get("n"),
            XML + "id": before.get(XML + "id"),
        }
        counts["blank"] += 1
    elif name == "c" and before.get("type") == "emphasis-delimiter":
        expected_tag = TEI + "seg"
        counts["delimiter"] += 1
    elif name == "head" and before.get("type") == "source-located-heading":
        expected_tag = TEI + "ab"
        expected_attributes["type"] = "source-h" + expected_attributes.pop("subtype")
        counts["located_heading"] += 1
    elif name == "head" and before.get("type") == "source-attached-title":
        expected_tag = TEI + "ab"
        expected_attributes["type"] = "source-heading"
        expected_attributes["subtype"] = "attached-title"
        counts["attached_title"] += 1
    if (after.tag != expected_tag or dict(after.attrib) != expected_attributes
            or after.text != before.text or after.tail != before.tail
            or len(after) != len(before)):
        raise ValueError(f"PG16739 adapted native source node differs: {name}")
    for source_child, native_child in zip(before, after, strict=True):
        _match(source_child, native_child, counts)


def check(adapted: bytes) -> dict[str, object]:
    """Verify the direct candidate against source, then every adapted XML node."""
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    direct = CandidatePackage.load(PACKAGE)
    report = validate(manifest, direct, _oracle)
    if report.status != "pass":
        raise ValueError("PG16739 independent full-source oracle failed")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    source = etree.fromstring(direct.member_bytes("content.tei.xml"), parser)
    native = etree.fromstring(adapted, parser)
    source_text = source.find(TEI + "text")
    native_text = native.find(TEI + "text")
    if (source_text is None or native_text is None or len(source_text) != 1
            or source_text[0].tag != TEI + "group" or len(source_text[0]) != 1
            or source_text[0][0].tag != TEI + "text" or len(source_text[0][0]) != 1
            or len(native_text) != 1):
        raise ValueError("PG16739 exact one-member envelope differs")
    member = source_text[0][0]
    expected_text_attributes = dict(source_text.attrib) | dict(member.attrib)
    if (native_text.attrib != expected_text_attributes or native_text.text != source_text.text
            or native_text.tail != source_text.tail or member[0].tag != TEI + "body"):
        raise ValueError("PG16739 adapted native text envelope differs")
    if (source.tag != native.tag or source.attrib != native.attrib
            or source.text != native.text or source.tail != native.tail
            or len(source) != len(native)):
        raise ValueError("PG16739 adapted native document envelope differs")
    counts: Counter[str] = Counter()
    for before, after in zip(source, native, strict=True):
        if before is source_text:
            _match(member[0], native_text[0], counts)
        else:
            _match(before, after, counts)
    expected_counts = {"blank": 665, "delimiter": 362, "located_heading": 18, "attached_title": 3}
    if dict(counts) != expected_counts:
        raise ValueError(f"PG16739 native carrier census differs: {dict(counts)}")
    return {
        "contract": "ocd-drummond-pg16739-source-to-native-independent-oracle-v1",
        "source_manifest_sha256": manifest.sha256,
        "direct_package_sha256": direct.sha256,
        "direct_tei_sha256": sha256(direct.member_bytes("content.tei.xml")).hexdigest(),
        "adapted_tei_sha256": sha256(adapted).hexdigest(),
        "source_oracle_status": report.status,
        "carrier_counts": expected_counts,
    }
