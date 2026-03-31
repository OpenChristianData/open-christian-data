"""
Extend data/authors/registry.json with 13 non-church-fathers entries.
Idempotent: skips author_ids already present.
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY_PATH = REPO_ROOT / "data" / "authors" / "registry.json"
LOG_PATH = Path(__file__).resolve().parent / "extend_registry_non_cf.log"

logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
)


def make_entry(author_id, display_name, aliases, birth_year, death_year, tradition, nationality, works, notes):
    return {
        "author_id": author_id,
        "display_name": display_name,
        "aliases": aliases,
        "birth_year": birth_year,
        "death_year": death_year,
        "tradition": tradition,
        "nationality": nationality,
        "works": works,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# 13 non-church-fathers entries
# ---------------------------------------------------------------------------
# Albert Barnes: all 27 files in data/commentaries/barnes/
BARNES_WORKS = [
    "1-corinthians", "1-john", "1-peter", "1-thessalonians", "1-timothy",
    "2-corinthians", "2-john", "2-peter", "2-thessalonians", "2-timothy",
    "3-john", "acts", "colossians", "ephesians", "galatians", "hebrews",
    "james", "john", "jude", "luke", "mark", "matthew", "philemon",
    "philippians", "revelation", "romans", "titus",
]

NEW_ENTRIES = [
    make_entry(
        "albert-barnes", "Albert Barnes",
        ["Barnes", "Albert Barnes (1798-1870)"],
        1798, 1870,
        ["reformed", "presbyterian"],
        "American",
        BARNES_WORKS,
        "American Presbyterian minister and biblical commentator. Author of Barnes' Notes on the Bible.",
    ),
    make_entry(
        "evelyn-underhill", "Evelyn Underhill",
        ["E. Underhill"],
        1875, 1941,
        ["anglican", "evangelical"],
        "English",
        ["practical-mysticism"],
        None,
    ),
    make_entry(
        "george-macdonald", "George MacDonald",
        ["G. MacDonald"],
        1824, 1905,
        ["reformed", "evangelical"],
        "Scottish",
        ["george-macdonald-unspoken-sermons"],
        None,
    ),
    make_entry(
        "john-bunyan", "John Bunyan",
        ["J. Bunyan"],
        1628, 1688,
        ["puritan", "baptist"],
        "English",
        ["pilgrims-progress"],
        None,
    ),
    make_entry(
        "john-milton", "John Milton",
        ["J. Milton"],
        1608, 1674,
        ["puritan"],
        "English",
        ["paradise-lost"],
        None,
    ),
    make_entry(
        "jonathan-bagster", "Jonathan Bagster",
        ["J. Bagster"],
        # Confirmed: born 1813, died 1872 (son of Samuel Bagster; compiler of Daily Light)
        1813, 1872,
        ["evangelical"],
        "English",
        ["daily-light"],
        "English publisher and compiler; son of Samuel Bagster. Compiled 'Daily Light on the Daily Path' for family worship; published posthumously by his son Robert in 1875.",
    ),
    make_entry(
        "matthew-george-easton", "Matthew George Easton",
        ["M. G. Easton", "Easton"],
        1823, 1894,
        ["reformed", "presbyterian"],
        "Scottish",
        ["eastons-bible-dictionary"],
        None,
    ),
    make_entry(
        "orville-j-nave", "Orville J. Nave",
        ["O. J. Nave", "Orville James Nave"],
        # Confirmed: April 30, 1841 -- June 24, 1917 (Internet Archive, Wikipedia)
        1841, 1917,
        ["methodist"],
        "American",
        ["naves-topical-bible"],
        "American Methodist chaplain in the US Army; compiled Nave's Topical Bible (first published 1897).",
    ),
    make_entry(
        "reuben-archer-torrey", "Reuben Archer Torrey",
        ["R. A. Torrey", "R.A. Torrey"],
        1856, 1928,
        ["evangelical", "reformed"],
        "American",
        ["torreys-topical-textbook"],
        None,
    ),
    make_entry(
        "roswell-dwight-hitchcock", "Roswell Dwight Hitchcock",
        ["R. D. Hitchcock"],
        # Confirmed: August 15, 1817 -- June 16, 1887 (Wikipedia, 1911 Britannica)
        # Note: Congregationalist (not Presbyterian); Reformed/evangelical tradition
        1817, 1887,
        ["reformed", "evangelical"],
        "American",
        ["hitchcocks-bible-names-dictionary"],
        "American Congregationalist minister and biblical scholar; professor and president of Union Theological Seminary, New York.",
    ),
    make_entry(
        "third-plenary-council-of-baltimore", "Third Plenary Council of Baltimore",
        ["Baltimore Catechism"],
        None, None,
        ["catholic"],
        None,
        [
            "baltimore-catechism-no-1",
            "baltimore-catechism-no-2",
            "baltimore-catechism-no-3",
        ],
        "Third Plenary Council of the Catholic Church in the United States, held in Baltimore in 1884. Produced the Baltimore Catechism.",
    ),
    make_entry(
        "thomas-a-kempis", "Thomas a Kempis",
        ["Thomas Hemerken", "Thomas von Kempen", "Thomas a Kempis (1380-1471)"],
        1380, 1471,
        ["catholic"],
        None,
        ["imitation-of-christ"],
        "Probable author of 'The Imitation of Christ', one of the most widely read Christian devotional books. Augustinian canon at Mount Saint Agnes monastery.",
    ),
    make_entry(
        "william-smith", "William Smith",
        ["W. Smith", "Sir William Smith"],
        1813, 1893,
        ["anglican"],
        "English",
        ["smiths-bible-dictionary"],
        None,
    ),
]

# Guard: must be exactly 13 entries
assert len(NEW_ENTRIES) == 13, f"Expected 13 NEW_ENTRIES, got {len(NEW_ENTRIES)}"


def main():
    start = datetime.now()
    logging.info("extend_registry_non_cf.py started")

    # Load existing registry
    try:
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            registry = json.load(f)
    except FileNotFoundError:
        msg = f"ERROR: Registry file not found at {REGISTRY_PATH} -- check REGISTRY_PATH is correct."
        print(msg)
        logging.error(msg)
        sys.exit(1)
    except Exception as exc:
        msg = f"ERROR: Could not load registry: {exc}"
        print(msg)
        logging.error(msg)
        sys.exit(1)

    existing_ids = {a["author_id"] for a in registry["authors"]}
    candidate_count = len(NEW_ENTRIES)
    logging.info(
        "Existing registry: %d authors; %d candidate entries to process",
        len(existing_ids), candidate_count,
    )
    print(f"Existing registry: {len(existing_ids)} authors; processing {candidate_count} candidates")

    added = 0
    skipped = 0
    errors = 0

    for entry in NEW_ENTRIES:
        try:
            if entry["author_id"] in existing_ids:
                logging.info("SKIP (already present): %s", entry["author_id"])
                skipped += 1
            else:
                registry["authors"].append(entry)
                existing_ids.add(entry["author_id"])
                logging.info("ADD: %s", entry["author_id"])
                added += 1
        except Exception as exc:
            logging.error("ERROR processing entry %s: %s", entry, exc)
            errors += 1

    # Save back to registry
    try:
        with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except Exception as exc:
        msg = f"ERROR: Could not save registry to {REGISTRY_PATH}: {exc}"
        print(msg)
        logging.error(msg)
        sys.exit(1)

    elapsed = (datetime.now() - start).total_seconds()
    total = len(registry["authors"])

    # Quality stats over the newly added entries
    new_entries_in_registry = [
        a for a in registry["authors"]
        if a["author_id"] in {e["author_id"] for e in NEW_ENTRIES}
    ]
    null_birth = sum(1 for a in new_entries_in_registry if a["birth_year"] is None)
    null_death = sum(1 for a in new_entries_in_registry if a["death_year"] is None)
    empty_aliases = sum(1 for a in new_entries_in_registry if not a["aliases"])
    n = len(new_entries_in_registry) or 1

    print(
        f"Done in {elapsed:.1f}s -- added {added}, skipped {skipped}, errors {errors}, "
        f"total registry size: {total}"
    )
    print(
        f"Quality (new entries): birth_year null={null_birth}/{n} ({100*null_birth//n}%), "
        f"death_year null={null_death}/{n} ({100*null_death//n}%), "
        f"empty aliases={empty_aliases}/{n} ({100*empty_aliases//n}%)"
    )
    logging.info(
        "Done in %.1fs -- added %d, skipped %d, errors %d, total %d; "
        "null birth=%d/%d, null death=%d/%d, empty aliases=%d/%d",
        elapsed, added, skipped, errors, total,
        null_birth, n, null_death, n, empty_aliases, n,
    )

    if errors:
        print(f"WARNING: {errors} entries failed to process -- check the log at {LOG_PATH}")
    if added == 0 and skipped == candidate_count:
        print("All entries already present -- registry unchanged.")


if __name__ == "__main__":
    main()
