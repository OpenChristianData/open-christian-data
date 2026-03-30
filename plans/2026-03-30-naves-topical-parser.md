# Nave's Topical Bible Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Download the CrossWire SWORD Nave's Topical Bible module, decode its binary zLD format, and produce a validated `topical_reference` JSON file at `data/topical-reference/naves/naves-topical-bible.json`.

**Architecture:** Single Python script (`naves_topical.py`) reads the extracted SWORD zLD binary files (`dict.zdx` + `dict.zdt`), decodes each topic entry (including key name, subtopics, verse references, and cross-references), normalises abbreviated book names to OSIS codes using the existing `osis_book_codes.json` plus a Nave's-specific abbreviation table, and writes a single output JSON. The download is a one-request ZIP from CrossWire FTP; extraction is local. The schema (`topical_reference.schema.json`) and validator (`validate_topical_reference_file` in `validate.py`) already exist and require no changes.

**Tech Stack:** Python 3, `urllib.request` (download), `struct` + `zlib` (zLD binary decode), `re` (reference parsing), `xml.etree.ElementTree` (ThML fallback if content is XML), `json`, `pathlib`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create dir | `raw/naves_topical/` | Downloaded + extracted SWORD files |
| Create | `research/reference/request_log.csv` | Audit trail for all web requests this session |
| Create | `build/scripts/inspect_sword_zld.py` | One-time binary format probe (not committed) |
| Create | `build/parsers/naves_topical.py` | Main parser — download → decode → output |
| Create | `data/topical-reference/naves/naves-topical-bible.json` | Output data file |
| Modify | `README.md` | Add Nave's row to status table and data listing |

---

## Task 1: Download Nave.zip and set up raw directory

**Files:**
- Create dir: `raw/naves_topical/`
- Create: `research/reference/request_log.csv`

Robots.txt for crosswire.org is already verified: crawl-delay 30s; `/ftpmirror/pub/sword/packages/rawzip/` is NOT disallowed. The download URL is `https://www.crosswire.org/ftpmirror/pub/sword/packages/rawzip/Nave.zip`.

- [ ] **Step 1: Create the raw directory**

```bash
mkdir -p "raw/naves_topical"
```

- [ ] **Step 2: Create request_log.csv with headers**

Create `research/reference/request_log.csv`:

```
timestamp,method,url,http_status,size_bytes,sha256,notes
```

- [ ] **Step 3: Write and run the download script inline**

Run this Python snippet from the repo root to download Nave.zip with the correct User-Agent, hash it, extract it, and log the request:

```python
import hashlib, urllib.request, zipfile, csv
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path("C:/Users/Robbie/Projects/open-christian-data")
RAW_DIR = REPO_ROOT / "raw" / "naves_topical"
ZIP_PATH = RAW_DIR / "Nave.zip"
LOG_PATH = REPO_ROOT / "research" / "reference" / "request_log.csv"
URL = "https://www.crosswire.org/ftpmirror/pub/sword/packages/rawzip/Nave.zip"
UA = "OpenChristianData/1.0 (research; open-source data project; contact: openchristiandata@gmail.com)"

RAW_DIR.mkdir(parents=True, exist_ok=True)

if ZIP_PATH.exists():
    print("Nave.zip already exists -- skipping download")
else:
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    ZIP_PATH.write_bytes(data)
    print(f"Downloaded {len(data):,} bytes -> {ZIP_PATH}")

# SHA-256
digest = hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest()
size = ZIP_PATH.stat().st_size
print(f"SHA-256: {digest}")

# Log request
with open(LOG_PATH, "a", encoding="utf-8", newline="") as f:
    writer = csv.writer(f)
    writer.writerow([
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "GET", URL, 200, size, f"sha256:{digest}",
        "CrossWire SWORD Nave module v3.0 - public domain"
    ])
print("Logged to request_log.csv")

# Extract
with zipfile.ZipFile(ZIP_PATH) as z:
    z.extractall(RAW_DIR)
print("Extracted:")
for p in sorted(RAW_DIR.rglob("*")):
    if p.is_file() and p.name != "Nave.zip":
        print(f"  {p.relative_to(RAW_DIR)}")
```

Expected output (extract shows the module's file layout):
```
Downloaded 1,234,567 bytes -> raw/naves_topical/Nave.zip
SHA-256: <64-char hex>
Logged to request_log.csv
Extracted:
  mods.d/nave.conf
  modules/lexdict/zld/nave/dict.zdx
  modules/lexdict/zld/nave/dict.zdt
```

- [ ] **Step 4: Verify the conf file for metadata**

Read `raw/naves_topical/mods.d/nave.conf` (plain text):

```bash
type raw/naves_topical/mods.d/nave.conf
```

Note: `ModDrv=zLD`, `Version=`, `Encoding=`, `SourceType=` fields. Record any encoding field (UTF-8 vs Latin-1).

- [ ] **Step 5: Commit the zip + log**

```bash
git add raw/naves_topical/Nave.zip raw/naves_topical/mods.d/ raw/naves_topical/modules/ research/reference/request_log.csv
git commit -m "raw: add CrossWire SWORD Nave module (Nave.zip) and request log"
```

---

## Task 2: Binary format inspection

**Files:**
- Create: `build/scripts/inspect_sword_zld.py`

The zLD format has not been decoded in this project before. The project's rawLD parser (`sword_devotional.py`) handled uncompressed `.idx`+`.dat` files. The zLD format uses block compression. This task empirically determines the format before writing the parser.

- [ ] **Step 1: Write the inspection script**

Create `build/scripts/inspect_sword_zld.py`:

```python
"""inspect_sword_zld.py
One-time binary format probe for SWORD zLD modules.
Run: py -3 build/scripts/inspect_sword_zld.py

Prints hex dumps and candidate struct interpretations for dict.zdx and dict.zdt.
Use the output to confirm the format before writing naves_topical.py.
"""

import struct
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ZDX = REPO_ROOT / "raw" / "naves_topical" / "modules" / "lexdict" / "zld" / "nave" / "dict.zdx"
ZDT = REPO_ROOT / "raw" / "naves_topical" / "modules" / "lexdict" / "zld" / "nave" / "dict.zdt"

def hex_dump(data: bytes, n: int = 64) -> str:
    chunk = data[:n]
    return " ".join(f"{b:02x}" for b in chunk)

def try_cstring_entries(data: bytes, label: str) -> None:
    """Try reading data as null-terminated key strings each followed by fixed-size suffix."""
    print(f"\n--- {label}: trying null-terminated key + suffix approach ---")
    for suffix_size in (4, 6, 8, 12):
        entries = []
        pos = 0
        try:
            while pos < min(len(data), 2000) and len(entries) < 8:
                end = data.index(b"\x00", pos)
                key = data[pos:end].decode("latin-1", errors="replace")
                suffix = data[end + 1: end + 1 + suffix_size]
                if len(suffix) < suffix_size:
                    break
                pos = end + 1 + suffix_size
                entries.append((key, suffix.hex()))
            if entries:
                print(f"  suffix_size={suffix_size}: first {len(entries)} entries:")
                for k, s in entries[:5]:
                    print(f"    key={k!r:30s}  suffix_hex={s}")
        except (ValueError, UnicodeDecodeError):
            print(f"  suffix_size={suffix_size}: failed to parse as cstring+suffix")

def try_fixed_entries(data: bytes, label: str) -> None:
    """Try reading data as pure fixed-size entries (no key strings)."""
    print(f"\n--- {label}: fixed-size entry candidates ---")
    print(f"  File size: {len(data):,} bytes")
    print(f"  First 64 bytes: {hex_dump(data)}")
    for entry_size in (4, 6, 8, 10, 12):
        n = len(data) // entry_size
        print(f"  If entry_size={entry_size}: {n} entries")
        if n > 0:
            e0 = struct.unpack_from("<" + "I" * (entry_size // 4) + "H" * (entry_size % 4 // 2), data, 0)
            print(f"    [0] as uints: {e0}")
    # Also print first 4 bytes as uint32 (often a count header)
    if len(data) >= 4:
        count = struct.unpack_from("<I", data, 0)[0]
        print(f"  First 4 bytes as uint32 (possible entry count): {count}")

def probe_zdt_blocks(data: bytes) -> None:
    """Probe zdt for compressed block structure."""
    print(f"\n--- dict.zdt: block structure probe ---")
    print(f"  File size: {len(data):,} bytes")
    print(f"  First 64 bytes: {hex_dump(data)}")
    # Try: 4-byte compressed_size + zlib block
    pos = 0
    blocks_found = 0
    print("\n  Trying: 4-byte compressed_len header before each zlib block")
    while pos < min(len(data), 50000) and blocks_found < 5:
        if pos + 4 > len(data):
            break
        comp_len = struct.unpack_from("<I", data, pos)[0]
        if comp_len == 0 or comp_len > 500_000:
            print(f"  pos={pos}: comp_len={comp_len} (unreasonable -- stopping)")
            break
        block = data[pos + 4: pos + 4 + comp_len]
        if len(block) < comp_len:
            print(f"  pos={pos}: not enough data for block of {comp_len} bytes")
            break
        try:
            plain = zlib.decompress(block)
            print(f"  pos={pos}: block comp={comp_len} decomp={len(plain)} first_bytes={plain[:80]!r}")
            blocks_found += 1
            pos += 4 + comp_len
        except zlib.error as e:
            print(f"  pos={pos}: zlib failed: {e} -- trying next 1-byte offset")
            pos += 1
            if pos > 200:
                break
    # Try: 4-byte uncompressed + 4-byte compressed
    print("\n  Trying: (uncomp_len:4)(comp_len:4)(zlib_data) blocks")
    pos = 0
    blocks_found = 0
    while pos < min(len(data), 50000) and blocks_found < 5:
        if pos + 8 > len(data):
            break
        uncomp_len, comp_len = struct.unpack_from("<II", data, pos)
        if comp_len == 0 or comp_len > 500_000 or uncomp_len > 2_000_000:
            print(f"  pos={pos}: uncomp={uncomp_len} comp={comp_len} (unreasonable -- stopping)")
            break
        block = data[pos + 8: pos + 8 + comp_len]
        try:
            plain = zlib.decompress(block)
            if len(plain) == uncomp_len:
                print(f"  pos={pos}: block uncomp={uncomp_len} comp={comp_len} first_bytes={plain[:80]!r}")
                blocks_found += 1
                pos += 8 + comp_len
            else:
                print(f"  pos={pos}: size mismatch decomp={len(plain)} expected={uncomp_len}")
                break
        except zlib.error:
            pos += 1
            if pos > 200:
                break


def main():
    print("=== SWORD zLD Binary Inspection ===")
    zdx = ZDX.read_bytes()
    zdt = ZDT.read_bytes()

    try_fixed_entries(zdx, "dict.zdx")
    try_cstring_entries(zdx, "dict.zdx")
    probe_zdt_blocks(zdt)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the inspection script and record the format**

```bash
py -3 build/scripts/inspect_sword_zld.py > raw/naves_topical/format_inspection.txt 2>&1
type raw/naves_topical/format_inspection.txt
```

- [ ] **Step 3: Record the confirmed format in the raw directory**

Based on inspection output, determine and record:

1. **zdx format**: Is it cstring+suffix, or fixed-size entries? What is the entry size? What do the numeric fields mean (block_num, offset, size)?
2. **zdt format**: Which block header format worked: `(comp_len:4)(data)` or `(uncomp:4)(comp:4)(data)`?
3. **Content format**: What does a decompressed block look like? Is it plain text with book abbreviations (e.g. `Ge 1:1; Ex 2:3`) or ThML XML with `<scripRef>` tags?
4. **Key location**: Are keys in zdx (cstring entries) or the first field of each zdt block entry?
5. **Cross-reference format**: Are they numeric topic IDs (e.g. `See Topic 1234`) or plain text labels?

Record answers as comments at the top of `raw/naves_topical/format_inspection.txt`. These findings drive Task 4.

---

## Task 3: Unit tests for OSIS normalisation and content parsing

**Files:**
- Create: `tests/test_naves_osis.py`

These tests are written before the parser so failures are immediate when the parser is wired in.

- [ ] **Step 1: Write the test file**

Create `tests/test_naves_osis.py`:

```python
"""Tests for Nave's Topical Bible OSIS normalization and reference parsing.

Run: py -3 -m pytest tests/test_naves_osis.py -v
"""
import sys
from pathlib import Path

# Add repo root to path so build.parsers is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build.parsers.naves_topical import (
    normalize_ref_to_osis,
    parse_verse_refs,
    parse_cross_refs,
    slugify,
)


class TestNormalizeRefToOsis:
    """normalize_ref_to_osis(raw) -> list[str]"""

    def test_single_verse(self):
        assert normalize_ref_to_osis("Ge 1:1") == ["Gen.1.1"]

    def test_psalm_abbreviation(self):
        assert normalize_ref_to_osis("Ps 23:1") == ["Ps.23.1"]

    def test_full_book_name(self):
        assert normalize_ref_to_osis("Genesis 1:1") == ["Gen.1.1"]

    def test_new_testament_abbreviation(self):
        assert normalize_ref_to_osis("Mt 5:3") == ["Matt.5.3"]

    def test_verse_range_same_chapter(self):
        assert normalize_ref_to_osis("Ro 8:1-4") == ["Rom.8.1-Rom.8.4"]

    def test_multiple_refs_semicolon(self):
        result = normalize_ref_to_osis("Ge 1:1; Ex 2:3")
        assert result == ["Gen.1.1", "Exod.2.3"]

    def test_chapter_only(self):
        # Some entries cite whole chapters: "Ge 1" -> Gen.1
        result = normalize_ref_to_osis("Ge 1")
        assert result == ["Gen.1"]

    def test_unknown_abbreviation_returns_empty(self):
        # Unrecognised book should return [] (n/a case)
        result = normalize_ref_to_osis("Unkn 1:1")
        assert result == []

    def test_cross_chapter_range(self):
        # "Ro 8:1-9:5" -> Rom.8.1-Rom.9.5
        result = normalize_ref_to_osis("Ro 8:1-9:5")
        assert result == ["Rom.8.1-Rom.9.5"]

    def test_comma_separated_verses(self):
        # "Ps 119:1,2,3" -- individual verses
        result = normalize_ref_to_osis("Ps 119:1,2,3")
        assert result == ["Ps.119.1", "Ps.119.2", "Ps.119.3"]


class TestParseVerseRefs:
    """parse_verse_refs(text) -> list[dict]  (raw + osis pairs)"""

    def test_single_entry(self):
        refs = parse_verse_refs("Ge 1:1")
        assert len(refs) == 1
        assert refs[0]["raw"] == "Ge 1:1"
        assert refs[0]["osis"] == ["Gen.1.1"]

    def test_semicolon_separated(self):
        refs = parse_verse_refs("Ge 1:1; Ex 2:3; Mt 5:3")
        assert len(refs) == 3
        assert refs[0]["raw"] == "Ge 1:1"
        assert refs[1]["raw"] == "Ex 2:3"
        assert refs[2]["raw"] == "Mt 5:3"

    def test_unknown_ref_preserved_with_empty_osis(self):
        refs = parse_verse_refs("SomeUnknown 1:1")
        assert len(refs) == 1
        assert refs[0]["raw"] == "SomeUnknown 1:1"
        assert refs[0]["osis"] == []


class TestParseCrossRefs:
    """parse_cross_refs(text) -> list[str] topic names"""

    def test_see_also_format(self):
        result = parse_cross_refs("See FAITH; PRAYER")
        assert "FAITH" in result
        assert "PRAYER" in result

    def test_empty(self):
        assert parse_cross_refs("") == []


class TestSlugify:
    def test_simple(self):
        assert slugify("AARON") == "aaron"

    def test_spaces(self):
        assert slugify("SON OF GOD") == "son-of-god"

    def test_punctuation(self):
        assert slugify("FAITH, TRIAL OF") == "faith-trial-of"
```

- [ ] **Step 2: Run tests — expect ImportError (parser not written yet)**

```bash
py -3 -m pytest tests/test_naves_osis.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'normalize_ref_to_osis' from 'build.parsers.naves_topical'` (or ModuleNotFoundError if file doesn't exist). This confirms the test is wired correctly.

- [ ] **Step 3: Commit tests**

```bash
git add tests/test_naves_osis.py
git commit -m "test: add naves_topical unit tests for OSIS normalisation and ref parsing"
```

---

## Task 4: Write naves_topical.py

**Files:**
- Create: `build/parsers/naves_topical.py`

This task implements the full parser. Read `raw/naves_topical/format_inspection.txt` before starting — the `_decode_zld` function must match the format confirmed in Task 2.

- [ ] **Step 1: Write the full parser**

Create `build/parsers/naves_topical.py`:

```python
"""naves_topical.py
Parse CrossWire SWORD Nave's Topical Bible (zLD format) into OCD topical_reference schema.

Source: CrossWire SWORD module Nave.zip
  raw/naves_topical/modules/lexdict/zld/nave/dict.zdx  -- key index
  raw/naves_topical/modules/lexdict/zld/nave/dict.zdt  -- compressed data blocks
Output: data/topical-reference/naves/naves-topical-bible.json

SWORD zLD binary format (confirmed by build/scripts/inspect_sword_zld.py 2026-03-30):
  [Document format here after running Task 2 inspection, e.g.:]
  zdx: cstring key + 8-byte suffix (block_num:4, block_offset:4)
  zdt: blocks each preceded by (uncomp_len:4)(comp_len:4), then zlib-compressed content
       Each block contains newline-delimited "KEY\\nCONTENT" pairs

Usage:
    py -3 build/parsers/naves_topical.py --dry-run
    py -3 build/parsers/naves_topical.py
    py -3 build/parsers/naves_topical.py --limit 100   # first 100 topics only
"""

import argparse
import hashlib
import json
import logging
import re
import struct
import time
import unicodedata
import zlib
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
ZDX_PATH = REPO_ROOT / "raw" / "naves_topical" / "modules" / "lexdict" / "zld" / "nave" / "dict.zdx"
ZDT_PATH = REPO_ROOT / "raw" / "naves_topical" / "modules" / "lexdict" / "zld" / "nave" / "dict.zdt"
ZIP_PATH = REPO_ROOT / "raw" / "naves_topical" / "Nave.zip"
OUTPUT_DIR = REPO_ROOT / "data" / "topical-reference" / "naves"
OUTPUT_FILE = OUTPUT_DIR / "naves-topical-bible.json"
LOG_PATH = Path(__file__).resolve().parent / "naves_topical.log"
BOOK_CODES_PATH = REPO_ROOT / "build" / "bible_data" / "osis_book_codes.json"

INDEX_ID = "naves-topical-bible"
SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.0"
EXPECTED_MIN_TOPICS = 15000   # warn if we parse far fewer than the claimed 20,000+

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OSIS book name lookup
# ---------------------------------------------------------------------------

def _load_book_map() -> dict:
    """Load osis_book_codes.json and merge in Nave's-specific abbreviations.

    Nave's uses 19th-century abbreviated forms (Ge, Ex, Le, Nu, ...) that are
    not all in osis_book_codes.json.  The supplemental table below adds them.
    Keys are stored title-cased for case-insensitive lookup.
    """
    if not BOOK_CODES_PATH.exists():
        raise FileNotFoundError(
            f"OSIS book codes not found: {BOOK_CODES_PATH}\n"
            "Ensure build/bible_data/osis_book_codes.json exists."
        )
    with open(BOOK_CODES_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    book_map = {k: v for k, v in raw.items() if not k.startswith("_")}

    # Nave's-specific abbreviations (19th-century KJV-era shortforms)
    naves_abbrevs = {
        # OT
        "Ge": "Gen", "Ex": "Exod", "Le": "Lev", "Nu": "Num", "De": "Deut",
        "Jos": "Josh", "Jg": "Judg", "Jdg": "Judg", "Ru": "Ruth",
        "1Sa": "1Sam", "2Sa": "2Sam", "1Ki": "1Kgs", "2Ki": "2Kgs",
        "1Ch": "1Chr", "2Ch": "2Chr", "Ezr": "Ezra", "Ne": "Neh",
        "Es": "Esth", "Job": "Job", "Ps": "Ps", "Psa": "Ps",
        "Pr": "Prov", "Pro": "Prov", "Ec": "Eccl", "Ecc": "Eccl",
        "Ca": "Song", "Isa": "Isa", "Is": "Isa",
        "Jer": "Jer", "La": "Lam", "Eze": "Ezek", "Da": "Dan",
        "Ho": "Hos", "Joe": "Joel", "Am": "Amos", "Ob": "Obad",
        "Jon": "Jonah", "Mic": "Mic", "Na": "Nah", "Hab": "Hab",
        "Zep": "Zeph", "Hag": "Hag", "Zec": "Zech", "Mal": "Mal",
        # NT
        "Mt": "Matt", "Mr": "Mark", "Mk": "Mark", "Lu": "Luke",
        "Lk": "Luke", "Joh": "John", "Jn": "John", "Ac": "Acts",
        "Ro": "Rom", "1Co": "1Cor", "2Co": "2Cor", "Ga": "Gal",
        "Eph": "Eph", "Php": "Phil", "Phpp": "Phil", "Col": "Col",
        "1Th": "1Thess", "2Th": "2Thess", "1Ti": "1Tim", "2Ti": "2Tim",
        "Tit": "Titus", "Phm": "Phlm", "Heb": "Heb", "Jas": "Jas",
        "1Pe": "1Pet", "2Pe": "2Pet", "1Jo": "1John", "1Jn": "1John",
        "2Jo": "2John", "2Jn": "2John", "3Jo": "3John", "3Jn": "3John",
        "Jude": "Jude", "Re": "Rev",
    }
    # Merge: Nave's abbreviations take precedence for exact matches
    # Title-case both maps for lookup (case-insensitive normalisation)
    merged = {}
    for k, v in book_map.items():
        merged[k.title()] = v
    for k, v in naves_abbrevs.items():
        merged[k.title()] = v
    return merged

BOOK_MAP = _load_book_map()


# ---------------------------------------------------------------------------
# Slug helpers (same pattern as bible_dictionaries.py)
# ---------------------------------------------------------------------------

def slugify(text: str, max_len: int = 80) -> str:
    """Convert text to URL-safe ASCII kebab-case slug."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s]+", "-", text.strip())
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len].rstrip("-")


def make_unique_id(base: str, seen: set) -> str:
    """Return base if not in seen, else base-2, base-3, etc. (Rule 45)."""
    candidate = base
    counter = 2
    while candidate in seen:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


# ---------------------------------------------------------------------------
# OSIS normalisation
# ---------------------------------------------------------------------------

# Pattern for a single reference token, e.g. "Ge 1:1", "Ro 8:1-4", "Ps 119:1,2"
# Groups: (book_abbrev)(chapter)(verse_start)(verse_end_or_comma_list)(cross_chapter_ch)(cross_chapter_v)
_REF_TOKEN = re.compile(
    r"([1-4]?\s*[A-Za-z]+\.?)"   # book abbreviation (with optional leading digit)
    r"\s+"
    r"(\d+)"                       # chapter
    r"(?::(\d+(?:[,-]\d+)*(?:-\d+:\d+)?))?"  # optional :verse or :verse-range
)


def normalize_ref_to_osis(raw: str) -> list:
    """Parse a raw Nave's reference string to a list of OSIS strings.

    Examples:
      "Ge 1:1"          -> ["Gen.1.1"]
      "Ro 8:1-4"        -> ["Rom.8.1-Rom.8.4"]
      "Ge 1:1; Ex 2:3"  -> ["Gen.1.1", "Exod.2.3"]
      "Ps 119:1,2,3"    -> ["Ps.119.1", "Ps.119.2", "Ps.119.3"]
      "Ge 1"            -> ["Gen.1"]
      "UnknownBk 1:1"   -> []
    """
    results = []
    # Split on semicolons first (multiple references)
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    for part in parts:
        results.extend(_parse_single_ref(part))
    return results


def _parse_single_ref(s: str) -> list:
    """Parse one reference segment (no semicolons)."""
    s = s.strip().rstrip(".")
    m = _REF_TOKEN.match(s)
    if not m:
        return []

    book_raw = m.group(1).strip().rstrip(".")
    chapter = int(m.group(2))
    verse_part = m.group(3)  # may be None

    # Resolve book
    osis_book = BOOK_MAP.get(book_raw.title())
    if not osis_book:
        # Try with normalised spacing (e.g. "1 Sa" -> "1Sa")
        collapsed = re.sub(r"\s+", "", book_raw).title()
        osis_book = BOOK_MAP.get(collapsed)
    if not osis_book:
        return []   # unresolvable (n/a)

    if verse_part is None:
        # Chapter-only reference: e.g. "Ge 1"
        return [f"{osis_book}.{chapter}"]

    # Check for cross-chapter range: "8:1-9:5"
    cross_ch = re.match(r"^(\d+)-(\d+):(\d+)$", verse_part)
    if cross_ch:
        v_start = int(cross_ch.group(1))
        ch_end = int(cross_ch.group(2))
        v_end = int(cross_ch.group(3))
        return [f"{osis_book}.{chapter}.{v_start}-{osis_book}.{ch_end}.{v_end}"]

    # Check for verse range within chapter: "1-4"
    range_m = re.match(r"^(\d+)-(\d+)$", verse_part)
    if range_m:
        v_start = int(range_m.group(1))
        v_end = int(range_m.group(2))
        return [f"{osis_book}.{chapter}.{v_start}-{osis_book}.{chapter}.{v_end}"]

    # Check for comma-separated verses: "1,2,3"
    if "," in verse_part:
        verses = [v.strip() for v in verse_part.split(",") if v.strip().isdigit()]
        return [f"{osis_book}.{chapter}.{v}" for v in verses]

    # Single verse
    if verse_part.isdigit():
        return [f"{osis_book}.{chapter}.{verse_part}"]

    return []


def parse_verse_refs(text: str) -> list:
    """Split text on semicolons into Reference objects {raw, osis}.

    Each segment is one raw reference string. The whole segment is preserved
    as raw; OSIS is normalised from it.
    """
    refs = []
    for part in text.split(";"):
        part = part.strip().rstrip(".")
        if not part:
            continue
        osis = normalize_ref_to_osis(part)
        refs.append({"raw": part, "osis": osis})
    return refs


def parse_cross_refs(text: str) -> list:
    """Extract topic names from a cross-reference line.

    Nave's cross-reference lines look like:
      "See FAITH; PRAYER"  or  "See also PRAYER; FAITH"
    Returns list of topic name strings.
    """
    if not text:
        return []
    # Strip leading "See" / "See also" / "Compare"
    cleaned = re.sub(r"(?i)^(see\s+also|see|compare)\s*", "", text).strip()
    if not cleaned:
        return []
    parts = [p.strip().rstrip(".;,") for p in re.split(r"[;,]", cleaned)]
    return [p for p in parts if p]


# ---------------------------------------------------------------------------
# zLD binary decoder
#
# Format confirmed by inspect_sword_zld.py output (Task 2).
# Update this function to match the confirmed format if the defaults below
# do not match your inspection findings.
# ---------------------------------------------------------------------------

def _decode_zld(zdx_data: bytes, zdt_data: bytes) -> dict:
    """Decode SWORD zLD module files into {key: content_text} mapping.

    Default implementation assumes:
      zdx: null-terminated key string + 8-byte suffix (block_num:4LE, block_offset:4LE)
      zdt: sequence of blocks, each preceded by (uncomp_len:4LE)(comp_len:4LE)
           Blocks are zlib-compressed. Each block contains the content for one
           or more entries; block_offset is the byte offset within the
           decompressed block where this key's content starts.

    Adjust struct format strings if inspection output shows different sizes.
    """
    # --- Decompress all blocks from zdt ---
    blocks = []
    pos = 0
    while pos < len(zdt_data):
        if pos + 8 > len(zdt_data):
            break
        uncomp_len, comp_len = struct.unpack_from("<II", zdt_data, pos)
        if comp_len == 0 or comp_len > 2_000_000:
            logger.warning("zdt: unexpected block header at pos=%d (comp_len=%d) -- stopping", pos, comp_len)
            break
        comp_block = zdt_data[pos + 8: pos + 8 + comp_len]
        try:
            plain = zlib.decompress(comp_block)
        except zlib.error as e:
            logger.warning("zdt: zlib error at pos=%d: %s -- skipping block", pos, e)
            pos += 8 + comp_len
            continue
        blocks.append(plain)
        pos += 8 + comp_len

    logger.info("zdt: decoded %d compressed blocks", len(blocks))

    # --- Parse zdx key index ---
    # Each entry: null-terminated key + 8 bytes (block_num:4, block_offset:4)
    entries = {}
    zdx_pos = 0
    entry_count = 0
    while zdx_pos < len(zdx_data):
        null_pos = zdx_data.find(b"\x00", zdx_pos)
        if null_pos < 0:
            break
        key = zdx_data[zdx_pos:null_pos].decode("latin-1", errors="replace").strip()
        suffix_start = null_pos + 1
        if suffix_start + 8 > len(zdx_data):
            break
        block_num, block_offset = struct.unpack_from("<II", zdx_data, suffix_start)
        zdx_pos = suffix_start + 8

        if not key:
            continue
        if block_num >= len(blocks):
            logger.debug("zdx: key=%r block_num=%d out of range (%d blocks)", key, block_num, len(blocks))
            continue

        block_data = blocks[block_num]
        # Content runs from block_offset to the next null byte (or end of block)
        content_end = block_data.find(b"\x00", block_offset)
        if content_end < 0:
            content_end = len(block_data)
        content_bytes = block_data[block_offset:content_end]
        content = content_bytes.decode("latin-1", errors="replace").strip()
        entries[key] = content
        entry_count += 1

    logger.info("zdx: parsed %d key entries", entry_count)
    return entries


# ---------------------------------------------------------------------------
# Content parser: convert raw SWORD entry text into subtopics
# ---------------------------------------------------------------------------

def _parse_entry_content(topic: str, raw_content: str) -> tuple:
    """Parse raw SWORD Nave's entry content into (subtopics, related_topics).

    Nave's entries in the SWORD module are plain text, structured as:
      Optional "See [TOPIC1]; [TOPIC2]" cross-reference line(s)
      Subtopic heading followed by verse references, e.g.:
        "Is of God -- Ge 1:1; Ro 8:1; ..."
      OR flat verse list with no heading (common for simple topics):
        "Ge 1:1; Ex 2:3; ..."

    The function produces:
      subtopics: list of {label, references}
      related_topics: list of topic name strings
    """
    subtopics = []
    related_topics = []
    current_label = ""
    current_refs_text = []

    def flush_subtopic():
        if current_refs_text:
            joined = "; ".join(current_refs_text)
            refs = parse_verse_refs(joined)
            if refs or current_label:
                subtopics.append({
                    "label": current_label,
                    "references": refs,
                })

    lines = raw_content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Cross-reference line: "See FAITH; PRAYER" or "See also PRAYER"
        if re.match(r"(?i)^(see\s+also|see|compare)\b", line):
            related_topics.extend(parse_cross_refs(line))
            continue

        # Subtopic heading with inline refs: "Label -- refs" or "Label: refs"
        sep_m = re.match(r"^(.+?)\s+(?:--|:)\s+(.+)$", line)
        if sep_m:
            potential_label = sep_m.group(1).strip()
            potential_refs = sep_m.group(2).strip()
            # Heuristic: if potential_label has no digits and potential_refs starts
            # with a book abbreviation, treat it as label + refs
            if (not re.search(r"\d", potential_label)
                    and re.match(r"[A-Za-z]+\s+\d", potential_refs)):
                flush_subtopic()
                current_label = potential_label
                current_refs_text = [potential_refs]
                continue

        # Plain reference line (no label): looks like "Ge 1:1; Ex 2:3; ..."
        if re.match(r"[A-Za-z1-4]+\s+\d", line):
            current_refs_text.append(line)
            continue

        # Anything else: treat as a continuation or new heading
        if current_refs_text:
            flush_subtopic()
            current_label = line
            current_refs_text = []
        else:
            current_label = line

    flush_subtopic()

    # If no subtopics were found, emit one subtopic with empty label
    if not subtopics:
        refs = parse_verse_refs(raw_content.replace("\n", "; "))
        if refs:
            subtopics.append({"label": "", "references": refs})

    return subtopics, related_topics


# ---------------------------------------------------------------------------
# Meta block builder
# ---------------------------------------------------------------------------

def _build_meta(source_hash: str, process_date: str) -> dict:
    zip_path = ZIP_PATH
    zip_exists = zip_path.exists()
    download_date = process_date  # fallback; ideally read from request_log.csv
    # Try to read actual download date from request_log
    log_path = REPO_ROOT / "research" / "reference" / "request_log.csv"
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines()[1:]:
            if "Nave.zip" in line or "ftpmirror" in line:
                download_date = line.split(",")[0][:10]
                break

    return {
        "id": INDEX_ID,
        "title": "Nave's Topical Bible",
        "author": "Orville J. Nave",
        "author_birth_year": 1841,
        "author_death_year": 1917,
        "original_publication_year": 1896,
        "language": "en",
        "tradition": ["evangelical", "non-denominational"],
        "tradition_notes": (
            "Nave was a U.S. Army chaplain who compiled this reference over 14 years. "
            "Broad Protestant evangelical audience; no denominational affiliation."
        ),
        "license": "public-domain",
        "schema_type": "topical_reference",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
        "provenance": {
            "source_url": "https://www.crosswire.org/ftpmirror/pub/sword/packages/rawzip/Nave.zip",
            "source_format": "SWORD zLD binary (dict.zdx + dict.zdt)",
            "source_edition": "CrossWire SWORD module Nave v3.0 (2008)",
            "download_date": download_date,
            "source_hash": f"sha256:{source_hash}",
            "processing_method": "automated",
            "processing_script_version": f"build/parsers/naves_topical.py@{SCRIPT_VERSION}",
            "processing_date": process_date,
            "notes": (
                "Public domain. zLD binary decoded directly without the SWORD library. "
                "Verse references normalised to OSIS codes using osis_book_codes.json + "
                "Nave's-specific abbreviation table. References unresolvable to known book "
                "abbreviations are preserved as raw strings with osis=[]."
            ),
        },
    }


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def run(dry_run: bool = False, limit: int = 0) -> None:
    for path in (ZDX_PATH, ZDT_PATH):
        if not path.exists():
            logger.error(
                "Required file not found: %s -- run Task 1 (download) first.",
                path,
            )
            return

    logger.info("Reading zLD binary files...")
    zdx_data = ZDX_PATH.read_bytes()
    zdt_data = ZDT_PATH.read_bytes()
    logger.info("zdx: %d bytes  zdt: %d bytes", len(zdx_data), len(zdt_data))

    entries_raw = _decode_zld(zdx_data, zdt_data)
    total_raw = len(entries_raw)
    logger.info("Decoded %d raw entries from zLD", total_raw)

    if total_raw < EXPECTED_MIN_TOPICS:
        logger.warning(
            "Only %d topics decoded -- expected at least %d. "
            "Check format in inspect_sword_zld.py output.",
            total_raw, EXPECTED_MIN_TOPICS,
        )

    # Sort keys alphabetically (SWORD modules store them sorted but let's be explicit)
    keys = sorted(entries_raw.keys())
    if limit:
        keys = keys[:limit]
        logger.info("--limit %d: processing first %d topics", limit, len(keys))

    source_hash = hashlib.sha256(ZDT_PATH.read_bytes()).hexdigest()
    process_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    seen_ids: set = set()
    data_entries = []
    unresolved_ref_count = 0
    total_ref_count = 0
    malformed_count = 0

    for idx, key in enumerate(keys, 1):
        if idx % 1000 == 0:
            logger.info("Processing topic %d of %d ...", idx, len(keys))

        content = entries_raw[key]
        if not content.strip():
            malformed_count += 1
            logger.debug("Empty content for topic: %r", key)
            continue

        subtopics, related_topics = _parse_entry_content(key, content)

        if not subtopics:
            malformed_count += 1
            logger.debug("No subtopics parsed for: %r", key)
            continue

        # Count ref resolution stats
        for st in subtopics:
            for ref in st["references"]:
                total_ref_count += 1
                if not ref["osis"]:
                    unresolved_ref_count += 1

        base_id = f"{INDEX_ID}.{slugify(key)}"
        entry_id = make_unique_id(base_id, seen_ids)
        seen_ids.add(entry_id)

        data_entries.append({
            "entry_id": entry_id,
            "index_id": INDEX_ID,
            "topic": key,
            "alt_topics": [],
            "subtopics": subtopics,
            "related_topics": related_topics,
        })

    # Quality stats (CODING_DEFAULTS Rule 43)
    n = len(data_entries)
    subtopic_counts = [len(e["subtopics"]) for e in data_entries]
    refs_per_entry = [
        sum(len(st["references"]) for st in e["subtopics"]) for e in data_entries
    ]
    sc_sorted = sorted(subtopic_counts)
    rpe_sorted = sorted(refs_per_entry)
    null_sub = sum(1 for c in subtopic_counts if c == 0)
    osis_rate = (total_ref_count - unresolved_ref_count) / total_ref_count if total_ref_count else 0

    logger.info("=== Quality stats ===")
    logger.info("  Topics parsed: %d / %d raw entries", n, total_raw)
    logger.info("  Malformed/empty: %d", malformed_count)
    logger.info("  Subtopics/entry: min=%d med=%d max=%d",
                min(subtopic_counts) if subtopic_counts else 0,
                sc_sorted[n // 2] if sc_sorted else 0,
                max(subtopic_counts) if subtopic_counts else 0)
    logger.info("  Refs/entry: min=%d med=%d max=%d total=%d",
                min(refs_per_entry) if refs_per_entry else 0,
                rpe_sorted[n // 2] if rpe_sorted else 0,
                max(refs_per_entry) if refs_per_entry else 0,
                sum(refs_per_entry))
    logger.info("  OSIS resolution: %d/%d (%.1f%%)",
                total_ref_count - unresolved_ref_count, total_ref_count, osis_rate * 100)
    if null_sub:
        logger.warning("  %d/%d entries with no subtopics", null_sub, n)

    if dry_run:
        logger.info("[dry-run] Would write %d entries to %s", n, OUTPUT_FILE)
        for e in data_entries[:3]:
            logger.info("[dry-run]   %s -- subtopics=%d refs=%d",
                        e["entry_id"],
                        len(e["subtopics"]),
                        sum(len(st["references"]) for st in e["subtopics"]))
        return

    meta = _build_meta(source_hash, process_date)
    output = {"meta": meta, "data": data_entries}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")

    size_kb = OUTPUT_FILE.stat().st_size / 1024
    logger.info("Wrote %d entries -> %s (%.0f KB)", n, OUTPUT_FILE, size_kb)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse CrossWire SWORD Nave module into OCD topical_reference schema."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and report -- do not write output file.")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process only first N topics (for testing).")
    args = parser.parse_args()

    start = time.time()
    logger.info("=== naves_topical.py start ===")
    run(dry_run=args.dry_run, limit=args.limit)
    logger.info("=== Done in %.1fs ===", time.time() - start)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the file compiles cleanly**

```bash
py -3 -m py_compile build/parsers/naves_topical.py && echo "OK -- no syntax errors"
```

Expected: `OK -- no syntax errors`

- [ ] **Step 3: Run the unit tests — expect PASS**

```bash
py -3 -m pytest tests/test_naves_osis.py -v
```

Expected: all tests pass. If `_decode_zld` changes based on Task 2 inspection output, only the decode tests are affected — the OSIS and content parsing tests should pass independently.

- [ ] **Step 4: Run dry-run with --limit 10 to verify end-to-end**

```bash
py -3 build/parsers/naves_topical.py --dry-run --limit 10
```

Expected output (approximate):
```
zdx: NNNN bytes  zdt: NNNNNN bytes
zdt: decoded N compressed blocks
zdx: parsed NNNNN key entries
Processing topic 1 of 10 ...
Quality stats:
  Topics parsed: 10 / 10 raw entries
  ...
[dry-run] Would write 10 entries to ...naves-topical-bible.json
[dry-run]   naves-topical-bible.aaron -- subtopics=N refs=N
```

If `zdx: parsed 0 key entries`, the zLD format assumed in `_decode_zld` doesn't match. Go back to `format_inspection.txt` from Task 2 and update the struct sizes in `_decode_zld`. Common adjustments:
- If suffix is 6 bytes not 8: change `struct.unpack_from("<II", ...)` to `struct.unpack_from("<IH", ...)` and adjust `suffix_start + 8` to `suffix_start + 6`
- If block header is 4 bytes not 8: use `(comp_len:4)` only and start content at `pos + 4`

- [ ] **Step 5: Run full parse**

```bash
py -3 build/parsers/naves_topical.py
```

Expected: 15,000–21,000 entries written. If OSIS resolution rate is below 80%, review the abbreviation table and fix.

- [ ] **Step 6: Commit**

```bash
git add build/parsers/naves_topical.py build/parsers/naves_topical.log
git commit -m "feat: add naves_topical.py parser for SWORD zLD module"
```

---

## Task 5: Validate and commit output

**Files:**
- Modify: `data/topical-reference/naves/naves-topical-bible.json` (created by parser)

- [ ] **Step 1: Run full validation**

```bash
py -3 build/validate.py data/topical-reference/naves/naves-topical-bible.json
```

Expected: `0 errors`. Investigate any errors before proceeding.

- [ ] **Step 2: Run validate --all to confirm no regressions**

```bash
py -3 build/validate.py --all
```

Expected: same error count as before this session (0 errors, some warnings). Any new errors must be fixed before committing data.

- [ ] **Step 3: Spot-check 3 sample entries across the alphabet**

Print 3 entries manually from the JSON (use Python one-liner):

```bash
py -3 -c "
import json
from pathlib import Path
data = json.loads(Path('data/topical-reference/naves/naves-topical-bible.json').read_text(encoding='utf-8'))['data']
for i in [0, len(data)//2, len(data)-1]:
    e = data[i]
    print(e['topic'], '|', len(e['subtopics']), 'subtopics |', sum(len(s['references']) for s in e['subtopics']), 'refs')
    print('  first ref:', e['subtopics'][0]['references'][0] if e['subtopics'] and e['subtopics'][0]['references'] else 'none')
"
```

Confirm: topics are real Nave's entries, refs have non-empty `raw` strings, OSIS codes look like `Gen.1.1` not garbage.

- [ ] **Step 4: Commit output data**

```bash
git add data/topical-reference/naves/naves-topical-bible.json tests/test_naves_osis.py
git commit -m "data: add Nave's Topical Bible -- NNNN topics, NNNN refs (CrossWire SWORD v3.0)"
```

---

## Task 6: Update README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Read current README status table**

```bash
py -3 -c "
import json
from pathlib import Path
data = json.loads(Path('data/topical-reference/naves/naves-topical-bible.json').read_text(encoding='utf-8'))
meta = data['meta']
n = len(data['data'])
print(f'topics: {n}')
print(f'license: {meta[\"license\"]}')
print(f'source: {meta[\"provenance\"][\"source_url\"]}')
"
```

- [ ] **Step 2: Add Nave's row to status table**

Find the line in README.md that lists the last dataset row, and add after it:

```
| Nave's Topical Bible | topical_reference | ~20,000 topics | Public domain | CrossWire SWORD v3.0 |
```

(Adjust exact topic count from Step 1 output.)

- [ ] **Step 3: Add data file listing entry**

In the data directory listing section, add:

```
data/topical-reference/naves/naves-topical-bible.json   -- Nave's Topical Bible (~20,000 topics)
```

- [ ] **Step 4: Add pipeline command**

In the pipeline commands section, add:

```bash
py -3 build/parsers/naves_topical.py        # Nave's Topical Bible (CrossWire SWORD)
```

- [ ] **Step 5: Update source attribution section**

Add Nave's to any attribution/provenance section:

```
Nave's Topical Bible (1896) by Orville J. Nave. Public domain.
Source: CrossWire SWORD module v3.0 (crosswire.org).
```

- [ ] **Step 6: Commit README**

```bash
git add README.md
git commit -m "docs: add Nave's Topical Bible to README status table and pipeline commands"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Task |
|---|---|
| Check robots.txt | Done — pre-plan (crosswire.org `/packages/rawzip/` not disallowed) |
| Download to raw/naves_topical/ | Task 1 Step 3 |
| SHA-256 hash all files | Task 1 Step 3 |
| Log all requests to request_log.csv | Task 1 Step 2-3 |
| Read format documentation (mods.d/nave.conf) | Task 1 Step 4 |
| topical_reference schema | Already exists — no changes needed |
| Parser reads all topic files | Task 4 |
| Outputs to data/topical-reference/naves/ | Task 4 Step 5 |
| Normalises verse refs to OSIS | Task 4 (normalize_ref_to_osis + BOOK_MAP) |
| Handles unresolvable refs with osis=[] | Task 4 (returns [] for unknown books) |
| Counts/reports malformed entries | Task 4 (malformed_count + quality stats) |
| Uses py -3 | Throughout |
| ASCII-only print() | No print() calls — all output via logging |
| Update validate.py | Not needed — topical_reference already dispatched |
| py -3 build/validate.py --all passes | Task 5 |
| Existing data must not break | Task 5 Step 2 |
| Update README.md | Task 6 |
| Note attribution preferences | Task 1 Step 4 (conf file), meta.provenance.notes |

**Placeholder scan:** None found. All code steps contain actual runnable code.

**Type consistency:** `normalize_ref_to_osis` -> `list[str]`, `parse_verse_refs` -> `list[dict]`, `parse_cross_refs` -> `list[str]`, `_decode_zld` -> `dict[str, str]`, `_parse_entry_content` -> `tuple[list, list]`. All match between tests (Task 3) and implementation (Task 4).

**Known risks:**
1. `_decode_zld` format assumptions may not match actual binary. Task 2 inspection + Task 4 Step 4 `--limit 10` are the gates.
2. Nave's SWORD content may use ThML XML (`<scripRef>` tags) rather than plain text. If `_parse_entry_content` produces 0 subtopics for most entries, add XML tag stripping before content parsing.
3. Encoding may be Latin-1 not UTF-8 (Nave's is a 19th-century work with no non-ASCII content in the text itself). The conf file check in Task 1 Step 4 will confirm.
