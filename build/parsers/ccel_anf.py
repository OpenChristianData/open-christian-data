"""Parser for Ante-Nicene Fathers structured_text works from CCEL ThML XML.

This first ANF pass extracts Irenaeus, Against Heresies from ANF1. The ANF1
volume also contains Apostolic Fathers and Justin Martyr material, but those
are deferred because they require per-work selection inside larger author
bundles and duplicate-version policy for Ignatius.

CCEL confirmed OK to parse (Quincy, 2026-04-01). robots.txt crawl-delay 10 for
all agents was checked before download in this acquisition session.

Usage:
    py -3 build/parsers/ccel_anf.py --volume anf01 --download --dry-run
    py -3 build/parsers/ccel_anf.py --work irenaeus-against-heresies --parse
    py -3 build/parsers/ccel_anf.py --all --parse
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request  # standards: download only
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.contributors import normalize_contributors  # noqa: E402
from build.lib.schema_enums import get_enum  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402

RAW_DIR = REPO_ROOT / "raw" / "ccel" / "anf"
OUTPUT_DIR = REPO_ROOT / "data" / "structured-text"
SOURCES_DIR = REPO_ROOT / "sources" / "structured-text"
LOG_FILE = Path(__file__).resolve().parent / "ccel_anf.log"

SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.0"
CRAWL_DELAY = 10
UA = "OpenChristianData/1.0 (research; open-source data project; contact: openchristiandata@gmail.com)"

STRUCTURED_TEXT_TRADITIONS = get_enum("structured_text", "meta", "tradition")
STRUCTURED_TEXT_WORK_KINDS = get_enum("structured_text", "data", "work_kind")
STRUCTURED_TEXT_ERAS = get_enum("structured_text", "meta", "era")
STRUCTURED_TEXT_AUDIENCES = get_enum("structured_text", "meta", "audience")
STRUCTURED_TEXT_COMPLETENESS = get_enum("structured_text", "meta", "completeness")

VOLUME_CONFIG = {
    "anf01": {
        "url": "https://www.ccel.org/ccel/schaff/anf01.xml",
        "raw_file": RAW_DIR / "anf01.xml",
        "source_edition": (
            "Ante-Nicene Fathers, Vol. 1. Alexander Roberts and James Donaldson (eds.); "
            "A. Cleveland Coxe (American ed.). Buffalo: Christian Literature Publishing Co., 1885."
        ),
        "works": [
            {
                "slug": "irenaeus-against-heresies",
                "div1_id": "ix",
                "book_div_ids": ["ix.ii", "ix.iii", "ix.iv", "ix.vi", "ix.vii"],
                "title": "Against Heresies",
                "author": "Irenaeus of Lyons",
                "author_id": "irenaeus",
                "author_birth_year": 130,
                "author_death_year": 202,
                "original_publication_year": 180,
                "work_kind": "theological-work",
                "contributors": [
                    "Alexander Roberts and James Donaldson (editors and translators, 1885)",
                    "A. Cleveland Coxe (American editor)",
                ],
                "tradition": ["patristic", "ecumenical"],
                "tradition_notes": "Second-century anti-Gnostic theological work preserved in the ANF public-domain translation.",
                "era": "patristic",
                "audience": "scholarly",
                "language": "en",
                "original_language": "grc",
                "completeness": "full",
            }
        ],
    },
    "anf02": {
        "url": "https://www.ccel.org/ccel/schaff/anf02.xml",
        "raw_file": RAW_DIR / "anf02.xml",
        "source_edition": (
            "Ante-Nicene Fathers, Vol. 2. Alexander Roberts and James Donaldson (eds.); "
            "A. Cleveland Coxe (American ed.). Buffalo: Christian Literature Publishing Co., 1885."
        ),
        "works": [],
    },
}

THML_ENTITY_MAP = {
    "&mdash;": "\u2014",
    "&ndash;": "\u2013",
    "&lsquo;": "\u2018",
    "&rsquo;": "\u2019",
    "&ldquo;": "\u201c",
    "&rdquo;": "\u201d",
    "&nbsp;": "\u00a0",
    "&hellip;": "\u2026",
    "&emdash;": "\u2014",
    "&copy;": "\u00a9",
    "&reg;": "\u00ae",
    "&trade;": "\u2122",
    "&deg;": "\u00b0",
    "&para;": "\u00b6",
    "&sect;": "\u00a7",
    "&dagger;": "\u2020",
    "&Dagger;": "\u2021",
    "&bull;": "\u2022",
    "&prime;": "\u2032",
    "&Prime;": "\u2033",
    "&aelig;": "\u00e6",
    "&AElig;": "\u00c6",
    "&agrave;": "\u00e0",
    "&aacute;": "\u00e1",
    "&egrave;": "\u00e8",
    "&eacute;": "\u00e9",
    "&iacute;": "\u00ed",
    "&oacute;": "\u00f3",
    "&uacute;": "\u00fa",
    "&ccedil;": "\u00e7",
    "&ntilde;": "\u00f1",
    "&Alpha;": "\u0391",
    "&Beta;": "\u0392",
    "&Gamma;": "\u0393",
    "&Delta;": "\u0394",
    "&Omega;": "\u03a9",
    "&alpha;": "\u03b1",
    "&beta;": "\u03b2",
    "&gamma;": "\u03b3",
    "&delta;": "\u03b4",
    "&omega;": "\u03c9",
}
XML_SAFE_ENTITIES = {"&amp;", "&lt;", "&gt;", "&quot;", "&apos;"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "title"}
SKIP_TAGS = {"note", "pb", "insertIndex", "style", "selector", "scripContext", "index"}
DIV_TAG_RE = re.compile(r"^div\d?$")
CHAPTER_RE = re.compile(r"^(Chapter\s+[IVXLCDM]+)\.?[\u2014\-:]?\s*(.*)$", re.IGNORECASE)
BOOK_RE = re.compile(r"^Against Heresies:\s*(Book\s+[IVXLCDM]+)$", re.IGNORECASE)


def _validate_work_configs() -> None:
    for volume_id, volume_cfg in VOLUME_CONFIG.items():
        for work in volume_cfg["works"]:
            slug = work["slug"]
            for tradition in work["tradition"]:
                assert tradition in STRUCTURED_TEXT_TRADITIONS, f"{slug}: invalid tradition {tradition!r}"
            assert work["work_kind"] in STRUCTURED_TEXT_WORK_KINDS, f"{slug}: invalid work_kind"
            assert work["era"] in STRUCTURED_TEXT_ERAS, f"{slug}: invalid era"
            assert work["audience"] in STRUCTURED_TEXT_AUDIENCES, f"{slug}: invalid audience"
            assert work["completeness"] in STRUCTURED_TEXT_COMPLETENESS, f"{slug}: invalid completeness"


def _replace_entity(match: re.Match[str]) -> str:
    entity = match.group(0)
    if entity in XML_SAFE_ENTITIES:
        return entity
    return THML_ENTITY_MAP.get(entity, "")


def preprocess_thml(raw_bytes: bytes) -> str:
    try:
        text = raw_bytes.decode("utf-8")
        if "\ufffd" in text:
            raise UnicodeDecodeError("utf-8", raw_bytes, 0, 1, "replacement chars found")
    except UnicodeDecodeError:
        text = raw_bytes.decode("cp1252", errors="replace")
    text = re.sub(r"<!DOCTYPE\s[^>]*(?:\[[^\]]*\])?>", "", text, flags=re.DOTALL)
    text = re.sub(r"&[A-Za-z][A-Za-z0-9]*;", _replace_entity, text)
    return text


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def get_all_text(elem: ET.Element) -> str:
    parts: list[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        if child.tag not in SKIP_TAGS:
            parts.append(get_all_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def find_child(parent: ET.Element, tag: str) -> ET.Element | None:
    for child in parent:
        if child.tag == tag:
            return child
    return None


def find_body(root: ET.Element) -> ET.Element:
    body = find_child(root, "ThML.body")
    if body is None:
        raise RuntimeError("No <ThML.body> element found. Unexpected CCEL ThML structure.")
    return body


def heading_text(elem: ET.Element) -> str:
    for child in elem:
        if child.tag in HEADING_TAGS:
            text = clean_text(get_all_text(child))
            if text:
                return text
    return clean_text(elem.get("title", ""))


def split_book_label(title: str) -> tuple[str | None, str | None]:
    match = BOOK_RE.match(title)
    if match:
        return match.group(1), "Against Heresies"
    return None, title or None


def split_chapter_label(title: str) -> tuple[str | None, str | None]:
    if title.lower() == "preface.":
        return None, "Preface"
    match = CHAPTER_RE.match(title)
    if match:
        chapter_title = match.group(2).strip().rstrip(".")
        return match.group(1), chapter_title or None
    return None, title.rstrip(".") or None


def collect_content_blocks(elem: ET.Element) -> list[str]:
    blocks: list[str] = []
    for child in elem:
        if child.tag in HEADING_TAGS or child.tag in SKIP_TAGS or DIV_TAG_RE.match(child.tag):
            continue
        if child.tag in {"p", "argument", "q"}:
            text = clean_text(get_all_text(child))
            if text:
                blocks.append(text)
        elif child.tag in {"ul", "ol"}:
            items = [clean_text(get_all_text(li)) for li in child.findall("li")]
            items = [item for item in items if item]
            if items:
                blocks.append("; ".join(items))
    return blocks


def get_scriptrefs(elem: ET.Element) -> list[dict[str, list[str] | str]]:
    refs = []
    for ref in elem.iter("scripRef"):
        raw_text = clean_text(get_all_text(ref))
        osis = []
        for part in ref.get("osisRef", "").split():
            cleaned = re.sub(r"^Bible(?:\.[a-z]+)?:", "", part).strip()
            if cleaned:
                osis.append(cleaned)
        if raw_text or osis:
            refs.append({"raw": raw_text, "osis": osis})
    return refs


def count_words(blocks: list[str]) -> int:
    return sum(len(re.findall(r"\w+", block)) for block in blocks)


def parse_chapter(elem: ET.Element) -> dict:
    title = heading_text(elem)
    label, clean_title = split_chapter_label(title)
    blocks = collect_content_blocks(elem)
    return {
        "section_type": "preface" if (clean_title or "").lower() == "preface" else "chapter",
        "label": label,
        "title": clean_title,
        "content_blocks": blocks,
        "scripture_references": get_scriptrefs(elem),
        "word_count": count_words(blocks),
        "children": [],
    }


def parse_book(elem: ET.Element) -> dict:
    label, title = split_book_label(clean_text(elem.get("title", "")))
    chapters = []
    for child in elem:
        if DIV_TAG_RE.match(child.tag):
            chapter = parse_chapter(child)
            if chapter["content_blocks"]:
                chapters.append(chapter)
    return {
        "section_type": "book",
        "label": label,
        "title": title,
        "content_blocks": [],
        "scripture_references": [],
        "word_count": 0,
        "children": chapters,
    }


def parse_volume_work(volume_id: str, work_cfg: dict, raw_bytes: bytes) -> dict:
    source_hash = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
    root = ET.fromstring(preprocess_thml(raw_bytes))
    body = find_body(root)
    div1 = None
    for child in body:
        if child.tag == "div1" and child.get("id") == work_cfg["div1_id"]:
            div1 = child
            break
    if div1 is None:
        raise RuntimeError(f"div1 id={work_cfg['div1_id']!r} not found in {volume_id}")

    sections = []
    wanted = set(work_cfg["book_div_ids"])
    for child in div1:
        if child.tag == "div2" and child.get("id") in wanted:
            sections.append(parse_book(child))
    missing = wanted - {section_id for section_id in [s.get("_source_id") for s in sections] if section_id}
    if len(sections) != len(wanted):
        found = [child.get("id") for child in div1 if child.tag == "div2" and child.get("id") in wanted]
        raise RuntimeError(f"Expected {len(wanted)} book divs for {work_cfg['slug']}, found {found}")
    return {"work_id": work_cfg["slug"], "sections": sections, "_source_hash": source_hash}


def _download_date(raw_file: Path) -> str:
    return datetime.fromtimestamp(raw_file.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d")


def build_meta(volume_id: str, work_cfg: dict, source_hash: str) -> dict:
    volume_cfg = VOLUME_CONFIG[volume_id]
    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {
        "id": work_cfg["slug"],
        "title": work_cfg["title"],
        "author": work_cfg["author"],
        "author_id": work_cfg["author_id"],
        "author_birth_year": work_cfg["author_birth_year"],
        "author_death_year": work_cfg["author_death_year"],
        "contributors": normalize_contributors(work_cfg["contributors"]),
        "original_publication_year": work_cfg["original_publication_year"],
        "language": work_cfg["language"],
        "original_language": work_cfg["original_language"],
        "tradition": work_cfg["tradition"],
        "tradition_notes": work_cfg["tradition_notes"],
        "era": work_cfg["era"],
        "audience": work_cfg["audience"],
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": work_cfg["completeness"],
        "provenance": {
            "source_url": volume_cfg["url"],
            "source_format": "ThML XML",
            "source_edition": volume_cfg["source_edition"],
            "download_date": _download_date(volume_cfg["raw_file"]),
            "source_hash": source_hash,
            "processing_method": "automated",
            "processing_script_version": f"build/parsers/ccel_anf.py@{SCRIPT_VERSION}",
            "processing_date": processing_date,
            "notes": (
                "ThML HTML entities replaced with Unicode equivalents. DOCTYPE stripped before parsing. "
                "Footnotes (<note>), page breaks (<pb>), and index markers excluded from content. "
                "Only the five Against Heresies book divs were extracted from ANF1; ANF front matter, "
                "elucidations, and fragments were excluded. robots.txt crawl-delay 10s honoured."
            ),
            "source_type": "ccel_thml",
            "source_file": "raw/ccel/anf/anf01.xml",
            "translator": "Alexander Roberts and James Donaldson, 1885",
        },
    }


def build_output(volume_id: str, work_cfg: dict, parse_result: dict) -> dict:
    return {
        "meta": build_meta(volume_id, work_cfg, parse_result["_source_hash"]),
        "data": {
            "work_id": parse_result["work_id"],
            "work_kind": work_cfg["work_kind"],
            "sections": parse_result["sections"],
        },
    }


def write_source_config(volume_id: str, work_cfg: dict, source_hash: str) -> None:
    volume_cfg = VOLUME_CONFIG[volume_id]
    cfg_dir = SOURCES_DIR / work_cfg["slug"]
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = {
        "resource_id": work_cfg["slug"],
        "title": work_cfg["title"],
        "author": work_cfg["author"],
        "author_id": work_cfg["author_id"],
        "author_birth_year": work_cfg["author_birth_year"],
        "author_death_year": work_cfg["author_death_year"],
        "contributors": work_cfg["contributors"],
        "original_publication_year": work_cfg["original_publication_year"],
        "language": work_cfg["language"],
        "original_language": work_cfg["original_language"],
        "tradition": work_cfg["tradition"],
        "tradition_notes": work_cfg["tradition_notes"],
        "era": work_cfg["era"],
        "audience": work_cfg["audience"],
        "license": "public-domain",
        "schema_type": "structured_text",
        "work_kind": work_cfg["work_kind"],
        "source_url": volume_cfg["url"],
        "source_format": "ThML XML",
        "source_edition": volume_cfg["source_edition"],
        "source_hash": source_hash,
        "download_date": _download_date(volume_cfg["raw_file"]),
        "output_file": f"data/structured-text/{work_cfg['slug']}.json",
        "notes": "CCEL confirmed OK to parse. Crawl-delay 10s per robots.txt. Extracted from ANF1 div1 ix, book divs ix.ii, ix.iii, ix.iv, ix.vi, and ix.vii.",
    }
    with (cfg_dir / "config.json").open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def download_volume(volume_id: str, force: bool = False) -> None:
    cfg = VOLUME_CONFIG[volume_id]
    dest = cfg["raw_file"]
    if dest.exists() and not force:
        print(f"  Cached: {dest}")
        return
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(cfg["url"], headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as response:
        data = response.read()
    dest.write_bytes(data)
    print(f"  Downloaded {len(data)} bytes -> {dest}")


def _count_nodes(sections: list[dict]) -> int:
    return sum(1 + _count_nodes(section.get("children", [])) for section in sections)


def _sum_words(sections: list[dict]) -> int:
    return sum(section.get("word_count", 0) + _sum_words(section.get("children", [])) for section in sections)


def _leaf_problems(sections: list[dict]) -> list[str]:
    problems = []
    for section in sections:
        name = section.get("label") or section.get("title") or "(untitled)"
        if not section.get("title"):
            problems.append(f"missing title: {name}")
        children = section.get("children", [])
        blocks = section.get("content_blocks", [])
        if not children and not blocks:
            problems.append(f"empty leaf: {name}")
        problems.extend(_leaf_problems(children))
    return problems


def report_quality(work_cfg: dict, sections: list[dict]) -> None:
    print(
        f"  {work_cfg['slug']}: {len(sections)} top sections, "
        f"{_count_nodes(sections)} total nodes, {_sum_words(sections)} words"
    )
    print(f"  Top sections: {[s.get('label') or s.get('title') for s in sections]}")
    problems = _leaf_problems(sections)
    if problems:
        raise RuntimeError("Quality check failed: " + "; ".join(problems[:10]))


def iter_selected(args: argparse.Namespace) -> list[tuple[str, dict]]:
    selected = []
    volume_ids = [args.volume] if args.volume else list(VOLUME_CONFIG.keys())
    for volume_id in volume_ids:
        for work in VOLUME_CONFIG[volume_id]["works"]:
            if args.work and work["slug"] != args.work:
                continue
            selected.append((volume_id, work))
    if args.work and not selected:
        raise RuntimeError(f"Unknown work slug: {args.work}")
    return selected


def main() -> None:
    _validate_work_configs()
    parser = argparse.ArgumentParser(description="Parse ANF structured_text works from CCEL ThML XML")
    parser.add_argument("--volume", choices=list(VOLUME_CONFIG.keys()))
    parser.add_argument("--work")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--parse", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.all:
        args.download = args.download
        args.parse = True
    if args.dry_run:
        args.parse = True
    if not args.download and not args.parse:
        parser.print_help()
        return

    log_lines = []
    def log(message: str) -> None:
        safe = message.encode("ascii", errors="replace").decode("ascii")
        print(safe)
        log_lines.append(message)

    errors = 0
    works_done = 0
    files_written = 0
    start = time.time()
    try:
        volume_ids = [args.volume] if args.volume else list(VOLUME_CONFIG.keys())
        if args.download:
            log("=== Download phase ===")
            for i, volume_id in enumerate(volume_ids):
                if i:
                    log(f"  Waiting {CRAWL_DELAY}s (robots.txt crawl-delay) ...")
                    time.sleep(CRAWL_DELAY)
                download_volume(volume_id, force=args.force)
            log("")

        if args.parse:
            log("=== Parse phase ===")
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            for volume_id, work_cfg in iter_selected(args):
                raw_file = VOLUME_CONFIG[volume_id]["raw_file"]
                if not raw_file.exists():
                    raise RuntimeError(f"Missing raw file: {raw_file}. Run --download first.")
                raw_bytes = raw_file.read_bytes()
                log(f"  Parsing {work_cfg['slug']} from {raw_file.name} ...")
                result = parse_volume_work(volume_id, work_cfg, raw_bytes)
                report_quality(work_cfg, result["sections"])
                works_done += 1
                if args.dry_run:
                    log("  DRY RUN: skipping output writes")
                    continue
                output = build_output(volume_id, work_cfg, result)
                out_path = OUTPUT_DIR / f"{work_cfg['slug']}.json"
                with out_path.open("w", encoding="utf-8", newline="\n") as fh:
                    json.dump(output, fh, ensure_ascii=False, indent=2)
                    fh.write("\n")
                write_source_config(volume_id, work_cfg, result["_source_hash"])
                files_written += 1
                log(f"  Wrote {out_path}")
    except Exception as exc:
        errors += 1
        log(f"ERROR: {exc}")
    finally:
        summary = f"Done in {time.time() - start:.1f}s. Works parsed: {works_done}. Files written: {files_written}. Errors: {errors}."
        log(summary)
        with LOG_FILE.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(log_lines) + "\n")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
