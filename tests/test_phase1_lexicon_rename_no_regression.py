"""CI guard: asserts the R53 lexicon rename (el → grc, he_latn → hbo_latn) has landed and cannot regress."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_LEXICONS_DIR = REPO_ROOT / "build" / "lib" / "lexicons"


def test_old_lexicon_files_do_not_exist() -> None:
    """The renamed source files must not exist — not even as shim re-exports."""
    assert not (_LEXICONS_DIR / "el.py").exists(), (
        "build/lib/lexicons/el.py still exists — R53 rename has not landed or a shim was introduced"
    )
    assert not (_LEXICONS_DIR / "he_latn.py").exists(), (
        "build/lib/lexicons/he_latn.py still exists — R53 rename has not landed or a shim was introduced"
    )


def test_new_lexicon_modules_import_successfully() -> None:
    """grc and hbo_latn must be importable; en and la must continue to work."""
    from build.lib.lexicons import grc, hbo_latn, en, la  # noqa: F401 — import-check only

    # Sanity: the modules expose the same public API as the old ones did.
    assert hasattr(grc, "ARCHAIC_FORMS")
    assert hasattr(grc, "COVERAGE_STATUS")
    assert hasattr(hbo_latn, "ARCHAIC_FORMS")
    assert hasattr(hbo_latn, "COVERAGE_STATUS")
    assert hasattr(en, "ARCHAIC_FORMS")
    assert hasattr(la, "ARCHAIC_FORMS")


def test_lang_classifier_uses_new_lang_codes() -> None:
    """lang_classifier.py must not reference the old codes 'el' or 'he_latn' in language-code positions."""
    classifier_src = (REPO_ROOT / "build" / "lib" / "lang_classifier.py").read_text(encoding="utf-8")

    # _script_spans call for Greek must use "grc", not "el".
    assert '"grc"' in classifier_src, (
        'lang_classifier.py does not contain "grc" — rename may not have landed'
    )
    assert '"he_latn"' not in classifier_src, (
        'lang_classifier.py still contains "he_latn" in a language-code context'
    )
    # "el" as a bare quoted string should not appear; allow "hbo_latn" as the new he-latn code.
    # We scan only _script_spans / _term_spans call sites (lines 40–50) to avoid false positives.
    import re
    code_block = re.search(
        r"def classify_spans.*?(?=\ndef |\Z)", classifier_src, re.DOTALL
    )
    assert code_block is not None, "classify_spans not found in lang_classifier.py"
    block_text = code_block.group(0)
    assert '"el"' not in block_text, (
        '"el" found inside classify_spans in lang_classifier.py — old lang code not replaced'
    )
