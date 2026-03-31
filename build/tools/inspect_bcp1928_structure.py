"""inspect_bcp1928_structure.py
Structural census of cached episcopalnet.org BCP 1928 HTML files.

Run BEFORE writing any parser logic, or retroactively to validate that an
existing parser handles every observed variant. Reads every cached raw file
and reports all structural variants found: title tag forms, collect marker
forms, closing tag capitalisation, and noscript nesting depth. Write the
parser once, based on the full census -- not on a sample.

Usage:
    py -3 build/tools/inspect_bcp1928_structure.py

Requires: raw/bcp-1928/*.html (populated by bcp1928.py --dry-run or full run)
"""

import re
import sys
from pathlib import Path
from collections import Counter, defaultdict

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "raw" / "bcp-1928"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_html(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return path.read_bytes().decode("latin-1", errors="replace")


def noscript_nesting_depth(html: str) -> int:
    """Return the maximum noscript nesting depth found in this HTML."""
    depth = 0
    max_depth = 0
    for m in re.finditer(r"<(/?)noscript[^>]*>", html, re.IGNORECASE):
        if m.group(1) == "":
            depth += 1
            max_depth = max(max_depth, depth)
        else:
            depth = max(0, depth - 1)
    return max_depth


# ---------------------------------------------------------------------------
# Census functions — each returns a short label for the variant found
# ---------------------------------------------------------------------------

def title_tag_variant(html: str) -> str:
    """Classify the title block tag structure after </h2>."""
    h2_end = re.search(r"</h2\s*>", html, re.IGNORECASE)
    if not h2_end:
        return "NO_H2"
    # Narrow window: 600 chars after </h2>
    region = html[h2_end.end() : h2_end.end() + 600]
    # Find the first significant tag (ignoring whitespace/anchors)
    for m in re.finditer(r"<([a-zA-Z][a-zA-Z0-9]*)[^>]*>", region):
        tag = m.group(1).lower()
        if tag in ("a", "br", "iframe", "center", "p", "div"):
            continue  # these are structural wrappers, not title tags
        return tag
    return "NO_TITLE_TAG"


def collect_marker_variant(html: str) -> str:
    """Classify the collect marker form."""
    m = re.search(r"The\s+Collects?\s*\.", html, re.IGNORECASE)
    if not m:
        return "ABSENT"
    return m.group(0).strip()


def closing_tag_case(html: str) -> str:
    """Report whether </center> tags use lower or upper case."""
    lower = len(re.findall(r"</center>", html))
    upper = len(re.findall(r"</CENTER>", html))
    mixed = len(re.findall(r"</[Cc][Ee][Nn][Tt][Ee][Rr]>", html)) - lower - upper
    if upper > 0 and lower == 0:
        return "UPPER"
    if lower > 0 and upper == 0:
        return "lower"
    if upper > 0 and lower > 0:
        return "MIXED"
    return "none_found"


def has_nbsp_spacer(html: str) -> bool:
    """Return True if there is a <p>&nbsp;</p> or <p> </p> spacer paragraph."""
    return bool(re.search(r"<p[^>]*>\s*(&nbsp;|\xa0|\s)\s*</p>", html, re.IGNORECASE))


# ---------------------------------------------------------------------------
# Main census
# ---------------------------------------------------------------------------

def main() -> None:
    html_files = sorted(RAW_DIR.glob("*.html"))
    if not html_files:
        print(f"ERROR: No HTML files found in {RAW_DIR}")
        print("Run: py -3 build/parsers/bcp1928.py --dry-run")
        print("  or: py -3 build/parsers/bcp1928.py")
        sys.exit(1)

    print(f"Inspecting {len(html_files)} cached HTML files in {RAW_DIR}")
    print()

    title_tag_counts: Counter = Counter()
    collect_marker_counts: Counter = Counter()
    closing_case_counts: Counter = Counter()
    noscript_depth_counts: Counter = Counter()

    title_tag_examples: defaultdict = defaultdict(list)
    collect_marker_examples: defaultdict = defaultdict(list)
    nbsp_spacer_files: list = []
    absent_collect_files: list = []
    deep_noscript_files: list = []

    for path in html_files:
        name = path.name
        html = load_html(path)

        tt = title_tag_variant(html)
        title_tag_counts[tt] += 1
        if len(title_tag_examples[tt]) < 3:
            title_tag_examples[tt].append(name)

        cm = collect_marker_variant(html)
        collect_marker_counts[cm] += 1
        if len(collect_marker_examples[cm]) < 5:
            collect_marker_examples[cm].append(name)
        if cm == "ABSENT":
            absent_collect_files.append(name)

        cc = closing_tag_case(html)
        closing_case_counts[cc] += 1

        depth = noscript_nesting_depth(html)
        noscript_depth_counts[depth] += 1
        if depth >= 2:
            deep_noscript_files.append(f"{name} (depth={depth})")

        if has_nbsp_spacer(html):
            nbsp_spacer_files.append(name)

    # --- Report ---

    print("=" * 60)
    print("TITLE TAG VARIANTS (first tag after </h2>)")
    print("=" * 60)
    for tag, count in title_tag_counts.most_common():
        examples = ", ".join(title_tag_examples[tag])
        print(f"  {tag:<20} {count:>3} pages  e.g. {examples}")
    print()

    print("=" * 60)
    print("COLLECT MARKER VARIANTS")
    print("=" * 60)
    for marker, count in collect_marker_counts.most_common():
        examples = ", ".join(collect_marker_examples[marker])
        print(f"  {repr(marker):<30} {count:>3} pages  e.g. {examples}")
    print()
    if absent_collect_files:
        print(f"  Pages with no collect marker ({len(absent_collect_files)}):")
        for f in absent_collect_files:
            print(f"    {f}")
    print()

    print("=" * 60)
    print("</CENTER> TAG CAPITALISATION")
    print("=" * 60)
    for case, count in closing_case_counts.most_common():
        print(f"  {case:<15} {count:>3} pages")
    print()

    print("=" * 60)
    print("NOSCRIPT NESTING DEPTH")
    print("=" * 60)
    for depth, count in sorted(noscript_depth_counts.items()):
        print(f"  depth={depth}  {count:>3} pages")
    if deep_noscript_files:
        print(f"\n  Pages with nesting depth >= 2 ({len(deep_noscript_files)}):")
        for f in deep_noscript_files:
            print(f"    {f}")
    print()

    print("=" * 60)
    print("OTHER VARIANTS")
    print("=" * 60)
    if nbsp_spacer_files:
        print(f"  <p>&nbsp;</p> spacer paragraphs: {len(nbsp_spacer_files)} pages")
        for f in nbsp_spacer_files[:5]:
            print(f"    {f}")
        if len(nbsp_spacer_files) > 5:
            print(f"    ... and {len(nbsp_spacer_files) - 5} more")
    else:
        print("  No <p>&nbsp;</p> spacer paragraphs found")
    print()

    print("=" * 60)
    print(f"Census complete -- {len(html_files)} files inspected")
    print("=" * 60)


if __name__ == "__main__":
    main()
