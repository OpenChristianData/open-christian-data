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
