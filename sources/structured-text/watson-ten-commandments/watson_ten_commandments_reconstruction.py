"""Watson-specific correction for ThML navigation titles in body content.

The shared selected-ThML converter maps source ``div@title`` values to
synthetic TEI heads when they differ from direct headings. For this witness,
those attributes are navigation labels and every affected division already
has a direct source heading. This adapter preserves the shared element mapping
and removes only those unsupported duplicate body heads.
"""

from __future__ import annotations

import json

from lxml import etree

from build.tei.selected_thml import _convert as _convert_selected_thml


WORK_ID = "watson-ten-commandments"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
PROFILE_RULE = {
    "source_attribute": "div@title",
    "disposition": "Retain as source navigation metadata in the complete source-feature ledger.",
    "when_direct_heading_exists": (
        "Map the direct source h1, h2, or h3 headings only; do not synthesize a TEI head from div@title."
    ),
    "when_no_direct_heading_exists": "Preserve div@title as a synthetic TEI head.",
    "source_derived_synthetic_heads_suppressed": 7,
}
_HEADING_TAGS = frozenset({"h1", "h2", "h3"})


def _normalized_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def _convert(manifest):
    """Produce a source-bound candidate without body heads from nav labels."""

    if manifest.record.get("work_id") != WORK_ID:
        raise ValueError("Watson Ten Commandments route received another work")
    manifest.verify()
    profile = json.loads(manifest.authority_path("profile").read_text(encoding="utf-8"))
    rule = profile.get("heading_policy", {}).get("division_title_rule")
    if rule != PROFILE_RULE:
        raise ValueError("Watson division-title rule differs from the bound profile")

    produced = _convert_selected_thml(manifest)
    raw = manifest.authority_path("retained-source").read_bytes()
    source_root = etree.fromstring(
        raw,
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            recover=False,
            remove_comments=False,
            remove_pis=False,
        ),
    )
    account = json.loads(produced["source-accountability.json"].decode("utf-8"))
    features_by_path = {row["source_path"]: row for row in account["features"]}
    if len(features_by_path) != len(account["features"]):
        raise ValueError("Watson source feature paths are not unique")
    tei_root = etree.fromstring(
        produced["content.tei.xml"],
        etree.XMLParser(resolve_entities=False, no_network=True, recover=False),
    )

    suppressed = 0
    source_tree = source_root.getroottree()
    for source in source_root.iter():
        if (
            not isinstance(source.tag, str)
            or not source.tag.startswith("div")
            or not source.get("title")
        ):
            continue
        direct_headings = [
            child for child in source
            if isinstance(child.tag, str) and child.tag in _HEADING_TAGS
        ]
        if not direct_headings:
            continue
        title = source.get("title")
        if any(
            _normalized_text("".join(heading.itertext())) == _normalized_text(title)
            for heading in direct_headings
        ):
            continue

        source_path = source_tree.getpath(source)
        feature = features_by_path.get(source_path)
        if feature is None:
            raise ValueError(f"Watson division lacks a source feature row: {source_path}")
        targets = tei_root.xpath(
            "//*[@xml:id=$value]",
            namespaces={"xml": XML_NS},
            value=feature["tei_id"],
        )
        if len(targets) != 1:
            raise ValueError(f"Watson division target is missing or ambiguous: {source_path}")
        target = targets[0]
        if not len(target):
            raise ValueError(f"Watson division has no synthesized title head: {source_path}")
        synthetic = target[0]
        if (
            synthetic.tag != f"{{{TEI_NS}}}head"
            or synthetic.get(f"{{{XML_NS}}}id") is not None
            or synthetic.get("type") is not None
            or synthetic.text != title
        ):
            raise ValueError(f"Watson division title mapping differs: {source_path}")
        target.remove(synthetic)
        suppressed += 1

    expected = PROFILE_RULE["source_derived_synthetic_heads_suppressed"]
    if suppressed != expected:
        raise ValueError(
            f"Watson source-derived synthetic-head count differs: {suppressed} != {expected}"
        )
    produced["content.tei.xml"] = etree.tostring(
        tei_root, encoding="utf-8", xml_declaration=True
    )
    return produced


_convert.converter_id = "ocd-watson-ten-commandments-selected-thml-to-tei"
_convert.converter_version = "1"
