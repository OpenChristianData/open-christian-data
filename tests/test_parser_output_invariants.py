"""test_parser_output_invariants.py
Smoke tests for shipped parser output JSON.

Tests output invariants on shipped data to catch 'parser regenerated garbage'
without the cost of re-running a full parse.

Targets:
  - data/commentaries/expositors-bible/acts.json  (OSIS ref validation)
  - data/commentaries/expositors-bible/amos.json  (_CCEL_OSISREF_CORRECTIONS spot-check)
  - data/reference/schaff-herzog-encyclopedia.json (structure + content guards)

Pre-flight field names verified against actual data (PIPE-18):
  - Expositor's Bible: meta.title (not source_title), verse_range_osis (not anchor_ref),
    commentary_text (not text)
  - Schaff-Herzog: definition_blocks (not body)

Retro finding 2026-04-14: new parsers shipped without automated tests.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.scripts.validate_osis import validate_osis_ref  # noqa: E402
from build.parsers.ccel_expositors_bible import _CCEL_OSISREF_CORRECTIONS  # noqa: E402

EXPOSITORS_ACTS = REPO_ROOT / "data" / "commentaries" / "expositors-bible" / "acts.json"
EXPOSITORS_AMOS = REPO_ROOT / "data" / "commentaries" / "expositors-bible" / "amos.json"
SCHAFF_FILE = REPO_ROOT / "data" / "reference" / "schaff-herzog-encyclopedia.json"

_SCHAFF_FRONT_MATTER = {"PREFACE", "SAN FRANCISCO CUSTOM HOUSE 1846"}

# Every test in this module loads large committed JSON files from data/ — slow by design.
pytestmark = pytest.mark.slow


# ---------------------------------------------------------------------------
# Expositor's Bible: structure invariants (acts.json -- 0 invalid OSIS refs)
# ---------------------------------------------------------------------------

def test_expositors_file_loads():
    d = json.loads(EXPOSITORS_ACTS.read_text(encoding="utf-8"))
    assert "meta" in d
    assert "data" in d


def test_expositors_meta_title():
    d = json.loads(EXPOSITORS_ACTS.read_text(encoding="utf-8"))
    assert d["meta"]["title"] == "The Expositor's Bible"


def test_expositors_data_nonempty():
    d = json.loads(EXPOSITORS_ACTS.read_text(encoding="utf-8"))
    assert len(d["data"]) > 0


def test_expositors_entry_keys():
    """Every entry has the required schema keys."""
    d = json.loads(EXPOSITORS_ACTS.read_text(encoding="utf-8"))
    for entry in d["data"]:
        assert "entry_id" in entry, f"missing entry_id in entry"
        assert "verse_range_osis" in entry, f"missing verse_range_osis: {entry.get('entry_id')}"
        assert "commentary_text" in entry, f"missing commentary_text: {entry.get('entry_id')}"


def test_expositors_unique_entry_ids():
    """No duplicate entry_ids."""
    d = json.loads(EXPOSITORS_ACTS.read_text(encoding="utf-8"))
    ids = [e["entry_id"] for e in d["data"]]
    assert len(ids) == len(set(ids)), "duplicate entry_id values found"


def test_expositors_verse_range_osis_all_valid():
    """Every non-None verse_range_osis in acts.json passes validate_osis_ref.
    Uses acts.json (not amos.json) -- amos has known out-of-range refs
    from a multi-book volume (chapters beyond Amos 9)."""
    d = json.loads(EXPOSITORS_ACTS.read_text(encoding="utf-8"))
    for entry in d["data"]:
        ref = entry.get("verse_range_osis")
        if ref is None:
            continue
        ok, reason = validate_osis_ref(ref)
        assert ok, f"{entry['entry_id']}: verse_range_osis {ref!r} invalid: {reason}"


# ---------------------------------------------------------------------------
# Expositor's Bible: _CCEL_OSISREF_CORRECTIONS spot-check (amos.json)
# ---------------------------------------------------------------------------

def test_osisref_corrections_not_in_amos_cross_refs():
    """Bad source refs in _CCEL_OSISREF_CORRECTIONS must not appear in
    any shipped cross_references (they must have been dropped or corrected)."""
    d = json.loads(EXPOSITORS_AMOS.read_text(encoding="utf-8"))
    all_refs = set()
    for entry in d["data"]:
        all_refs.update(entry.get("cross_references") or [])
    bad_refs = set(_CCEL_OSISREF_CORRECTIONS.keys())
    leaked = bad_refs & all_refs
    assert not leaked, f"corrected-away refs still in amos cross_references: {leaked}"


def test_osisref_correction_job_remapped_in_amos():
    """Job.40.26 -> Job.41.2 correction: corrected ref must appear
    in Amos-3-1 (the entry citing the Expositor's note on Hebrew Job 40)."""
    d = json.loads(EXPOSITORS_AMOS.read_text(encoding="utf-8"))
    entry = next(
        (e for e in d["data"] if e["entry_id"] == "expositors-bible.Amos-3-1"),
        None,
    )
    assert entry is not None, "expositors-bible.Amos-3-1 not found in amos.json"
    assert "Job.41.2" in (entry.get("cross_references") or []), (
        "corrected ref Job.41.2 missing from Amos-3-1 cross_references"
    )


# ---------------------------------------------------------------------------
# Schaff-Herzog: structure + content guards
# ---------------------------------------------------------------------------

def test_schaff_file_loads():
    d = json.loads(SCHAFF_FILE.read_text(encoding="utf-8"))
    assert "meta" in d
    assert "data" in d


def test_schaff_entry_count():
    """Entry count >= 8000 (baseline 8,358 as of 2026-04-14)."""
    d = json.loads(SCHAFF_FILE.read_text(encoding="utf-8"))
    count = len(d["data"])
    assert count >= 8000, f"expected >= 8000 entries, got {count}"


def test_schaff_entry_keys():
    """Every entry has the three required keys.
    Note: actual field is definition_blocks (not body)."""
    d = json.loads(SCHAFF_FILE.read_text(encoding="utf-8"))
    for entry in d["data"]:
        assert "entry_id" in entry
        assert "term" in entry
        assert "definition_blocks" in entry


def test_schaff_unique_entry_ids():
    """No duplicate entry_ids (catches the re-run merge bug)."""
    d = json.loads(SCHAFF_FILE.read_text(encoding="utf-8"))
    ids = [e["entry_id"] for e in d["data"]]
    dupes = len(ids) - len(set(ids))
    assert dupes == 0, f"{dupes} duplicate entry_id(s) found"


def test_schaff_no_the_prefix_terms():
    """No entry term starts with 'THE ' (running header leak)."""
    d = json.loads(SCHAFF_FILE.read_text(encoding="utf-8"))
    leaked = [
        e["term"] for e in d["data"]
        if isinstance(e.get("term"), str) and e["term"].upper().startswith("THE ")
    ]
    assert not leaked, f"running header leaked as article term: {leaked[:5]}"


def test_schaff_no_front_matter_terms():
    """No front-matter entry survived into data (parsing overrun guard)."""
    d = json.loads(SCHAFF_FILE.read_text(encoding="utf-8"))
    found = [e["term"] for e in d["data"] if e.get("term") in _SCHAFF_FRONT_MATTER]
    assert not found, f"front-matter entries in data: {found}"


# ============================================================================
# Spurgeon MTP (data/sermons/spurgeon-mtp/sermons-<start>-<end>.json)
# ============================================================================

import glob as _glob
import os as _os
import re as _re
from collections import Counter as _Counter

from build.parsers.spurgeon_mtp import natural_sort_key as _natural_sort_key

SPURGEON_CHUNK_GLOB = str(REPO_ROOT / "data" / "sermons" / "spurgeon-mtp" / "sermons-*.json")


def _load_all_spurgeon_chunks():
    paths = sorted(_glob.glob(SPURGEON_CHUNK_GLOB), key=_natural_sort_key)
    return [(p, json.loads(open(p, encoding="utf-8").read())) for p in paths]


def test_spurgeon_total_entry_count_is_3547():
    chunks = _load_all_spurgeon_chunks()
    total = sum(len(obj["data"]) for _, obj in chunks)
    assert total == 3547, f"expected 3547 entries, got {total}"


def test_spurgeon_sermon_ids_are_unique_across_chunks():
    chunks = _load_all_spurgeon_chunks()
    ids = [e["sermon_id"] for _, obj in chunks for e in obj["data"]]
    dupes = [sid for sid, n in _Counter(ids).items() if n > 1]
    assert not dupes, f"duplicate sermon_ids across chunks: {dupes[:10]}"


def test_spurgeon_every_chunk_has_meta_block():
    chunks = _load_all_spurgeon_chunks()
    for path, obj in chunks:
        assert "meta" in obj, f"missing meta in {path}"
        assert obj["meta"]["id"] == "spurgeon-mtp", f"wrong meta.id in {path}"
        assert obj["meta"].get("schema_type") == "sermon", f"wrong schema_type in {path}"


def test_spurgeon_chunks_are_contiguous_and_cover_1_to_3547():
    """Each chunk's filename range must be contiguous with the next; together
    they must cover sermons 1..3547 with no gaps or overlaps."""
    paths = sorted(_glob.glob(SPURGEON_CHUNK_GLOB), key=_natural_sort_key)
    ranges = []
    for p in paths:
        m = _re.search(r"sermons-(\d+)-(\d+)\.json$", _os.path.basename(p))
        assert m, f"filename doesn't match sermons-<N>-<N>.json: {p}"
        ranges.append((int(m.group(1)), int(m.group(2))))
    # First chunk starts at 1
    assert ranges[0][0] == 1, f"first chunk doesn't start at 1: {ranges[0]}"
    # Last chunk ends at 3547
    assert ranges[-1][1] == 3547, f"last chunk doesn't end at 3547: {ranges[-1]}"
    # Consecutive chunks must be adjacent
    for (_, prev_end), (next_start, _) in zip(ranges, ranges[1:], strict=False):
        assert next_start == prev_end + 1, f"gap between {prev_end} and {next_start}"


def test_spurgeon_no_chunk_exceeds_50mb():
    """GitHub warns at 50 MB. Ensure no chunk file crosses that threshold."""
    for path in _glob.glob(SPURGEON_CHUNK_GLOB):
        size_mb = _os.path.getsize(path) / (1024 * 1024)
        assert size_mb < 50, f"{path} is {size_mb:.1f} MB — exceeds 50 MB threshold"


# ---------------------------------------------------------------------------
# Run directly for quick feedback
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
