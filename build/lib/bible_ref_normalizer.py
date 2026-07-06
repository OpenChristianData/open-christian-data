"""bible_ref_normalizer.py
Parse human-readable ThML scripture-reference strings into OSIS verse refs.

Used by sword_commentary.py to populate cross_references for Barnes (passage=
attribute format) and Wesley (text-content format) SWORD commentary modules.
Also used by helloao_commentary.py via extract_refs_from_text() to extract
cross-references from plain commentary text.

Public API:
    parse_thml_refs(passage_str: str) -> list[str]
    extract_refs_from_text(text: str) -> list[str]

Example:
    parse_thml_refs('Lev 4:3, 6:20, Ex 28:41, 29:7')
    -> ['Lev.4.3', 'Lev.6.20', 'Exod.28.41', 'Exod.29.7']

    extract_refs_from_text('See Pe2 3:5 and Sa1 17:4 for context.')
    -> ['2Pet.3.5', '1Sam.17.4']

Source data quirks (confirmed by grepping all Barnes + Wesley scripRef tags):
  - Verse suffix:    'John 3:16a'      -> suffix stripped, emits 'John.3.16'
  - Dot separator:        'Mt 15.28'        -> normalised to 'Mt 15:28' pre-parse
  - Verse continuation:   'De 32:11.12'     -> chapter=32, verse=11 (.12 dropped)
  - Semicolon-as-colon:   'Jn 12;4'         -> normalised to 'Jn 12:4' pre-parse
  - Chapter-only:         'Mt 4', 'Ps 102'  -> skipped (no verse, can't emit OSIS)
  - Range (verse):        '1Sam 14:24-27'   -> start verse only (deliberate trade-off)
  - HelloAO digit-after:  'Sa1 17:4'        -> digit follows abbreviation, not precedes
  - 179+ distinct abbreviations found in corpus; _BOOK_LOOKUP covers all known forms
    but may be extended as new corpus abbreviations are discovered.
"""

import logging
import re

# Library module — do not configure a root handler here; callers are responsible.
# This NullHandler prevents "No handlers could be found" warnings when this module
# is imported by scripts that haven't yet called logging.basicConfig().
logging.getLogger(__name__).addHandler(logging.NullHandler())

# ---------------------------------------------------------------------------
# Book abbreviation lookup  (abbreviation -> canonical OSIS code)
# ---------------------------------------------------------------------------
# Built from probing ALL scripRef tags across Barnes + Wesley SWORD modules
# (179+ distinct forms found). Covers:
#   - All 66 canonical OSIS codes
#   - Full book names
#   - All abbreviated forms actually present in the corpus
#   - Known OCR/transcription typos (e.g. 'Actsts', 'Hen' for 'Heb')
# Lookup is case-insensitive (keys are lowercase).
#
# NOT included: deuterocanonical books (1Macc etc.) -- out of scope per spec.

_BOOK_LOOKUP_RAW = {
    # ------------------------------------------------------------------ OT
    # Genesis
    "gen": "Gen", "genesis": "Gen", "ge": "Gen", "genn": "Gen",
    # Exodus  (typo: 'Ex' / 'Exo' -> 'Exod')
    "exod": "Exod", "exodus": "Exod", "ex": "Exod", "exo": "Exod",
    # Leviticus  ('Le' is a rare HelloAO short form; included per spec)
    "lev": "Lev", "leviticus": "Lev", "levit": "Lev", "levv": "Lev", "le": "Lev",
    # Numbers  ('Nu' / 'Numb' are common short forms)
    "num": "Num", "numbers": "Num", "numb": "Num", "nu": "Num",
    # Deuteronomy  ('De' / 'Deu' / 'Dt' all appear in corpus)
    "deut": "Deut", "deuteronomy": "Deut", "deu": "Deut", "de": "Deut", "dt": "Deut",
    # Joshua
    "josh": "Josh", "joshua": "Josh", "jos": "Josh",
    # Judges
    # 'Jud' defaults to Judges (not Jude): Jude is a single-chapter book so any
    # 'Jud X:Y' with X > 1 is certainly Judges; commentary authors overwhelmingly
    # use 'Jud' for Judges. Full 'Jude' is used when Jude is intended.
    "judg": "Judg", "judges": "Judg", "jdg": "Judg", "jud": "Judg",
    # Ruth
    "ruth": "Ruth", "rut": "Ruth", "ru": "Ruth",
    # 1 Samuel
    "1sam": "1Sam", "1samuel": "1Sam", "1sa": "1Sam",
    # 2 Samuel
    "2sam": "2Sam", "2samuel": "2Sam", "2sa": "2Sam",
    # 1 Kings  (typos: '1Kings' / '1Kin' / '1Ki' -> '1Kgs')
    "1kgs": "1Kgs", "1kings": "1Kgs", "1kin": "1Kgs", "1ki": "1Kgs",
    # 2 Kings  (typos: '2Kings' / '2Kin' / '2Ki' -> '2Kgs')
    "2kgs": "2Kgs", "2kings": "2Kgs", "2kin": "2Kgs", "2ki": "2Kgs",
    # 1 Chronicles  (typos: '1Chron' / '1Ch' -> '1Chr')
    "1chr": "1Chr", "1chronicles": "1Chr", "1chron": "1Chr", "1ch": "1Chr",
    # 2 Chronicles  (typos: '2Chron' / '2Ch' -> '2Chr')
    "2chr": "2Chr", "2chronicles": "2Chr", "2chron": "2Chr", "2ch": "2Chr",
    # Ezra
    "ezra": "Ezra", "ezr": "Ezra",
    # Nehemiah  (typos: 'Nehh' / 'Nehem' / 'Ne' -> 'Neh')
    "neh": "Neh", "nehemiah": "Neh", "nehh": "Neh", "nehem": "Neh", "ne": "Neh",
    # Esther
    "esth": "Esth", "esther": "Esth", "est": "Esth", "es": "Esth",
    # Job
    "job": "Job",
    # Psalms  (OSIS code is 'Ps', NOT 'Psa')
    "ps": "Ps", "psalms": "Ps", "psalm": "Ps", "psa": "Ps", "psal": "Ps",
    # Proverbs  (typo: 'Provo' -> 'Prov'; 'Pr' is a rare HelloAO short form)
    "prov": "Prov", "proverbs": "Prov", "pro": "Prov", "prv": "Prov", "provo": "Prov",
    "pr": "Prov",
    # Ecclesiastes  ('Ec' / 'Eccles' are short forms in corpus)
    "eccl": "Eccl", "ecclesiastes": "Eccl", "ecc": "Eccl", "ec": "Eccl",
    "eccles": "Eccl",
    # Song of Solomon  (OSIS code is 'Song', NOT 'SongOfSol')
    # 'So' used by Wesley ('So 1:15' etc.)
    "song": "Song", "songofsolomon": "Song", "sos": "Song",
    "cant": "Song", "canticles": "Song", "so": "Song", "ca": "Song",
    # Isaiah  ('Is' / 'Isai' appear in corpus)
    "isa": "Isa", "isaiah": "Isa", "is": "Isa", "isai": "Isa",
    # Jeremiah  ('Je' appears once)
    "jer": "Jer", "jeremiah": "Jer", "je": "Jer",
    # Lamentations
    "lam": "Lam", "lamentations": "Lam", "la": "Lam",
    # Ezekiel  (typo: 'Eze' -> 'Ezek')
    "ezek": "Ezek", "ezekiel": "Ezek", "eze": "Ezek",
    # Daniel  ('Da' appears in corpus)
    "dan": "Dan", "daniel": "Dan", "da": "Dan",
    # Hosea  (typo: 'Hoss' -> 'Hos')
    "hos": "Hos", "hosea": "Hos", "hoss": "Hos", "ho": "Hos",
    # Joel  (typo: 'Joell' -> 'Joel')
    "joel": "Joel", "joell": "Joel",
    # Amos
    "amos": "Amos", "am": "Amos",
    # Obadiah
    "obad": "Obad", "obadiah": "Obad", "oba": "Obad", "ob": "Obad",
    # Jonah  ('Jon' appears in corpus and unambiguously means Jonah here)
    "jonah": "Jonah", "jon": "Jonah",
    # Micah  ('Mi' appears in corpus)
    "mic": "Mic", "micah": "Mic", "mi": "Mic",
    # Nahum  (typos: 'Nahh' -> 'Nah')
    "nah": "Nah", "nahum": "Nah", "nahh": "Nah", "na": "Nah",
    # Habakkuk  ('habbakkuk' is a source typo found in Maclaren Expositions)
    "hab": "Hab", "habakkuk": "Hab", "habbakkuk": "Hab",
    # Zephaniah
    "zeph": "Zeph", "zephaniah": "Zeph", "zep": "Zeph",
    # Haggai
    "hag": "Hag", "haggai": "Hag",
    # Zechariah
    "zech": "Zech", "zechariah": "Zech", "zec": "Zech",
    # Malachi
    "mal": "Mal", "malachi": "Mal",
    # ------------------------------------------------------------------ NT
    # Matthew  ('Mt' is the dominant form in corpus)
    "matt": "Matt", "matthew": "Matt", "mat": "Matt", "mt": "Matt",
    # Mark  ('Mk' / 'Mr' / 'Mar' appear in corpus)
    "mark": "Mark", "mk": "Mark", "mar": "Mark", "mr": "Mark",
    # Luke  ('Lk' / 'Lu' / 'Lkke' appear in corpus)
    "luke": "Luke", "luk": "Luke", "lk": "Luke", "lu": "Luke", "lkke": "Luke",
    # John  ('Jn' / 'Joh' / 'Jnn' appear in corpus)
    "john": "John", "jhn": "John", "jn": "John", "joh": "John", "jnn": "John",
    # Acts  ('Ac' / 'Actst' / 'Actsts' appear in corpus; 'Actsts' is an OCR artifact)
    "acts": "Acts", "act": "Acts", "ac": "Acts", "actst": "Acts", "actsts": "Acts",
    # Romans  ('Ro' / 'Romm' appear in corpus)
    "rom": "Rom", "romans": "Rom", "ro": "Rom", "romm": "Rom",
    # 1 Corinthians
    "1cor": "1Cor", "1corinthians": "1Cor", "1co": "1Cor",
    # 2 Corinthians
    "2cor": "2Cor", "2corinthians": "2Cor", "2co": "2Cor",
    # Galatians  ('Ga' appears once)
    "gal": "Gal", "galatians": "Gal", "ga": "Gal", "gall": "Gal",
    # Ephesians  ('Ep' / 'Eph' both appear)
    "eph": "Eph", "ephesians": "Eph", "ep": "Eph",
    # Philippians  ('Php' / 'Phi' are common short forms; 'Ph' appears once)
    "phil": "Phil", "philippians": "Phil", "php": "Phil", "phi": "Phil", "ph": "Phil",
    # Colossians  ('co' used in Wesley/Barnes, e.g. 'Co 1:15' means Colossians)
    "col": "Col", "colossians": "Col", "co": "Col",
    # 1 Thessalonians  (typos: '1Thes' -> '1Thess')
    "1thess": "1Thess", "1thessalonians": "1Thess", "1thes": "1Thess", "1th": "1Thess",
    # 2 Thessalonians  (typos: '2Thes' -> '2Thess')
    "2thess": "2Thess", "2thessalonians": "2Thess", "2thes": "2Thess", "2th": "2Thess",
    # 1 Timothy  (typos: '1Timm' -> '1Tim')
    "1tim": "1Tim", "1timothy": "1Tim", "1ti": "1Tim", "1timm": "1Tim",
    # 2 Timothy
    "2tim": "2Tim", "2timothy": "2Tim", "2ti": "2Tim",
    # Titus
    "titus": "Titus", "tit": "Titus",
    # Philemon  ('Phm' appears in corpus)
    "phlm": "Phlm", "philemon": "Phlm", "phm": "Phlm", "phile": "Phlm",
    # Hebrews  ('He' appears in corpus — unambiguous inside scripRef tags)
    # 'Hen' is likely an OCR artifact for 'Heb' (b/n confusion in scan)
    "heb": "Heb", "hebrews": "Heb", "he": "Heb", "hen": "Heb",
    # James
    "jas": "Jas", "james": "Jas", "jam": "Jas",
    # 1 Peter
    "1pet": "1Pet", "1peter": "1Pet", "1pe": "1Pet", "1pt": "1Pet",
    # 2 Peter
    "2pet": "2Pet", "2peter": "2Pet", "2pe": "2Pet", "2pt": "2Pet",
    # 1 John  ('1Jo' / '1Jn' both appear in corpus)
    "1john": "1John", "1jhn": "1John", "1jn": "1John", "1jo": "1John", "1joh": "1John",
    # 2 John  ('2Jo' appears in corpus)
    "2john": "2John", "2jhn": "2John", "2jn": "2John", "2jo": "2John",
    # 3 John
    "3john": "3John", "3jhn": "3John", "3jn": "3John", "3jo": "3John",
    # Jude  (use full 'Jude' only; bare 'jud' is mapped to Judges above)
    "jude": "Jude",
    # Revelation  ('Revv' typo and 're' short form appear in corpus)
    "rev": "Rev", "revelation": "Rev", "apocalypse": "Rev", "revv": "Rev", "re": "Rev",
    # -------------------------------------------------------------- HelloAO
    # HelloAO uses digit-AFTER-abbreviation for numbered books (e.g. 'Sa1', 'Kg2').
    # These map to the same OSIS codes as the digit-prefix forms above.
    # Neh and Ezr already covered above; Sol/Plm/Jde/Joe/Amo/Zac are alias additions.
    # Joe/Amo/Zac: HelloAO standard abbreviations not covered by the existing table.
    "joe": "Joel",   # HelloAO: Joel (avoids collision with 'joel' already present)
    "amo": "Amos",   # HelloAO: Amos ('am' already present; 'amo' is the full HelloAO form)
    "zac": "Zech",   # HelloAO: Zechariah ('zec' already present; 'zac' is the HelloAO form)
    "sa1": "1Sam", "sa2": "2Sam",
    "kg1": "1Kgs", "kg2": "2Kgs",
    "ch1": "1Chr", "ch2": "2Chr",
    "co1": "1Cor", "co2": "2Cor",
    "th1": "1Thess", "th2": "2Thess",
    "ti1": "1Tim", "ti2": "2Tim",
    "pe1": "1Pet", "pe2": "2Pet",
    "jo1": "1John", "jo2": "2John", "jo3": "3John",
    "sol": "Song",   # HelloAO abbreviation for Song of Solomon
    "plm": "Phlm",   # HelloAO abbreviation for Philemon
    "jde": "Jude",   # HelloAO abbreviation for Jude
}

# Build final lookup (lowercase -> OSIS code, internal spaces stripped)
_BOOK_LOOKUP: dict[str, str] = {
    re.sub(r"\s+", "", k).lower(): v
    for k, v in _BOOK_LOOKUP_RAW.items()
}

# ---------------------------------------------------------------------------
# Pre-normalization patterns
# ---------------------------------------------------------------------------

# Semicolon used as chapter:verse separator: 'Jn 12;4' -> 'Jn 12:4'
# Only fires when digit after ';' is NOT followed by letters (i.e. it's a verse
# number, not a book name like '2Kgs').
_SEMI_AS_CHV_RE = re.compile(r";(\d+)(?!\s*[A-Za-z])")

# Dot used as chapter.verse separator: 'Mt 15.28' -> 'Mt 15:28'
# Lookbehind requires a space (i.e. the digits follow a book name),
# leaving verse-continuation dots like '11.12' in '32:11.12' untouched.
_DOT_SEP_RE = re.compile(r"(?<=\s)(\d+)\.(\d+)")

# Space after colon: 'Heb 10: 5' -> 'Heb 10:5'
_SPACE_AFTER_COLON_RE = re.compile(r":\s+(\d)")

# ---------------------------------------------------------------------------
# Token-matching patterns
# ---------------------------------------------------------------------------

# Token that starts with a book name, followed by chapter:verse.
# Allows:
#   - Simple:           '14:24'
#   - Verse range:      '14:24-27'
#   - Verse cont.:      '32:11.12'
#   - Cross-chap range: '24:1-25:27'  (start verse taken, end discarded)
# Group 1 = book abbreviation (e.g. '1Sam', 'Isaiah', 'Sa1', 'Pe2')
# Group 2 = chapter:verse portion
# The trailing \d? in group 1 handles HelloAO digit-after format (Sa1, Kg2 etc.)
_BOOK_REF_RE = re.compile(
    r"^(\d?\s*[A-Za-z]+\d?)\s+(\d+:\d+[a-z]?(?:[-.](?:\d+:)?\d+)?)$",
)

# Book + chapter-only token (no verse): e.g. 'Ps 29', 'Mt 4', 'Sa1 17'.
# No ref is emitted, but context is updated so subsequent bare ch:v tokens work.
# Group 1 = book abbreviation, Group 2 = chapter number.
_BOOK_CHAP_ONLY_RE = re.compile(r"^(\d?\s*[A-Za-z]+\d?)\s+(\d+)$")

# Bare chapter:verse token (no book name), with optional range/continuation.
_BARE_CHAP_VERSE_RE = re.compile(r"^(\d+):(\d+)(?:[-.](?:\d+:)?\d+)?$")

# Bare verse-range token (e.g. '7-9', '29-32') -- continuation using current
# book and chapter; only the start verse is emitted.
_BARE_VERSE_RANGE_RE = re.compile(r"^(\d+)-\d+$")

# Bare verse-number token (continuation of current chapter).
_BARE_VERSE_RE = re.compile(r"^(\d+)$")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_thml_refs(passage_str: str) -> list[str]:
    """
    Parse a human-readable ThML passage string into a list of OSIS verse refs.

    Returns [] for strings that cannot be parsed (logs a warning per token).
    Skips partial refs that have no prior book context.
    Chapter-only refs (e.g. 'Ps 29') update book/chapter context but emit no ref.
    For verse ranges or verse continuations (e.g. '14:24-27', '32:11.12'),
    returns the start/first verse only (deliberate trade-off).

    Examples:
        'Lev 4:3, 6:20, Ex 28:41, 29:7'
            -> ['Lev.4.3', 'Lev.6.20', 'Exod.28.41', 'Exod.29.7']
        'Dan 2:44; 7:13,14'
            -> ['Dan.2.44', 'Dan.7.13', 'Dan.7.14']
        'Mt 15.28'              (dot separator)       -> ['Matt.15.28']
        'Jn 12;4'               (semi-as-colon)       -> ['John.12.4']
        'De 32:11.12, Ps 91:4'  (verse continuation)  -> ['Deut.32.11', 'Ps.91.4']
        '1Timm 3:2'             (typo)                -> ['1Tim.3.2']
        '25:41'                 (no prior context)    -> []
        ''                                            -> []
    """
    if not passage_str or not passage_str.strip():
        return []

    # --- Pre-normalise unusual separators ---
    # 1. Semicolon used as chapter:verse separator ('Jn 12;4' -> 'Jn 12:4')
    passage_str = _SEMI_AS_CHV_RE.sub(r":\1", passage_str)
    # 2. Dot used as chapter.verse separator ('Mt 15.28' -> 'Mt 15:28')
    passage_str = _DOT_SEP_RE.sub(r"\1:\2", passage_str)
    # 3. Space after colon ('Heb 10: 5' -> 'Heb 10:5')
    passage_str = _SPACE_AFTER_COLON_RE.sub(r":\1", passage_str)

    results: list[str] = []
    current_book: str | None = None   # OSIS code of last seen book
    current_chapter: int | None = None  # chapter from last ch:v token

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
                book_key = re.sub(r"\s+", "", book_raw).lower()
                osis_book = _BOOK_LOOKUP.get(book_key)
                if not osis_book:
                    logging.warning(
                        "bible_ref_normalizer: unknown book '%s' in '%s' -- skipping"
                        " (add to _BOOK_LOOKUP_RAW in bible_ref_normalizer.py to fix)",
                        book_raw, passage_str,
                    )
                    # Clear stale context so subsequent bare ch:v tokens don't
                    # fabricate refs against the previous book.
                    current_book = None
                    current_chapter = None
                    continue
                chap_verse = m.group(2)
                chap_str, verse_raw = chap_verse.split(":", 1)
                # Strip range end or verse continuation (.N): '24-27' -> '24', '11.12' -> '11'
                verse_str = re.split(r"[-.]", verse_raw)[0]
                verse_str = verse_str.rstrip("abcdefghijklmnopqrstuvwxyz")  # half-verse suffix
                try:
                    chapter = int(chap_str)
                    verse = int(verse_str)
                except ValueError:
                    logging.warning(
                        "bible_ref_normalizer: could not parse ch:v from '%s' -- skipping",
                        token,
                    )
                    # Clear stale context so subsequent bare ch:v tokens don't
                    # fabricate refs against the previous book.
                    current_book = None
                    current_chapter = None
                    continue
                current_book = osis_book
                current_chapter = chapter
                results.append(f"{osis_book}.{chapter}.{verse}")
                continue

            # --- Case 1b: book+chapter-only token (e.g. 'Ps 29', 'Mt 4') ---
            # No verse specified — cannot emit a ref, but MUST update context
            # so subsequent bare ch:v tokens like '104:3' use the right book.
            m1b = _BOOK_CHAP_ONLY_RE.match(token)
            if m1b:
                book_raw = m1b.group(1).strip()
                book_key = re.sub(r"\s+", "", book_raw).lower()
                osis_book = _BOOK_LOOKUP.get(book_key)
                if osis_book:
                    current_book = osis_book
                    current_chapter = int(m1b.group(2))
                else:
                    logging.warning(
                        "bible_ref_normalizer: unknown book '%s' in chapter-only"
                        " token '%s' -- clearing context",
                        book_raw, token,
                    )
                    current_book = None
                    current_chapter = None
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
                verse = int(m2.group(2))
                current_chapter = chapter
                results.append(f"{current_book}.{chapter}.{verse}")
                continue

            # --- Case 3: bare verse range (e.g. '7-9', '29-32') ---
            # Uses current_book + current_chapter; start verse only.
            m3r = _BARE_VERSE_RANGE_RE.match(token)
            if m3r:
                if current_book is None or current_chapter is None:
                    logging.warning(
                        "bible_ref_normalizer: bare verse range '%s' has no prior"
                        " book/chapter context in '%s' -- skipping",
                        token, passage_str,
                    )
                    continue
                verse = int(m3r.group(1))
                results.append(f"{current_book}.{current_chapter}.{verse}")
                continue

            # --- Case 4: bare verse number (continuation of current chapter) ---
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

            # --- No pattern matched (chapter-only like 'Mt 4', or unrecognised) ---
            logging.warning(
                "bible_ref_normalizer: could not parse token '%s' in '%s' -- skipping",
                token, passage_str,
            )

    return results


# ---------------------------------------------------------------------------
# Plain-text reference extraction  (HelloAO commentary text)
# ---------------------------------------------------------------------------

# Matches scripture citations in plain commentary text, e.g.:
#   'Luk 1:2'   'Exo 20:9-11'   'Pe2 3:5'   'Sa1 17:4'   'Psa 8:1-9'
#   'Genesis 12:3'  'gen 12:3'  'Revelation 22:17'  'Luke 1:2'
#   '1Cor 10:1'  '1 Cor 10:1'  '2 Timothy 2:15'   '1 Samuel 17:4'
# Pattern allows an optional leading digit so numbered-book abbreviations in
# digit-prefix form (1Cor, 2Pet, 1 Sam) are captured. The optional \s* after
# the digit covers '1 Cor' (digit-space-abbreviation). The _BOOK_LOOKUP table
# strips internal whitespace via re.sub(r"\s+","",key).lower() so '1 cor'
# resolves the same as '1cor'. Case-insensitive to catch lowercase abbreviations.
# Unknown abbreviations are silently dropped by parse_thml_refs() lookup.
_TEXT_REF_RE = re.compile(r"\b(\d?\s*[A-Za-z][A-Za-z]+\d?)\s+(\d+:\d+(?:-\d+)?)\b")


def extract_refs_from_text(text: str) -> list[str]:
    """Extract OSIS cross-references from plain commentary text.

    Scans for scripture citation patterns in commentary text, including:
    - HelloAO abbreviated forms: 'Luk 1:2', 'Exo 20:9-11', 'Pe2 3:5'
    - Lowercase abbreviations: 'gen 12:3', 'luk 1:2', 'psa 8:1'
    - Full book names: 'Genesis 12:3', 'Luke 1:2', 'Revelation 22:17'

    Normalizes to OSIS format via _BOOK_LOOKUP. Unknown abbreviations are
    silently skipped. Deduplicates preserving first-seen order.

    Returns [] for empty input or text with no recognisable citations.
    """
    if not text:
        return []
    seen: set[str] = set()
    results: list[str] = []
    for m in _TEXT_REF_RE.finditer(text):
        ref_str = f"{m.group(1)} {m.group(2)}"
        for ref in parse_thml_refs(ref_str):
            if ref not in seen:
                seen.add(ref)
                results.append(ref)
    return results


# ---------------------------------------------------------------------------
# Maclaren Expositions Roman-numeral chapter parser
# ---------------------------------------------------------------------------
# Maclaren's Expositions of Holy Scripture uses Roman-numeral chapters:
#   "GENESIS xii. 6, 7"              -> ['Gen.12.6', 'Gen.12.7']
#   "ACTS xiii. 44-52; xiv. 1-7"    -> ['Acts.13.44', 'Acts.14.1']
#   "JER. x. 16, R.V"               -> ['Jer.10.16']
#
# Strategy: pre-process the raw string into parse_thml_refs-compatible format
# (book OSIS_code arabic_chapter:verse_list), then delegate to parse_thml_refs.
#
# Source quirks handled here:
#   - Roman-numeral chapters:     'GENESIS xii. 6, 7'
#   - Comma chapter separator:    'ACTS xi, 24'
#   - No-space chained periods:   'MATT.xxii.34-46'
#   - R.V. / R. V annotation:     'JER. x. 16, R.V'
#   - Trailing .-- junk:          'ISAIAH liv, 10.--'
#   - Saint prefix:               'ST. MATT. xxvii. 11-26'
#   - Cross-chapter Roman range:  'GENESIS i. 26-ii. 3'  (start verse only)
#   - Semicolon multi-segment:    'ACTS xiii. 44-52; xiv. 1-7'
#   - Arabic chapter (outlier):   'ISAIAH 1,1-9; 16-20'

# Strip trailing "R.V." / "R.V" / "R. V" annotation (with optional leading comma).
_MAC_RV_RE = re.compile(r",?\s*R\.?\s*V\.?\s*$", re.IGNORECASE)
# Strip trailing ".--.." / "--" junk.
_MAC_DASH_RE = re.compile(r"\.?-+\s*$")
# Strip trailing orphan comma or period.
_MAC_TRAIL_RE = re.compile(r"[,.]\s*$")
# Strip "ST." saint prefix before the book name.
_MAC_SAINT_RE = re.compile(r"^ST\.\s*", re.IGNORECASE)

# Match a Maclaren segment that begins with a book name:
#   Group 1: optional single-digit book prefix (e.g. '1' in '1 Peter')
#   Group 2: book name letters (letters only; trailing period handled by \.? below)
#   Group 3: chapter -- Roman numeral letters OR Arabic digits
#   Group 4: verse list (the remainder of the segment)
_MAC_BOOK_CHAP_RE = re.compile(
    r"^"
    r"(?:(\d)\s*)?"                         # g1: optional digit prefix
    r"([A-Za-z]+)"                          # g2: book name letters
    r"\.?"                                  # optional trailing period in abbreviation
    r"[.,]?\s*"                             # separator between book and chapter
    r"([ivxlcdmIVXLCDM]+|\d+)"             # g3: chapter (Roman or Arabic)
    r"[.,]?\s*"                             # separator between chapter and verse list
    r"(.+)$"                                # g4: verse list
)

# Match a Maclaren segment that begins directly with a Roman-numeral chapter
# (no book name -- book carries over from the previous semicolon segment):
#   Group 1: Roman-numeral chapter
#   Group 2: verse list
_MAC_CHAP_ONLY_RE = re.compile(
    r"^([ivxlcdmIVXLCDM]+)\s*[.,]?\s*(.+)$",
    re.IGNORECASE,
)

# Matches a Roman-numeral chapter reference embedded in a verse list, e.g.
# "ii. 3" in "26-ii. 3" (cross-chapter range end).  Replaced with "2:3".
_MAC_ROMAN_IN_VERSE_RE = re.compile(r"\b([ivxlcdm]+)\.\s*(\d+)", re.IGNORECASE)

# Roman numeral value table (covers Bible chapter range i..cl = 1..150).
_ROMAN_VALUES: dict[str, int] = {
    "i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000,
}


# Verse-part cleanup patterns (applied in _clean_maclaren_verse_part).
# Colon-space-digit: e.g. '1-11: 17-20' -> '1-11; 17-20'  (treat as range separator)
_MAC_COLON_SEP_RE = re.compile(r":\s+(\d)")
# Period-space-digit: e.g. '4. 6. 7' -> '4, 6, 7'  (treat as verse list separator)
_MAC_DOT_SEP_RE = re.compile(r"\.\s+(\d)")
# 'and' as verse separator: e.g. '26 and 29' -> '26, 29'
_MAC_AND_SEP_RE = re.compile(r"\s+and\s+", re.IGNORECASE)


def _roman_to_int(s: str) -> int:
    """Convert a Roman numeral string to an integer (subtractive notation)."""
    result = 0
    prev = 0
    for ch in reversed(s.lower()):
        curr = _ROMAN_VALUES.get(ch, 0)
        if curr < prev:
            result -= curr
        else:
            result += curr
        prev = curr
    return result


def _mac_roman_in_verse_sub(m: "re.Match[str]") -> str:
    """Callback for _MAC_ROMAN_IN_VERSE_RE: replace 'ii. 3' with '2:3'."""
    return f"{_roman_to_int(m.group(1))}:{m.group(2)}"


def _clean_maclaren_verse_part(verse_part: str) -> str:
    """
    Normalise the verse-list portion of a Maclaren ref for parse_thml_refs.

    Applies in order:
    1. Convert Roman-numeral chapter refs in range ends ('ii. 3' -> '2:3').
    2. Normalise 'and' as a verse separator ('26 and 29' -> '26, 29').
    3. Normalise '. N' as a verse separator ('4. 6. 7' -> '4, 6, 7').
    4. Normalise ': N' as a range-group separator ('1-11: 17-20' -> '1-11; 17-20').
       (Only fires when a space follows the colon, so embedded 'ch:v' refs are safe.)
    """
    # Step 1: Roman-numeral chapter refs in cross-chapter ranges
    verse_part = _MAC_ROMAN_IN_VERSE_RE.sub(_mac_roman_in_verse_sub, verse_part)
    # Step 2: 'and' as verse separator
    verse_part = _MAC_AND_SEP_RE.sub(", ", verse_part)
    # Step 3: period-space-digit as verse separator
    verse_part = _MAC_DOT_SEP_RE.sub(r", \1", verse_part)
    # Step 4: colon-space-digit as range-group separator (becomes '; digit')
    verse_part = _MAC_COLON_SEP_RE.sub(r"; \1", verse_part)
    return verse_part


def parse_maclaren_ref(raw: str) -> list[str]:
    """
    Parse a Maclaren Expositions primary_reference.raw string into OSIS verse refs.

    Maclaren's Expositions of Holy Scripture (15 PG volumes) uses Roman-numeral
    chapters.  This function normalises the raw string to the format expected by
    parse_thml_refs, then delegates to it for verse-level parsing.

    Examples:
        'GENESIS xii. 6, 7'              -> ['Gen.12.6', 'Gen.12.7']
        'ACTS xiii. 44-52; xiv. 1-7'    -> ['Acts.13.44', 'Acts.14.1']
        'JER. x. 16, R.V'               -> ['Jer.10.16']
        'ISAIAH 1,1-9; 16-20'           -> ['Isa.1.1', 'Isa.1.16']
        ''                               -> []
    """
    if not raw or not raw.strip():
        return []

    s = raw.strip()

    # --- Strip "Saint" prefix (e.g. "ST. MATT." -> "MATT.") ---
    s = _MAC_SAINT_RE.sub("", s)

    # --- Strip trailing noise (order matters: RV before dashes before comma) ---
    s = _MAC_RV_RE.sub("", s)
    s = _MAC_DASH_RE.sub("", s)
    s = _MAC_TRAIL_RE.sub("", s)
    s = s.strip()

    if not s:
        return []

    # --- Split into semicolon-separated segments ---
    segments = [seg.strip() for seg in s.split(";")]

    current_book: str | None = None   # OSIS code, carries across segments
    normalized_parts: list[str] = []

    for seg in segments:
        if not seg:
            continue

        # --- Try: segment begins with a book name ---
        m = _MAC_BOOK_CHAP_RE.match(seg)
        if m:
            digit_prefix = m.group(1) or ""
            book_letters = m.group(2)
            chapter_str = m.group(3)
            verse_part = m.group(4).strip()

            # Build lookup key: strip dots, lowercase, prepend any digit prefix.
            book_key = (digit_prefix + book_letters).lower()
            osis_book = _BOOK_LOOKUP.get(book_key)

            if osis_book:
                # Convert chapter to Arabic.
                try:
                    chapter = int(chapter_str)
                except ValueError:
                    chapter = _roman_to_int(chapter_str)

                verse_part = _clean_maclaren_verse_part(verse_part)
                current_book = osis_book
                normalized_parts.append(f"{osis_book} {chapter}:{verse_part}")
                continue

            # Book key not in _BOOK_LOOKUP -- log and fall through.
            logging.warning(
                "parse_maclaren_ref: unknown book '%s' in '%s' --"
                " add to _BOOK_LOOKUP_RAW in bible_ref_normalizer.py to fix",
                book_letters, raw,
            )

        # --- Try: segment is a Roman chapter only (continues previous book) ---
        m2 = _MAC_CHAP_ONLY_RE.match(seg)
        if m2 and current_book:
            chapter = _roman_to_int(m2.group(1))
            verse_part = _clean_maclaren_verse_part(m2.group(2).strip())
            normalized_parts.append(f"{current_book} {chapter}:{verse_part}")
            continue

        # --- Fallback: bare verse range (e.g. '17-20'); parse_thml_refs uses context ---
        normalized_parts.append(seg)

    if not normalized_parts:
        return []

    return parse_thml_refs("; ".join(normalized_parts))
