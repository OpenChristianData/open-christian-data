"""bible_ref_normalizer.py
Parse human-readable ThML scripture-reference strings into OSIS verse refs.

Used by sword_commentary.py to populate cross_references for Barnes (passage=
attribute format) and Wesley (text-content format) SWORD commentary modules.

Public API:
    parse_thml_refs(passage_str: str) -> list[str]

Example:
    parse_thml_refs('Lev 4:3, 6:20, Ex 28:41, 29:7')
    -> ['Lev.4.3', 'Lev.6.20', 'Exod.28.41', 'Exod.29.7']
"""

import logging
import re

# ---------------------------------------------------------------------------
# Book abbreviation lookup  (abbreviation -> canonical OSIS code)
# ---------------------------------------------------------------------------
# Covers all 66 canonical books with common abbreviations, full names, and
# known OCR/transcription typos present in Barnes and Wesley SWORD modules.
# Lookup is case-insensitive (keys are lowercase).
#
# OSIS codes derived from sword_commentary.OSIS_TO_NAME (source of truth).
# Range behaviour: start verse only (deliberate trade-off -- expanding all
# verses in a range would add complexity with minimal query-path benefit).

_BOOK_LOOKUP_RAW = {
    # ------------------------------------------------------------------ OT
    # Genesis
    "gen": "Gen", "genesis": "Gen",
    # Exodus  (typo: 'Ex' -> 'Exod')
    "exod": "Exod", "exodus": "Exod", "ex": "Exod",
    # Leviticus
    "lev": "Lev", "leviticus": "Lev",
    # Numbers
    "num": "Num", "numbers": "Num", "numb": "Num",
    # Deuteronomy
    "deut": "Deut", "deuteronomy": "Deut", "deu": "Deut", "dt": "Deut",
    # Joshua
    "josh": "Josh", "joshua": "Josh", "jos": "Josh",
    # Judges
    "judg": "Judg", "judges": "Judg", "jdg": "Judg",
    # Ruth
    "ruth": "Ruth", "rut": "Ruth",
    # 1 Samuel
    "1sam": "1Sam", "1samuel": "1Sam", "1sa": "1Sam",
    # 2 Samuel
    "2sam": "2Sam", "2samuel": "2Sam", "2sa": "2Sam",
    # 1 Kings  (typo: '1Kings' -> '1Kgs')
    "1kgs": "1Kgs", "1kings": "1Kgs", "1kin": "1Kgs", "1ki": "1Kgs",
    # 2 Kings  (typo: '2Kings' -> '2Kgs')
    "2kgs": "2Kgs", "2kings": "2Kgs", "2kin": "2Kgs", "2ki": "2Kgs",
    # 1 Chronicles  (typo: '1Chron' -> '1Chr')
    "1chr": "1Chr", "1chronicles": "1Chr", "1chron": "1Chr", "1ch": "1Chr",
    # 2 Chronicles  (typo: '2Chron' -> '2Chr')
    "2chr": "2Chr", "2chronicles": "2Chr", "2chron": "2Chr", "2ch": "2Chr",
    # Ezra
    "ezra": "Ezra", "ezr": "Ezra",
    # Nehemiah
    "neh": "Neh", "nehemiah": "Neh",
    # Esther
    "esth": "Esth", "esther": "Esth", "est": "Esth",
    # Job
    "job": "Job",
    # Psalms  (OSIS code is 'Ps', not 'Psa')
    "ps": "Ps", "psalms": "Ps", "psalm": "Ps", "psa": "Ps",
    # Proverbs
    "prov": "Prov", "proverbs": "Prov", "pro": "Prov", "prv": "Prov",
    # Ecclesiastes
    "eccl": "Eccl", "ecclesiastes": "Eccl", "ecc": "Eccl",
    # Song of Solomon  (OSIS code is 'Song', NOT 'SongOfSol')
    "song": "Song", "songofsolomon": "Song", "sos": "Song",
    "cant": "Song", "canticles": "Song",
    # Isaiah  ('Is' is a common abbreviation in older commentary sources)
    "isa": "Isa", "isaiah": "Isa", "is": "Isa",
    # Jeremiah
    "jer": "Jer", "jeremiah": "Jer",
    # Lamentations
    "lam": "Lam", "lamentations": "Lam",
    # Ezekiel  (typo: 'Eze' -> 'Ezek')
    "ezek": "Ezek", "ezekiel": "Ezek", "eze": "Ezek",
    # Daniel
    "dan": "Dan", "daniel": "Dan",
    # Hosea
    "hos": "Hos", "hosea": "Hos",
    # Joel
    "joel": "Joel",
    # Amos
    "amos": "Amos", "am": "Amos",
    # Obadiah
    "obad": "Obad", "obadiah": "Obad", "oba": "Obad", "ob": "Obad",
    # Jonah  (distinct from 'Jon' which some use for 1John -- we don't add 'Jon')
    "jonah": "Jonah",
    # Micah
    "mic": "Mic", "micah": "Mic",
    # Nahum
    "nah": "Nah", "nahum": "Nah",
    # Habakkuk
    "hab": "Hab", "habakkuk": "Hab",
    # Zephaniah
    "zeph": "Zeph", "zephaniah": "Zeph", "zep": "Zeph",
    # Haggai
    "hag": "Hag", "haggai": "Hag",
    # Zechariah
    "zech": "Zech", "zechariah": "Zech", "zec": "Zech",
    # Malachi
    "mal": "Mal", "malachi": "Mal",
    # ------------------------------------------------------------------ NT
    # Matthew
    "matt": "Matt", "matthew": "Matt", "mat": "Matt", "mt": "Matt",
    # Mark
    "mark": "Mark", "mk": "Mark", "mar": "Mark",
    # Luke
    "luke": "Luke", "luk": "Luke", "lk": "Luke",
    # John  (use 'jn' / 'john' only -- 'jon' reserved for Jonah)
    "john": "John", "jhn": "John", "jn": "John",
    # Acts
    "acts": "Acts", "act": "Acts",
    # Romans
    "rom": "Rom", "romans": "Rom",
    # 1 Corinthians
    "1cor": "1Cor", "1corinthians": "1Cor", "1co": "1Cor",
    # 2 Corinthians
    "2cor": "2Cor", "2corinthians": "2Cor", "2co": "2Cor",
    # Galatians
    "gal": "Gal", "galatians": "Gal",
    # Ephesians
    "eph": "Eph", "ephesians": "Eph",
    # Philippians
    "phil": "Phil", "philippians": "Phil",
    # Colossians
    "col": "Col", "colossians": "Col",
    # 1 Thessalonians  (typo: '1Thes' -> '1Thess')
    "1thess": "1Thess", "1thessalonians": "1Thess", "1thes": "1Thess", "1th": "1Thess",
    # 2 Thessalonians  (typo: '2Thes' -> '2Thess')
    "2thess": "2Thess", "2thessalonians": "2Thess", "2thes": "2Thess", "2th": "2Thess",
    # 1 Timothy  (typo: '1Timm' -> '1Tim')
    "1tim": "1Tim", "1timothy": "1Tim", "1ti": "1Tim", "1timm": "1Tim",
    # 2 Timothy
    "2tim": "2Tim", "2timothy": "2Tim", "2ti": "2Tim",
    # Titus
    "titus": "Titus", "tit": "Titus",
    # Philemon
    "phlm": "Phlm", "philemon": "Phlm", "phm": "Phlm", "phile": "Phlm",
    # Hebrews
    "heb": "Heb", "hebrews": "Heb",
    # James
    "jas": "Jas", "james": "Jas", "jam": "Jas",
    # 1 Peter
    "1pet": "1Pet", "1peter": "1Pet", "1pe": "1Pet", "1pt": "1Pet",
    # 2 Peter
    "2pet": "2Pet", "2peter": "2Pet", "2pe": "2Pet", "2pt": "2Pet",
    # 1 John
    "1john": "1John", "1jhn": "1John", "1jn": "1John",
    # 2 John
    "2john": "2John", "2jhn": "2John", "2jn": "2John",
    # 3 John
    "3john": "3John", "3jhn": "3John", "3jn": "3John",
    # Jude
    "jude": "Jude", "jud": "Jude",
    # Revelation
    "rev": "Rev", "revelation": "Rev", "apocalypse": "Rev",
}

# Build final lookup (lowercase -> OSIS code)
_BOOK_LOOKUP: dict[str, str] = {k.lower(): v for k, v in _BOOK_LOOKUP_RAW.items()}

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# Token that starts with a book name, followed by chapter:verse (possibly a range).
# Group 1 = book abbreviation (e.g. '1Sam', 'Isaiah')
# Group 2 = chapter:verse portion (e.g. '14:24', '14:24-27')
_BOOK_REF_RE = re.compile(
    r"^(\d?\s*[A-Za-z]+)\s+(\d+:\d+(?:-\d+)?)$",
)

# Bare chapter:verse token (no book name), possibly a range.
# Group 1 = chapter, group 2 = verse (start of range if present).
_BARE_CHAP_VERSE_RE = re.compile(r"^(\d+):(\d+)(?:-\d+)?$")

# Bare verse-number token (continuation of current chapter), no colon.
_BARE_VERSE_RE = re.compile(r"^(\d+)$")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_thml_refs(passage_str: str) -> list[str]:
    """
    Parse a human-readable ThML passage string into a list of OSIS verse refs.

    Returns [] for strings that cannot be parsed (logs a warning per token).
    Skips partial refs that have no prior book context.
    For verse ranges (e.g. '14:24-27'), returns the start verse only.

    Examples:
        'Lev 4:3, 6:20, Ex 28:41, 29:7'
            -> ['Lev.4.3', 'Lev.6.20', 'Exod.28.41', 'Exod.29.7']
        'Dan 2:44; 7:13,14'
            -> ['Dan.2.44', 'Dan.7.13', 'Dan.7.14']
        '1Timm 3:2'
            -> ['1Tim.3.2']
        '25:41'              (no prior book context)  -> []
        ''                                            -> []
    """
    if not passage_str or not passage_str.strip():
        return []

    results: list[str] = []
    current_book: str | None = None   # OSIS code of last seen book
    current_chapter: int | None = None  # chapter number from last ch:v token

    # Split on ; first to get ref groups, then , within each group.
    # current_book persists across groups so bare ch:v/verse tokens work:
    #   'Dan 2:44; 7:13,14' -> group 1 sets book=Dan; group 2 uses it.
    groups = passage_str.split(";")
    for group in groups:
        tokens = group.split(",")
        for raw_token in tokens:
            token = raw_token.strip()
            if not token:
                continue

            # --- Case 1: token starts with a book name ---
            m = _BOOK_REF_RE.match(token)
            if m:
                book_raw = m.group(1).strip()
                # Remove any internal whitespace (e.g. '1 Sam' -> '1Sam')
                book_key = re.sub(r"\s+", "", book_raw).lower()
                osis_book = _BOOK_LOOKUP.get(book_key)
                if not osis_book:
                    logging.warning(
                        "bible_ref_normalizer: unknown book '%s' in '%s' -- skipping",
                        book_raw, passage_str,
                    )
                    continue
                chap_verse = m.group(2)
                chap_str, verse_str = chap_verse.split(":")
                verse_str = verse_str.split("-")[0]  # range -> start verse only
                try:
                    chapter = int(chap_str)
                    verse = int(verse_str)
                except ValueError:
                    logging.warning(
                        "bible_ref_normalizer: could not parse ch:v from '%s' -- skipping",
                        token,
                    )
                    continue
                current_book = osis_book
                current_chapter = chapter
                results.append(f"{osis_book}.{chapter}.{verse}")
                continue

            # --- Case 2: bare ch:v token (e.g. '6:20', '7:13-14') ---
            m2 = _BARE_CHAP_VERSE_RE.match(token)
            if m2:
                if current_book is None:
                    logging.warning(
                        "bible_ref_normalizer: bare ref '%s' has no prior book context"
                        " in '%s' -- skipping",
                        token, passage_str,
                    )
                    continue
                chapter = int(m2.group(1))
                verse = int(m2.group(2))  # already strips range end via regex group
                current_chapter = chapter
                results.append(f"{current_book}.{chapter}.{verse}")
                continue

            # --- Case 3: bare verse number (continuation of current chapter) ---
            m3 = _BARE_VERSE_RE.match(token)
            if m3:
                if current_book is None or current_chapter is None:
                    logging.warning(
                        "bible_ref_normalizer: bare verse '%s' has no prior"
                        " book/chapter context in '%s' -- skipping",
                        token, passage_str,
                    )
                    continue
                verse = int(m3.group(1))
                results.append(f"{current_book}.{current_chapter}.{verse}")
                continue

            # --- No pattern matched ---
            logging.warning(
                "bible_ref_normalizer: could not parse token '%s' in '%s' -- skipping",
                token, passage_str,
            )

    return results
