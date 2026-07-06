"""Normalise ALL CAPS source_title values to Title Case across all church_fathers JSON files.

The upstream HistoricalChristianFaith dataset used ALL CAPS for source_title.
Newer editorial patches use Title Case. This script normalises the legacy ALL CAPS entries
so the entire church_fathers dataset has a consistent format.

Conversion rules:
  - A title is converted only if ALL its alphabetic characters are uppercase.
  - First word is always capitalised.
  - 'Small words' (articles, short prepositions, coordinating conjunctions) are lowercased
    unless they are the first word.
  - Tokens whose alphabetic core consists entirely of Roman numeral characters
    (I, V, X, L, C, D, M) and is 1-7 chars stay uppercase (e.g. VII, XIV, XXXII).
  - Pure-numeric tokens (digits, colons, hyphens, dots) are unchanged.
  - Leading/trailing non-alphabetic characters around each token are preserved.

Run twice to verify idempotency (TEST-05).
"""

import json
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
CF_DIR = REPO_ROOT / "data" / "church-fathers"
VALIDATE_SCRIPT = REPO_ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Title-case conversion logic
# ---------------------------------------------------------------------------

SMALL_WORDS = frozenset([
    "a", "an", "the",
    "and", "but", "or", "nor", "so", "yet",
    "at", "by", "from", "in", "into", "of", "off", "on", "onto",
    "out", "over", "to", "up", "with", "as", "vs",
])

ROMAN_CHARS = frozenset("IVXLCDM")


def _is_roman(token: str) -> bool:
    """True if token looks like a standalone Roman numeral (1-7 chars, all Roman letters)."""
    return bool(token) and 1 <= len(token) <= 7 and token.isalpha() and all(c in ROMAN_CHARS for c in token)


def _titlecase_token(token: str, is_first: bool) -> str:
    """Apply title-case rules to a single whitespace-separated token."""
    # Split into: leading non-alpha, alphabetic core, trailing non-alpha
    start = 0
    while start < len(token) and not token[start].isalpha():
        start += 1
    end = len(token)
    while end > start and not token[end - 1].isalpha():
        end -= 1

    prefix = token[:start]
    core = token[start:end]
    suffix = token[end:]

    if not core:
        return token  # all non-alpha (number, punctuation), leave unchanged

    if _is_roman(core):
        return prefix + core + suffix  # keep Roman numerals uppercase

    if not is_first and core.lower() in SMALL_WORDS:
        return prefix + core.lower() + suffix

    return prefix + core[0].upper() + core[1:].lower() + suffix


def to_title_case(title: str) -> str:
    """Convert an ALL CAPS title to Title Case.

    Returns the input unchanged if it is not entirely uppercase or contains
    no alphabetic characters.
    """
    if not title or not any(c.isalpha() for c in title):
        return title
    if title != title.upper():
        return title  # already mixed/lower case -- skip
    tokens = title.split()
    return " ".join(_titlecase_token(tok, i == 0) for i, tok in enumerate(tokens))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    json_files = sorted(CF_DIR.glob("*.json"))
    print(f"Processing {len(json_files)} church-fathers JSON files ...")
    print()

    total_converted = 0
    files_changed = 0

    for json_path in json_files:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)

        entries = data.get("data", [])
        converted_count = 0

        for entry in entries:
            old_title = entry.get("source_title", "")
            new_title = to_title_case(old_title)
            if new_title != old_title:
                entry["source_title"] = new_title
                converted_count += 1

        if converted_count:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            total_converted += converted_count
            files_changed += 1
            print(f"  {json_path.name}: {converted_count} converted")

    print()
    print(f"Total titles converted: {total_converted}")
    print(f"Files changed:          {files_changed}")
    print(f"Files unchanged:        {len(json_files) - files_changed}")

    # Run full validation to confirm nothing broke
    print()
    print("Running validate.py --all ...")
    try:
        subprocess.run(
            ["py", "-3", str(VALIDATE_SCRIPT), "--all"],
            cwd=REPO_ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    main()
