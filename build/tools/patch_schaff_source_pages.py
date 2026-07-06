"""patch_schaff_source_pages.py
Populate source_pages and fix pd_anchor in the 12 Schaff-Herzog original records.

CCEL volumes (1, 2, 9):
  - pd_anchor stays "ccel-thml"
  - Parses raw/ccel/schaff-herzog/encycNN.xml, extracts <pb n="X"> page numbers
  - Populates source_pages = [{"rendering_id": "ccel-thml", "page_number": N}] per block
  - N is None if the entry appears before page 1 (front matter Roman numerals)

IA volumes (3, 4, 5, 6, 7, 8, 10, 11, 12):
  - pd_anchor changed from "ccel-thml" to "ia-ocr"
  - attested_by changed from ["ccel-thml"] to ["ia-ocr"] on every block
  - Parses raw/internet-archive/schaff-herzog/*.txt, extracts page markers
  - Populates source_pages = [{"rendering_id": "ia-ocr", "page_number": N}] per block

Usage:
    py -3 build/tools/patch_schaff_source_pages.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.paths import REPO_ROOT  # noqa: E402  -- re-import for canonical value

CCEL_RAW_DIR = REPO_ROOT / "raw" / "ccel" / "schaff-herzog"
IA_RAW_DIR = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog"
ORIGINAL_DIR = (
    REPO_ROOT / "data" / "reference" / "schaff" / "encyclopedia" / "1908-1914" / "original"
)

CCEL_VOLUMES: dict[int, str] = {1: "encyc01", 2: "encyc02", 9: "encyc09"}
IA_VOLUMES: dict[int, str] = {
    3: "03.NewSchaffHerzogEncycReligKnowl.v3.1909.Jackson.Sherman.Gilmore.1909._djvu.txt",
    4: "04.NewSchaffHerzogEncycReligKnowl.BibliogApend.v1-4.v4.Jackson.Sherman.Gilmore.1909._djvu.txt",
    5: "05.NewSchaffHerzogEncycReligKnowl.v5.Jackson.Sherman.Gilmore.1909._djvu.txt",
    6: "06.NewSchaffHerzogEncycReligKnowl.v6.Jackson.Sherman.Gilmore.1909._djvu.txt",
    7: "07.NewSchaffHerzogEncycReligKnowl.v7.Jackson.Sherman.Gilmore.1909._djvu.txt",
    8: "08.NewSchaffHerzogEncycReligKnowl.v8.Jackson.Sherman.Gilmore.1909._djvu.txt",
    10: "10.NewSchaffHerzogEncyc.ReligKnowl.v10.Jackson.Sherman.Gilmore.1909._djvu.txt",
    11: "11.NewSchaffHerzogEncyc.ReligKnowl.v11.Jackson.Sherman.Gilmore.1911._djvu.txt",
    12: "12.NewSchaffHerzogEncyc.ReligKnowl.v12.Jackson.Sherman.Gilmore.1912._djvu.txt",
}

CCEL_ANCHOR = "ccel-thml"
IA_ANCHOR = "ia-ocr"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared helpers (replicated to avoid parser module-level side effects)
# ---------------------------------------------------------------------------

import unicodedata


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "-", text)
    text = re.sub(r"[\s_-]+", "-", text.strip())
    text = text.strip("-")
    return text or "entry"


def _make_unique_id(base: str, seen: set) -> str:
    candidate = base
    counter = 2
    while candidate in seen:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


# ---------------------------------------------------------------------------
# CCEL ThML page extraction
# ---------------------------------------------------------------------------

# Minimal entity map for preprocessing (covers entities found in Schaff-Herzog ThML)
_ENTITY_REPLACEMENTS = {
    "&mdash;": "—", "&ndash;": "–", "&lsquo;": "‘", "&rsquo;": "’",
    "&ldquo;": "“", "&rdquo;": "”", "&nbsp;": " ", "&hellip;": "…",
    "&emdash;": "—", "&copy;": "©", "&reg;": "®", "&trade;": "™",
    "&deg;": "°", "&para;": "¶", "&sect;": "§", "&dagger;": "†",
    "&Dagger;": "‡", "&bull;": "•", "&prime;": "′", "&Prime;": "″",
    "&oline;": "‾", "&frasl;": "⁄", "&agrave;": "à", "&aacute;": "á",
    "&acirc;": "â", "&atilde;": "ã", "&auml;": "ä", "&aring;": "å",
    "&aelig;": "æ", "&ccedil;": "ç", "&egrave;": "è", "&eacute;": "é",
    "&ecirc;": "ê", "&euml;": "ë", "&igrave;": "ì", "&iacute;": "í",
    "&icirc;": "î", "&iuml;": "ï", "&eth;": "ð", "&ntilde;": "ñ",
    "&ograve;": "ò", "&oacute;": "ó", "&ocirc;": "ô", "&otilde;": "õ",
    "&ouml;": "ö", "&oslash;": "ø", "&ugrave;": "ù", "&uacute;": "ú",
    "&ucirc;": "û", "&uuml;": "ü", "&yacute;": "ý", "&thorn;": "þ",
    "&yuml;": "ÿ", "&alpha;": "α", "&beta;": "β", "&gamma;": "γ",
    "&delta;": "δ", "&epsilon;": "ε", "&zeta;": "ζ", "&eta;": "η",
    "&theta;": "θ", "&iota;": "ι", "&kappa;": "κ", "&lambda;": "λ",
    "&mu;": "μ", "&nu;": "ν", "&xi;": "ξ", "&omicron;": "ο",
    "&pi;": "π", "&rho;": "ρ", "&sigma;": "σ", "&tau;": "τ",
    "&upsilon;": "υ", "&phi;": "φ", "&chi;": "χ", "&psi;": "ψ",
    "&omega;": "ω",
}
_XML_SAFE = {"&amp;", "&lt;", "&gt;", "&quot;", "&apos;"}


def _replace_entity(m: re.Match) -> str:
    ent = m.group(0)
    if ent in _XML_SAFE:
        return ent
    return _ENTITY_REPLACEMENTS.get(ent, "")


def _preprocess_thml(raw_bytes: bytes) -> str:
    try:
        text = raw_bytes.decode("utf-8")
        if "�" in text:
            raise UnicodeDecodeError("utf-8", raw_bytes, 0, 1, "replacement chars found")
    except UnicodeDecodeError:
        text = raw_bytes.decode("cp1252", errors="replace")
    text = re.sub(r"<!DOCTYPE\s[^[>]*(?:\[[^\]]*\])?>", "", text, flags=re.DOTALL)
    text = re.sub(r"&[A-Za-z][A-Za-z0-9]*;", _replace_entity, text)
    return text


def _get_all_text(elem) -> str:
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        parts.append(_get_all_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_ccel_pages(vol_id: str) -> dict[str, int | None]:
    """Parse ThML XML; return {entry_id: page_number_or_None} for all articles.

    Traverses elements in document order. current_page tracks the last <pb>
    with an integer n= attribute; the page assigned to an article is the page
    current at the moment its <term type='Encyclopedia'> element is encountered.
    """
    xml_path = CCEL_RAW_DIR / f"{vol_id}.xml"
    raw_bytes = xml_path.read_bytes()
    xml_text = _preprocess_thml(raw_bytes)
    root = ET.fromstring(xml_text)

    current_page: int | None = None
    article_pages: list[tuple[str, int | None]] = []

    for elem in root.iter():
        if elem.tag == "pb":
            try:
                current_page = int(elem.get("n", ""))
            except (ValueError, TypeError):
                pass  # Roman numerals in front matter -- leave current_page unchanged
        elif elem.tag == "term" and elem.get("type") == "Encyclopedia":
            term_text = _clean_text(_get_all_text(elem))
            article_pages.append((term_text, current_page))

    seen_ids: set[str] = set()
    result: dict[str, int | None] = {}
    for term_text, page_num in article_pages:
        base_id = f"schaff-herzog.{_slugify(term_text)}"
        entry_id = _make_unique_id(base_id, seen_ids)
        seen_ids.add(entry_id)
        result[entry_id] = page_num

    logger.info("  %s: %d articles with page data", vol_id, sum(1 for v in result.values() if v is not None))
    return result


# ---------------------------------------------------------------------------
# IA _djvu.txt page extraction
# ---------------------------------------------------------------------------

_BODY_MARKER_RE = re.compile(r"ENCYCLOPEDIA\s+OF\s+RELI\w+\s+KNOWLEDGE", re.IGNORECASE)
_MULTI_SPACE_RE = re.compile(r"  +")


def _normalize_line(line: str) -> str:
    return _MULTI_SPACE_RE.sub(" ", line).rstrip()


def _is_running_header(norm: str) -> bool:
    if ":" in norm:
        return False
    if norm.upper().startswith("THE "):
        return True
    alpha_only = re.sub(r"[^A-Z ]", "", norm.upper())
    alpha_only = re.sub(r"\s+", " ", alpha_only).strip()
    schaff_frag = bool(re.search(r"SCHAFF|CHAFF", alpha_only))
    herz_frag = "HERZ" in alpha_only
    if schaff_frag and herz_frag:
        return True
    if re.match(r"^TH[A-Z] ", alpha_only) and (schaff_frag or herz_frag):
        return True
    has_encycl = bool(re.search(r"ENCY|NCYCL", alpha_only))
    has_relig = "RELIG" in alpha_only
    if has_encycl and (has_relig or len(alpha_only) < 30):
        return True
    if has_relig and "KNOWLEDGE" in alpha_only:
        return True
    return False


def _is_page_marker(norm: str) -> bool:
    stripped = norm.strip()
    if not stripped:
        return False
    if re.match(r"^\d+\s*$", stripped):
        return True
    if re.match(r"^[IVXLCDM]+[\s.—–-]+\d", stripped.upper()):
        return True
    if len(stripped) <= 3 and not any(c.isalpha() for c in stripped):
        return True
    return False


def _is_article_heading(norm: str) -> bool:
    if not re.match(r"^[A-Z]{2}", norm):
        return False
    if _is_running_header(norm):
        return False
    if re.match(r"^[IVXLCDM]+\.?\s", norm):
        return False
    if ":" in norm:
        return True
    stripped = norm.strip()
    if stripped == stripped.upper():
        alpha_count = sum(1 for c in stripped if c.isalpha())
        if alpha_count >= 4:
            return True
    return False


def _extract_term(norm: str) -> str:
    """Extract the article term from a heading line."""
    if norm.endswith(":"):
        raw = norm[:-1].strip()
    else:
        m = re.search(r":\s+", norm)
        if m:
            raw = norm[:m.start()].strip()
        else:
            raw = norm.strip().rstrip(".")
    # Strip pronunciation guides (lowercase segments)
    normalized = re.sub(r"  +", " ", raw).strip()
    parts = [p.strip() for p in normalized.split(",")]
    upper_parts = []
    for part in parts:
        if not part:
            continue
        alpha_chars = [c for c in part if c.isalpha()]
        if not alpha_chars:
            continue
        if sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars) >= 0.70:
            upper_parts.append(part)
    return ", ".join(upper_parts) if upper_parts else normalized


def extract_ia_pages(vol_num: int, filename: str) -> dict[str, int | None]:
    """Parse _djvu.txt; return {entry_id: page_number_or_None} for all articles.

    Scans from the body start marker. Tracks current_page from standalone
    digit lines (page markers). The page recorded for an article is the last
    page marker seen before that article's heading line.
    """
    txt_path = IA_RAW_DIR / filename
    lines = txt_path.read_text(encoding="utf-8").splitlines()

    body_start: int | None = None
    for i, line in enumerate(lines):
        norm = _normalize_line(line).strip()
        if _BODY_MARKER_RE.search(norm) and len(norm) < 50:
            for j in range(i + 1, len(lines)):
                if _normalize_line(lines[j]).strip():
                    body_start = j
                    break
            break

    if body_start is None:
        for i, line in enumerate(lines):
            if _is_article_heading(_normalize_line(line)):
                body_start = i
                break

    if body_start is None:
        logger.error("  Vol %d: cannot find body start", vol_num)
        return {}

    logger.info("  Vol %d: body starts at line %d", vol_num, body_start + 1)

    current_page: int | None = None
    article_pages: list[tuple[str, int | None]] = []

    for line in lines[body_start:]:
        norm = _normalize_line(line)
        stripped = norm.strip()
        if not stripped:
            continue
        if _is_running_header(norm):
            continue
        if _is_page_marker(norm):
            m = re.match(r"^(\d+)\s*$", stripped)
            if m:
                try:
                    val = int(m.group(1))
                    # Years (1800+) appear as standalone OCR lines in bibliography sections.
                    # No volume has more than ~600 pages, so cap at 700.
                    if val <= 700:
                        current_page = val
                except ValueError:
                    pass
            continue
        if _is_article_heading(norm):
            term = _extract_term(norm)
            article_pages.append((term, current_page))

    seen_ids: set[str] = set()
    result: dict[str, int | None] = {}
    for term_text, page_num in article_pages:
        base_id = f"schaff-herzog.{_slugify(term_text)}"
        entry_id = _make_unique_id(base_id, seen_ids)
        seen_ids.add(entry_id)
        result[entry_id] = page_num

    logger.info(
        "  Vol %d: %d articles, %d with page numbers",
        vol_num,
        len(result),
        sum(1 for v in result.values() if v is not None),
    )
    return result


# ---------------------------------------------------------------------------
# Record patching
# ---------------------------------------------------------------------------


def patch_record(
    path: Path,
    page_map: dict[str, int | None],
    anchor: str,
    dry_run: bool,
) -> dict[str, int]:
    """Patch source_pages (and optionally pd_anchor/attested_by) in an original record."""
    record = json.loads(path.read_text(encoding="utf-8"))

    matched = 0
    unmatched = 0

    if anchor != CCEL_ANCHOR:
        record["meta"]["pd_anchor"] = anchor

    for block in record["blocks"]:
        block_id = block.get("block_id", "")
        page_num = page_map.get(block_id)
        if page_num is not None:
            matched += 1
        else:
            unmatched += 1
        block["source_pages"] = [{"rendering_id": anchor, "page_number": page_num}]
        if anchor != CCEL_ANCHOR:
            block["attested_by"] = [anchor]

    if dry_run:
        logger.info("  [dry-run] %s: matched=%d unmatched=%d", path.name, matched, unmatched)
    else:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        tmp.replace(path)
        logger.info("  %s: matched=%d unmatched=%d", path.name, matched, unmatched)

    return {"matched": matched, "unmatched": unmatched}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report without writing files.")
    args = parser.parse_args(argv)

    total_matched = total_unmatched = 0

    for vol_num, vol_id in sorted(CCEL_VOLUMES.items()):
        logger.info("--- CCEL vol %d (%s) ---", vol_num, vol_id)
        page_map = extract_ccel_pages(vol_id)
        rec_path = ORIGINAL_DIR / f"vol_{vol_num:02d}.json"
        stats = patch_record(rec_path, page_map, CCEL_ANCHOR, args.dry_run)
        total_matched += stats["matched"]
        total_unmatched += stats["unmatched"]

    for vol_num, filename in sorted(IA_VOLUMES.items()):
        logger.info("--- IA vol %d ---", vol_num)
        page_map = extract_ia_pages(vol_num, filename)
        rec_path = ORIGINAL_DIR / f"vol_{vol_num:02d}.json"
        stats = patch_record(rec_path, page_map, IA_ANCHOR, args.dry_run)
        total_matched += stats["matched"]
        total_unmatched += stats["unmatched"]

    print("=== SUMMARY ===")
    print(f"  Blocks with page numbers matched: {total_matched}")
    print(f"  Blocks with page_number=null (no match): {total_unmatched}")
    if args.dry_run:
        print("  [dry-run] No files written.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
