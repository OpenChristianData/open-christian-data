"""npnf1_census.py
Structural census for NPNF1 Augustine volumes (npnf101-npnf108).
Prints div1/div2 structure, heading patterns, and sample paragraphs.
Run after downloading all 8 XMLs.
"""

import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

RAW_DIR = Path(__file__).resolve().parents[2] / "raw" / "ccel" / "npnf1"

THML_ENTITY_MAP = {
    "&mdash;": "\u2014", "&ndash;": "\u2013", "&lsquo;": "\u2018",
    "&rsquo;": "\u2019", "&ldquo;": "\u201c", "&rdquo;": "\u201d",
    "&nbsp;": " ", "&hellip;": "...", "&emdash;": "\u2014",
    "&agrave;": "\u00e0", "&aacute;": "\u00e1", "&egrave;": "\u00e8",
    "&eacute;": "\u00e9", "&iacute;": "\u00ed", "&oacute;": "\u00f3",
    "&uacute;": "\u00fa", "&Agrave;": "\u00c0", "&Aacute;": "\u00c1",
    "&Egrave;": "\u00c8", "&Eacute;": "\u00c9", "&Iacute;": "\u00cd",
    "&Oacute;": "\u00d3", "&Uacute;": "\u00da", "&auml;": "\u00e4",
    "&euml;": "\u00eb", "&iuml;": "\u00ef", "&ouml;": "\u00f6",
    "&uuml;": "\u00fc", "&Auml;": "\u00c4", "&Euml;": "\u00cb",
    "&Ouml;": "\u00d6", "&Uuml;": "\u00dc", "&aelig;": "\u00e6",
    "&AElig;": "\u00c6", "&ccedil;": "\u00e7", "&Ccedil;": "\u00c7",
    "&ntilde;": "\u00f1", "&Ntilde;": "\u00d1", "&szlig;": "\u00df",
    "&laquo;": "\u00ab", "&raquo;": "\u00bb", "&alpha;": "\u03b1",
    "&beta;": "\u03b2", "&gamma;": "\u03b3", "&delta;": "\u03b4",
    "&epsilon;": "\u03b5", "&zeta;": "\u03b6", "&eta;": "\u03b7",
    "&theta;": "\u03b8", "&iota;": "\u03b9", "&kappa;": "\u03ba",
    "&lambda;": "\u03bb", "&mu;": "\u03bc", "&nu;": "\u03bd",
    "&xi;": "\u03be", "&omicron;": "\u03bf", "&pi;": "\u03c0",
    "&rho;": "\u03c1", "&sigma;": "\u03c3", "&tau;": "\u03c4",
    "&upsilon;": "\u03c5", "&phi;": "\u03c6", "&chi;": "\u03c7",
    "&psi;": "\u03c8", "&omega;": "\u03c9",
}
XML_SAFE = {"&amp;", "&lt;", "&gt;", "&quot;", "&apos;"}


def _replace_entity(m):
    e = m.group(0)
    return e if e in XML_SAFE else THML_ENTITY_MAP.get(e, "")


def preprocess(raw_bytes):
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = raw_bytes.decode("cp1252", errors="replace")
    text = re.sub(r"<!DOCTYPE\s[^[>]*(?:\[[^\]]*\])?>", "", text, flags=re.DOTALL)
    text = re.sub(r"&[A-Za-z][A-Za-z0-9]*;", _replace_entity, text)
    return text


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def get_all_text(elem, max_chars=200):
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        if child.tag in ("note", "pb"):
            if child.tail:
                parts.append(child.tail)
            continue
        parts.append(get_all_text(child, max_chars))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)[:max_chars]


def first_paragraph(div_elem, max_depth=3, depth=0):
    """Return first non-empty paragraph text found under elem."""
    for child in div_elem:
        if child.tag == "p":
            t = clean(get_all_text(child, 300))
            if t:
                return t
        if re.match(r"^div\d?$", child.tag) and depth < max_depth:
            result = first_paragraph(child, max_depth, depth + 1)
            if result:
                return result
    return None


def census_volume(slug):
    xml_path = RAW_DIR / f"{slug}.xml"
    if not xml_path.exists():
        print(f"  MISSING: {xml_path}")
        return

    raw = xml_path.read_bytes()
    text = preprocess(raw)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        print(f"  PARSE ERROR: {e}")
        return

    body = root.find("ThML.body")
    if body is None:
        print("  No <ThML.body>")
        return

    div_re = re.compile(r"^div\d?$")
    print(f"\n--- {slug} ({xml_path.stat().st_size // 1024} KB) ---")

    div1_count = 0
    for div1 in body:
        if not div_re.match(div1.tag):
            continue
        div1_count += 1
        d1_id = div1.get("id", "")
        d1_type = div1.get("type", "")
        d1_title = clean(div1.get("title", ""))
        d1_n = div1.get("n", "")

        # Get heading from first h* child if no title attr
        if not d1_title:
            for child in div1:
                if child.tag in ("h1", "h2", "h3", "h4", "title"):
                    d1_title = clean(get_all_text(child, 100))
                    break

        print(f"  div1 id={d1_id!r:8s} type={d1_type!r:20s} n={d1_n!r:5s} title={d1_title[:80]!r}")

        # Show div2 children
        div2_shown = 0
        for div2 in div1:
            if not div_re.match(div2.tag):
                continue
            d2_id = div2.get("id", "")
            d2_type = div2.get("type", "")
            d2_title = clean(div2.get("title", ""))
            d2_n = div2.get("n", "")
            if not d2_title:
                for child in div2:
                    if child.tag in ("h1", "h2", "h3", "h4", "title"):
                        d2_title = clean(get_all_text(child, 100))
                        break
            print(f"    div2 id={d2_id!r:12s} type={d2_type!r:20s} n={d2_n!r:5s} title={d2_title[:70]!r}")
            div2_shown += 1
            if div2_shown >= 8:
                # Count remaining
                remaining = sum(1 for d in div1 if div_re.match(d.tag)) - div2_shown
                if remaining > 0:
                    print(f"    ... ({remaining} more div2 elements)")
                break

        # Show a sample paragraph
        sample = first_paragraph(div1)
        if sample:
            print(f"    SAMPLE: {sample[:200]!r}")

    print(f"  Total div1 elements: {div1_count}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    volumes = [f"npnf10{i}" for i in range(1, 9)]
    if len(sys.argv) > 1:
        volumes = sys.argv[1:]
    for slug in volumes:
        census_volume(slug)


if __name__ == "__main__":
    main()
