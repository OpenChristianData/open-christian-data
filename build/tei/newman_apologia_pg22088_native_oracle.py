"""Independent source and reversible-structure check for PG22088 native TEI."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path
import re

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.reconstruction.decision import _load_bound_validator


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "sources/structured-text/newman-apologia-pro-vita-sua/LIB-068.source-manifest.json"
PACKAGE = Path("D:/Library/Open Christian Data/candidate-reviews/newman-apologia-pg22088-agent-20260928-r1/package")
TEI = "{http://www.tei-c.org/ns/1.0}"
EXPECTED = {
    "source-whitespace": 1360,
    "source-column-fragment": 743,
    "numbered-list": 47,
    "numbered-verse-group": 1,
    "numbered-embedded-letter": 9,
    "recipient-address": 8,
    "recipient-address-line": 8,
    "table-cell-source-n": 667,
}


def _restore(node: etree._Element, counts: Counter[str]) -> None:
    """Recover the direct carrier model from adapted TEI, without producer code."""
    if node.tag == TEI + "ab" and node.get("type") == "source-block" and node.get("subtype") == "source-whitespace":
        del node.attrib["subtype"]
        node.set("type", "source-whitespace")
        counts["source-whitespace"] += 1
    elif node.tag == TEI + "seg" and (node.get("subtype") or "").startswith("source-part-"):
        subtype = node.attrib.pop("subtype")
        match = re.fullmatch(r"source-part-(I|F|N)__(source-column-[a-z]+-[0-9]+-[0-9]+)", subtype)
        if node.get("type") != "source-line-fragment" or match is None:
            raise ValueError("PG22088 source-column subtype cannot be reversed")
        node.set("part", match.group(1))
        node.set("function", match.group(2))
        counts["source-column-fragment"] += 1
    elif node.tag in {TEI + "list", TEI + "lg", TEI + "floatingText"} and "__source_n_" in (node.get("type") or ""):
        role, separator, number = node.get("type").rpartition("__source_n_")
        if not separator or not role or re.fullmatch(r"[1-9][0-9]*(?:-[1-9][0-9]*)?", number) is None:
            raise ValueError("PG22088 source coordinate cannot be reversed")
        node.set("type", role)
        node.set("n", number)
        counts[{TEI + "list": "numbered-list", TEI + "lg": "numbered-verse-group",
                TEI + "floatingText": "numbered-embedded-letter"}[node.tag]] += 1
    elif node.tag == TEI + "seg" and node.get("type") == "source-recipient-address":
        if dict(node.attrib) != {"type": "source-recipient-address"}:
            raise ValueError("PG22088 recipient address attributes cannot be reversed")
        node.tag = TEI + "address"
        node.set("type", "source-recipient")
        counts["recipient-address"] += 1
    elif node.tag == TEI + "seg" and node.get("type") == "source-recipient-address-line":
        if dict(node.attrib) != {"type": "source-recipient-address-line"}:
            raise ValueError("PG22088 recipient address line attributes cannot be reversed")
        node.tag = TEI + "addrLine"
        del node.attrib["type"]
        counts["recipient-address-line"] += 1
    elif node.tag == TEI + "cell" and "__source_n_" in (node.get("role") or ""):
        role, marker, number = node.get("role").rpartition("__source_n_")
        if not marker or not role or not number or "__source_n_" in number:
            raise ValueError("PG22088 table-cell coordinate cannot be reversed")
        node.set("role", role)
        node.set("n", number)
        counts["table-cell-source-n"] += 1
    for child in node:
        _restore(child, counts)


def _compare(direct: etree._Element, restored: etree._Element, path: str = "TEI") -> None:
    if (direct.tag != restored.tag or dict(direct.attrib) != dict(restored.attrib)
            or direct.text != restored.text or direct.tail != restored.tail
            or len(direct) != len(restored)):
        raise ValueError(f"PG22088 reverse structural or text difference at {path}")
    for position, (before, after) in enumerate(zip(direct, restored, strict=True), 1):
        _compare(before, after, f"{path}/{position}")


def check(adapted: bytes) -> dict[str, object]:
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    package = CandidatePackage.load(PACKAGE)
    report = validate(manifest, package, _load_bound_validator(manifest))
    if report.status != "pass" or report.findings:
        raise ValueError("PG22088 independent complete-source oracle failed")
    direct = package.member_bytes("content.tei.xml")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    before = etree.fromstring(direct, parser)
    after = etree.fromstring(adapted, parser)
    counts: Counter[str] = Counter()
    _restore(after, counts)
    if dict(counts) != EXPECTED:
        raise ValueError(f"PG22088 reverse carrier census differs: {dict(counts)}")
    _compare(before, after)
    return {
        "contract": "ocd-newman-apologia-pg22088-source-to-native-independent-oracle-v1",
        "source_manifest_sha256": manifest.sha256,
        "direct_package_sha256": package.sha256,
        "direct_tei_sha256": sha256(direct).hexdigest(),
        "adapted_tei_sha256": sha256(adapted).hexdigest(),
        "source_oracle_status": report.status,
        "carrier_counts": EXPECTED,
    }


def check_partition(adapted: bytes, work: bytes, header: bytes, license: bytes) -> dict[str, object]:
    """Independently rejoin evidence-only divisions and compare the full TEI tree."""
    source_report = check(adapted)
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    complete_root = etree.fromstring(adapted, parser)
    work_root = etree.fromstring(work, parser)
    header_node = etree.fromstring(header, parser)
    license_node = etree.fromstring(license, parser)
    complete_scope = complete_root.find(TEI + "text/" + TEI + "body/" + TEI + "div")
    work_scope = work_root.find(TEI + "text/" + TEI + "body/" + TEI + "div")
    if complete_scope is None or work_scope is None or len(complete_scope) != 9 or len(work_scope) != 7:
        raise ValueError("PG22088 complete/work division census differs")
    if ([node.get("type") for node in complete_scope] !=
            ["gutenberg-header", "title-page", "preface", "contents", "main-text",
             "notes", "supplement", "additional-notes", "gutenberg-license"]):
        raise ValueError("PG22088 source-profile division boundary differs")
    if (header_node.get("type"), header_node.get("n")) != ("gutenberg-header", "1"):
        raise ValueError("PG22088 provider-header evidence identity differs")
    if (license_node.get("type"), license_node.get("n")) != ("gutenberg-license", "13823"):
        raise ValueError("PG22088 provider-license evidence identity differs")

    def lines(node: etree._Element) -> list[int]:
        base = "newman-apologia-pro-vita-sua-line-"
        xml_id = "{http://www.w3.org/XML/1998/namespace}id"
        return [int(seg.get("n")) for seg in node.iter(TEI + "seg") if seg.get("n") and
                (seg.get("type") == "source-line" or
                 (seg.get("type") == "source-line-fragment" and
                  seg.get(xml_id) == base + seg.get("n")))]

    if (lines(header_node) != list(range(1, 33))
            or lines(work_scope) != list(range(33, 13823))
            or lines(license_node) != list(range(13823, 14175))):
        raise ValueError("PG22088 source line partition differs")
    work_scope.insert(0, header_node)
    work_scope.append(license_node)
    _compare(complete_root, work_root)
    return source_report | {
        "partition_contract": "ocd-newman-apologia-pg22088-provider-evidence-partition-v1",
        "work_tei_sha256": sha256(work).hexdigest(),
        "provider_header_sha256": sha256(header).hexdigest(),
        "provider_license_sha256": sha256(license).hexdigest(),
        "work_line_range": [33, 13822],
        "provider_header_line_range": [1, 32],
        "provider_license_line_range": [13823, 14174],
        "represented_work_lines": 13790,
        "evidence_only_provider_lines": 384,
    }
