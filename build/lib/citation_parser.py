"""build/lib/citation_parser.py
Utilities for parsing biblical citation strings into OSIS book codes.

OSIS book codes follow the standard used in build/validate.py KNOWN_BOOK_NUMBERS.
"""

# Maps normalised input (stripped of trailing period, lowercased) -> OSIS code.
# Covers abbreviations observed in WSC proof texts plus common full names.
BOOK_ABBREVIATIONS: dict[str, str] = {
    # Genesis
    "gen": "Gen",
    "genesis": "Gen",
    # Exodus
    "ex": "Exod",
    "exo": "Exod",
    "exod": "Exod",
    "exodus": "Exod",
    # Leviticus
    "lev": "Lev",
    "leviticus": "Lev",
    # Numbers
    "num": "Num",
    "numbers": "Num",
    # Deuteronomy
    "deut": "Deut",
    "deu": "Deut",
    "deuteronomy": "Deut",
    # Joshua
    "josh": "Josh",
    "joshua": "Josh",
    # Judges
    "judg": "Judg",
    "judges": "Judg",
    # Ruth
    "ruth": "Ruth",
    # 1 Samuel
    "1 sam": "1Sam",
    "1sam": "1Sam",
    "1 samuel": "1Sam",
    # 2 Samuel
    "2 sam": "2Sam",
    "2sam": "2Sam",
    "2 samuel": "2Sam",
    # 1 Kings
    "1 kgs": "1Kgs",
    "1kgs": "1Kgs",
    "1 kings": "1Kgs",
    # 2 Kings
    "2 kgs": "2Kgs",
    "2kgs": "2Kgs",
    "2 kings": "2Kgs",
    # 1 Chronicles
    "1 chr": "1Chr",
    "1chr": "1Chr",
    "1 chron": "1Chr",
    "1chron": "1Chr",
    "1 chronicles": "1Chr",
    # 2 Chronicles
    "2 chr": "2Chr",
    "2chr": "2Chr",
    "2 chron": "2Chr",
    "2chron": "2Chr",
    "2 chronicles": "2Chr",
    # Ezra
    "ezra": "Ezra",
    # Nehemiah
    "neh": "Neh",
    "nehemiah": "Neh",
    # Esther
    "esth": "Esth",
    "esther": "Esth",
    # Job
    "job": "Job",
    # Psalms
    "ps": "Ps",
    "psa": "Ps",
    "psalm": "Ps",
    "psalms": "Ps",
    # Proverbs
    "prov": "Prov",
    "proverbs": "Prov",
    # Ecclesiastes
    "ecc": "Eccl",
    "eccl": "Eccl",
    "eccle": "Eccl",
    "ecclesiastes": "Eccl",
    # Song of Solomon / Song of Songs
    "song": "Song",
    "ss": "Song",
    "songs": "Song",
    # Isaiah
    "isa": "Isa",
    "isaiah": "Isa",
    # Jeremiah
    "jer": "Jer",
    "jeremiah": "Jer",
    # Lamentations
    "lam": "Lam",
    "lamentations": "Lam",
    # Ezekiel
    "ezek": "Ezek",
    "ezekiel": "Ezek",
    # Daniel
    "dan": "Dan",
    "daniel": "Dan",
    # Hosea
    "hos": "Hos",
    "hosea": "Hos",
    # Joel
    "joel": "Joel",
    # Amos
    "amos": "Amos",
    # Obadiah
    "obad": "Obad",
    "obadiah": "Obad",
    # Jonah
    "jonah": "Jonah",
    # Micah
    "mic": "Mic",
    "micah": "Mic",
    # Nahum
    "nah": "Nah",
    "nahum": "Nah",
    # Habakkuk
    "hab": "Hab",
    "habakkuk": "Hab",
    # Zephaniah
    "zeph": "Zeph",
    "zephaniah": "Zeph",
    # Haggai
    "hag": "Hag",
    "haggai": "Hag",
    # Zechariah
    "zech": "Zech",
    "zechariah": "Zech",
    # Malachi
    "mal": "Mal",
    "malachi": "Mal",
    # Matthew
    "matt": "Matt",
    "mat": "Matt",
    "matthew": "Matt",
    # Mark
    "mark": "Mark",
    # Luke
    "luke": "Luke",
    # John
    "john": "John",
    # Acts
    "acts": "Acts",
    # Romans
    "rom": "Rom",
    "romans": "Rom",
    # 1 Corinthians
    "1 cor": "1Cor",
    "1cor": "1Cor",
    "1 corinthians": "1Cor",
    # 2 Corinthians
    "2 cor": "2Cor",
    "2cor": "2Cor",
    "2 corinthians": "2Cor",
    # Galatians
    "gal": "Gal",
    "galatians": "Gal",
    # Ephesians
    "eph": "Eph",
    "ephesians": "Eph",
    # Philippians
    "phil": "Phil",
    "philippians": "Phil",
    # Colossians
    "col": "Col",
    "colossians": "Col",
    # 1 Thessalonians
    "1 thess": "1Thess",
    "1thess": "1Thess",
    "1 thessalonians": "1Thess",
    # 2 Thessalonians
    "2 thess": "2Thess",
    "2thess": "2Thess",
    "2 thessalonians": "2Thess",
    # 1 Timothy
    "1 tim": "1Tim",
    "1tim": "1Tim",
    "1 timothy": "1Tim",
    # 2 Timothy
    "2 tim": "2Tim",
    "2tim": "2Tim",
    "2 timothy": "2Tim",
    # Titus
    "titus": "Titus",
    "tit": "Titus",
    # Philemon
    "phlm": "Phlm",
    "philemon": "Phlm",
    # Hebrews
    "heb": "Heb",
    "hebrews": "Heb",
    # James
    "jas": "Jas",
    "james": "Jas",
    # 1 Peter
    "1 pet": "1Pet",
    "1pet": "1Pet",
    "1 peter": "1Pet",
    # 2 Peter
    "2 pet": "2Pet",
    "2pet": "2Pet",
    "2 peter": "2Pet",
    # 1 John
    "1 john": "1John",
    "1john": "1John",
    # 2 John
    "2 john": "2John",
    "2john": "2John",
    # 3 John
    "3 john": "3John",
    "3john": "3John",
    # Jude
    "jude": "Jude",
    # Revelation
    "rev": "Rev",
    "revelation": "Rev",
}


def lookup_book(abbrev: str) -> str | None:
    """Return the OSIS book code for a raw abbreviation, or None if not found.

    Handles:
    - Trailing periods (stripped before lookup)
    - Numbered book prefixes with a space (e.g. "1 Cor." -> "1Cor")
    - Full book names (e.g. "Romans" -> "Rom")
    - Case-insensitive matching

    Args:
        abbrev: Raw abbreviation string, e.g. "1 Cor.", "Gen", "Romans".

    Returns:
        OSIS book code string (e.g. "1Cor", "Gen", "Rom"), or None if unknown.
    """
    if not abbrev:
        return None
    # Strip trailing period(s) and surrounding whitespace
    normalised = abbrev.strip().rstrip(".").strip().lower()
    return BOOK_ABBREVIATIONS.get(normalised)


def _extract_book_and_remainder(ref: str) -> tuple[str, str]:
    """Extract the book abbreviation token and the remaining chapter/verse string.

    Strategy: consume tokens from the front while they look like part of a book
    name (optional digit prefix, word characters, optional trailing period).
    Stop when the next token starts with a digit that represents chapter/verse
    data (i.e. after we already have at least one word token for the book name).

    Returns:
        (osis_book_code, remainder_string) where remainder is the chapter:verse
        portion (e.g. "11:36" or "1").

    Raises:
        ValueError: if no valid book can be identified.
    """
    import re

    s = ref.strip()

    # Try increasingly longer prefixes to find the longest matching book token.
    # A book token is: optional "N " prefix + word(s) + optional period(s).
    # We walk through the string position by position looking for where the
    # chapter number begins.

    best_book: str | None = None
    best_end: int = 0

    # Pattern for one "word" in a book name: letters only, optional trailing dot
    word_pat = re.compile(r'[A-Za-z]+\.?')

    # Optional leading digit prefix like "1 " or "2 "
    num_prefix_pat = re.compile(r'^(\d)\s+')

    pos = 0
    candidate = ""

    m = num_prefix_pat.match(s)
    if m:
        candidate = m.group(0)  # e.g. "1 "
        pos = m.end()

    # Consume word tokens and test each as a book abbreviation
    while pos < len(s):
        wm = word_pat.match(s, pos)
        if not wm:
            break
        candidate += wm.group(0)
        pos = wm.end()

        code = lookup_book(candidate.strip())
        if code is not None:
            best_book = code
            best_end = pos

        # Skip a single space after the word if more word tokens might follow
        if pos < len(s) and s[pos] == ' ':
            # Peek: if next char is a digit it's chapter data, stop consuming
            if pos + 1 < len(s) and s[pos + 1].isdigit():
                break
            candidate += ' '
            pos += 1

    if best_book is None:
        raise ValueError(f"Could not identify book in reference: {ref!r}")

    remainder = s[best_end:].strip()
    return best_book, remainder


def _parse_verse_token(token: str) -> str | None:
    """Parse a single verse token which may be a range ('25-28') or plain int.

    Returns a range string like '25-28' or a plain string like '25', or None
    if the token is empty.
    """
    token = token.strip()
    if not token:
        return None
    return token  # keep as-is; caller formats with book/chapter


def _build_osis_entries(book: str, chapter: str, verse_portion: str) -> list[str]:
    """Convert a chapter + verse portion string into a list of OSIS ref strings.

    verse_portion examples:
        ""          -> chapter-only ref: ["Gen.1"]
        "36"        -> ["Rom.11.36"]
        "25-28"     -> ["Ps.73.25-Ps.73.28"]
        "4,11"      -> ["Eph.1.4", "Eph.1.11"]
        "1-2, 7, 9" -> ["Ps.51.1-Ps.51.2", "Ps.51.7", "Ps.51.9"]
        "42, 46-47" -> ["Acts.2.42", "Acts.2.46-Acts.2.47"]
    """
    if not verse_portion:
        # Chapter-only reference
        return [f"{book}.{chapter}"]

    entries: list[str] = []
    parts = [p.strip() for p in verse_portion.split(',')]
    for part in parts:
        if not part:
            continue
        if '-' in part:
            v1, v2 = part.split('-', 1)
            v1, v2 = v1.strip(), v2.strip()
            entries.append(f"{book}.{chapter}.{v1}-{book}.{chapter}.{v2}")
        else:
            entries.append(f"{book}.{chapter}.{part}")
    return entries


def parse_single_reference(ref: str) -> dict:
    """Parse a single biblical reference string into an OSIS reference dict.

    Handles:
    - Simple verse: "Rom. 11:36"
    - Verse range: "Ps. 73:25-28"
    - Comma-separated verses: "Eph. 1:4,11"
    - Chapter-only: "Gen. 1"
    - Numbered books: "1 Cor. 10:31"
    - Mixed range+list: "Ps. 51:1-2, 7, 9"

    Args:
        ref: Raw reference string.

    Returns:
        dict with keys:
            "raw": stripped original input
            "osis": list of OSIS reference strings
    """
    raw = ref.strip()
    book, remainder = _extract_book_and_remainder(raw)

    if ':' in remainder:
        chapter, verse_portion = remainder.split(':', 1)
        chapter = chapter.strip()
        verse_portion = verse_portion.strip()
    else:
        chapter = remainder.strip()
        verse_portion = ""

    osis_list = _build_osis_entries(book, chapter, verse_portion)
    return {"raw": raw, "osis": osis_list}


def parse_citation_string(citation: str) -> list[dict]:
    """Parse a full citation string containing multiple references.

    Handles:
    - Semicolon-separated refs: "Rom. 11:36; Ps. 73:25-28."
    - Trailing period on entire string
    - 'with' conjunction as a separator: "Gen. 17:10 with Col. 2:11-12"

    Args:
        citation: Raw citation string from HTML proof text.

    Returns:
        List of reference dicts as returned by parse_single_reference().
    """
    # Strip trailing period from the whole string
    s = citation.strip().rstrip('.')

    # Normalise ' with ' conjunction to semicolon separator
    s = s.replace(' with ', '; ')

    # Split on semicolons
    parts = [p.strip() for p in s.split(';')]

    results = []
    for part in parts:
        if part:
            results.append(parse_single_reference(part))
    return results
