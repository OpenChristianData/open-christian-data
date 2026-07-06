"""ia_schaff_herzog_census.py
Census script for Internet Archive _djvu.txt OCR files of the Schaff-Herzog Encyclopedia.

NOT a parser. Outputs structural statistics to inform ia_schaff_herzog.py design.

Downloads vols 3 and 8 (non-adjacent) to raw/internet-archive/schaff-herzog/.
Run once before writing the parser; delete or archive afterward.

Usage:
    py -3 build/parsers/ia_schaff_herzog_census.py
"""

import re
import time
import urllib.request  # standards: download only
import sys
from pathlib import Path

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

from build.lib.paths import REPO_ROOT  # noqa: E402
RAW_DIR = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog"

USER_AGENT = (
    "OpenChristianData/1.0 (research; open-source data project; "
    "contact: openchristiandata@gmail.com)"
)
DOWNLOAD_DELAY_SECONDS = 10

IA_BASE_URL = "https://archive.org/download/NewSchaffHerzogEncyclopediaOfReligious/{filename}"

# Two non-adjacent pilot volumes
PILOT_VOLUMES = [
    ("vol3", "03.NewSchaffHerzogEncycReligKnowl.v3.1909.Jackson.Sherman.Gilmore.1909._djvu.txt"),
    ("vol8", "08.NewSchaffHerzogEncycReligKnowl.v8.Jackson.Sherman.Gilmore.1909._djvu.txt"),
]

# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def download_file(filename: str) -> Path:
    """Download a _djvu.txt file if not cached. Returns local path."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    local_path = RAW_DIR / filename

    if local_path.exists():
        print(f"  Cached: {filename} ({local_path.stat().st_size // 1024} KB)")
        return local_path

    url = IA_BASE_URL.format(filename=filename)
    print(f"  Downloading {url} ...")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = resp.read()
    with open(str(local_path), "wb") as f:
        f.write(data)
    print(f"  Downloaded {len(data) // 1024} KB -> {filename}")
    return local_path


# ---------------------------------------------------------------------------
# Census helpers
# ---------------------------------------------------------------------------


def census_volume(label: str, filepath: Path) -> None:
    """Print structural census for one _djvu.txt file."""
    print(f"\n{'=' * 70}")
    print(f"CENSUS: {label} ({filepath.name})")
    print(f"{'=' * 70}")

    raw = filepath.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")

    lines = text.splitlines()
    print(f"Total lines: {len(lines)}")
    print(f"Total chars: {len(text)}")

    # --- First 80 lines (front matter / header) ---
    print("\n--- First 80 lines (front matter) ---")
    for i, line in enumerate(lines[:80], 1):
        print(f"  {i:4d}: {line[:120]}")

    # --- ALL CAPS line detection ---
    # A line is "ALL CAPS heading" if:
    #   - len >= 3 chars
    #   - has at least 2 uppercase letters
    #   - contains no lowercase letters (allowing spaces, digits, punctuation)
    all_caps_lines = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if len(stripped) >= 3 and stripped.upper() == stripped and any(c.isalpha() for c in stripped):
            all_caps_lines.append((i + 1, stripped))

    print(f"\n--- ALL CAPS lines (total: {len(all_caps_lines)}) ---")
    print("  First 30:")
    for lineno, content in all_caps_lines[:30]:
        print(f"  L{lineno:5d}: {content[:100]}")
    print("  Last 10:")
    for lineno, content in all_caps_lines[-10:]:
        print(f"  L{lineno:5d}: {content[:100]}")

    # --- Length distribution of ALL CAPS lines ---
    lengths = [len(c) for _, c in all_caps_lines]
    if lengths:
        short = [(ln, c) for ln, c in all_caps_lines if len(c) <= 4]
        medium = [(ln, c) for ln, c in all_caps_lines if 5 <= len(c) <= 30]
        long_ = [(ln, c) for ln, c in all_caps_lines if len(c) > 30]
        print(f"\n  Length distribution: <=4: {len(short)}, 5-30: {len(medium)}, >30: {len(long_)}")
        print("  Sample short (<= 4 chars):")
        for ln, c in short[:10]:
            print(f"    L{ln}: '{c}'")
        print("  Sample long (> 30 chars):")
        for ln, c in long_[:5]:
            print(f"    L{ln}: '{c[:80]}'")

    # --- Detect front matter boundary ---
    # Hypothesis: A-Z entries begin after a line that looks like "A" (single letter section divider)
    # or after a bibliographic appendix section ends
    print("\n--- Front matter boundary detection ---")
    # Find first occurrence of line that is just "A" or "A." or "THE LETTER A"
    for i, line in enumerate(lines[:500]):
        stripped = line.strip()
        if stripped in ("A", "A.", "THE LETTER A", "LETTER A"):
            print(f"  Potential A-section start at line {i + 1}: '{stripped}'")
        if re.match(r'^[A-Z]{1,3}$', stripped) and i > 10:
            print(f"  Short ALL-CAPS at line {i + 1}: '{stripped}'")

    # Look for common front matter markers
    front_markers = ["PREFACE", "CONTENTS", "TABLE OF CONTENTS", "ABBREVIATIONS",
                     "CONTRIBUTORS", "EDITORS", "INTRODUCTION", "BIBLIOGRAPH"]
    for marker in front_markers:
        for i, line in enumerate(lines[:300]):
            if marker in line.upper():
                print(f"  Front matter marker '{marker}' at line {i + 1}: {line.strip()[:80]}")
                break

    # Find first "plausible article heading" after line 100
    # (ALL CAPS, length 5-40, not a Roman numeral or section divider)
    print("\n  Scanning for first plausible article heading (after line 100):")
    for i, line in enumerate(lines[100:600], 100):
        stripped = line.strip()
        if (len(stripped) >= 5 and len(stripped) <= 50
                and stripped.upper() == stripped
                and any(c.isalpha() for c in stripped)
                and not re.match(r'^[IVXLCDM]+\.?$', stripped)):
            print(f"  L{i + 1}: '{stripped}'")
            # Show 5 lines after to confirm it's an article
            print("  Next 5 lines:")
            for j in range(i + 1, min(i + 6, len(lines))):
                print(f"    L{j + 1}: {lines[j][:100]}")
            break

    # --- Page / column break markers ---
    print("\n--- Structural markers ---")
    page_patterns = [
        (r'^\s*\d+\s*$', "Standalone digit lines (possible page numbers)"),
        (r'^\s*\[\d+\]\s*$', "Bracketed page numbers"),
        (r'^\s*-\s*\d+\s*-\s*$', "Dashed page numbers"),
        (r'^\s*={3,}\s*$', "=== dividers"),
        (r'^\s*-{3,}\s*$', "--- dividers"),
        (r'^\s*\*{3,}\s*$', "*** dividers"),
    ]
    for pattern, label in page_patterns:
        matches = [(i + 1, lines[i]) for i in range(len(lines)) if re.match(pattern, lines[i])]
        print(f"  {label}: {len(matches)} occurrences")
        if matches:
            for lineno, content in matches[:3]:
                print(f"    L{lineno}: '{content[:60]}'")

    # --- OCR noise samples ---
    print("\n--- OCR noise patterns ---")
    noise_patterns = [
        (r'[^\x00-\x7F]', "Non-ASCII characters"),
        (r'\b[a-z]-\s*\n\s*[a-z]', "Hyphenated line breaks"),
        (r'\d{3,}', "Long digit sequences (possible OCR artifacts)"),
        (r'[|\\]{2,}', "Double pipe/backslash (OCR noise)"),
    ]
    for pattern, label in noise_patterns:
        matches = re.findall(pattern, text[:50000])
        print(f"  {label}: {len(matches)} in first 50k chars")
        if matches and len(str(matches[0])) < 30:
            print(f"    Sample: {str(matches[:5])}")

    # --- Heading + body pair sample ---
    # Show 5 consecutive ALL CAPS + following body text pairs from mid-volume
    mid = len(lines) // 2
    print(f"\n--- Sample heading+body pairs (around line {mid}) ---")
    found = 0
    for i in range(mid, min(mid + 2000, len(lines))):
        stripped = lines[i].strip()
        if (len(stripped) >= 5 and len(stripped) <= 50
                and stripped.upper() == stripped
                and any(c.isalpha() for c in stripped)
                and not re.match(r'^[IVXLCDM]+\.?$', stripped)):
            print(f"\n  Heading L{i + 1}: '{stripped}'")
            for j in range(i + 1, min(i + 8, len(lines))):
                print(f"  Body L{j + 1}: {lines[j][:100]}")
            found += 1
            if found >= 5:
                break


def main() -> None:
    print("Schaff-Herzog IA Census")
    print("Pilot volumes: vol3, vol8")
    print(f"Raw dir: {RAW_DIR}")

    paths = []
    for idx, (label, filename) in enumerate(PILOT_VOLUMES):
        if idx > 0:
            print(f"\nWaiting {DOWNLOAD_DELAY_SECONDS}s (crawl delay)...")
            time.sleep(DOWNLOAD_DELAY_SECONDS)
        try:
            path = download_file(filename)
            paths.append((label, path))
        except Exception as exc:
            print(f"  ERROR downloading {filename}: {exc}")

    for label, path in paths:
        census_volume(label, path)

    print("\n\n=== CENSUS COMPLETE ===")


if __name__ == "__main__":
    main()
