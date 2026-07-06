"""
Prepare a Church Fathers source_title curation session.

Runs all the one-time setup work so the orchestrator doesn't have to
remember anything:

  1. Computes current gap totals across data/church-fathers/ (no stale table
     in a markdown file to maintain).
  2. Filters out known blockers (from pre_flight_source_availability.py).
  3. Picks the top N*batch_size authors by remaining gap size.
  4. Runs pre-flight per-author and embeds each constraint note into a
     ready-to-dispatch agent prompt.
  5. Emits a complete session plan: orchestrator checklist, TodoWrite
     payload, and one self-contained agent prompt per author.

The orchestrator (Claude) runs this script once at the start of the
session and follows its output. No pre-flight step to remember, no
static batch list to update, no manual constraint-note copy-pasting.

Usage:
  py -3 build/scripts/prepare_curation_session.py [--batches N] [--batch-size M] [--include-blocked]

Defaults: --batches 3, --batch-size 3 (9 agents).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Import library functions from the pre-flight script. This is the
# structural enforcement: you cannot prepare a session without the
# pre-flight data because it is inlined into every agent prompt.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# standards: relative path ok -- importing from sibling script by module name
from pre_flight_source_availability import (  # noqa: E402
    KNOWN_BLOCKERS,
    build_constraint_note,
)

# ==========================================================================
# CONFIG
# ==========================================================================

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "church-fathers"

# CODING_DEFAULTS.md lives outside the repo. Set COWORK_ROOT env var to
# the workspace root. Paths are resolved at runtime only -- never
# baked into committed source.
_cowork_env = os.environ.get("COWORK_ROOT")
if not _cowork_env:
    raise EnvironmentError(
        "COWORK_ROOT environment variable is not set. "
        "Set it to the path of your local workspace root."
    )
COWORK_ROOT = Path(_cowork_env)
CODING_DEFAULTS_PATH = COWORK_ROOT / "CODING_DEFAULTS.md"

# Claude Code auto-memory directory. The per-project subfolder name is
# derived by replacing path separators in COWORK_ROOT with dashes.
_CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
_cowork_key = (
    str(COWORK_ROOT)
    .replace(":", "-").replace("\\", "-")
    .replace("/", "-").replace(" ", "-")
)
MEMORY_FILE = (
    _CLAUDE_PROJECTS / _cowork_key / "memory"
    / "project_ocd_church_fathers_curation.md"
)

DEFAULT_BATCHES = 3
DEFAULT_BATCH_SIZE = 3

DIVIDER_MAJOR = "=" * 72
DIVIDER_MINOR = "-" * 72


# ==========================================================================
# GAP SCAN
# ==========================================================================

def scan_gaps():
    """Return a list of (missing_count, slug) for every author with gaps."""
    out = []
    for fname in sorted(os.listdir(DATA_DIR)):
        if not fname.endswith(".json"):
            continue
        slug = fname[:-5]
        with open(DATA_DIR / fname, encoding="utf-8") as f:
            doc = json.load(f)
        missing = sum(
            1 for e in doc.get("data", []) if not e.get("source_title")
        )
        if missing:
            out.append((missing, slug))
    out.sort(reverse=True)
    return out


# ==========================================================================
# AGENT PROMPT TEMPLATE
# ==========================================================================

# Placeholder tokens: __SLUG__, __MISSING__, __CONSTRAINT_NOTE__,
# __REPO_ROOT__, __CODING_DEFAULTS__, __HANDBOOK__
#
# Static workflow content (steps, conventions, failure modes) lives in
# build/prompts/CHURCH_FATHERS_CURATION_HANDBOOK.md. The agent reads that
# handbook; this template carries only the variable per-agent context.
AGENT_PROMPT_TEMPLATE = """WORKING DIRECTORY: __REPO_ROOT__

Read the two files below before starting:
1. __CODING_DEFAULTS__
2. __HANDBOOK__

The handbook contains the workflow (Steps 1-6), title conventions,
failure modes, and commit format. Follow it for every step not covered
by the per-agent context below.

Your assignment: curate source_title for **__SLUG__** (__MISSING__ entries missing).

## Pre-flight findings (from the orchestrator -- do not rediscover)

__CONSTRAINT_NOTE__

## What changes per-agent

Wherever the handbook uses the placeholder `<SLUG>`, substitute
`__SLUG__` -- e.g. your patch script goes at
`build/scripts/patch_source_title___SLUG__.py` and you load
`data/church-fathers/__SLUG__.json`.

Apply the Pre-flight findings above literally -- the dominant format hint,
the URL-density assessment, and any KNOWN BLOCKER note override the
handbook's generic guidance where they conflict. If the findings flag a
KNOWN BLOCKER, produce a documented-blank commit (0 HIGH patches,
patch script docstring explains why) rather than spending tool calls
rediscovering what the orchestrator already knows.

Report back: how many entries patched, how many left blank (with reason
categories), any upstream bugs flagged, any interesting findings.
"""

# Placeholders that must be fully substituted before emitting a prompt.
# --selftest uses this list to catch regressions.
REQUIRED_PLACEHOLDERS = (
    "__SLUG__",
    "__MISSING__",
    "__CONSTRAINT_NOTE__",
    "__REPO_ROOT__",
    "__CODING_DEFAULTS__",
    "__HANDBOOK__",
)


HANDBOOK_PATH = REPO_ROOT / "docs" / "CHURCH_FATHERS_CURATION_HANDBOOK.md"


def render_agent_prompt(slug, missing):
    constraint_lines = build_constraint_note(slug)
    constraint_note = "\n".join(constraint_lines)
    return (
        AGENT_PROMPT_TEMPLATE
        .replace("__SLUG__", slug)
        .replace("__MISSING__", str(missing))
        .replace("__CONSTRAINT_NOTE__", constraint_note)
        .replace("__REPO_ROOT__", str(REPO_ROOT))
        .replace("__CODING_DEFAULTS__", str(CODING_DEFAULTS_PATH))
        .replace("__HANDBOOK__", str(HANDBOOK_PATH))
    )


# ==========================================================================
# SESSION PLAN OUTPUT
# ==========================================================================

def build_todowrite_payload(selected):
    """Return a JSON string suitable for pasting into the TodoWrite tool."""
    todos = []
    for idx, (missing, slug) in enumerate(selected, start=1):
        todos.append({
            "content": f"Agent {idx}: {slug} ({missing} missing)",
            "status": "pending",
            "activeForm": f"Curating {slug}",
        })
    todos.append({
        "content": (
            "Post-session: run count, update prompt status line and memory"
        ),
        "status": "pending",
        "activeForm": "Updating post-session records",
    })
    return json.dumps(todos, indent=2)


def emit_plan(selected, blockers_skipped, total_missing, total_authors,
              batches, batch_size):
    print(DIVIDER_MAJOR)
    print("CHURCH FATHERS CURATION -- SESSION PLAN")
    print(DIVIDER_MAJOR)
    print()
    print(
        f"Current state: {total_missing} missing across {total_authors} "
        f"authors."
    )
    print()

    if blockers_skipped:
        print("Blocked authors (skipped from this session):")
        for missing, slug in blockers_skipped:
            note = KNOWN_BLOCKERS.get(slug, "blocked")
            first_sentence = note.split(". ")[0]
            print(f"  {slug:40s} ({missing} missing) -- {first_sentence}")
        print(
            "  See UNBLOCK_PLAN.md for acquisition paths. Use "
            "--include-blocked to dispatch anyway."
        )
        print()

    total_agents = len(selected)
    print(
        f"Session plan: {batches} batches of up to {batch_size} agents = "
        f"{total_agents} agents"
    )
    print()
    for b in range(batches):
        start = b * batch_size
        end = start + batch_size
        batch = selected[start:end]
        if not batch:
            continue
        print(f"Batch {b + 1}:")
        for idx, (missing, slug) in enumerate(batch, start=start + 1):
            print(f"  {idx}. {slug:40s} ({missing} missing)")
        print()

    print(DIVIDER_MAJOR)
    print("ORCHESTRATOR CHECKLIST (follow in order)")
    print(DIVIDER_MAJOR)
    print("""
1. TodoWrite the payload below (copy verbatim).
2. Dispatch Batch 1 -- make N Agent tool calls in a single message, one
   per author, using the matching AGENT PROMPT block below.
3. Wait for every Batch 1 agent to complete. Review summaries, mark todos
   completed.
4. Repeat for Batch 2, Batch 3, etc.
5. After the final batch, run the post-session block (below).
""")

    print(DIVIDER_MINOR)
    print("TodoWrite payload -- copy this JSON into a TodoWrite tool call:")
    print(DIVIDER_MINOR)
    print(build_todowrite_payload(selected))
    print()

    print(DIVIDER_MAJOR)
    print("AGENT PROMPTS (dispatch one Agent call per prompt)")
    print(DIVIDER_MAJOR)
    for idx, (missing, slug) in enumerate(selected, start=1):
        batch_num = ((idx - 1) // batch_size) + 1
        print()
        print(DIVIDER_MINOR)
        print(f"BATCH {batch_num} / AGENT {idx} / {slug}")
        print(DIVIDER_MINOR)
        print(render_agent_prompt(slug, missing))

    print()
    print(DIVIDER_MAJOR)
    print("POST-SESSION (run after the final batch completes)")
    print(DIVIDER_MAJOR)
    print()
    print("1. Run the gap count:")
    print()
    print(
        "   py -3 -c \"import json, os; "
        "counts=[(sum(1 for e in json.load(open(f'data/church-fathers/{f}', "
        "encoding='utf-8'))['data'] if not e.get('source_title')), f[:-5]) "
        "for f in sorted(os.listdir('data/church-fathers')) "
        "if f.endswith('.json')]; counts=[c for c in counts if c[0]]; "
        "total=sum(c for c,_ in counts); "
        "print(f'Remaining: {total} missing across {len(counts)} authors'); "
        "[print(f'{c:4d}  {n}') for c,n in sorted(counts, reverse=True)[:15]]\""
    )
    print()
    print("2. Update the memory file at:")
    print(f"     {MEMORY_FILE}")
    print("   with the new completed-author entries and the new total.")
    print()
    print(
        "3. If new source-availability blockers were discovered, add them "
        "to the"
    )
    print(
        "   KNOWN_BLOCKERS dict in build/scripts/"
        "pre_flight_source_availability.py."
    )
    print()
    print("4. If upstream data bugs were found, add rows to UPSTREAM_BUGS.md.")
    print()
    print(DIVIDER_MAJOR)
    print("END OF SESSION PLAN")
    print(DIVIDER_MAJOR)


# ==========================================================================
# MAIN
# ==========================================================================

# ==========================================================================
# SELFTEST
# ==========================================================================

def run_selftest():
    """
    Adversarial self-test: verifies the template renderer produces valid
    output for a known-good slug, and that the unexpanded-placeholder
    check catches regressions.

    Exits with code 0 on pass, 1 on fail. TEST-09 compliance: includes
    both true-positive (broken template flagged) and true-negative
    (good template passes) cases.
    """
    failures = []

    # --- True-negative: render_agent_prompt with a real slug must produce
    #     output free of unexpanded placeholders and containing key markers.
    test_slug = "athanasius-of-alexandria"
    test_missing = 12
    rendered = render_agent_prompt(test_slug, test_missing)

    for marker in REQUIRED_PLACEHOLDERS:
        if marker in rendered:
            failures.append(
                f"Rendered output still contains unexpanded placeholder: "
                f"{marker}"
            )

    required_substrings = [
        test_slug,
        str(test_missing),
        "Pre-flight findings",
        "WORKING DIRECTORY:",
        "CHURCH_FATHERS_CURATION_HANDBOOK.md",
        f"Pre-flight findings for {test_slug}:",
    ]
    for s in required_substrings:
        if s not in rendered:
            failures.append(f"Rendered output missing required substring: {s!r}")

    # --- True-positive: a template string that still has placeholders
    #     must be detected by the same check as "broken".
    broken = "WORKING DIRECTORY: __REPO_ROOT__ still unexpanded"
    detected = any(p in broken for p in REQUIRED_PLACEHOLDERS)
    if not detected:
        failures.append(
            "Adversarial case failed: known-broken template with "
            "unexpanded placeholders was not detected."
        )

    # --- scan_gaps returns a list (even empty) and is sorted descending.
    gaps = scan_gaps()
    if not isinstance(gaps, list):
        failures.append(f"scan_gaps() did not return a list (got {type(gaps)})")
    else:
        counts = [m for m, _ in gaps]
        if counts != sorted(counts, reverse=True):
            failures.append("scan_gaps() output is not sorted by count desc")

    # --- KNOWN_BLOCKERS must contain strings (not None or other junk).
    for slug, note in KNOWN_BLOCKERS.items():
        if not isinstance(note, str) or not note:
            failures.append(f"KNOWN_BLOCKERS[{slug!r}] is not a non-empty string")

    if failures:
        print("SELFTEST FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("SELFTEST PASS")
    print(
        f"  - rendered {test_slug}: "
        f"{len(rendered)} chars, no unexpanded placeholders"
    )
    print(f"  - scan_gaps(): {len(gaps)} authors with gaps, sorted")
    print(f"  - KNOWN_BLOCKERS: {len(KNOWN_BLOCKERS)} entries, all valid")
    return 0


# ==========================================================================
# MAIN
# ==========================================================================

def validate_args(args):
    """Fail fast on invalid CLI inputs and environment issues."""
    errors = []
    if args.batches <= 0:
        errors.append(f"--batches must be > 0 (got {args.batches})")
    if args.batch_size <= 0:
        errors.append(f"--batch-size must be > 0 (got {args.batch_size})")
    if not DATA_DIR.is_dir():
        errors.append(
            f"DATA_DIR does not exist: {DATA_DIR}. Is this the right repo?"
        )
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)

    # Warn (not error) on COWORK_ROOT issues -- the plan still renders,
    # but the path baked into each agent prompt will be unreadable.
    if not COWORK_ROOT.is_dir():
        print(
            f"WARNING: COWORK_ROOT does not exist: {COWORK_ROOT}",
            file=sys.stderr,
        )
        print(
            "  Agent prompts will reference this path but agents won't "
            "be able to read CODING_DEFAULTS.md.",
            file=sys.stderr,
        )
        print(
            "  Set COWORK_ROOT env var to the correct location and rerun.",
            file=sys.stderr,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--batches", type=int, default=DEFAULT_BATCHES,
        help=f"How many batches to plan (default: {DEFAULT_BATCHES})",
    )
    parser.add_argument(
        "--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
        help=f"Agents per batch (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--include-blocked", action="store_true",
        help=(
            "Include known-blocker authors (they'll still get a BLOCKER "
            "note in the prompt -- useful for producing documented 0-patch "
            "commits)"
        ),
    )
    parser.add_argument(
        "--selftest", action="store_true",
        help="Run adversarial self-tests and exit (exit 0 pass, 1 fail).",
    )
    args = parser.parse_args()

    if args.selftest:
        sys.exit(run_selftest())

    validate_args(args)

    gaps = scan_gaps()
    total_missing = sum(m for m, _ in gaps)
    total_authors = len(gaps)

    blockers_skipped = []
    if args.include_blocked:
        available = gaps
    else:
        available = []
        for m, slug in gaps:
            if slug in KNOWN_BLOCKERS:
                blockers_skipped.append((m, slug))
            else:
                available.append((m, slug))

    wanted = args.batches * args.batch_size
    selected = available[:wanted]

    if not selected:
        print("No unblocked authors with gaps. Nothing to do.")
        if blockers_skipped:
            print()
            print(
                "All authors with gaps are in KNOWN_BLOCKERS. "
                "Rerun with --include-blocked to emit documented-blank "
                "prompts, or update UNBLOCK_PLAN.md and acquire the "
                "missing sources."
            )
        return

    emit_plan(
        selected=selected,
        blockers_skipped=blockers_skipped,
        total_missing=total_missing,
        total_authors=total_authors,
        batches=args.batches,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
