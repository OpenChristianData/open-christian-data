"""
Patch source_title for Cassiodorus's 7 blank entries (5 resolved here).

Confidence tiers (per entry in PATCH dict below):
  HIGH -- confirmed against primary source (historicalchristian.faith,
          cross-reference to same-TOML adjacent block with known source_title,
          or near-verbatim duplicate entry with confirmed attribution).

Only HIGH-confidence entries are included. 2 entries remain blank:

  cassiodorus.Acts.2.26.unknown -- Commentary on Acts 2:26, which quotes
    Psalm 16:9. Content style is identical to surrounding Ps 16:8/10/11
    entries (all from Explanation of the Psalms), but no Psalms_16_9.toml
    exists in the raw data, and historicalchristian.faith lists no Cassiodorus
    entry for Ps 16:9. Section number cannot be confirmed without access to
    the full Expositio Psalmorum text (Archive.org copy is access-restricted).
    Downgraded to MEDIUM; left blank.

  cassiodorus.Col.1.12.unknown -- Commentary on Colossians 1:12 discussing
    "lot of the saints in light" and lots in OT/NT. Style matches the
    Expositio Psalmorum but the specific Psalm section cannot be determined
    from TOML, HCF, or any accessible primary source. No Source: label on
    historicalchristian.faith/colossians/1/12. Downgraded to LOW; left blank.

Spot-checked against primary source:
  - cassiodorus.Acts.2.25.unknown (historicalchristian.faith/psalms/16/8) --
    confirmed: Cassiodorus entry at Ps 16:8 carries
    "Source: EXPLANATION OF THE PSALMS 16:8"; text matches "unique remedy ...
    avoid sins ... mental eye" language in both this entry and TOML.
  - cassiodorus.Acts.2.27.unknown (historicalchristian.faith/psalms/16/10) --
    confirmed: Cassiodorus entry at Ps 16:10 carries
    "Source: EXPLANATION OF THE PSALMS 16:10"; text matches.
  - cassiodorus.Rev.1.4.unknown (cassiodorus.Exod.3.14.exposition-of-the-psalms-28
    cross-ref AND historicalchristian.faith/psalms/2/7) -- confirmed: near-verbatim
    duplicate in Exod.3.14 TOML has source_title "Exposition of the Psalms 2:8";
    HCF Ps 2:7 page shows "Source: EXPLANATION OF THE PSALMS 2:8" for the same
    Cassiodorus entry.

Run twice to verify idempotency.
"""

import json
import subprocess
from pathlib import Path

# Project root is three levels up from this script (build/scripts/ -> build/ -> root)
ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "cassiodorus.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# ---------------------------------------------------------------------------
# Patch dict: entry_id -> source_title (HIGH confidence only)
# ---------------------------------------------------------------------------
PATCH: dict[str, str] = {
    # ---- Explanation of the Psalms 16:8 ----
    # Acts 2:25 quotes Psalm 16:8 (Peter's speech). Cassiodorus comments on the
    # Psalm verse, not the Acts verse itself. Text matches the existing
    # cassiodorus.Ps.16.8.explanation-of-the-psalms-168 entry.
    # Confirmed: historicalchristian.faith/psalms/16/8 shows Cassiodorus with
    # "Source: EXPLANATION OF THE PSALMS 16:8"; same "unique remedy / avoid sins /
    # mental eye" phrasing.
    "cassiodorus.Acts.2.25.unknown": "Explanation of the Psalms 16:8",

    # ---- Explanation of the Psalms 16:10 ----
    # Acts 2:27 quotes Psalm 16:10. Text matches the content of Ps 16:10
    # commentary (Apollinarians / soul not abandoned / swift resurrection).
    # Confirmed: historicalchristian.faith/psalms/16/10 shows Cassiodorus with
    # "Source: EXPLANATION OF THE PSALMS 16:10".
    "cassiodorus.Acts.2.27.unknown": "Explanation of the Psalms 16:10",

    # ---- Explanation of the Psalms 16:11 ----
    # Acts 2:28 quotes Psalm 16:11. Quote is contained verbatim within the
    # existing Psalms_16_11.toml block (source_title="EXPLANATION OF THE PSALMS 16:11").
    # Confirmed: historicalchristian.faith/psalms/16/11 shows Cassiodorus with
    # "Source: EXPLANATION OF THE PSALMS 16:11".
    "cassiodorus.Acts.2.28.unknown": "Explanation of the Psalms 16:11",

    # ---- Exposition of the Psalms 2:8 ----
    # Rev 1:4 discusses "him that is" / present tense of God's eternity.
    # Near-verbatim duplicate found in cassiodorus.Exod.3.14.exposition-of-the-psalms-28
    # (source_title="Exposition of the Psalms 2:8").
    # Confirmed: historicalchristian.faith/psalms/2/7 shows Cassiodorus entry
    # carries "Source: EXPLANATION OF THE PSALMS 2:8".
    "cassiodorus.Rev.1.4.unknown": "Exposition of the Psalms 2:8",

    # ---- Explanation of the Psalms 88:37 ----
    # Wis.3.7.unknown is the same text as the adjacent block in Wisdom_3_7.toml
    # which has source_title="EXPLANATION OF THE PSALMS 88:37". The quote content
    # is identical (moon / faithful witness / righteous shine like sparks).
    # The existing cassiodorus.Wis.3.7.explanation-of-the-psalms-8837 entry also
    # carries source_title="Explanation of the Psalms 88:37".
    "cassiodorus.Wis.3.7.unknown": "Explanation of the Psalms 88:37",
}


def main() -> None:
    print(f"Loading {DATA_FILE}")
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    entries = data["data"]
    blank_before = sum(1 for e in entries if not e.get("source_title"))
    print(f"Blank source_title entries before patch: {blank_before}")

    set_count = 0
    skipped_already_set = 0
    skipped_not_in_data = []

    # Build lookup by entry_id
    entry_map = {e["entry_id"]: e for e in entries}

    for entry_id, title in PATCH.items():
        if entry_id not in entry_map:
            skipped_not_in_data.append(entry_id)
            continue
        entry = entry_map[entry_id]
        if entry.get("source_title"):
            skipped_already_set += 1  # idempotent skip
        else:
            entry["source_title"] = title
            set_count += 1

    blank_after = sum(1 for e in entries if not e.get("source_title"))

    print(f"Set:                    {set_count}")
    print(f"Skipped (already set):  {skipped_already_set}")
    if skipped_not_in_data:
        print(f"WARNING: entry_ids not found in data ({len(skipped_not_in_data)}):")
        for eid in skipped_not_in_data:
            print(f"  {eid}")
    print(f"Blank source_title entries after patch: {blank_after}")

    print(f"\nWriting {DATA_FILE}")
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("Done.")

    # Run validator
    print("\nRunning validate.py ...")
    try:
        subprocess.run(
            ["py", "-3", str(VALIDATE_SCRIPT),
             "data/church-fathers/cassiodorus.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 5, f"Expected 5 patch entries, got {len(PATCH)}"
    main()
