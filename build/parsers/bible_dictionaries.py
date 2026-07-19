"""bible_dictionaries.py
Parse JWBickel/BibleDictionaries JSONL files into OCD schema.

Reads raw JSONL from raw/bible_dictionaries/.
Outputs normalized JSON to data/reference/ -- one file per dictionary.

Schema types:
  reference_entry -- Easton's, Smith's, Hitchcock's
  topical_reference -- Torrey's New Topical Textbook

Usage:
    py -3 build/parsers/bible_dictionaries.py --dictionary eastons
    py -3 build/parsers/bible_dictionaries.py --dictionary smiths
    py -3 build/parsers/bible_dictionaries.py --dictionary hitchcocks
    py -3 build/parsers/bible_dictionaries.py --dictionary torreys
    py -3 build/parsers/bible_dictionaries.py --all

Source: https://huggingface.co/datasets/JWBickel/BibleDictionaries
"""

import argparse
import hashlib
import json
import logging
import re
import time
import unicodedata
from datetime import datetime, timezone
import sys
from pathlib import Path

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib._generated_enums import REFERENCE_ENTRY__META__TRADITION
from ocd_kernel.lib.bible_ref_normalizer import parse_thml_refs

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

from build.lib import writer_manifest  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402
RAW_DIR = REPO_ROOT / "raw" / "bible_dictionaries"
OUTPUT_DIR = REPO_ROOT / "data" / "reference"
LOG_PATH = Path(__file__).resolve().parent / "bible_dictionaries.log"

SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.1.0"

# ---------------------------------------------------------------------------
# Logging -- persists to file alongside script (Rule 3)
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    """Configure file + console logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(),
        ],
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )

# ---------------------------------------------------------------------------
# Dictionary configs
# ---------------------------------------------------------------------------

# All underlying texts are public domain by age (19th century works).
# Structured JSONL format is from JWBickel/BibleDictionaries on HuggingFace
# (license confirmation pending -- EMAIL-4 sent). Source texts are PD.

DICTIONARIES = {
    "eastons": {
        "resource_id": "eastons-bible-dictionary",
        "dictionary_id": "eastons-bible-dictionary",
        "title": "Easton's Bible Dictionary",
        "author": "Matthew George Easton",
        "author_birth_year": 1823,
        "author_death_year": 1894,
        "original_publication_year": 1893,
        "language": "en",
        "tradition": ["evangelical", "reformed"],
        "tradition_notes": (
            "Easton was a Scottish Free Church minister. "
            "The dictionary reflects broad evangelical Protestant scholarship of the late 19th century."
        ),
        "license": "public-domain",
        "schema_type": "reference_entry",
        "source_file": "eastons.jsonl",
        "expected_count": 3963,
    },
    "smiths": {
        "resource_id": "smiths-bible-dictionary",
        "dictionary_id": "smiths-bible-dictionary",
        "title": "Smith's Bible Dictionary",
        "author": "William Smith",
        "author_birth_year": 1813,
        "author_death_year": 1893,
        "original_publication_year": 1863,
        "language": "en",
        "tradition": ["evangelical"],
        "tradition_notes": (
            "Smith was an English Anglican classical scholar. "
            "The dictionary reflects broad evangelical Protestant scholarship of the mid-19th century."
        ),
        "license": "public-domain",
        "schema_type": "reference_entry",
        "source_file": "smiths.jsonl",
        "expected_count": 4560,
    },
    "hitchcocks": {
        "resource_id": "hitchcocks-bible-names-dictionary",
        "dictionary_id": "hitchcocks-bible-names-dictionary",
        "title": "Hitchcock's Bible Names Dictionary",
        "author": "Roswell Dwight Hitchcock",
        "author_birth_year": 1817,
        "author_death_year": 1887,
        "original_publication_year": 1874,
        "language": "en",
        "tradition": ["evangelical"],
        "tradition_notes": (
            "Hitchcock was an American Presbyterian minister. "
            "This dictionary focuses on Hebrew and Greek name etymologies."
        ),
        "license": "public-domain",
        "schema_type": "reference_entry",
        "source_file": "hitchcocks.jsonl",
        "expected_count": 2622,
    },
    "torreys": {
        "resource_id": "torreys-topical-textbook",
        "index_id": "torreys-topical-textbook",
        "title": "Torrey's New Topical Textbook",
        "author": "Reuben Archer Torrey",
        "author_birth_year": 1856,
        "author_death_year": 1928,
        "original_publication_year": 1897,
        "language": "en",
        "tradition": ["evangelical"],
        "tradition_notes": (
            "Torrey was an American Congregationalist evangelist and Bible teacher. "
            "The textbook is organized topically with verse references supporting each subtopic."
        ),
        "license": "public-domain",
        "schema_type": "topical_reference",
        "source_file": "torreys.jsonl",
        "expected_count": 623,
    },
}


def _validate_work_configs() -> None:
    for key, cfg in DICTIONARIES.items():
        for t in cfg.get("tradition", []):
            assert t in REFERENCE_ENTRY__META__TRADITION, f"{key}: invalid tradition {t!r}"


_validate_work_configs()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def slugify(text: str) -> str:
    """Convert text to a URL-safe lowercase slug."""
    # Normalize unicode to ASCII where possible
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    # Lowercase and strip non-alphanumeric (keep spaces and hyphens)
    text = re.sub(r"[^\w\s-]", "", text.lower())
    # Collapse whitespace to hyphens
    text = re.sub(r"[\s]+", "-", text.strip())
    return text


def make_unique_id(base: str, seen: set) -> str:
    """Return base if not in seen, else base-2, base-3, etc.
    Uses set as source of truth per CODING_DEFAULTS Rule 45.
    """
    candidate = base
    counter = 2
    while candidate in seen:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def count_words(blocks: list) -> int:
    """Count total words across all definition blocks."""
    return sum(len(b.split()) for b in blocks)


def sha256_file(path: Path) -> str:
    """Return sha256 hex digest of a file."""
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load_jsonl(path: Path) -> list:
    """Load a JSONL file and return list of parsed objects."""
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


# The JSONL source does not carry separate apparatus fields.  Its citation
# and cross-reference apparatus is embedded in the definition strings, so the
# extractors below preserve the source text while delegating OSIS parsing to
# the shared normalizer.
_SCRIPTURE_REF_RE = re.compile(
    r"\b(\d?\s*[A-Z][A-Za-z]+\.?\d?)\s+"
    r"(\d+:\d+(?:-\d+)?"
    r"(?:\s*(?:[,;]\s*|\s+and\s+)"
    r"\d+(?::\d+)?(?:-\d+)?)*"
    r")\b"
)
_SEE_CLAUSE_RE = re.compile(
    r"\b[Ss]ee(?:\s+also)?\s+(?P<clause>[^.;)]{1,160})"
)
_INDEXED_SEE_TARGET_RE = re.compile(
    r"\[\d+\]\s*(?P<target>[A-Z][^\[]*?)(?=\s*\[\d+\]|$)"
)
_NON_TERM_SEE_PREFIXES = (
    "illustration ",
    "chapters ",
    "chapter ",
    "margin",
    "below",
    "above",
    "the ",
    "a ",
    "an ",
    "him ",
    "his ",
    "her ",
    "it ",
    "this ",
    "that ",
    "following ",
    "same ",
)


def extract_scripture_references(blocks: list[str]) -> list[dict]:
    """Extract source citations and normalize them through the shared parser.

    The source stores citations inline in prose rather than in a structured
    field.  ``raw`` preserves the matched source spelling; the trailing full
    stop after an abbreviated book name is removed only for the normalizer.
    Unparseable matches remain in the definition text and are not guessed into
    the structured field.
    """
    references: list[dict] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for block in blocks:
        for match in _SCRIPTURE_REF_RE.finditer(block):
            raw = match.group(0).strip()
            normalizer_input = f"{match.group(1).strip().rstrip('.')} {match.group(2).strip()}"
            osis = parse_thml_refs(normalizer_input)
            if not osis:
                continue
            key = (raw, tuple(osis))
            if key in seen:
                continue
            seen.add(key)
            references.append({"raw": raw, "osis": osis})
    return references


def extract_related_terms(blocks: list[str]) -> list[str]:
    """Extract only explicit ``See``/``See also`` headword assertions.

    Numbered references such as ``See [12]MOSES`` are common in the source.
    The bracketed number is a source locator, not part of the target term.
    Generic prose such as ``See chapters ...`` and ``See illustration ...``
    is intentionally excluded.
    """
    related: list[str] = []
    seen: set[str] = set()
    for block in blocks:
        for match in _SEE_CLAUSE_RE.finditer(block):
            clause = match.group("clause").strip()
            indexed_targets = [
                indexed.group("target")
                for indexed in _INDEXED_SEE_TARGET_RE.finditer(clause)
            ]
            candidates = indexed_targets or [clause]
            for candidate in candidates:
                target = re.split(r"[\[\]\(\)]", candidate, maxsplit=1)[0]
                target = target.strip(' "\' .;,')
                if not target or not target[0].isupper():
                    continue
                if target.lower().startswith(_NON_TERM_SEE_PREFIXES):
                    continue
                if "chapter" in target.lower() or ":" in target:
                    continue
                if target in seen:
                    continue
                seen.add(target)
                related.append(target)
    return related


def _normalize_inline_references(text: str) -> list[str]:
    """Return deduplicated OSIS values from a Torrey inline reference block."""
    seen: set[str] = set()
    osis: list[str] = []
    for reference in extract_scripture_references([text]):
        for value in reference["osis"]:
            if value not in seen:
                seen.add(value)
                osis.append(value)
    return osis


# ---------------------------------------------------------------------------
# Torrey's subtopic parser
# ---------------------------------------------------------------------------


def parse_torrey_subtopics(definitions: list) -> list:
    """Convert Torrey's definition blocks into subtopic objects.

    Each definition block is either:
      "Label -- Ref1; Ref2."   -> subtopic with label + one Reference (raw refs string)
      "Label --Ref1; Ref2."    -> same, variant with no space after '--' (rare in source)
      "Label"                  -> subtopic with empty references (section heading)

    The raw refs string (after ' --') is stored as a single Reference object.
    Its OSIS list is populated from the source-backed inline citations.
    """
    subtopics = []
    for block in definitions:
        block = block.strip()
        # Use regex to handle both ' -- ' and ' --' (no trailing space) variants
        m = re.search(r" --\s*", block)
        if m:
            label = block[: m.start()].strip()
            raw_refs = block[m.end() :].strip()
            subtopics.append({
                "label": label,
                "references": [{
                    "raw": raw_refs,
                    "osis": _normalize_inline_references(raw_refs),
                }],
            })
        else:
            # Bare label with no references (section heading like "Exemplified")
            subtopics.append({
                "label": block,
                "references": [],
            })
    return subtopics


# ---------------------------------------------------------------------------
# Meta builder
# ---------------------------------------------------------------------------


def build_meta(
    config: dict,
    source_hash: str,
    process_date: str,
    download_date: str,
    apparatus_stats: dict | None = None,
) -> dict:
    """Build the meta envelope block from a dictionary config."""
    schema_type = config["schema_type"]
    resource_id = config["resource_id"]
    source_url = "https://huggingface.co/datasets/JWBickel/BibleDictionaries"

    notes = (
        "Sourced from JWBickel/BibleDictionaries on HuggingFace. "
        "Underlying text is public domain (19th century). "
        "Structured JSONL format by JWBickel; license confirmation pending (EMAIL-4 sent). "
        "The 2026-07-16 full field census found only term and definitions in every "
        "record; no explicit alternate-term field is present. "
    )
    if schema_type == "reference_entry":
        notes += (
            "Bible citations embedded in definitions are mapped to scripture_references "
            "through the shared OSIS normalizer, and explicit See/See also headword "
            "assertions are mapped to related_terms. alt_terms remains empty because "
            "the source does not provide that apparatus."
        )
    else:
        notes += (
            "Inline Bible citations after Torrey subtopic separators are normalized "
            "into subtopic references, and explicit See/See also topic assertions are "
            "mapped to related_topics. alt_topics remains empty because the source does "
            "not provide that apparatus."
        )
    if apparatus_stats:
        if schema_type == "reference_entry":
            notes += (
                f" Observed populated fields: scripture_references on "
                f"{apparatus_stats['scripture_populated']}/{apparatus_stats['entry_count']} "
                f"entries ({apparatus_stats['scripture_total']} citation groups); "
                f"related_terms on {apparatus_stats['related_populated']}/"
                f"{apparatus_stats['entry_count']} entries "
                f"({apparatus_stats['related_total']} links)."
            )
        else:
            notes += (
                f" Observed normalized OSIS values: {apparatus_stats['reference_total']} "
                f"across {apparatus_stats['reference_subtopics']} subtopics; "
                f"related_topics on {apparatus_stats['related_populated']}/"
                f"{apparatus_stats['entry_count']} topics "
                f"({apparatus_stats['related_total']} links)."
            )

    meta = {
        "id": resource_id,
        "title": config["title"],
        "author": config["author"],
        "author_birth_year": config.get("author_birth_year"),
        "author_death_year": config.get("author_death_year"),
        "original_publication_year": config.get("original_publication_year"),
        "language": config["language"],
        "tradition": config["tradition"],
        "tradition_notes": config.get("tradition_notes"),
        "license": config["license"],
        "schema_type": schema_type,
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
        "provenance": {
            "source_url": source_url,
            "source_format": "JSONL",
            "source_edition": (
                f"JWBickel/BibleDictionaries HuggingFace dataset -- {config['source_file']}"
            ),
            "download_date": download_date,
            "source_hash": f"sha256:{source_hash}",
            "processing_method": "automated",
            "processing_script_version": (
                f"build/parsers/bible_dictionaries.py@{SCRIPT_VERSION}"
            ),
            "processing_date": process_date,
            "notes": notes,
        },
    }
    return meta


# ---------------------------------------------------------------------------
# Dictionary processors
# ---------------------------------------------------------------------------


def _get_download_date(source_file: str, fallback: str) -> str:
    """Read download date for source_file from manifest.json, or return fallback."""
    manifest_path = RAW_DIR / "manifest.json"
    if not manifest_path.exists():
        return fallback
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        for entry in manifest.get("files", []):
            if entry.get("local_filename") == source_file:
                return entry.get("download_date", fallback)[:10]
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read manifest.json: %s", exc)
    return fallback


def _write_with_manifest(out_path: Path, output: dict) -> None:
    """Write a dictionary output file wrapped in its writer manifest.

    The emitter captures the before-hash around the write, so the write must happen
    inside the block (see build/lib/writer_manifest). Both write sites in this parser
    share this helper so the two cannot drift apart.
    """
    previous = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else None
    # Derive the root from OUTPUT_DIR (<root>/data/reference) rather than importing
    # REPO_ROOT, so a test that redirects OUTPUT_DIR gets its manifests in the matching
    # tree instead of writing into the real repo.
    root = OUTPUT_DIR.parents[1]
    with writer_manifest.run(
        writer_identity="bible_dictionaries_parser",
        writer_version=f"build/parsers/bible_dictionaries.py@{SCRIPT_VERSION}",
        data_paths=[out_path],
        repo_root=root,
        manifests_dir=root / "review" / "writer-manifests",
    ) as manifest_run:
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
            f.write("\n")
        entries_changed, fields_changed = writer_manifest.diff_counts(
            previous, output, key=lambda entry: entry["entry_id"]
        )
        manifest_run.record_delta(
            out_path, entries_changed=entries_changed, fields_changed=fields_changed
        )
    logger.info(
        "  Writer manifest: %d entries changed, %d fields changed",
        entries_changed,
        fields_changed,
    )


def process_reference_dict(key: str, config: dict, dry_run: bool = False) -> dict:
    """Process one reference dictionary (Easton's, Smith's, Hitchcock's).

    Returns a stats dict, or {} on failure.
    """
    source_path = RAW_DIR / config["source_file"]
    if not source_path.exists():
        logger.error(
            "Source file not found: %s -- run the download script first: "
            "py -3 build/parsers/bible_dictionaries.py does not download; "
            "re-run the HuggingFace download block in the session notes.",
            source_path,
        )
        return {}

    logger.info("Processing %s ...", config["title"])
    raw_entries = load_jsonl(source_path)
    actual_count = len(raw_entries)
    expected_count = config.get("expected_count", 0)
    if actual_count != expected_count:
        logger.info(
            "  NOTE: %d entries found (expected %d) -- source may have minor count variation",
            actual_count, expected_count,
        )

    source_hash = sha256_file(source_path)
    process_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    download_date = _get_download_date(config["source_file"], process_date)

    dictionary_id = config["dictionary_id"]
    seen_ids: set = set()
    data_entries = []
    empty_def_count = 0
    scripture_populated = 0
    scripture_total = 0
    related_populated = 0
    related_total = 0

    for line_num, raw in enumerate(raw_entries, 1):
        term = raw.get("term", "").strip()
        definitions = raw.get("definitions", [])

        if not term:
            logger.warning(
                "  Empty term at source line %d (raw record: %s) -- skipping",
                line_num, str(raw)[:80],
            )
            continue
        if not definitions:
            empty_def_count += 1

        scripture_references = extract_scripture_references(definitions)
        related_terms = extract_related_terms(definitions)
        scripture_populated += bool(scripture_references)
        scripture_total += len(scripture_references)
        related_populated += bool(related_terms)
        related_total += len(related_terms)

        # Build stable unique entry_id (set as source of truth -- Rule 45)
        base_id = f"{dictionary_id}.{slugify(term)}"
        entry_id = make_unique_id(base_id, seen_ids)
        seen_ids.add(entry_id)

        entry = {
            "entry_id": entry_id,
            "dictionary_id": dictionary_id,
            "term": term,
            "alt_terms": [],
            "definition_blocks": definitions,
            "scripture_references": scripture_references,
            "related_terms": related_terms,
            "word_count": count_words(definitions),
        }
        data_entries.append(entry)

    if dry_run:
        logger.info("  [dry-run] %d source entries -> %d records", actual_count, len(data_entries))
        for e in data_entries[:3]:
            logger.info(
                "  [dry-run]   entry_id=%s  blocks=%d  words=%d",
                e["entry_id"], len(e["definition_blocks"]), e["word_count"],
            )
        out_path = OUTPUT_DIR / f"{dictionary_id}.json"
        logger.info("  [dry-run] Would write to: %s", out_path)
        return {"status": "dry-run", "entry_count": len(data_entries), "dictionary": dictionary_id}

    # Build output
    apparatus_stats = {
        "entry_count": len(data_entries),
        "scripture_populated": scripture_populated,
        "scripture_total": scripture_total,
        "related_populated": related_populated,
        "related_total": related_total,
    }
    meta = build_meta(config, source_hash, process_date, download_date, apparatus_stats)
    output = {"meta": meta, "data": data_entries}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{dictionary_id}.json"
    _write_with_manifest(out_path, output)

    size_kb = out_path.stat().st_size / 1024
    logger.info("  Wrote %d entries -> %s (%.0f KB)", len(data_entries), out_path.name, size_kb)
    logger.info(
        "  Apparatus: scripture_references=%d entries/%d groups; "
        "related_terms=%d entries/%d links; alt_terms=0 entries",
        scripture_populated, scripture_total, related_populated, related_total,
    )

    # Quality stats (CODING_DEFAULTS Rule 43)
    words = [e["word_count"] for e in data_entries]
    words_sorted = sorted(words)
    n = len(words_sorted)
    null_def = sum(1 for e in data_entries if not e["definition_blocks"])
    short = sum(1 for e in data_entries if e["word_count"] < 5)
    logger.info(
        "  Quality: words min=%d med=%d max=%d",
        min(words), words_sorted[n // 2], max(words),
    )
    if null_def:
        logger.warning("  %d/%d entries with empty definition_blocks", null_def, n)
    if short:
        logger.info(
            "  %d/%d entries under 5 words (expected for stub/name entries)", short, n
        )
    if empty_def_count:
        logger.warning(
            "  %d source entries with missing definitions field", empty_def_count
        )

    return {
        "key": key,
        "dictionary_id": dictionary_id,
        "schema_type": "reference_entry",
        "entry_count": len(data_entries),
        "file": out_path.name,
        "status": "ok",
        "scripture_populated": scripture_populated,
        "scripture_total": scripture_total,
        "related_populated": related_populated,
        "related_total": related_total,
    }


def process_torrey(key: str, config: dict, dry_run: bool = False) -> dict:
    """Process Torrey's New Topical Textbook into topical_reference records.

    Returns a stats dict, or {} on failure.
    """
    source_path = RAW_DIR / config["source_file"]
    if not source_path.exists():
        logger.error(
            "Source file not found: %s -- re-run the HuggingFace download block "
            "in the session notes to populate raw/bible_dictionaries/.",
            source_path,
        )
        return {}

    logger.info("Processing %s ...", config["title"])
    raw_entries = load_jsonl(source_path)
    actual_count = len(raw_entries)
    expected_count = config.get("expected_count", 0)
    if actual_count != expected_count:
        logger.info(
            "  NOTE: %d entries found (expected %d) -- source may have minor count variation",
            actual_count, expected_count,
        )

    source_hash = sha256_file(source_path)
    process_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    download_date = _get_download_date(config["source_file"], process_date)

    index_id = config["index_id"]
    seen_ids: set = set()
    data_entries = []

    for line_num, raw in enumerate(raw_entries, 1):
        topic = raw.get("term", "").strip()
        definitions = raw.get("definitions", [])

        if not topic:
            logger.warning(
                "  Empty topic at source line %d (raw record: %s) -- skipping",
                line_num, str(raw)[:80],
            )
            continue

        base_id = f"{index_id}.{slugify(topic)}"
        entry_id = make_unique_id(base_id, seen_ids)
        seen_ids.add(entry_id)

        subtopics = parse_torrey_subtopics(definitions)
        related_topics = extract_related_terms(definitions)

        entry = {
            "entry_id": entry_id,
            "index_id": index_id,
            "topic": topic,
            "alt_topics": [],
            "subtopics": subtopics,
            "related_topics": related_topics,
        }
        data_entries.append(entry)

    if dry_run:
        logger.info("  [dry-run] %d source entries -> %d records", actual_count, len(data_entries))
        for e in data_entries[:3]:
            refs_total = sum(
                len(reference["osis"])
                for subtopic in e["subtopics"]
                for reference in subtopic["references"]
            )
            logger.info(
                "  [dry-run]   entry_id=%s  subtopics=%d  refs=%d",
                e["entry_id"], len(e["subtopics"]), refs_total,
            )
        out_path = OUTPUT_DIR / f"{index_id}.json"
        logger.info("  [dry-run] Would write to: %s", out_path)
        return {"status": "dry-run", "entry_count": len(data_entries), "dictionary": index_id}

    # Build output
    reference_subtopics = sum(
        1
        for entry in data_entries
        for subtopic in entry["subtopics"]
        for reference in subtopic["references"]
        if reference["osis"]
    )
    reference_total = sum(
        len(reference["osis"])
        for entry in data_entries
        for subtopic in entry["subtopics"]
        for reference in subtopic["references"]
    )
    related_populated = sum(bool(entry["related_topics"]) for entry in data_entries)
    related_total = sum(len(entry["related_topics"]) for entry in data_entries)
    apparatus_stats = {
        "entry_count": len(data_entries),
        "reference_subtopics": reference_subtopics,
        "reference_total": reference_total,
        "related_populated": related_populated,
        "related_total": related_total,
    }
    meta = build_meta(config, source_hash, process_date, download_date, apparatus_stats)
    output = {"meta": meta, "data": data_entries}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{index_id}.json"
    _write_with_manifest(out_path, output)

    size_kb = out_path.stat().st_size / 1024
    logger.info("  Wrote %d entries -> %s (%.0f KB)", len(data_entries), out_path.name, size_kb)
    logger.info(
        "  Apparatus: normalized OSIS=%d across %d subtopics; "
        "related_topics=%d entries/%d links; alt_topics=0 entries",
        reference_total, reference_subtopics, related_populated, related_total,
    )

    # Quality stats (CODING_DEFAULTS Rule 43)
    n = len(data_entries)
    subtopic_counts = [len(e["subtopics"]) for e in data_entries]
    sc_sorted = sorted(subtopic_counts)
    refs_per_entry = [
        sum(
            len(reference["osis"])
            for subtopic in e["subtopics"]
            for reference in subtopic["references"]
        )
        for e in data_entries
    ]
    total_refs = sum(refs_per_entry)
    rpe_sorted = sorted(refs_per_entry)
    null_sub = sum(1 for e in data_entries if not e["subtopics"])
    null_topic = sum(1 for e in data_entries if not e.get("topic", "").strip())
    logger.info(
        "  Quality: subtopics/entry min=%d med=%d max=%d",
        min(subtopic_counts), sc_sorted[n // 2], max(subtopic_counts),
    )
    logger.info(
        "  Quality: refs/entry min=%d med=%d max=%d; total=%d",
        min(refs_per_entry), rpe_sorted[n // 2], max(refs_per_entry), total_refs,
    )
    if null_topic:
        logger.warning("  %d/%d entries with empty topic field", null_topic, n)
    if null_sub:
        logger.warning("  %d/%d entries with no subtopics", null_sub, n)

    return {
        "key": key,
        "index_id": index_id,
        "schema_type": "topical_reference",
        "entry_count": len(data_entries),
        "file": out_path.name,
        "status": "ok",
        "reference_subtopics": reference_subtopics,
        "reference_total": reference_total,
        "related_populated": related_populated,
        "related_total": related_total,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Parse JWBickel/BibleDictionaries JSONL into OCD reference schemas."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--dictionary",
        metavar="KEY",
        help="Dictionary to process: eastons, smiths, hitchcocks, torreys",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Process all four dictionaries.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report -- do not write output files.",
    )
    args = parser.parse_args()

    if args.all:
        keys = list(DICTIONARIES.keys())
    else:
        key = args.dictionary.lower()
        if key not in DICTIONARIES:
            logger.error(
                "Unknown dictionary '%s'. Choose from: %s",
                key, ", ".join(DICTIONARIES),
            )
            return
        keys = [key]

    logger.info("Output dir: %s", OUTPUT_DIR)
    logger.info("Log file: %s", LOG_PATH)

    all_stats = []
    failed_keys = []
    start_time = time.time()
    total_keys = len(keys)

    for idx, key in enumerate(keys, 1):
        config = DICTIONARIES[key]
        schema_type = config["schema_type"]
        logger.info("--- Dictionary %d of %d: %s ---", idx, total_keys, config["title"])
        try:
            if schema_type == "reference_entry":
                stats = process_reference_dict(key, config, dry_run=args.dry_run)
            elif schema_type == "topical_reference":
                stats = process_torrey(key, config, dry_run=args.dry_run)
            else:
                logger.error("Unknown schema_type '%s' for key '%s'", schema_type, key)
                stats = {}
        except Exception as exc:
            logger.error("Unhandled error processing '%s': %s", key, exc, exc_info=True)
            stats = {}
        if not stats:
            failed_keys.append(key)
        all_stats.append(stats)

    elapsed = time.time() - start_time
    processed = [s for s in all_stats if s]
    total_entries = sum(s.get("entry_count", 0) for s in processed)
    failed_count = len(failed_keys)

    summary = (
        f"=== DONE: {len(processed)}/{total_keys} dictionaries processed, "
        f"{total_entries} entries, {elapsed:.1f}s ==="
    )
    if failed_count:
        summary += f" -- {failed_count} FAILED: {', '.join(failed_keys)}"
        logger.error(summary)
    else:
        logger.info(summary)


if __name__ == "__main__":
    main()
