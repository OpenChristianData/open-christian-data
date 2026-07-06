"""
Patch source_title for Thietland of Einsiedeln (19 of 24 entries).

Thietland of Einsiedeln (died c. 964) is known for a single work:
Commentary on 2 Thessalonians. Modern scholarly edition: Cartwright, Steven R.
and Hughes, Kevin L. (eds./trans.), "Second Thessalonians: Two Early Medieval
Apocalyptic Commentaries," Medieval Institute Publications, 2001 (ISBN 1-58044-018-5).
Academic sources confirm the work is an apocalyptic commentary containing
"digressions on the Antichrist and the End of the Millennium."

Confidence tiers:
  HIGH   = single known work; entry filed under 2 Thessalonians in upstream database;
            work title confirmed by multiple academic sources (PIPE-12 satisfied)
  MEDIUM = Revelation 20 entries (Rev 20:1-2, 20:7): likely digressions within
            the 2 Thess commentary (millennium content, no other known work),
            but no primary-source quote-match confirmed -- left blank per project rules

Verification spot-check (BEFORE commit):
  - thietland-of-einsiedeln.2Thess.1.3.unknown (wmich.edu/medievalpublications/teams/commentary)
      confirmed: Cartwright/Hughes 2001 establishes "Commentary on 2 Thessalonians"
      as the sole known work of Thietland; entry is filed under 2 Thess in upstream DB
  - thietland-of-einsiedeln.2Thess.1.8.unknown -- internal quote reference check
      confirmed: quote explicitly cites "Apocalypse of John... Rev 20:9" as a
      reference FROM the 2 Thess commentary, proving the 2 Thess work is the source
  - thietland-of-einsiedeln.2Thess.2.5.unknown -- content check
      confirmed: "Christ would not come unless the Antichrist came first" -- core
      Antichrist/apocalyptic argument, consistent with known 2 Thess commentary focus

5 Revelation 20 entries left blank (MEDIUM confidence): Rev.20.1.unknown,
Rev.20.1.unknown-2, Rev.20.1.unknown-3, Rev.20.2.unknown, Rev.20.7.unknown.

Run twice to verify idempotency (TEST-05).
"""

import json
from collections import Counter
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "church-fathers" / "thietland-of-einsiedeln.json"

HIGH = "HIGH"

OVERRIDES: dict[str, tuple[str, str]] = {
    # ------------------------------------------------------------------
    # 2 THESSALONIANS (chapter 1)
    # ------------------------------------------------------------------
    "thietland-of-einsiedeln.2Thess.1.3.unknown":  ("Commentary on 2 Thessalonians", HIGH),
    "thietland-of-einsiedeln.2Thess.1.4.unknown":  ("Commentary on 2 Thessalonians", HIGH),
    "thietland-of-einsiedeln.2Thess.1.5.unknown":  ("Commentary on 2 Thessalonians", HIGH),
    "thietland-of-einsiedeln.2Thess.1.6.unknown":  ("Commentary on 2 Thessalonians", HIGH),
    "thietland-of-einsiedeln.2Thess.1.7.unknown":  ("Commentary on 2 Thessalonians", HIGH),
    "thietland-of-einsiedeln.2Thess.1.8.unknown":  ("Commentary on 2 Thessalonians", HIGH),
    "thietland-of-einsiedeln.2Thess.1.9.unknown":  ("Commentary on 2 Thessalonians", HIGH),
    "thietland-of-einsiedeln.2Thess.1.10.unknown": ("Commentary on 2 Thessalonians", HIGH),
    "thietland-of-einsiedeln.2Thess.1.11.unknown": ("Commentary on 2 Thessalonians", HIGH),
    "thietland-of-einsiedeln.2Thess.1.12.unknown": ("Commentary on 2 Thessalonians", HIGH),
    # ------------------------------------------------------------------
    # 2 THESSALONIANS (chapter 2)
    # ------------------------------------------------------------------
    "thietland-of-einsiedeln.2Thess.2.3.unknown":  ("Commentary on 2 Thessalonians", HIGH),
    "thietland-of-einsiedeln.2Thess.2.5.unknown":  ("Commentary on 2 Thessalonians", HIGH),
    "thietland-of-einsiedeln.2Thess.2.8.unknown":  ("Commentary on 2 Thessalonians", HIGH),
    "thietland-of-einsiedeln.2Thess.2.11.unknown": ("Commentary on 2 Thessalonians", HIGH),
    "thietland-of-einsiedeln.2Thess.2.12.unknown": ("Commentary on 2 Thessalonians", HIGH),
    "thietland-of-einsiedeln.2Thess.2.13.unknown": ("Commentary on 2 Thessalonians", HIGH),
    "thietland-of-einsiedeln.2Thess.2.15.unknown": ("Commentary on 2 Thessalonians", HIGH),
    # ------------------------------------------------------------------
    # 2 THESSALONIANS (chapter 3)
    # ------------------------------------------------------------------
    "thietland-of-einsiedeln.2Thess.3.1.unknown":  ("Commentary on 2 Thessalonians", HIGH),
    "thietland-of-einsiedeln.2Thess.3.12.unknown": ("Commentary on 2 Thessalonians", HIGH),
    # ------------------------------------------------------------------
    # REVELATION 20 -- MEDIUM confidence, left blank (not included)
    # ------------------------------------------------------------------
    # thietland-of-einsiedeln.Rev.20.1.unknown    -- MEDIUM
    # thietland-of-einsiedeln.Rev.20.1.unknown-2  -- MEDIUM
    # thietland-of-einsiedeln.Rev.20.1.unknown-3  -- MEDIUM
    # thietland-of-einsiedeln.Rev.20.2.unknown    -- MEDIUM
    # thietland-of-einsiedeln.Rev.20.7.unknown    -- MEDIUM (also <20 words)
}

_EXPECTED_PATCH_COUNT = 19


def main() -> None:
    assert len(OVERRIDES) == _EXPECTED_PATCH_COUNT, (
        f"OVERRIDES has {len(OVERRIDES)} entries, expected {_EXPECTED_PATCH_COUNT}. "
        "Update _EXPECTED_PATCH_COUNT after adding or removing entries."
    )

    print(f"Loading {DATA_FILE}")
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    entries = data["data"]
    blank_before = sum(1 for e in entries if not e.get("source_title"))
    print(f"Blank source_title entries before patch: {blank_before}")

    patched = 0
    skipped = 0
    confidence_counts: Counter = Counter()
    patched_titles: Counter = Counter()
    unresolved: list[str] = []

    for entry in entries:
        entry_id = entry["entry_id"]
        if entry.get("source_title"):
            skipped += 1
            continue
        if entry_id in OVERRIDES:
            title, confidence = OVERRIDES[entry_id]
            entry["source_title"] = title
            patched += 1
            confidence_counts[confidence] += 1
            patched_titles[title] += 1
        else:
            unresolved.append(entry_id)

    blank_after = sum(1 for e in entries if not e.get("source_title"))

    print(f"Already populated (skipped): {skipped}")
    print(f"Patched: {patched}")
    print(f"  HIGH confidence:   {confidence_counts[HIGH]}")
    print(f"Blank source_title entries after patch: {blank_after}")

    if unresolved:
        print(f"UNRESOLVED ({len(unresolved)}):")
        for eid in unresolved:
            print(f"  {eid}")
    else:
        print("All blank entries resolved.")

    if patched == 0 and not unresolved:
        print("No changes needed -- all entries already fully patched (idempotent re-run).")
        return

    if patched_titles:
        print("\nAssignment summary (titles patched this run):")
        for title, count in sorted(patched_titles.items(), key=lambda x: -x[1]):
            print(f"  {count:3d}  {title}")

    print(f"\nWriting {DATA_FILE}")
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("Done.")


if __name__ == "__main__":
    main()
