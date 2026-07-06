"""
One-shot patch script: add 2 PG-unique Whitefield sermons to george-whitefield-sermons.json.

Sermons LVIII and LIX from PG#77041 (The Works of the Reverend George Whitefield, Vol 6, 1771)
are not present in the CCEL 'Selected Sermons' dataset. This script extracts them from the
cached PG plain-text file and appends them to the existing JSON.

Run once from the repo root:
    py -3 build/scripts/add_pg_whitefield_sermons.py

Idempotent: exits cleanly if sermon_id "60" already exists in the dataset.
"""

import json
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent.parent
PG_VOL6 = REPO_ROOT / "raw" / "gutenberg" / "sermons" / "whitefield" / "pg77041.txt"
OUTPUT_FILE = REPO_ROOT / "data" / "sermons" / "george-whitefield-sermons.json"


# ---------------------------------------------------------------------------
# Text processing
# ---------------------------------------------------------------------------

def clean_italic(text: str) -> str:
    """Remove PG underscore italic markers: _word_ -> word."""
    return re.sub(r"_([^_]+)_", r"\1", text)


def extract_paragraphs(raw_lines: list[str]) -> list[str]:
    """
    Extract body paragraphs from PG plain-text lines for a single sermon.

    In PG vol 6, body text lines have 0 leading spaces. Everything structural
    (centered headings, scripture refs, scripture quotes, footnotes) has 1+
    leading spaces. Paragraphs are separated by blank lines.
    """
    paragraphs = []
    current: list[str] = []

    for line in raw_lines:
        stripped = line.strip()

        # Blank line: flush current paragraph
        if not stripped:
            if current:
                para = " ".join(current)
                para = clean_italic(para)
                para = re.sub(r"  +", " ", para).strip()
                if para:
                    paragraphs.append(para)
                current = []
            continue

        # Only 0-leading-space lines are body text
        leading = len(line) - len(line.lstrip(" "))
        if leading == 0:
            current.append(stripped)

    # Flush any remaining paragraph
    if current:
        para = " ".join(current)
        para = clean_italic(para)
        para = re.sub(r"  +", " ", para).strip()
        if para:
            paragraphs.append(para)

    return paragraphs


# ---------------------------------------------------------------------------
# Locate sermon boundaries in PG vol 6
# ---------------------------------------------------------------------------

def find_sermon_boundaries(lines: list[str]) -> dict[str, int]:
    """Return {roman_numeral: line_index} for all SERMON headings."""
    boundaries: dict[str, int] = {}
    for i, line in enumerate(lines):
        m = re.search(r"SERMON\s+([LXIVCDM]+)\.", line)
        if m:
            boundaries[m.group(1)] = i
    return boundaries


def find_finis(lines: list[str], start: int) -> int:
    """Return the line index of FINIS. after start."""
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == "FINIS.":
            return i
    return len(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # Load existing dataset
    with open(OUTPUT_FILE, encoding="utf-8") as f:
        dataset = json.load(f)

    existing_ids = {e["sermon_id"] for e in dataset["data"]}
    if "60" in existing_ids:
        print("Sermon 60 already exists -- nothing to do.")
        return

    # Load PG vol 6
    pg_text = PG_VOL6.read_text(encoding="utf-8", errors="replace")
    lines = pg_text.split("\n")

    # Locate boundaries
    bounds = find_sermon_boundaries(lines)
    lviii_start = bounds["LVIII"]
    lix_start = bounds["LIX"]
    lix_end = find_finis(lines, lix_start)

    print(f"LVIII: lines {lviii_start}-{lix_start - 1}")
    print(f"LIX:   lines {lix_start}-{lix_end}")

    # Extract paragraphs (skip the first heading line of each sermon)
    lviii_paras = extract_paragraphs(lines[lviii_start + 1 : lix_start])
    lix_paras = extract_paragraphs(lines[lix_start + 1 : lix_end])

    def word_count(paras: list[str]) -> int:
        return sum(len(p.split()) for p in paras)

    print(f"\nLVIII: {len(lviii_paras)} paragraphs, {word_count(lviii_paras)} words")
    print(f"  First: {lviii_paras[0][:120]!r}")
    print(f"  Last:  {lviii_paras[-1][:80]!r}")
    print(f"\nLIX: {len(lix_paras)} paragraphs, {word_count(lix_paras)} words")
    print(f"  First: {lix_paras[0][:120]!r}")
    print(f"  Last:  {lix_paras[-1][:80]!r}")

    # Build entries
    entry_lviii = {
        "collection_id": "george-whitefield-sermons",
        "sermon_id": "60",
        "series": None,
        "title": "Peter's Denial of his Lord",
        "primary_reference": {"raw": "Matthew 26:75", "osis": []},
        "primary_reference_text": None,
        "content_blocks": lviii_paras,
        "date_preached": None,
        "location": None,
        "word_count": word_count(lviii_paras),
    }

    entry_lix = {
        "collection_id": "george-whitefield-sermons",
        "sermon_id": "61",
        "series": None,
        "title": "The True Way of Beholding the Lamb of God",
        "primary_reference": {"raw": "John 1:35-36", "osis": []},
        "primary_reference_text": None,
        "content_blocks": lix_paras,
        "date_preached": None,
        "location": None,
        "word_count": word_count(lix_paras),
    }

    # Append to dataset
    dataset["data"].append(entry_lviii)
    dataset["data"].append(entry_lix)

    # Update meta notes to reflect mixed provenance
    old_notes: str = dataset["meta"]["provenance"]["notes"]
    supplement_note = (
        " Sermons 60-61 ('Peter's Denial of his Lord'; 'The True Way of Beholding the Lamb of God') "
        "are supplementary entries extracted from PG#77041 (Works Vol 6, 1771) -- "
        "these two 1771 Works sermons are not present in the CCEL Selected Sermons source."
    )
    dataset["meta"]["provenance"]["notes"] = old_notes + supplement_note

    # Write output
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)

    print(f"\nSummary: appended sermons 60 + 61 to {OUTPUT_FILE.name}")
    print(f"Total entries: {len(dataset['data'])}")
    print("DONE")


if __name__ == "__main__":
    main()
