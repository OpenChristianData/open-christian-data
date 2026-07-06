"""patterns.py -- OCR detection rules (pure functions) for the OCD OCR scanner.

Each detector takes a token (str) and a DetectorContext, returns Candidate | None.
All functions are pure: no file I/O, no global state mutation, no side effects.
Import-safe: no work at import time (PY-06).

Detectors are grouped by pattern_set. The scanner dispatches via
_DETECTORS_BY_PATTERN_SET in scanner.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    pass  # avoid circular imports; models imported below at runtime

from build.tools.ocr_scanner.models import Candidate, REASON_CODES

try:
    from enchant.errors import Error as _EnchantError  # type: ignore
except ImportError:
    _EnchantError = Exception  # type: ignore  # enchant not installed; _enchant_dicts will be []


# ===========================================================================
# Compiled regexes -- Tier 1 ia_djvu
# Each one is tested in selftest.py's regex sanity block and in test_ocr_patterns.py.
# All character classes below are ASCII-only; no \uXXXX escapes needed here.
# ===========================================================================

# Matches tokens consisting solely of [A-Za-z0-9] that contain >=1 digit and >=2 letters.
# Tokens with '.', spaces, or other punctuation are implicitly excluded because they fall
# outside the [A-Za-z0-9]+ character class (so A.D. and D.D. are safely rejected).
# The [^:]* lookahead explicitly excludes colon-separated refs like 3:16.
_DIGIT_IN_LETTER_RE = re.compile(
    r"^(?=[^:]*[0-9])(?=[^:]*[A-Za-z]{2})[A-Za-z0-9]+$"
)

# Matches tokens starting with ( followed by an uppercase letter.
# Captures OCR corruption of Oe/AE ligatures: (ECOLAMPADIUS, (ESAR, etc.
# Does NOT match lowercase-after-paren (normal parentheticals like "(see").
_LIGATURE_BRACKET_RE = re.compile(r"^\([A-Z]")

# Matches (E or (e mid-word (alpha char on both sides of the opening paren).
# Captures: C(ESAR, pr(elude, DIOC(ESAN.
# Does NOT match tokens starting with ( (those are ligature_bracket territory).
_LIGATURE_AE_LOSS_RE = re.compile(r"(?<=[A-Za-z])\(E[a-zA-Z]|(?<=[A-Za-z])\(e[a-zA-Z]")

# Matches | or \ between two alpha characters.
# Captures: CHR|ST, b\ok, wor|d.
_STRAY_PIPE_RE = re.compile(r"[A-Za-z][|\\][A-Za-z]")

# Digit substitution table: digit -> most-likely-letter in religious OCR text.
_DIGIT_SUB: dict[str, str] = {
    "0": "O",
    "8": "S",
    "1": "I",
    "5": "S",
}


# ===========================================================================
# DetectorContext -- bundles per-call data so detector signatures stay short
# ===========================================================================

@dataclass
class DetectorContext:
    """Immutable context passed to every detector invocation.

    Import-safe: pure data container, no I/O at construction time (PY-06).
    """
    source_id: str
    entry_id: str
    field_path: str            # e.g. "term" or "definition_blocks[3]"
    context_before: str        # ~40 chars of surrounding text before the token
    context_after: str         # ~40 chars of surrounding text after the token
    cand_id: str               # pre-allocated "cand-NNNN"
    dictionary: "DictionaryStack"
    whitelist_terms: set       # from per-source config; upper-cased at load time
    whitelist_patterns: list   # compiled re.Pattern objects from per-source config
    adjacent_prev: Optional[str]  # previous token in stream (for space-insertion)
    adjacent_next: Optional[str]  # next token in stream


# ===========================================================================
# DictionaryStack -- layered word lookup
# ===========================================================================

class DictionaryStack:
    """Layered dictionary lookup. A token is 'real' if ANY layer accepts it.

    Layers (in order):
      1. Per-source whitelist (set of uppercase strings, case-normalised at load)
      2. OCD-specific lexicon (set: naves topics + SH term census + theological_seed.txt)
      3. pyenchant en_US + en_GB (optional -- graceful degradation if not installed)

    All lookups are case-insensitive (token uppercased before checking layers 2+3).
    Layer 1 (whitelist) is exact-match uppercase.

    Import-safe: no file I/O at class definition time. Lexicon loaded in __init__
    only when called explicitly from scanner.py (PY-06).
    """

    def __init__(
        self,
        whitelist_terms: set,
        lexicon_terms: Optional[set] = None,
        enable_enchant: bool = True,
    ) -> None:
        self._whitelist: set[str] = {t.upper() for t in whitelist_terms}
        self._lexicon: set[str] = {t.upper() for t in (lexicon_terms or set())}
        self._enchant_dicts: list = []
        if enable_enchant:
            try:
                import enchant  # type: ignore
                self._enchant_dicts = [
                    enchant.Dict("en_US"),
                    enchant.Dict("en_GB"),
                ]
            except (ImportError, Exception):
                # Enchant not installed or initialisation failed -- continue without it.
                # Layers 1 and 2 still function. Log is emitted by scanner.py at startup.
                pass

    def check(self, token: str) -> bool:
        """Return True if token is recognised by any layer."""
        upper = token.upper()
        if upper in self._whitelist:
            return True
        if upper in self._lexicon:
            return True
        for d in self._enchant_dicts:
            try:
                if d.check(token):
                    return True
            except _EnchantError:
                pass  # enchant Dict.check() can raise on unusual tokens (e.g. null bytes); non-fatal
        return False

    def add_to_lexicon(self, term: str) -> None:
        """Add a term to the in-memory OCD lexicon layer (does not write to disk)."""
        self._lexicon.add(term.upper())


# ===========================================================================
# Helper functions
# ===========================================================================

def _apply_digit_sub(token: str) -> str:
    """Replace digit substitutions with most-likely letters."""
    return "".join(_DIGIT_SUB.get(c, c) for c in token)


def _apply_ligature_fix(token: str) -> str:
    """Replace leading ( with O -- the ( is the corrupted form of the O in the OE ligature.

    Example: (ECOLAMPADIUS -> OECOLAMPADIUS  (token[1:] is already ECOLAMPADIUS).
    The OCR reads the OE ligature as '(' + E, so the leading ( represents the O only.
    """
    if token.startswith("("):
        return "O" + token[1:]
    return token


# ===========================================================================
# Tier 1 detectors -- ia_djvu pattern_set
# ===========================================================================

def detect_digit_in_letter(token: str, ctx: DetectorContext) -> Optional[Candidate]:
    """Detect tokens mixing digits with >=2 letters (0->O, 8->S corruptions).

    Excludes: tokens containing ':' (scripture refs), tokens containing '.' (abbreviations).
    """
    if not _DIGIT_IN_LETTER_RE.match(token):
        return None
    suggestion = _apply_digit_sub(token)
    return Candidate(
        id=ctx.cand_id,
        tier=REASON_CODES["digit_in_letter"],
        reason="digit_in_letter",
        source_id=ctx.source_id,
        entry_id=ctx.entry_id,
        field_path=ctx.field_path,
        value=token,
        suggestion=suggestion,
        suggestion_source="digit_substitution_table",
        confidence=0.45,
        context_before=ctx.context_before,
        context_after=ctx.context_after,
        occurrences=1,
    )


def detect_ligature_bracket(token: str, ctx: DetectorContext) -> Optional[Candidate]:
    """Detect tokens starting with ( followed by uppercase letter.

    Catches OCR corruption where Oe/AE ligatures are read as a left parenthesis.
    Examples: (ECOLAMPADIUS -> OECOLAMPADIUS, (ESAR -> OEESAR.
    """
    if not _LIGATURE_BRACKET_RE.match(token):
        return None
    suggestion = _apply_ligature_fix(token)
    return Candidate(
        id=ctx.cand_id,
        tier=REASON_CODES["ligature_bracket"],
        reason="ligature_bracket",
        source_id=ctx.source_id,
        entry_id=ctx.entry_id,
        field_path=ctx.field_path,
        value=token,
        suggestion=suggestion,
        suggestion_source="ligature_rule",
        confidence=0.10,
        context_before=ctx.context_before,
        context_after=ctx.context_after,
        occurrences=1,
    )


def detect_ligature_ae_loss(token: str, ctx: DetectorContext) -> Optional[Candidate]:
    """Detect tokens with (E or (e mid-word (alpha on both sides).

    Catches: C(ESAR, pr(elude, DIOC(ESAN.
    Does NOT catch tokens starting with ( (those are ligature_bracket).
    """
    if token.startswith("("):
        return None
    if not _LIGATURE_AE_LOSS_RE.search(token):
        return None
    suggestion = re.sub(r"\(E", "OE", re.sub(r"\(e", "oe", token))
    return Candidate(
        id=ctx.cand_id,
        tier=REASON_CODES["ligature_ae_loss"],
        reason="ligature_ae_loss",
        source_id=ctx.source_id,
        entry_id=ctx.entry_id,
        field_path=ctx.field_path,
        value=token,
        suggestion=suggestion,
        suggestion_source="ligature_rule",
        confidence=0.40,
        context_before=ctx.context_before,
        context_after=ctx.context_after,
        occurrences=1,
    )


def detect_stray_pipe_backslash(token: str, ctx: DetectorContext) -> Optional[Candidate]:
    """Detect tokens containing | or \\ between alpha characters.

    No auto-suggestion -- reviewer decides the correct letter.
    """
    if not _STRAY_PIPE_RE.search(token):
        return None
    return Candidate(
        id=ctx.cand_id,
        tier=REASON_CODES["stray_pipe_backslash"],
        reason="stray_pipe_backslash",
        source_id=ctx.source_id,
        entry_id=ctx.entry_id,
        field_path=ctx.field_path,
        value=token,
        suggestion=None,
        suggestion_source=None,
        confidence=0.90,
        context_before=ctx.context_before,
        context_after=ctx.context_after,
        occurrences=1,
    )


# ===========================================================================
# Tier 2 detectors -- ia_djvu pattern_set
# ===========================================================================

# Standard abbreviations that must NOT be flagged by this detector.
# Includes single letters that are genuine abbreviations (A = first/one, I = first/Roman),
# plus common two-letter theological and temporal shorthands.
# Whitelist_terms from per-source config supplement this set at runtime.
_STANDARD_ABBREVS: frozenset = frozenset({
    # Single-letter abbreviations in common use
    "A", "I",
    # Two-letter biblical / theological
    "AD", "BC", "AM", "PM", "NT", "OT",
    # Roman numerals (two-letter)
    "II", "IV", "VI", "IX", "XI",
    # Other common shorthands
    "CE", "BP",
})


def detect_short_allcaps_orphan(token: str, ctx: DetectorContext) -> Optional[Candidate]:
    """Tier 2: 1-2 char ALL-CAPS token not in standard-abbrev or config whitelist.

    Flags possible corruption like CN (should be IN?), PW, etc.
    No auto-suggestion (reviewer decides).
    """
    if len(token) > 2 or len(token) < 1:
        return None
    if not token.isupper():
        return None
    upper = token.upper()
    if upper in _STANDARD_ABBREVS:
        return None
    if upper in ctx.whitelist_terms:
        return None
    return Candidate(
        id=ctx.cand_id,
        tier=REASON_CODES["short_allcaps_orphan"],
        reason="short_allcaps_orphan",
        source_id=ctx.source_id,
        entry_id=ctx.entry_id,
        field_path=ctx.field_path,
        value=token,
        suggestion=None,
        suggestion_source=None,
        confidence=0.35,
        context_before=ctx.context_before,
        context_after=ctx.context_after,
        occurrences=1,
    )


def _detect_joined_word(token: str, ctx: DetectorContext, reason: str) -> Optional[Candidate]:
    """Shared logic: prev + token form a dictionary word when joined.

    Used by detect_apparent_space_insertion (ia_djvu) and detect_unusual_bigram (ccel_thml).
    Both tokens must be ALL-CAPS, 3-12 chars, and their join must pass dictionary.check().
    """
    if ctx.adjacent_prev is None:
        return None
    prev = ctx.adjacent_prev
    # Both tokens must be ALL-CAPS and in a reasonable length range.
    # Upper bound 12 covers long-but-plausible halves like DESTINATION (11).
    if not (token.isupper() and prev.isupper()):
        return None
    if not (3 <= len(prev) <= 12 and 3 <= len(token) <= 12):
        return None
    joined = prev + token
    if not ctx.dictionary.check(joined):
        return None
    return Candidate(
        id=ctx.cand_id,
        tier=REASON_CODES[reason],
        reason=reason,
        source_id=ctx.source_id,
        entry_id=ctx.entry_id,
        field_path=ctx.field_path,
        value=f"{prev} {token}",
        suggestion=joined,
        suggestion_source="dictionary",
        confidence=0.70,
        context_before=ctx.context_before,
        context_after=ctx.context_after,
        occurrences=1,
    )


def detect_apparent_space_insertion(token: str, ctx: DetectorContext) -> Optional[Candidate]:
    """Tier 2: Current token + adjacent_prev form a dictionary word when joined.

    The detector is invoked on the SECOND of the two tokens (the one after the
    potential spurious space). adjacent_prev holds the first token.
    """
    return _detect_joined_word(token, ctx, "apparent_space_insertion")


def detect_apparent_space_deletion(token: str, ctx: DetectorContext) -> Optional[Candidate]:
    """Tier 2: ALL-CAPS token not in dictionary that splits into two dictionary words.

    Tries all split points i in range(2, len(token)-1). Accepts the first split
    where both halves pass ctx.dictionary.check(). No split found -> None.

    Skips tokens already in the dictionary (real compound words).
    """
    if not token.isupper():
        return None
    if not (6 <= len(token) <= 20):
        return None
    # If the token itself is in the dictionary, it's a real word -- don't flag.
    if ctx.dictionary.check(token):
        return None
    for i in range(2, len(token) - 1):
        left, right = token[:i], token[i:]
        if ctx.dictionary.check(left) and ctx.dictionary.check(right):
            return Candidate(
                id=ctx.cand_id,
                tier=REASON_CODES["apparent_space_deletion"],
                reason="apparent_space_deletion",
                source_id=ctx.source_id,
                entry_id=ctx.entry_id,
                field_path=ctx.field_path,
                value=token,
                suggestion=f"{left} {right}",
                suggestion_source="split_point",
                confidence=0.55,
                context_before=ctx.context_before,
                context_after=ctx.context_after,
                occurrences=1,
            )
    return None


# ===========================================================================
# ccel_thml detectors
# ===========================================================================

# Matches raw HTML entities in text output (decode miss indicator).
_ENTITY_LEAK_RE = re.compile(r"&[a-z]+;|&#\d+;")


def detect_entity_leak(token: str, ctx: DetectorContext) -> Optional[Candidate]:
    """Tier 1 (ccel_thml): raw HTML entity in output text.

    Catches &amp;, &lt;, &#8212; etc. that were not decoded during ThML parsing.
    """
    if not _ENTITY_LEAK_RE.fullmatch(token):
        return None
    return Candidate(
        id=ctx.cand_id,
        tier=REASON_CODES["entity_leak"],
        reason="entity_leak",
        source_id=ctx.source_id,
        entry_id=ctx.entry_id,
        field_path=ctx.field_path,
        value=token,
        suggestion=None,
        suggestion_source=None,
        confidence=0.99,
        context_before=ctx.context_before,
        context_after=ctx.context_after,
        occurrences=1,
    )


def detect_unusual_bigram(token: str, ctx: DetectorContext) -> Optional[Candidate]:
    """Tier 2 (ccel_thml): same engine as detect_apparent_space_insertion.

    Shares the space-insertion detection logic via _detect_joined_word; the CCEL
    whitelist (ctx.whitelist_terms) provides corpus-specific suppression.
    Produces candidates labeled reason='unusual_bigram', not 'apparent_space_insertion'.
    """
    return _detect_joined_word(token, ctx, "unusual_bigram")


# ===========================================================================
# Universal field-level detectors (all pattern_sets)
# These receive the full field text rather than a single token.
# ===========================================================================

# Matches Project Gutenberg boilerplate phrases in content fields.
# "Gutenberg" alone is excluded to avoid false-positives on "Gutenberg Bible".
# PG plain-text files use ASCII apostrophes; '?s? covers "Transcriber's", "Transcribers",
# and "Transcriber" (no apostrophe) variants.
_PG_HEADER_RE = re.compile(
    r"Project\s+Gutenberg"
    r"|Distributed\s+Proofreaders"
    r"|\*{3,}\s*(?:START|END)\s+OF\b"
    r"|Transcriber'?s?\s+Notes?"
    r"|gutenberg\.org",
    re.IGNORECASE,
)


def detect_pg_header(text: str, ctx: DetectorContext) -> Optional[Candidate]:
    """Tier 1 (all pattern_sets): detect Project Gutenberg boilerplate in content fields.

    Catches 'Project Gutenberg', 'Distributed Proofreaders', PG divider lines
    ('*** START/END OF'), Transcriber Notes, and gutenberg.org URLs.

    Should NOT fire on meta.contributors -- exclude it via the source config's
    scan_fields (do not include 'contributors' or 'meta' in scan_fields).
    """
    m = _PG_HEADER_RE.search(text)
    if m is None:
        return None
    ctx_before = text[max(0, m.start() - 40): m.start()].strip()
    ctx_after = text[m.end(): m.end() + 40].strip()
    value = text[max(0, m.start() - 20): m.end() + 20].strip()
    return Candidate(
        id=ctx.cand_id,
        tier=REASON_CODES["pg_header"],
        reason="pg_header",
        source_id=ctx.source_id,
        entry_id=ctx.entry_id,
        field_path=ctx.field_path,
        value=value,
        suggestion=None,
        suggestion_source=None,
        confidence=0.97,
        context_before=ctx_before,
        context_after=ctx_after,
        occurrences=1,
    )
