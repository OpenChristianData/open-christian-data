"""
fix_misattributed_entries.py

One-shot idempotent patch script: fix 3 upstream misattribution bugs in the
church_fathers dataset. Safe to re-run -- exits cleanly if the work is already done.

Cases handled:
  Case 1: Delete 26 Paterius duplicates from pacian-of-barcelona.json
  Case 2: Move 9 Luke entries from isidore-of-seville to isidore-of-pelusium
  Case 3: Move 1 Matt entry from athanasius-of-alexandria to vigilius-of-thapsus
  Case 4: Skipped -- correct author uncertain (possibly Cyril of Alexandria, but not confirmed)

REL-03 exemption: one-shot patch script, prints summary to stdout.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "church-fathers"
VALIDATE_PY = REPO_ROOT / "build" / "validate.py"

# Case 1: entry IDs to DELETE from pacian-of-barcelona.json
PACIAN_REMOVE_IDS = {
    "pacian-of-barcelona.Exod.3.2.unknown",
    "pacian-of-barcelona.Exod.5.20.unknown",
    "pacian-of-barcelona.Exod.8.26.unknown",
    "pacian-of-barcelona.Exod.20.24.unknown",
    "pacian-of-barcelona.Exod.26.19.unknown",
    "pacian-of-barcelona.Exod.26.32.unknown",
    "pacian-of-barcelona.Exod.33.21.unknown",
    "pacian-of-barcelona.Exod.34.7.unknown",
    "pacian-of-barcelona.Lev.1.6.unknown",
    "pacian-of-barcelona.Lev.6.9.unknown",
    "pacian-of-barcelona.Lev.7.3.unknown",
    "pacian-of-barcelona.Lev.7.33.unknown",
    "pacian-of-barcelona.Lev.13.57.unknown",
    "pacian-of-barcelona.Lev.19.23.unknown",
    "pacian-of-barcelona.Num.7.89.unknown",
    "pacian-of-barcelona.Num.8.7.unknown",
    "pacian-of-barcelona.Num.8.24.unknown",
    "pacian-of-barcelona.Num.9.8.unknown",
    "pacian-of-barcelona.Num.10.2.unknown",
    "pacian-of-barcelona.Num.10.29.unknown",
    "pacian-of-barcelona.Num.19.15.unknown",
    "pacian-of-barcelona.Num.24.15.unknown",
    "pacian-of-barcelona.Num.24.21.unknown",
    "pacian-of-barcelona.Num.32.4.unknown",
    "pacian-of-barcelona.Num.35.28.unknown",
    "pacian-of-barcelona.Num.6.18.unknown",  # MEDIUM confidence, still Paterius content
}

# Case 2: entry IDs to MOVE from isidore-of-seville -> isidore-of-pelusium
ISIDORE_MOVE_IDS = [
    "isidore-of-seville.Luke.6.1.unknown",
    "isidore-of-seville.Luke.6.43.unknown",
    "isidore-of-seville.Luke.7.24.unknown",
    "isidore-of-seville.Luke.8.1.unknown",
    "isidore-of-seville.Luke.9.10.unknown",
    "isidore-of-seville.Luke.10.3.unknown",
    "isidore-of-seville.Luke.12.41.unknown",
    "isidore-of-seville.Luke.18.31.unknown",
    "isidore-of-seville.Luke.24.25.unknown",
]

# Case 3: entry ID to MOVE from athanasius-of-alexandria -> vigilius-of-thapsus
ATHANASIUS_MOVE_ID = "athanasius-of-alexandria.Matt.1.1.unknown"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def run_validate(json_path: Path) -> bool:
    """Run build/validate.py on the given file. Returns True if it passed."""
    try:
        subprocess.run(
            [sys.executable, str(VALIDATE_PY), str(json_path)],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"  VALIDATION FAILED: {json_path.name}")
        print(e.stdout)
        print(e.stderr)
        return False
    print(f"  validate OK: {json_path.name}")
    return True


# ---------------------------------------------------------------------------
# Case 1: Delete 26 Paterius duplicates from pacian-of-barcelona
# ---------------------------------------------------------------------------

def case1_pacian() -> bool:
    """Remove 26 Paterius-content duplicates from pacian-of-barcelona.json.

    Returns True on success.
    """
    path = DATA_DIR / "pacian-of-barcelona.json"
    data = load_json(path)
    entries = data["data"]
    before = len(entries)

    # Pre-flight: verify all 26 IDs exist (or have already been removed)
    existing_ids = {e["entry_id"] for e in entries}
    already_removed = PACIAN_REMOVE_IDS - existing_ids
    to_remove = PACIAN_REMOVE_IDS & existing_ids

    if len(to_remove) == 0:
        print(f"Case 1 (pacian-of-barcelona): already applied -- nothing to remove")
        print(f"  Remaining entries: {before}")
        return True

    if len(to_remove) + len(already_removed) != 26:
        print(f"Case 1 ERROR: expected 26 target IDs, got {len(to_remove)} present + {len(already_removed)} missing")
        return False

    print(f"Case 1 (pacian-of-barcelona): pre-flight passed -- removing {len(to_remove)} entries")

    # Remove the target entries
    data["data"] = [e for e in entries if e["entry_id"] not in PACIAN_REMOVE_IDS]
    after = len(data["data"])
    removed = before - after

    save_json(path, data)

    # Post-check: confirm legitimate entries still present
    with_source = [e for e in data["data"] if e.get("source_title")]
    print(f"  Removed: {removed}  |  Remaining: {after}  |  Entries with source_title: {len(with_source)}")
    return True


# ---------------------------------------------------------------------------
# Case 2: Move 9 Luke entries from isidore-of-seville -> isidore-of-pelusium
# ---------------------------------------------------------------------------

def case2_isidore() -> bool:
    """Move 9 Luke entries from isidore-of-seville to isidore-of-pelusium.

    Returns True on success.
    """
    seville_path = DATA_DIR / "isidore-of-seville.json"
    pelus_path = DATA_DIR / "isidore-of-pelusium.json"

    seville_data = load_json(seville_path)
    pelus_data = load_json(pelus_path)

    seville_ids = {e["entry_id"] for e in seville_data["data"]}
    pelus_ids = {e["entry_id"] for e in pelus_data["data"]}

    # Idempotency: check how many source IDs still exist
    present_in_seville = [i for i in ISIDORE_MOVE_IDS if i in seville_ids]
    new_pelus_ids = [i.replace("isidore-of-seville.", "isidore-of-pelusium.") for i in ISIDORE_MOVE_IDS]
    already_in_pelus = [i for i in new_pelus_ids if i in pelus_ids]

    if len(present_in_seville) == 0:
        print(f"Case 2 (isidore-of-seville -> isidore-of-pelusium): already applied -- nothing to move")
        return True

    # Pre-flight collision check
    present_src_as_new = [
        i.replace("isidore-of-seville.", "isidore-of-pelusium.")
        for i in present_in_seville
    ]
    collisions = [i for i in present_src_as_new if i in pelus_ids]
    if collisions:
        print(f"Case 2 ERROR: collision in isidore-of-pelusium: {collisions}")
        print(f"  Fix: manually inspect isidore-of-pelusium.json, remove the duplicate entry, then re-run.")
        return False

    print(f"Case 2 (isidore-of-seville -> isidore-of-pelusium): moving {len(present_in_seville)} entries")

    seville_before = len(seville_data["data"])
    pelus_before = len(pelus_data["data"])

    # Extract entries to move
    move_set = set(present_in_seville)
    to_move = [e for e in seville_data["data"] if e["entry_id"] in move_set]
    seville_data["data"] = [e for e in seville_data["data"] if e["entry_id"] not in move_set]

    # Update entry_id and author on each moved entry
    for entry in to_move:
        entry["entry_id"] = entry["entry_id"].replace("isidore-of-seville.", "isidore-of-pelusium.")
        entry["author"] = "Isidore of Pelusium"

    pelus_data["data"].extend(to_move)

    save_json(seville_path, seville_data)
    save_json(pelus_path, pelus_data)

    print(f"  isidore-of-seville: {seville_before} -> {len(seville_data['data'])} entries")
    print(f"  isidore-of-pelusium: {pelus_before} -> {len(pelus_data['data'])} entries")
    return True


# ---------------------------------------------------------------------------
# Case 3: Move 1 Matt entry from athanasius-of-alexandria -> vigilius-of-thapsus
# ---------------------------------------------------------------------------

def case3_athanasius() -> bool:
    """Move 1 Matthew entry from athanasius-of-alexandria to vigilius-of-thapsus.

    Returns True on success.
    """
    ath_path = DATA_DIR / "athanasius-of-alexandria.json"
    vig_path = DATA_DIR / "vigilius-of-thapsus.json"

    ath_data = load_json(ath_path)
    vig_data = load_json(vig_path)

    ath_ids = {e["entry_id"] for e in ath_data["data"]}
    vig_ids = {e["entry_id"] for e in vig_data["data"]}
    new_id = ATHANASIUS_MOVE_ID.replace("athanasius-of-alexandria.", "vigilius-of-thapsus.")

    # Idempotency
    if ATHANASIUS_MOVE_ID not in ath_ids:
        print(f"Case 3 (athanasius-of-alexandria -> vigilius-of-thapsus): already applied")
        return True

    # Pre-flight collision check
    if new_id in vig_ids:
        print(f"Case 3 ERROR: collision in vigilius-of-thapsus: {new_id}")
        print(f"  Fix: manually inspect vigilius-of-thapsus.json, remove the duplicate entry, then re-run.")
        return False

    print(f"Case 3 (athanasius-of-alexandria -> vigilius-of-thapsus): moving 1 entry")

    ath_before = len(ath_data["data"])
    vig_before = len(vig_data["data"])

    # Extract the entry
    entry_to_move = next(e for e in ath_data["data"] if e["entry_id"] == ATHANASIUS_MOVE_ID)
    ath_data["data"] = [e for e in ath_data["data"] if e["entry_id"] != ATHANASIUS_MOVE_ID]

    # Update entry_id and author
    entry_to_move["entry_id"] = new_id
    entry_to_move["author"] = "Vigilius of Thapsus"

    vig_data["data"].append(entry_to_move)

    save_json(ath_path, ath_data)
    save_json(vig_path, vig_data)

    print(f"  athanasius-of-alexandria: {ath_before} -> {len(ath_data['data'])} entries")
    print(f"  vigilius-of-thapsus: {vig_before} -> {len(vig_data['data'])} entries")
    return True


# ---------------------------------------------------------------------------
# Case 4: Skipped
# ---------------------------------------------------------------------------

def case4_cyril_skip() -> None:
    print("Case 4 skipped -- correct author uncertain (possibly Cyril of Alexandria, but not confirmed).")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=== fix_misattributed_entries.py ===")
    print()

    start = time.monotonic()
    errors = []

    # Run all three cases -- continue past failures to maximise progress
    if not case1_pacian():
        errors.append("Case 1 failed")
    print()

    if not case2_isidore():
        errors.append("Case 2 failed")
    print()

    if not case3_athanasius():
        errors.append("Case 3 failed")
    print()

    case4_cyril_skip()
    print()

    # Always validate all affected files, even if some cases failed --
    # successfully-mutated files should still be verified (REL-08).
    print("--- Validation ---")
    affected = [
        DATA_DIR / "pacian-of-barcelona.json",
        DATA_DIR / "isidore-of-seville.json",
        DATA_DIR / "isidore-of-pelusium.json",
        DATA_DIR / "athanasius-of-alexandria.json",
        DATA_DIR / "vigilius-of-thapsus.json",
    ]
    all_passed = True
    for p in affected:
        if not run_validate(p):
            all_passed = False

    elapsed = time.monotonic() - start
    print()
    print(f"--- Summary ({elapsed:.1f}s) ---")
    print(f"  Cases run: 3  |  Skipped: 1 (Case 4, author uncertain)")
    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
    if not all_passed:
        print("  One or more validations FAILED.")
    if errors or not all_passed:
        sys.exit(1)
    print("  All changes applied and validated successfully.")


if __name__ == "__main__":
    main()
