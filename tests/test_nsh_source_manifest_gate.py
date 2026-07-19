"""TEST-08 drift gate: no direct NSH source-manifest shape access outside the accessor.

Every consumer of an NSH ``vol_NN.manifest.json`` must read through
``build/lib/nsh_leaf_model.py`` (the accessor), never touch ``manifest["pages"]``
/ ``manifest["unnumbered_leaves"]`` directly. A prose "switch every consumer"
instruction rots; this gate makes a missed consumer impossible to reintroduce
(design ../EzraOCR/docs/DESIGN_nsh_leaf_sequence_manifest.md SS3, the red-team's TEST-08).

Two signals, chosen so the gate never false-positives on the S2/S3/WCT chain
(which reads a DIFFERENT ``pages[]`` -- the sidecar manifest):

  (1) ``unnumbered_leaves`` access (broad, over all of build/). This key is
      UNIQUE to NSH source manifests -- no sidecar / page_order / Azure / JE
      structure has it -- so any direct access outside the accessor and the
      write path is a real coupling to the source shape.

  (2) ``manifest`` / ``mf``-qualified ``pages`` access, scoped to the curated
      NSH source-consumer file list. ``pages`` is ambiguous (source vs sidecar
      vs page_order vs Azure, often on a var also named ``manifest``), so it is
      only checked in files KNOWN to consume the source manifest.

Allow-marker (TEST-10 documented): a line ending in ``# nsh-legacy-read: <why>``
is exempt. Used by the s0 integrity checker, whose job is to inspect the raw
legacy shape for duplicate/missing leaf ids -- routing it through the cleaning
accessor would hide the anomalies it exists to flag.

Scope (honest): a brand-new file reading ONLY ``manifest["pages"]`` of a source
manifest -- never touching unnumbered_leaves, not in the consumer list -- is the
one residual gap, the same inherent limit any grep gate has. Realistic new leaf-
model consumers handle front/back matter and so trip signal (1).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BUILD_DIR = REPO_ROOT / "build"

# Documented allow-marker (TEST-10).
MARKER = "# nsh-legacy-read:"

# (1) unnumbered_leaves: ["unnumbered_leaves"] or .get("unnumbered_leaves"...
_UNNUMBERED = re.compile(r"""(\[\s*["']unnumbered_leaves["']\s*\]|\.get\(\s*["']unnumbered_leaves["'])""")
# (2) manifest/mf-qualified pages: manifest["pages"] / mf["pages"] / manifest.get("pages"...
_PAGES_QUALIFIED = re.compile(
    r"""\b(?:manifest|mf)\s*(\[\s*["']pages["']\s*\]|\.get\(\s*["']pages["'])"""
)

# Files exempt from the unnumbered_leaves scan: the accessor itself, and the
# NSH write path (the fetcher builds + rewrites the legacy arrays; the design
# defers its conversion to leaves[] to P2).
_EXEMPT_UNNUMBERED = {
    "build/lib/nsh_leaf_model.py",
}

# Files that consume the NSH SOURCE manifest -- here a manifest/mf-qualified
# ``pages`` read is definitely the source shape and must go through the accessor.
_NSH_SOURCE_CONSUMERS = {
    "build/lib/s0_ingest.py",
    "build/lib/page_order.py",
    "build/tools/generate_page_order.py",
    "build/tools/verify_nsh_page_accounting.py",
    "build/tools/nsh_precommit_ocr_gate.py",
    "build/tools/ocr_pipeline/extract_ccel_page_gold.py",
    "build/parsers/ia_abbyy.py",
}


def scan_text(text: str, *, check_unnumbered: bool, check_pages: bool) -> list[tuple[int, str, str]]:
    """Return (line_no, stripped_line, signal) for each unmarked violation."""
    violations: list[tuple[int, str, str]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if MARKER in line:
            continue
        if check_unnumbered and _UNNUMBERED.search(line):
            violations.append((line_no, line.strip(), "unnumbered_leaves"))
        if check_pages and _PAGES_QUALIFIED.search(line):
            violations.append((line_no, line.strip(), "pages"))
    return violations


def _iter_build_py() -> list[Path]:
    return [p for p in BUILD_DIR.rglob("*.py") if "__pycache__" not in p.parts]


def find_violations() -> list[tuple[str, int, str, str]]:
    out: list[tuple[str, int, str, str]] = []
    for path in _iter_build_py():
        rel = path.relative_to(REPO_ROOT).as_posix()
        check_unnumbered = rel not in _EXEMPT_UNNUMBERED
        check_pages = rel in _NSH_SOURCE_CONSUMERS
        if not check_unnumbered and not check_pages:
            continue
        text = path.read_text(encoding="utf-8")
        for line_no, line, signal in scan_text(
            text, check_unnumbered=check_unnumbered, check_pages=check_pages
        ):
            out.append((rel, line_no, line, signal))
    return out


# --- the gate -------------------------------------------------------------


def test_no_direct_nsh_source_manifest_access():
    violations = find_violations()
    if violations:
        report = "\n".join(
            f"  {rel}:{ln}  [{sig}]  {line}" for rel, ln, line, sig in violations
        )
        raise AssertionError(
            "Direct NSH source-manifest shape access found. Read through "
            "build/lib/nsh_leaf_model.py (the accessor), or annotate a legitimate "
            f"legacy read with `{MARKER} <why>`:\n{report}"
        )


# --- TEST-09 self-tests: a true-positive and a true-negative per signal ----


def test_selftest_true_positive_pages():
    text = 'for p in manifest.get("pages", []):\n    pass\n'
    hits = scan_text(text, check_unnumbered=True, check_pages=True)
    assert any(sig == "pages" for _, _, sig in hits)


def test_selftest_true_positive_pages_subscript():
    text = 'pages = mf["pages"]\n'
    hits = scan_text(text, check_unnumbered=True, check_pages=True)
    assert any(sig == "pages" for _, _, sig in hits)


def test_selftest_true_positive_unnumbered():
    text = 'leaves = manifest.get("unnumbered_leaves", [])\n'
    hits = scan_text(text, check_unnumbered=True, check_pages=False)
    assert any(sig == "unnumbered_leaves" for _, _, sig in hits)


def test_selftest_true_negative_accessor_call():
    # The correct pattern -- going through the accessor -- is NOT flagged.
    text = "for p in body_pages(manifest):\n    pass\n"
    assert scan_text(text, check_unnumbered=True, check_pages=True) == []


def test_selftest_true_negative_non_source_pages_var():
    # A non-source structure (page_order / sidecar / Azure) read off a var that
    # is NOT named manifest/mf is not flagged by the pages signal.
    text = 'for p in data.get("pages", []):\n    pass\n'
    assert scan_text(text, check_unnumbered=True, check_pages=True) == []


def test_selftest_true_negative_marker_exempts():
    text = 'pages = manifest.get("pages", [])  # nsh-legacy-read: integrity detector\n'
    assert scan_text(text, check_unnumbered=True, check_pages=True) == []


def test_selftest_marker_exempts_unnumbered_too():
    text = 'u = manifest.get("unnumbered_leaves", [])  # nsh-legacy-read: integrity detector\n'
    assert scan_text(text, check_unnumbered=True, check_pages=True) == []
