"""Patch missing source_title for ambrosiaster church_fathers entries.

75 entries with entry_id suffix .unknown have empty source_title because the
upstream TOML files lacked the source_title field.  All 75 are deterministic:

  - Pauline epistles (1Cor, 2Cor, Col, Phlm, Rom): Commentary on Paul's Epistles
  - 1Thess: Commentary on the First Letter to the Thessalonians
  - 2Thess: Commentary on the Second Letter to the Thessalonians
  - 1Tim: Commentary on the First Letter to Timothy
  - Titus: Commentary on the Letter to Titus
  - Gal.5.10: Epistle to the Galatians 5.10 (matches adjacent entry format)
  - Acts (3 entries): Questions on the Old and New Testament
    (Ambrosiaster has no Acts commentary; these come from his Quaestiones
    Veteris et Novi Testamenti -- confirmed via Wikipedia and ACCS attribution)

Source-title strings match the exact byte values used in adjacent filled entries
in data/church-fathers/ambrosiaster.json (verified via repr() / hex dump).
"""

import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = REPO_ROOT / "data" / "church-fathers" / "ambrosiaster.json"

# ---------------------------------------------------------------------------
# Canonical source_title strings (U+2019 right single quotation mark in PAUL\u2019S)
# ---------------------------------------------------------------------------

_CPE = "COMMENTARY ON PAUL\u2019S EPISTLES"
_CFLT = "COMMENTARY ON THE FIRST LETTER TO THE THESSALONIANS"
_CSLT = "COMMENTARY ON THE SECOND LETTER TO THE THESSALONIANS"
_CFLTIM = "COMMENTARY ON THE FIRST LETTER TO TIMOTHY"
_CLTT = "COMMENTARY ON THE LETTER TO TITUS"
_EPIG510 = "EPISTLE TO THE GALATIANS 5.10"
_QONT = "QUESTIONS ON THE OLD AND NEW TESTAMENT"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title
# ---------------------------------------------------------------------------

PATCH = {
    # --- 1 Corinthians (5) ---
    "ambrosiaster.1Cor.10.20.unknown": _CPE,
    "ambrosiaster.1Cor.12.16.unknown": _CPE,
    "ambrosiaster.1Cor.1.19.unknown": _CPE,
    "ambrosiaster.1Cor.3.1.unknown": _CPE,
    "ambrosiaster.1Cor.6.16.unknown": _CPE,
    # --- 1 Thessalonians (1) ---
    "ambrosiaster.1Thess.1.2.unknown": _CFLT,
    # --- 1 Timothy (1) ---
    "ambrosiaster.1Tim.2.1.unknown": _CFLTIM,
    # --- 2 Corinthians (11) ---
    "ambrosiaster.2Cor.10.12.unknown": _CPE,
    "ambrosiaster.2Cor.11.18.unknown": _CPE,
    "ambrosiaster.2Cor.12.17.unknown": _CPE,
    "ambrosiaster.2Cor.13.5.unknown": _CPE,
    "ambrosiaster.2Cor.1.15.unknown": _CPE,
    "ambrosiaster.2Cor.1.18.unknown": _CPE,
    "ambrosiaster.2Cor.4.17.unknown": _CPE,
    "ambrosiaster.2Cor.4.4.unknown": _CPE,
    "ambrosiaster.2Cor.7.15.unknown": _CPE,
    "ambrosiaster.2Cor.8.7.unknown": _CPE,
    "ambrosiaster.2Cor.8.9.unknown": _CPE,
    # --- 2 Thessalonians (17) ---
    "ambrosiaster.2Thess.1.1.unknown": _CSLT,
    "ambrosiaster.2Thess.1.10.unknown": _CSLT,
    "ambrosiaster.2Thess.1.3.unknown": _CSLT,
    "ambrosiaster.2Thess.1.8.unknown": _CSLT,
    "ambrosiaster.2Thess.2.10.unknown": _CSLT,
    "ambrosiaster.2Thess.2.12.unknown": _CSLT,
    "ambrosiaster.2Thess.2.14.unknown": _CSLT,
    "ambrosiaster.2Thess.2.2.unknown": _CSLT,
    "ambrosiaster.2Thess.2.3.unknown": _CSLT,
    "ambrosiaster.2Thess.2.4.unknown": _CSLT,
    "ambrosiaster.2Thess.2.7.unknown": _CSLT,
    "ambrosiaster.2Thess.3.10.unknown": _CSLT,
    "ambrosiaster.2Thess.3.12.unknown": _CSLT,
    "ambrosiaster.2Thess.3.16.unknown": _CSLT,
    "ambrosiaster.2Thess.3.4.unknown": _CSLT,
    "ambrosiaster.2Thess.3.6.unknown": _CSLT,
    "ambrosiaster.2Thess.3.8.unknown": _CSLT,
    # --- Acts (3) -- Quaestiones Veteris et Novi Testamenti ---
    "ambrosiaster.Acts.1.17.unknown": _QONT,
    "ambrosiaster.Acts.3.15.unknown": _QONT,
    "ambrosiaster.Acts.3.17.unknown": _QONT,
    # --- Colossians (17) ---
    "ambrosiaster.Col.1.13.unknown": _CPE,
    "ambrosiaster.Col.1.16.unknown": _CPE,
    "ambrosiaster.Col.1.18.unknown": _CPE,
    "ambrosiaster.Col.1.19.unknown": _CPE,
    "ambrosiaster.Col.1.21.unknown": _CPE,
    "ambrosiaster.Col.1.24.unknown": _CPE,
    "ambrosiaster.Col.1.27.unknown": _CPE,
    "ambrosiaster.Col.2.11.unknown": _CPE,
    "ambrosiaster.Col.2.14.unknown": _CPE,
    "ambrosiaster.Col.2.18.unknown": _CPE,
    "ambrosiaster.Col.2.20.unknown": _CPE,
    "ambrosiaster.Col.2.8.unknown": _CPE,
    "ambrosiaster.Col.2.9.unknown": _CPE,
    "ambrosiaster.Col.3.14.unknown": _CPE,
    "ambrosiaster.Col.3.22.unknown": _CPE,
    "ambrosiaster.Col.4.5.unknown": _CPE,
    "ambrosiaster.Col.4.7.unknown": _CPE,
    # --- Galatians (1) -- matches adjacent entry format ---
    "ambrosiaster.Gal.5.10.unknown": _EPIG510,
    # --- Philemon (15) ---
    "ambrosiaster.Phlm.1.1.unknown": _CPE,
    "ambrosiaster.Phlm.1.1.unknown-2": _CPE,
    "ambrosiaster.Phlm.1.10.unknown": _CPE,
    "ambrosiaster.Phlm.1.11.unknown": _CPE,
    "ambrosiaster.Phlm.1.16.unknown": _CPE,
    "ambrosiaster.Phlm.1.17.unknown": _CPE,
    "ambrosiaster.Phlm.1.18.unknown": _CPE,
    "ambrosiaster.Phlm.1.2.unknown": _CPE,
    "ambrosiaster.Phlm.1.21.unknown": _CPE,
    "ambrosiaster.Phlm.1.22.unknown": _CPE,
    "ambrosiaster.Phlm.1.24.unknown": _CPE,
    "ambrosiaster.Phlm.1.25.unknown": _CPE,
    "ambrosiaster.Phlm.1.3.unknown": _CPE,
    "ambrosiaster.Phlm.1.7.unknown": _CPE,
    "ambrosiaster.Phlm.1.9.unknown": _CPE,
    # --- Romans (3) ---
    "ambrosiaster.Rom.11.12.unknown": _CPE,
    "ambrosiaster.Rom.1.10.unknown": _CPE,
    "ambrosiaster.Rom.9.27.unknown": _CPE,
    # --- Titus (1) ---
    "ambrosiaster.Titus.1.5.unknown": _CLTT,
}

EXPECTED_PATCH_COUNT = 75


def main() -> None:
    assert len(PATCH) == EXPECTED_PATCH_COUNT, (
        f"PATCH dict has {len(PATCH)} entries, expected {EXPECTED_PATCH_COUNT}"
    )

    print(f"Loading {DATA_FILE}")
    with open(DATA_FILE, encoding="utf-8") as f:
        doc = json.load(f)

    entries = doc["data"]

    # Build lookup by entry_id for fast access
    by_id = {e["entry_id"]: e for e in entries}

    # Verify all patch keys exist in the file before writing anything
    missing_ids = [eid for eid in PATCH if eid not in by_id]
    if missing_ids:
        print(f"ERROR: {len(missing_ids)} patch key(s) not found in data file:")
        for eid in missing_ids:
            print(f"  {eid}")
        sys.exit(1)

    set_count = 0
    skip_count = 0

    for entry_id, source_title in PATCH.items():
        entry = by_id[entry_id]
        if entry.get("source_title"):
            skip_count += 1
        else:
            entry["source_title"] = source_title
            set_count += 1

    print(f"Set: {set_count}  |  Skipped (already filled): {skip_count}")

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Saved {DATA_FILE}")

    # Quick spot-check: confirm 0 source_title warnings remain for this file
    remaining = sum(1 for e in entries if not e.get("source_title"))
    print(f"Remaining empty source_title: {remaining}")
    if remaining:
        print("WARNING: some entries still have no source_title -- check manually")


if __name__ == "__main__":
    main()
