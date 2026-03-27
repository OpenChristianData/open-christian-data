"""creeds_json_confession.py
Parse a Creeds.json confession document and map to the doctrinal_document schema.

Generic -- handles Westminster Confession of Faith, Belgic Confession, London Baptist
1689, Savoy Declaration, Scots Confession, and other Creeds.json confessions. Add an
entry to DOCUMENT_CONFIGS for any new document to set tradition and document_kind.

Usage:
    py -3 build/parsers/creeds_json_confession.py --source raw/Creeds.json/creeds/westminster_confession_of_faith.json
    py -3 build/parsers/creeds_json_confession.py --source raw/Creeds.json/creeds/belgic_confession_of_faith.json --tradition reformed
    py -3 build/parsers/creeds_json_confession.py --source raw/Creeds.json/creeds/london_baptist_1689.json --output data/doctrinal-documents/london-baptist-confession-1689.json
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "doctrinal-documents"
LOG_FILE = Path(__file__).resolve().parent / "creeds_json_confession.log"

SCRIPT_VERSION = "v1.0.0"

# Date raw Creeds.json data was downloaded to disk -- update if data is re-downloaded
SOURCE_DOWNLOAD_DATE = "2026-03-27"

# ---------------------------------------------------------------------------
# Per-document config
# Keyed by source filename stem (without .json).
# Add an entry here for any new Creeds.json confession. All fields can also
# be overridden via CLI args.
# ---------------------------------------------------------------------------

DOCUMENT_CONFIGS = {
    "westminster_confession_of_faith": {
        "document_id": "westminster-confession-of-faith",
        "document_kind": "confession",
        "tradition": ["reformed", "presbyterian"],
        "tradition_notes": (
            "Produced by the Westminster Assembly (1643-1652). "
            "The foundational confession of the Presbyterian tradition, "
            "widely adopted by Reformed and Presbyterian denominations worldwide."
        ),
    },
    "belgic_confession_of_faith": {
        "document_id": "belgic-confession-of-faith",
        "document_kind": "confession",
        "tradition": ["reformed"],
        "tradition_notes": (
            "Written by Guido de Bres in 1561. "
            "Standard for Reformed churches in the Netherlands and Belgium."
        ),
    },
    "london_baptist_1689": {
        "document_id": "london-baptist-confession-1689",
        "document_kind": "confession",
        "tradition": ["reformed", "baptist"],
        "tradition_notes": (
            "Second London Baptist Confession of Faith (1689). "
            "Closely follows the Westminster Confession with Baptist distinctives on baptism and church polity."
        ),
    },
    "scots_confession": {
        "document_id": "scots-confession",
        "document_kind": "confession",
        "tradition": ["reformed"],
        "tradition_notes": (
            "Composed by John Knox and others in 1560. "
            "First confession of the Church of Scotland."
        ),
    },
    "canons_of_dort": {
        "document_id": "canons-of-dort",
        "document_kind": "canon",
        "tradition": ["reformed"],
        "tradition_notes": (
            "Produced by the Synod of Dort (1618-1619). "
            "Defines the five points of Calvinism in response to Arminian objections (the Remonstrance)."
        ),
    },
    "savoy_declaration": {
        "document_id": "savoy-declaration",
        "document_kind": "confession",
        "tradition": ["reformed", "puritan", "nonconformist"],
        "tradition_notes": (
            "Congregationalist revision of the Westminster Confession, adopted at the Savoy Conference in 1658."
        ),
    },
    "abstract_of_principles": {
        "document_id": "abstract-of-principles",
        "document_kind": "confession",
        "tradition": ["reformed", "baptist"],
        "tradition_notes": (
            "Founding confession of The Southern Baptist Theological Seminary (1858). "
            "Reformed Baptist in character."
        ),
    },
    "french_confession_of_faith": {
        "document_id": "french-confession-of-faith",
        "document_kind": "confession",
        "tradition": ["reformed"],
        "tradition_notes": (
            "Confession de Foi, adopted by the first French Reformed Synod in Paris in 1559. "
            "Largely composed by John Calvin."
        ),
    },
    "first_helvetic_confession": {
        "document_id": "first-helvetic-confession",
        "document_kind": "confession",
        "tradition": ["reformed"],
        "tradition_notes": "Swiss Reformed confession adopted at Basel in 1536.",
    },
    "second_helvetic_confession": {
        "document_id": "second-helvetic-confession",
        "document_kind": "confession",
        "tradition": ["reformed"],
        "tradition_notes": (
            "Composed by Heinrich Bullinger in 1566. "
            "One of the most widely received Reformed confessions in Europe."
        ),
    },
    "chicago_statement_on_biblical_inerrancy": {
        "document_id": "chicago-statement-on-biblical-inerrancy",
        "document_kind": "declaration",
        "tradition": ["reformed", "ecumenical"],
        "tradition_notes": "Signed by nearly 300 evangelical scholars at Chicago in 1978.",
    },
    "apostles_creed": {
        "document_id": "apostles-creed",
        "document_kind": "creed",
        "tradition": ["ecumenical"],
        "tradition_notes": "Ancient baptismal creed of the Western church, final form c. 700 AD.",
    },
    "nicene_creed": {
        "document_id": "nicene-creed",
        "document_kind": "creed",
        "tradition": ["ecumenical"],
        "tradition_notes": (
            "Creed of the Council of Nicaea (325) and Council of Constantinople (381). "
            "Accepted by Roman Catholic, Eastern Orthodox, and most Protestant churches."
        ),
    },
    "athanasian_creed": {
        "document_id": "athanasian-creed",
        "document_kind": "creed",
        "tradition": ["ecumenical"],
        "tradition_notes": (
            "Latin creed attributed to Athanasius, probably 5th-6th century. "
            "Detailed exposition of Trinitarian and Christological doctrine."
        ),
    },
    "chalcedonian_definition": {
        "document_id": "chalcedonian-definition",
        "document_kind": "declaration",
        "tradition": ["ecumenical", "patristic"],
        "tradition_notes": "Definition of Christ's two natures adopted at the Council of Chalcedon (451).",
    },
    "council_of_orange": {
        "document_id": "council-of-orange",
        "document_kind": "canon",
        "tradition": ["patristic"],
        "tradition_notes": "Second Council of Orange (529). Addressed semi-Pelagianism; affirmed Augustinian grace.",
    },
    # --- Article-format docs ---
    "first_confession_of_basel": {
        "document_id": "first-confession-of-basel",
        "document_kind": "confession",
        "tradition": ["reformed"],
        "tradition_notes": "Early Swiss Reformed confession adopted at Basel in 1534.",
    },
    "consensus_tigurinus": {
        "document_id": "consensus-tigurinus",
        "document_kind": "declaration",
        "tradition": ["reformed", "continental-reformed"],
        "tradition_notes": (
            "Zurich Agreement (1549) between John Calvin and Heinrich Bullinger "
            "on the Lord's Supper."
        ),
    },
    "helvetic_consensus": {
        "document_id": "helvetic-consensus",
        "document_kind": "declaration",
        "tradition": ["reformed"],
        "tradition_notes": (
            "Formula Consensus Helvetica (1675). "
            "Swiss Reformed response to Amyraldianism (Saumur theology)."
        ),
    },
    "ten_theses_of_berne": {
        "document_id": "ten-theses-of-berne",
        "document_kind": "declaration",
        "tradition": ["reformed"],
        "tradition_notes": (
            "Theses from the Berne Disputation (1528), establishing Reformed worship in Berne."
        ),
    },
    "tetrapolitan_confession": {
        "document_id": "tetrapolitan-confession",
        "document_kind": "confession",
        "tradition": ["reformed", "continental-reformed"],
        "tradition_notes": (
            "Confession of the Four Cities (Strasbourg, Memmingen, Lindau, Constance), 1530. "
            "Early Reformed alternative to the Augsburg Confession."
        ),
    },
    "waldensian_confession": {
        "document_id": "waldensian-confession",
        "document_kind": "confession",
        "tradition": ["reformed"],
        "tradition_notes": (
            "Confession of the Waldensian church. "
            "Pre-Reformation movement later aligned with the Reformed tradition."
        ),
    },
    "zwinglis_67_articles": {
        "document_id": "zwinglis-67-articles",
        "document_kind": "declaration",
        "tradition": ["reformed", "continental-reformed"],
        "tradition_notes": (
            "Zwingli's 67 Articles (1523). "
            "Theses for the First Zurich Disputation; foundational for Swiss Reformed theology."
        ),
    },
    "zwinglis_fidei_ratio": {
        "document_id": "zwinglis-fidei-ratio",
        "document_kind": "declaration",
        "tradition": ["reformed", "continental-reformed"],
        "tradition_notes": (
            "Zwingli's Account of the Faith (Fidei Ratio, 1530). "
            "Presented to Emperor Charles V at the Diet of Augsburg."
        ),
    },
    # --- Single-content docs (Data is a dict, not a list) ---
    "christ_hymn_of_colossians": {
        "document_id": "christ-hymn-of-colossians",
        "document_kind": "creed",
        "tradition": ["ecumenical", "patristic"],
        "tradition_notes": (
            "Early Christian hymn from Colossians 1:15-20. "
            "One of the New Testament Christological hymns."
        ),
    },
    "christ_hymn_of_philippians": {
        "document_id": "christ-hymn-of-philippians",
        "document_kind": "creed",
        "tradition": ["ecumenical", "patristic"],
        "tradition_notes": (
            "Early Christian hymn from Philippians 2:6-11 (Carmen Christi). "
            "One of the New Testament Christological hymns."
        ),
    },
    "christian_shema": {
        "document_id": "christian-shema",
        "document_kind": "creed",
        "tradition": ["ecumenical"],
        "tradition_notes": (
            "1 Corinthians 8:6 -- the Pauline expansion of the Jewish Shema; "
            "an early Christological confession."
        ),
    },
    "confession_of_peter": {
        "document_id": "confession-of-peter",
        "document_kind": "creed",
        "tradition": ["ecumenical", "patristic"],
        "tradition_notes": "Peter's confession of Christ as found in Matthew 16:16.",
    },
    "gregorys_declaration_of_faith": {
        "document_id": "gregorys-declaration-of-faith",
        "document_kind": "creed",
        "tradition": ["patristic"],
        "tradition_notes": (
            "Declaration of faith by Gregory Thaumaturgus (c. 213-270). "
            "Early Trinitarian statement predating Nicaea."
        ),
    },
    "ignatius_creed": {
        "document_id": "ignatius-creed",
        "document_kind": "creed",
        "tradition": ["patristic"],
        "tradition_notes": (
            "Creedal statement from the letters of Ignatius of Antioch (c. 107 AD). "
            "One of the earliest post-apostolic confessions of Christ."
        ),
    },
    "irenaeus_rule_of_faith": {
        "document_id": "irenaeus-rule-of-faith",
        "document_kind": "creed",
        "tradition": ["patristic"],
        "tradition_notes": (
            "Rule of faith from Irenaeus of Lyon's Against Heresies (c. 180 AD). "
            "Early summary of the apostolic teaching."
        ),
    },
    "tertullians_rule_of_faith": {
        "document_id": "tertullians-rule-of-faith",
        "document_kind": "creed",
        "tradition": ["patristic"],
        "tradition_notes": (
            "Rule of faith from Tertullian's The Prescription of Heretics (c. 200 AD)."
        ),
    },
    "shema_yisrael": {
        "document_id": "shema-yisrael",
        "document_kind": "creed",
        "tradition": ["ecumenical"],
        "tradition_notes": (
            "Deuteronomy 6:4-5, the foundational declaration of monotheistic faith. "
            "Quoted by Jesus as the greatest commandment (Mark 12:29). "
            "Jewish in origin, foundational to Christian theology."
        ),
    },
}

# Valid tradition values (must match doctrinal_document.schema.json enum)
VALID_TRADITIONS = {
    "reformed", "lutheran", "anglican", "baptist", "methodist",
    "catholic", "orthodox", "ecumenical", "non-denominational",
    "puritan", "nonconformist", "patristic", "wesleyan",
    "presbyterian", "particular-baptist", "continental-reformed",
}

VALID_DOCUMENT_KINDS = {"confession", "canon", "creed", "declaration"}

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

_log_lines: list = []


def log(msg: str) -> None:
    """Print to console and buffer for log file."""
    print(msg)
    _log_lines.append(msg)


def flush_log() -> None:
    """Append buffered log lines to the log file."""
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"=== Run at {ts} ===\n")
        for line in _log_lines:
            f.write(line + "\n")
        f.write("\n")


# ---------------------------------------------------------------------------
# Proof text mapper
# ---------------------------------------------------------------------------


def map_proofs(raw_proofs: list) -> list:
    """Map Creeds.json Proofs to our proof schema.

    Input:  [{"Id": 1, "References": ["Ps.19.1-Ps.19.3", "John.15.12,John.15.17", ...]}, ...]
    Output: [{"id": 1, "references": [{"raw": "...", "osis": ["..."]}, ...]}, ...]

    Some Creeds.json documents join multiple OSIS refs with commas within one string
    (e.g. "John.15.12,John.15.17"). The raw field preserves the original string;
    osis splits on commas so each element is a single valid OSIS reference.
    Proofs are sorted by Id for consistency (source order is sometimes shuffled).
    """
    mapped = []
    for proof in sorted(raw_proofs, key=lambda p: p.get("Id", 0)):
        refs = []
        for ref_str in proof.get("References", []):
            osis_parts = [r.strip() for r in ref_str.split(",") if r.strip()]
            refs.append({"raw": ref_str, "osis": osis_parts})
        mapped.append({
            "id": proof["Id"],
            "references": refs,
        })
    return mapped


# ---------------------------------------------------------------------------
# Unit mappers
# ---------------------------------------------------------------------------


def map_section(section: dict) -> dict:
    """Map one Creeds.json section to a child unit dict."""
    unit: dict = {
        "unit_type": "section",
        "number": str(section["Section"]),
        "content": section["Content"],
    }
    if section.get("ContentWithProofs"):
        unit["content_with_proofs"] = section["ContentWithProofs"]
    if section.get("Proofs"):
        unit["proofs"] = map_proofs(section["Proofs"])
    return unit


def map_chapter(chapter: dict) -> dict:
    """Map one Creeds.json chapter to a top-level unit dict."""
    unit: dict = {
        "unit_type": "chapter",
        "number": str(chapter["Chapter"]),
    }
    if chapter.get("Title"):
        unit["title"] = chapter["Title"]
    children = [map_section(sec) for sec in chapter.get("Sections", [])]
    if children:
        unit["children"] = children
    return unit


def map_article(article: dict) -> dict:
    """Map one Creeds.json article to a unit dict (article-format documents).

    Article-format docs use {Article, Title, Content} instead of Chapter/Sections.
    Used by: Belgic Confession, Scots Confession, Abstract of Principles, etc.
    """
    unit: dict = {
        "unit_type": "article",
        "number": str(article["Article"]),
    }
    if article.get("Title"):
        unit["title"] = article["Title"]
    if article.get("Content"):
        unit["content"] = article["Content"]
    if article.get("ContentWithProofs"):
        unit["content_with_proofs"] = article["ContentWithProofs"]
    if article.get("Proofs"):
        unit["proofs"] = map_proofs(article["Proofs"])
    return unit


def map_single_content(data: dict) -> list:
    """Map a single-content document (Data is a dict) to a one-item units list.

    Used by: Apostles' Creed, Nicene Creed, patristic rules of faith,
    Christological hymns, etc.
    """
    unit: dict = {"unit_type": "text"}
    if data.get("Content"):
        unit["content"] = data["Content"]
    if data.get("ContentWithProofs"):
        unit["content_with_proofs"] = data["ContentWithProofs"]
    if data.get("Proofs"):
        unit["proofs"] = map_proofs(data["Proofs"])
    return [unit]


def detect_format(data) -> str:
    """Detect the Creeds.json data format for a document.

    Returns one of:
      'chapter_sections' -- Data is list of {Chapter, Sections[...]}
      'articles'         -- Data is list of {Article, Title, Content}
      'single_content'   -- Data is a dict {Content, ...}
      'unknown'          -- Cannot determine
    """
    if isinstance(data, dict):
        return "single_content"
    if not isinstance(data, list) or not data:
        return "unknown"
    first = data[0]
    if "Chapter" in first:
        return "chapter_sections"
    if "Article" in first:
        return "articles"
    return "unknown"


# ---------------------------------------------------------------------------
# Metadata builder
# ---------------------------------------------------------------------------


def _parse_year(year_str) -> int | None:
    """Parse a year string to int. Returns None on failure (e.g. '1618-1619', 'c. 451')."""
    if not year_str:
        return None
    try:
        return int(str(year_str).strip())
    except ValueError:
        log(f"WARNING: Could not parse year '{year_str}' as integer -- setting to None")
        return None


def build_meta(
    source_hash: str,
    doc_cfg: dict,
    metadata: dict,
    process_date: str,
) -> dict:
    """Build the resource-level meta envelope."""
    authors = metadata.get("Authors", [])
    return {
        "id": doc_cfg["document_id"],
        "title": metadata.get("Title", doc_cfg["document_id"]),
        "author": authors[0] if authors else None,
        "author_birth_year": None,
        "author_death_year": None,
        "contributors": authors[1:],
        "original_publication_year": _parse_year(metadata.get("Year")),
        "language": "en",
        "tradition": doc_cfg["tradition"],
        "tradition_notes": doc_cfg.get("tradition_notes"),
        "license": "cc0-1.0",
        "schema_type": "doctrinal_document",
        "schema_version": "2.1.0",
        "completeness": "full",
        "provenance": {
            "source_url": metadata.get("SourceUrl", ""),
            "source_format": "JSON",
            "source_edition": "Creeds.json (github.com/NonlinearFruit/Creeds.json)",
            "download_date": SOURCE_DOWNLOAD_DATE,
            "source_hash": f"sha256:{source_hash}",
            "processing_method": "automated",
            "processing_script_version": (
                f"build/parsers/creeds_json_confession.py@{SCRIPT_VERSION}"
            ),
            "processing_date": process_date,
            "notes": (
                "Proof texts from Creeds.json are already in OSIS format -- "
                "raw and osis fields are identical. "
                "Content used as canonical text; ContentWithProofs preserved as content_with_proofs."
            ),
        },
    }


# ---------------------------------------------------------------------------
# Main processor
# ---------------------------------------------------------------------------


def process_confession(
    source_file: Path,
    output_file: Path,
    doc_cfg: dict,
) -> bool:
    """Parse one Creeds.json confession file and write output. Returns True on success."""
    log(f"Source: {source_file}")
    log(f"Output: {output_file}")

    # Load source
    try:
        raw_text = source_file.read_text(encoding="utf-8")
        source_data = json.loads(raw_text)
    except (OSError, json.JSONDecodeError) as exc:
        log(f"ERROR: Failed to load source: {exc}")
        return False

    source_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

    metadata = source_data.get("Metadata", {})
    raw_data = source_data.get("Data", [])
    data_format = detect_format(raw_data)

    log(f"Title:  {metadata.get('Title', '(unknown)')}")
    log(f"Year:   {metadata.get('Year', '(unknown)')}")
    log(f"Format: {data_format}")
    if isinstance(raw_data, list):
        log(f"Items in source: {len(raw_data)}")

    # Map items to units based on detected format
    units = []
    errors = 0

    if data_format == "chapter_sections":
        for i, ch in enumerate(raw_data):
            try:
                units.append(map_chapter(ch))
            except Exception as exc:
                log(f"ERROR: Chapter {ch.get('Chapter', i)} failed: {exc}")
                errors += 1
        total_sections = sum(len(u.get("children", [])) for u in units)
        log(f"Mapped: {len(units)} chapters, {total_sections} sections, {errors} errors")
    elif data_format == "articles":
        for i, art in enumerate(raw_data):
            try:
                units.append(map_article(art))
            except Exception as exc:
                log(f"ERROR: Article {art.get('Article', i)} failed: {exc}")
                errors += 1
        log(f"Mapped: {len(units)} articles, {errors} errors")
    elif data_format == "single_content":
        units = map_single_content(raw_data)
        log(f"Mapped: single-content document ({len(units)} unit)")
    else:
        log(f"ERROR: Unknown data format -- cannot map units")
        return False

    process_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    output = {
        "meta": build_meta(source_hash, doc_cfg, metadata, process_date),
        "data": {
            "document_id": doc_cfg["document_id"],
            "document_kind": doc_cfg["document_kind"],
            "revision_history": [],
            "units": units,
        },
    }

    # Write output
    output_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(output_file, "w", encoding="utf-8", newline="\n") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except OSError as exc:
        log(f"ERROR: Failed to write output: {exc}")
        return False

    size_kb = output_file.stat().st_size / 1024
    log(f"Wrote {output_file} ({size_kb:.0f} KB)")

    return errors == 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse a Creeds.json confession to doctrinal_document schema"
    )
    parser.add_argument(
        "--source",
        required=True,
        metavar="PATH",
        help="Path to source Creeds.json confession JSON file (absolute or repo-relative)",
    )
    parser.add_argument(
        "--document-id",
        metavar="ID",
        help="Override document_id (default: from DOCUMENT_CONFIGS or derived from filename)",
    )
    parser.add_argument(
        "--document-kind",
        metavar="KIND",
        choices=sorted(VALID_DOCUMENT_KINDS),
        help="Override document_kind (default: from DOCUMENT_CONFIGS or 'confession')",
    )
    parser.add_argument(
        "--tradition",
        nargs="+",
        metavar="TRAD",
        help="Override tradition list (e.g. --tradition reformed presbyterian)",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Override output file path (absolute or repo-relative)",
    )
    args = parser.parse_args()

    start = datetime.now(timezone.utc)
    log(f"creeds_json_confession.py {SCRIPT_VERSION}")

    source_file = Path(args.source)
    if not source_file.is_absolute():
        source_file = REPO_ROOT / source_file

    if not source_file.exists():
        log(f"ERROR: Source file not found: {source_file}")
        flush_log()
        sys.exit(1)

    stem = source_file.stem

    # Load known config or fall back to defaults
    if stem in DOCUMENT_CONFIGS:
        doc_cfg = dict(DOCUMENT_CONFIGS[stem])
        log(f"Config: using DOCUMENT_CONFIGS entry for '{stem}'")
    else:
        doc_cfg = {
            "document_id": stem.replace("_", "-"),
            "document_kind": "confession",
            "tradition": [],
            "tradition_notes": None,
        }
        log(f"WARNING: No DOCUMENT_CONFIGS entry for '{stem}' -- using defaults. Consider adding one.")

    # Apply CLI overrides
    if args.document_id:
        doc_cfg["document_id"] = args.document_id
    if args.document_kind:
        doc_cfg["document_kind"] = args.document_kind
    if args.tradition:
        doc_cfg["tradition"] = args.tradition

    # Validate tradition values
    for t in doc_cfg["tradition"]:
        if t not in VALID_TRADITIONS:
            log(f"WARNING: Tradition value '{t}' not in VALID_TRADITIONS -- may fail schema validation")

    # Determine output path
    if args.output:
        output_file = Path(args.output)
        if not output_file.is_absolute():
            output_file = REPO_ROOT / output_file
    else:
        output_file = DATA_DIR / f"{doc_cfg['document_id']}.json"

    # Run
    try:
        success = process_confession(source_file, output_file, doc_cfg)
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        print("")
        if success:
            print(f"Done in {elapsed:.1f}s. Output: {output_file}")
            print(f"Validate: py -3 build/validate.py {output_file.relative_to(REPO_ROOT)}")
        else:
            print(f"Completed with errors in {elapsed:.1f}s. Check log: {LOG_FILE}")
    finally:
        flush_log()

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
