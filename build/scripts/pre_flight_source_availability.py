"""
Pre-flight source availability check for church_fathers curation.

Purpose: before dispatching parallel curation agents, sample each target's
inputs and blockers so each agent's prompt can be customised with the
orchestrator's knowledge. Saves hundreds of tool calls of rediscovery.

For each author slug on the command line, reports:
  - Entry counts (total / has_source_title / missing)
  - Existing source_title format examples (format hint)
  - Raw TOML availability and source_url density
  - Known-blocker lookup (configured list of authors with no digital source)

The "Constraint note for agent prompt" section at the end of each author's
report is designed to be pasted verbatim under a "Pre-flight findings"
heading in the agent's prompt.

Usage:
  py -3 build/scripts/pre_flight_source_availability.py <slug1> [<slug2> ...]

Run before dispatching parallel curation agents. No external API calls;
reads only local data and raw TOML files.
"""
from __future__ import annotations

import json
import logging
import sys
import tomllib
from collections import Counter
from pathlib import Path

# ==========================================================================
# CONFIG
# ==========================================================================

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "church-fathers"
RAW_DIR = REPO_ROOT / "raw" / "Commentaries-Database"

# Authors known to have no accessible digital source. Update when a source
# becomes available (e.g. a library scan is published on archive.org).
# Captured 2026-04-15 from the first 5-batch curation session.
KNOWN_BLOCKERS = {
    "nerses-of-lambron": (
        "Thomson 2007 'Commentary on the Revelation of Saint John' "
        "(Peeters, ISBN 9789042918665) is the only English translation. "
        "Not on archive.org, CCEL, or Google Books preview. "
        "Expected outcome: 0 HIGH patches."
    ),
    "leo-the-great": (
        "Acts and Colossians entries use FC vols 93/120 (CUA Press, modern "
        "translation) which are not digitised. NPNF Letters/Sermons are "
        "online (newadvent, tertullian) for some entries. "
        "Expected outcome: 1-2 HIGH patches for NPNF-matched quotes only."
    ),
    "caesarius-of-arles": (
        "Most entries use FC vols 47/130 (CUA Press). FC 47 (Sermons 81-186) "
        "is not digitised. A few explicit section labels are embedded in the "
        "TOML quote text (e.g. 'Sermon 124.X') -- treat those as HIGH. "
        "Expected outcome: 2-5 HIGH patches from embedded labels."
    ),
}

DIVIDER = "=" * 70
SAMPLE_CAP = 200  # max TOML files to scan per author
URL_SAMPLE_COUNT = 5


# ==========================================================================
# HELPERS
# ==========================================================================

def find_raw_dir(slug):
    """
    Find the raw/Commentaries-Database/ directory for a slug.

    Slug is lowercase-hyphenated (e.g. 'pope-urban-i'). Directory name is
    title-case with spaces (e.g. 'Pope Urban I'). Case-insensitive match
    handles the 'of'/'the' and roman-numeral casing naturally.
    """
    if not RAW_DIR.exists():
        return None
    target = slug.replace("-", " ").lower()
    for p in RAW_DIR.iterdir():
        if p.is_dir() and p.name.lower() == target:
            return p
    return None


def analyse_json(slug):
    """Load the author's JSON and return completeness and format-hint stats."""
    json_path = DATA_DIR / f"{slug}.json"
    if not json_path.exists():
        return {"error": f"Data file not found: {json_path}"}
    with open(json_path, encoding="utf-8") as f:
        doc = json.load(f)
    entries = doc.get("data", [])
    total = len(entries)
    has_title = sum(1 for e in entries if e.get("source_title"))
    missing = total - has_title
    title_counter = Counter(
        e["source_title"] for e in entries if e.get("source_title")
    )
    missing_ids = [
        e.get("entry_id", "?") for e in entries if not e.get("source_title")
    ]
    return {
        "total": total,
        "has_title": has_title,
        "missing": missing,
        "missing_ids": missing_ids,
        "top_titles": title_counter.most_common(5),
    }


def analyse_raw(slug):
    """Check raw TOML files for source_url density (a proxy for attribution hints)."""
    raw_dir = find_raw_dir(slug)
    if raw_dir is None:
        return {
            "raw_dir": None,
            "note": (
                "Raw directory not found -- slug-to-dirname lookup failed. "
                "Check raw/Commentaries-Database/ for the author's folder "
                "manually."
            ),
        }
    toml_files = sorted(raw_dir.glob("*.toml"))
    url_samples = []
    url_count_set = 0
    url_count_blank = 0
    for p in toml_files[:SAMPLE_CAP]:
        try:
            with open(p, "rb") as f:
                data = tomllib.load(f)
        except Exception as exc:
            logging.warning("Skipping malformed TOML at %s: %s", p, exc)
            continue
        url = data.get("source_url", "")
        if url:
            url_count_set += 1
            if len(url_samples) < URL_SAMPLE_COUNT:
                url_samples.append(url)
        else:
            url_count_blank += 1
    return {
        "raw_dir": str(raw_dir.relative_to(REPO_ROOT)),
        "toml_count": len(toml_files),
        "url_set": url_count_set,
        "url_blank": url_count_blank,
        "url_samples": url_samples,
    }


# ==========================================================================
# CONSTRAINT NOTE (library function -- also used by prepare_curation_session)
# ==========================================================================

def build_constraint_note(slug):
    """
    Return the per-author constraint note as a list of lines.

    This is the block that gets injected into an agent prompt under
    "## Pre-flight findings". It captures what the orchestrator knows so
    the agent doesn't rediscover it.
    """
    j = analyse_json(slug)
    if "error" in j:
        return [f"Pre-flight findings for {slug}:", f"- ERROR: {j['error']}"]
    r = analyse_raw(slug) if j["missing"] > 0 else None
    lines = [f"Pre-flight findings for {slug}:"]
    lines.append(
        f"- {j['missing']} entries missing source_title out of {j['total']}."
    )
    if j["top_titles"]:
        top = j["top_titles"][0]
        lines.append(
            f"- Dominant existing format: '{top[0]}' ({top[1]} entries). "
            f"Match this format unless contradicted by TOML metadata."
        )
    else:
        lines.append(
            "- No existing source_title format -- establish the convention "
            "from a comparable patch script in build/scripts/."
        )
    if r is not None and r.get("raw_dir") is not None:
        if r["url_set"] == 0 and r["url_blank"] > 0:
            lines.append(
                "- source_url is BLANK across raw TOMLs -- no URL hints. "
                "Attribution requires quote-matching against primary sources."
            )
        elif r["url_set"] > 0:
            total_sampled = r["url_set"] + r["url_blank"]
            lines.append(
                f"- source_url present in {r['url_set']} of "
                f"{total_sampled} sampled TOMLs. Use the URL pattern as a "
                "primary attribution signal."
            )
    if slug in KNOWN_BLOCKERS:
        lines.append(f"- KNOWN BLOCKER: {KNOWN_BLOCKERS[slug]}")
    return lines


# ==========================================================================
# REPORT (CLI entry point)
# ==========================================================================

def report(slug):
    """Print the pre-flight report for one author."""
    print(DIVIDER)
    print(f"AUTHOR: {slug}")
    print(DIVIDER)

    if slug in KNOWN_BLOCKERS:
        print(f"BLOCKER: {KNOWN_BLOCKERS[slug]}")
        print()

    j = analyse_json(slug)
    if "error" in j:
        print(f"ERROR: {j['error']}")
        return

    print(
        f"Entries: {j['total']} total, "
        f"{j['has_title']} have source_title, "
        f"{j['missing']} missing"
    )
    print()
    print("Top existing source_title values (format hint):")
    if j["top_titles"]:
        for title, count in j["top_titles"]:
            print(f"  {count:4d}  {title}")
    else:
        print("  (none set yet -- no format precedent in this file)")
    print()

    if j["missing"] > 0:
        r = analyse_raw(slug)
        if r.get("raw_dir") is None:
            print(f"Raw dir: NOT FOUND -- {r['note']}")
        else:
            print(f"Raw dir: {r['raw_dir']} ({r['toml_count']} TOML files)")
            print(f"  source_url set:   {r['url_set']}")
            print(f"  source_url blank: {r['url_blank']}")
            if r["url_samples"]:
                print("  Sample URLs:")
                for url in r["url_samples"]:
                    print(f"    - {url}")
            else:
                print(
                    "  No source_urls found -- "
                    "attribution requires quote-matching"
                )

    print()
    print("-- Constraint note for agent prompt --")
    for line in build_constraint_note(slug):
        print(line)
    print()


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: py -3 build/scripts/pre_flight_source_availability.py "
            "<slug1> [<slug2> ...]"
        )
        sys.exit(1)
    slugs = sys.argv[1:]
    print(
        f"Pre-flight source availability check for {len(slugs)} author(s)"
    )
    print()
    for slug in slugs:
        try:
            report(slug)
        except Exception as exc:
            print(f"ERROR reporting {slug}: {exc}")
            print()
    print(DIVIDER)
    print(
        "Done. Copy each '-- Constraint note --' block into the matching "
        "agent prompt under a 'Pre-flight findings' heading."
    )


if __name__ == "__main__":
    main()
