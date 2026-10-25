"""Independent complete-source and node check of the PG44035 native adaptation."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path

from lxml import etree

from build.tei.strong_vol1_pg44035_native import EXPECTED
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.reconstruction.decision import _load_bound_validator


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "sources/structured-text/strong-systematic-theology-vol-1/strong-systematic-theology-vol-1.source-manifest.json"
PACKAGE = Path("D:/Library/Open Christian Data/candidate-reviews/strong-systematic-theology-vol1-current-20260928-v1/package")
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _match(before: etree._Element, after: etree._Element, counts: Counter[str]) -> None:
    expected = dict(before.attrib)
    if before.tag == TEI + "ab" and before.get("type") in ("title-page-line", "contents-line"):
        kind = before.get("type")
        expected["type"] = "source-block"
        expected["subtype"] = kind
        counts[kind] += 1
    elif before.tag == TEI + "seg" and before.get("type") == "source-line":
        if expected.pop(XML_SPACE, None) != "preserve":
            raise ValueError("PG44035 direct source-line whitespace changed")
        expected["subtype"] = "xml-space-preserve"
        counts["source-line-space"] += 1
    if (after.tag != before.tag or dict(after.attrib) != expected
            or after.text != before.text or after.tail != before.tail
            or len(after) != len(before)):
        raise ValueError(f"PG44035 native adaptation changed source node {before.tag}")
    for original, adapted in zip(before, after, strict=True):
        _match(original, adapted, counts)


def check(adapted: bytes) -> dict[str, object]:
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    package = CandidatePackage.load(PACKAGE)
    report = validate(manifest, package, _load_bound_validator(manifest))
    if report.status != "pass":
        raise ValueError("PG44035 independent complete-source oracle failed")
    direct = package.member_bytes("content.tei.xml")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    before = etree.fromstring(direct, parser)
    after = etree.fromstring(adapted, parser)
    counts: Counter[str] = Counter()
    _match(before, after, counts)
    if dict(counts) != EXPECTED:
        raise ValueError(f"PG44035 native carrier census differs: {dict(counts)}")
    return {
        "contract": "ocd-strong-vol1-pg44035-source-to-native-independent-oracle-v1",
        "source_manifest_sha256": manifest.sha256,
        "direct_package_sha256": package.sha256,
        "direct_tei_sha256": sha256(direct).hexdigest(),
        "adapted_tei_sha256": sha256(adapted).hexdigest(),
        "source_oracle_status": report.status,
        "carrier_counts": EXPECTED,
    }
