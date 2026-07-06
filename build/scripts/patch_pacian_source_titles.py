"""Patch missing source_title for pacian-of-barcelona church_fathers entries.

=== RESULT: 0 entries patched ===

All 26 missing entries cite a single work, but HIGH confidence is unachievable.
See rationale below.

--- What the TOML files say ---

Every missing entry's TOML quote text ends with an embedded ACCS-style citation:
    "... Exposition of the Old and New Testament, Exodus"
    "... Exposition of the Old and New Testament, Leviticus"
    "... Exposition of the Old and New Testament, Numbers"

This is the source title as published in ACCS OT Vol. 3 (Lienhard, ed.),
the upstream source for these quotes.

--- Why no patch ---

HIGH confidence requires: "Verified against a primary source text
(newadvent.org, CCEL, archive.org scan)."

1. "Exposition of the Old and New Testament" is NOT in Pacian's authenticated
   corpus. Pacian's known extant works are: three letters to Sympronian,
   Paraenesis/De Paenitentibus, and De Baptismo. (tertullian.org/fathers/index.htm)

2. The work is absent from all standard primary source databases: NewAdvent,
   CCEL, tertullian.org, and archive.org. No Latin text with section numbers
   is available for verification.

3. The established format convention for pacian-of-barcelona.json is
   section-specific ALL CAPS (e.g. "LETTER 3.16.2", "ON PENITENTS 6.3").
   Section numbers for the "Exposition" are not determinable from TOML or
   from any source found. Per project rules, a work-level title must not be
   committed when section-specific is the file's established convention.
   Exception would apply only if the work is confirmed to lack numbered
   sections (as with Haimo's prose exegesis) -- but this cannot be confirmed
   without access to the primary text.

All 26 entries are rated MEDIUM confidence:
    - Strong converging signal: citation embedded directly in TOML quote text
    - ACCS OT Vol. 3 (Lienhard) is a peer-reviewed scholarly source
    - All 26 entries consistently cite the same work with book subdivision
    - Counter: no primary source text available for verification or section lookup

Only HIGH entries go in the patch. MEDIUM entries stay blank.

--- Upstream issue flagged ---

The attribution of "Exposition of the Old and New Testament" to Pacian of
Barcelona is likely a pseudo-Pacian or Hiberno-Latin work included in ACCS
under Pacian's name. Scholarship on Pacian (Hanson, Iberian Fathers Vol. 3,
CUA Press) notes that treatises attributed to Pacian by Dom G. Morin are of
doubtful authenticity. The ACCS may be drawing on such an attribution.

If this work can be located in PL (Patrologia Latina) or another primary
source with section numbering, all 26 entries could be patched using:
    "EXPOSITION OF THE OLD AND NEW TESTAMENT, EXODUS"
    "EXPOSITION OF THE OLD AND NEW TESTAMENT, LEVITICUS"
    "EXPOSITION OF THE OLD AND NEW TESTAMENT, NUMBERS"
(ALL CAPS with book subdivision, matching file's existing convention)

--- Current state ---

validate.py before patch: 26/42 entries (61.9%) missing source_title
No entries patched. File unchanged.
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "church-fathers" / "pacian-of-barcelona.json"
VALIDATE_SCRIPT = ROOT / "build" / "validate.py"

# No entries can be patched to HIGH confidence -- see docstring.
PATCH: dict[str, str] = {}


def main() -> None:
    print("pacian-of-barcelona: 0 entries patched (see docstring for rationale)")
    print(f"Data file unchanged: {DATA_FILE}")
    print("\nRunning validate.py ...")
    try:
        subprocess.run(
            ["py", "-3", str(VALIDATE_SCRIPT),
             "data/church-fathers/pacian-of-barcelona.json"],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("WARNING: validate.py returned non-zero exit code.")


if __name__ == "__main__":
    assert len(PATCH) == 0, f"Expected 0 patch entries, got {len(PATCH)}"
    main()
