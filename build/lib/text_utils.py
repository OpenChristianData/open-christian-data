import hashlib
import re
from pathlib import Path

_RE_MULTI_SPACE = re.compile(r"  +")


def normalize_line(line: str) -> str:
    """Normalize one line of _djvu.txt OCR: collapse double-spaces, strip trailing whitespace.

    Internet Archive _djvu.txt files use double (or triple) spaces between words
    due to typeset column layout.  After normalization,
    'THE  NEW  SCHAFF-HERZOG' becomes 'THE NEW SCHAFF-HERZOG'.
    """
    return _RE_MULTI_SPACE.sub(" ", line).rstrip()


def smart_title(s: str) -> str:
    """Title-case s, collapsing whitespace without capitalising after apostrophes.

    str.title() treats any non-letter as a word boundary, producing e.g.
    "Nobleman'S" from "NOBLEMAN'S". Splitting on whitespace and using
    str.capitalize() per token avoids this.  Multiple spaces are collapsed
    to one as a side-effect of split/join.
    """
    return " ".join(word.capitalize() for word in s.split())


def compute_source_hash(path: Path) -> str:
    """Return 'sha256:<hex>' for the file at *path*."""
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
