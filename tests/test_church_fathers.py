"""Tests for church_fathers parser corrections.

Verifies that KNOWN_CORRECTIONS in church_fathers.py are applied correctly.
All tests read committed output files under data/church-fathers/.

RED state:  tests fail because corrections are not yet implemented.
GREEN state: tests pass after corrections are applied and parser re-run.

Corrections covered (all documented in UPSTREAM_BUGS.md):
  Verse tag fixes  : pope-anterus, andreas-of-caesarea, caesarius-of-arles, callistus-i-of-rome
  Exclusions       : cyprian (composite), tatian-the-assyrian (truncated)
  Misattributions  : athanasius -> pseudo-athanasius (3 entries), jerome -> pseudo-jerome (2 entries)
  Reroute          : remigius-of-rheims (196 entries) -> remigius-of-auxerre
"""

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CHURCH_FATHERS_DIR = REPO_ROOT / "data" / "church-fathers"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load(slug: str) -> list:
    """Return the data array from data/church-fathers/{slug}.json."""
    path = CHURCH_FATHERS_DIR / f"{slug}.json"
    if not path.exists():
        pytest.skip(f"{slug}.json not yet generated")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data["data"]


def _load_meta(slug: str) -> dict:
    """Return the meta block from data/church-fathers/{slug}.json."""
    path = CHURCH_FATHERS_DIR / f"{slug}.json"
    if not path.exists():
        pytest.skip(f"{slug}.json not yet generated")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data["meta"]


def _id_set(entries: list) -> set:
    return {e["entry_id"] for e in entries}


# ---------------------------------------------------------------------------
# Verse tag fixes
# (UPSTREAM_BUGS.md -- Commentaries-Database: Verse-tag errors)
# ---------------------------------------------------------------------------


class TestVerseTagFixes:
    def test_pope_anterus_eph_4_29_absent(self):
        """pope-anterus.json must not contain Eph.4.29.

        UPSTREAM_BUGS.md: Eph.4.29 -> Eph.4.32
        ("And be ye kind one to another"). Found 2026-04-15.
        """
        ids = _id_set(_load("pope-anterus"))
        assert not any("Eph.4.29" in eid for eid in ids), (
            "Eph.4.29 entry still present in pope-anterus -- verse_fix not applied"
        )

    def test_pope_anterus_eph_4_32_present(self):
        """pope-anterus.json must contain an Eph.4.32 entry after verse fix."""
        ids = _id_set(_load("pope-anterus"))
        assert any("Eph.4.32" in eid for eid in ids), (
            "Eph.4.32 entry missing from pope-anterus -- verse_fix not applied"
        )

    def test_andreas_2thess_1_8_absent(self):
        """andreas-of-caesarea.json must not contain 2Thess.1.8.

        UPSTREAM_BUGS.md: 2Thess.1.8 -> Rev.20.9-10
        (commentary on fire-of-judgment imagery). Found 2026-04-15.
        """
        ids = _id_set(_load("andreas-of-caesarea"))
        assert not any("2Thess.1.8" in eid for eid in ids), (
            "2Thess.1.8 entry still present in andreas-of-caesarea -- verse_fix not applied"
        )

    def test_andreas_rev_20_9_10_present(self):
        """andreas-of-caesarea.json must have a Rev.20.9-10.unknown entry after verse fix.

        Andreas already has legitimate Rev.20.9 entries (from his own commentary).
        The fix targets specifically the 2Thess.1.8.unknown TOML, which must produce
        andreas-of-caesarea.Rev.20.9-10.unknown after correction.
        """
        ids = _id_set(_load("andreas-of-caesarea"))
        assert any("Rev.20.9-10.unknown" in eid for eid in ids), (
            "Rev.20.9-10.unknown entry missing from andreas-of-caesarea -- verse_fix not applied"
        )

    def test_caesarius_2thess_1_8_absent(self):
        """caesarius-of-arles.json must not contain 2Thess.1.8.unknown.

        UPSTREAM_BUGS.md: 2Thess.1.8 -> Rev.16.16
        (Exposition on the Apocalypse, Armageddon reference). Found 2026-04-15.
        Other legitimate 2Thess entries (sermons-232, sermons-451) are unaffected.
        """
        ids = _id_set(_load("caesarius-of-arles"))
        assert "caesarius-of-arles.2Thess.1.8.unknown" not in ids, (
            "caesarius-of-arles.2Thess.1.8.unknown still present -- verse_fix not applied"
        )

    def test_caesarius_rev_16_16_present(self):
        """caesarius-of-arles.json must contain a Rev.16.16 entry after verse fix."""
        ids = _id_set(_load("caesarius-of-arles"))
        assert any("Rev.16.16" in eid for eid in ids), (
            "Rev.16.16 entry missing from caesarius-of-arles -- verse_fix not applied"
        )

    def test_callistus_rom_3_3_absent(self):
        """callistus-i-of-rome.json must not contain Rom.3.3.

        UPSTREAM_BUGS.md: Rom.3.3 -> Rom.2.10
        ("glory, honour, and peace, to every man that worketh good"). Found 2026-04-15.
        """
        ids = _id_set(_load("callistus-i-of-rome"))
        assert not any("Rom.3.3" in eid for eid in ids), (
            "Rom.3.3 entry still present in callistus-i-of-rome -- verse_fix not applied"
        )

    def test_callistus_rom_2_10_present(self):
        """callistus-i-of-rome.json must contain a Rom.2.10 entry after verse fix."""
        ids = _id_set(_load("callistus-i-of-rome"))
        assert any("Rom.2.10" in eid for eid in ids), (
            "Rom.2.10 entry missing from callistus-i-of-rome -- verse_fix not applied"
        )


# ---------------------------------------------------------------------------
# Exclusions: unusable entries
# (UPSTREAM_BUGS.md -- Composite entries + Truncated/malformed quote text)
# ---------------------------------------------------------------------------


class TestExclusions:
    def test_cyprian_1pet_5_5_absent(self):
        """cyprian.json must not contain cyprian.1Pet.5.5.unknown.

        UPSTREAM_BUGS.md: composite of Epistle XIV.3 ("Crementius the sub-deacon...")
        and Epistle XIX ("To the number of five...") -- two distinct letters spliced
        into one TOML block. No valid single source_title possible. Found 2026-04-15.
        """
        ids = _id_set(_load("cyprian"))
        assert "cyprian.1Pet.5.5.unknown" not in ids, (
            "cyprian.1Pet.5.5.unknown still present -- composite entry not excluded"
        )

    def test_tatian_mark_9_48_absent(self):
        """tatian-the-assyrian.json must not contain tatian-the-assyrian.Mark.9.48.unknown.

        UPSTREAM_BUGS.md: quote text "With which he careth for. / us, to appear" is
        <10 words, visibly truncated or garbled. Attribution not possible. Found 2026-04-15.
        """
        ids = _id_set(_load("tatian-the-assyrian"))
        assert "tatian-the-assyrian.Mark.9.48.unknown" not in ids, (
            "tatian-the-assyrian.Mark.9.48.unknown still present -- truncated entry not excluded"
        )


# ---------------------------------------------------------------------------
# Misattribution: Pseudo-Athanasius
# (UPSTREAM_BUGS.md -- Synopsis Scripturae Sacrae, CPG 2249)
# ---------------------------------------------------------------------------


class TestPseudoAthanasius:
    def test_athanasius_ezra_1_1_absent(self):
        """athanasius-of-alexandria.json must not contain Ezra.1.1.

        UPSTREAM_BUGS.md: content from Synopsis Scripturae Sacrae (CPG 2249), dated >=6th
        century, universally attributed to Pseudo-Athanasius. The TOML quote begins with
        "[Synopsis on Ezra]". Contradicts Athanasius's authentic 39th Festal Letter.
        Source: Roger Pearse blog 2018-09-18 citing CPG 2249.
        """
        ids = _id_set(_load("athanasius-of-alexandria"))
        assert "athanasius-of-alexandria.Ezra.1.1.unknown" not in ids, (
            "Ezra.1.1 still in athanasius-of-alexandria -- misattribution not corrected"
        )

    def test_athanasius_neh_1_1_absent(self):
        """athanasius-of-alexandria.json must not contain Neh.1.1.

        UPSTREAM_BUGS.md: same work as Ezra.1.1 (Synopsis Scripturae Sacrae, CPG 2249).
        TOML quote begins with "[Synopsis on Nehemiah]".
        """
        ids = _id_set(_load("athanasius-of-alexandria"))
        assert "athanasius-of-alexandria.Neh.1.1.unknown" not in ids, (
            "Neh.1.1 still in athanasius-of-alexandria -- misattribution not corrected"
        )

    def test_athanasius_song_1_1_absent(self):
        """athanasius-of-alexandria.json must not contain Song.1.1.

        UPSTREAM_BUGS.md: same work as Ezra.1.1 (Synopsis Scripturae Sacrae, CPG 2249).
        """
        ids = _id_set(_load("athanasius-of-alexandria"))
        assert "athanasius-of-alexandria.Song.1.1.unknown" not in ids, (
            "Song.1.1 still in athanasius-of-alexandria -- misattribution not corrected"
        )

    def test_pseudo_athanasius_has_ezra_1_1(self):
        """pseudo-athanasius.json must contain the Ezra.1.1 entry rerouted from Athanasius."""
        ids = _id_set(_load("pseudo-athanasius"))
        assert any("Ezra.1.1" in eid for eid in ids), (
            "Ezra.1.1 missing from pseudo-athanasius -- rerouting not applied"
        )

    def test_pseudo_athanasius_has_neh_1_1(self):
        """pseudo-athanasius.json must contain the Neh.1.1 entry rerouted from Athanasius."""
        ids = _id_set(_load("pseudo-athanasius"))
        assert any("Neh.1.1" in eid for eid in ids), (
            "Neh.1.1 missing from pseudo-athanasius -- rerouting not applied"
        )

    def test_pseudo_athanasius_has_song_1_1(self):
        """pseudo-athanasius.json must contain the Song.1.1 entry rerouted from Athanasius."""
        ids = _id_set(_load("pseudo-athanasius"))
        assert any("Song.1.1" in eid for eid in ids), (
            "Song.1.1 missing from pseudo-athanasius -- rerouting not applied"
        )

    def test_pseudo_athanasius_rerouted_entries_author_name(self):
        """Rerouted entries in pseudo-athanasius.json must carry 'Pseudo-Athanasius' as author."""
        entries = _load("pseudo-athanasius")
        rerouted = [
            e for e in entries
            if any(ref in {"Ezra.1.1", "Neh.1.1", "Song.1.1"}
                   for ref in e["anchor_ref"]["osis"])
        ]
        assert rerouted, "No rerouted entries found in pseudo-athanasius.json"
        for e in rerouted:
            assert e["author"] == "Pseudo-Athanasius", (
                f"Entry {e['entry_id']} has wrong author: {e['author']!r}"
            )


# ---------------------------------------------------------------------------
# Misattribution: Pseudo-Jerome
# (UPSTREAM_BUGS.md -- Catena Aurea on Mark, Pseudo-Jerome label)
# ---------------------------------------------------------------------------


class TestPseudoJerome:
    def test_jerome_mark_1_11_absent(self):
        """jerome.json must not contain jerome.Mark.1.11.unknown.

        UPSTREAM_BUGS.md: Catena Aurea on Mark ch.1 explicitly labels both paragraphs
        of the dove/Canticles quote as PSEUDO-JEROME. Verified against
        HistoricalChristianFaith/Writings-Database Catena Aurea Mark Chapter 1.html.
        Found 2026-04-23.
        """
        ids = _id_set(_load("jerome"))
        assert "jerome.Mark.1.11.unknown" not in ids, (
            "jerome.Mark.1.11.unknown still present -- misattribution not corrected"
        )

    def test_jerome_mark_15_32_absent(self):
        """jerome.json must not contain jerome.Mark.15.32.unknown.

        UPSTREAM_BUGS.md: Catena Aurea on Mark ch.15 explicitly labels the "foal of
        Judah" quote as PSEUDO-JEROME. Verified against HistoricalChristianFaith/
        Writings-Database Catena Aurea Mark Chapter 15.html. Found 2026-04-23.
        """
        ids = _id_set(_load("jerome"))
        assert "jerome.Mark.15.32.unknown" not in ids, (
            "jerome.Mark.15.32.unknown still present -- misattribution not corrected"
        )

    def test_pseudo_jerome_has_mark_1_11(self):
        """pseudo-jerome.json must contain the Mark.1.11.unknown entry rerouted from Jerome.

        Note: pseudo-jerome already has Mark.1.9-11.catena-aurea-by-aquinas (a range entry
        from a separate Catena block). The rerouted entry is a distinct single-verse unknown.
        """
        ids = _id_set(_load("pseudo-jerome"))
        assert any("Mark.1.11.unknown" in eid for eid in ids), (
            "Mark.1.11.unknown missing from pseudo-jerome -- rerouting not applied"
        )

    def test_pseudo_jerome_has_mark_15_32(self):
        """pseudo-jerome.json must contain the Mark.15.32.unknown entry rerouted from Jerome.

        Note: pseudo-jerome already has Mark.15.29-32.catena-aurea-by-aquinas (range).
        The rerouted entry is a distinct single-verse unknown.
        """
        ids = _id_set(_load("pseudo-jerome"))
        assert any("Mark.15.32.unknown" in eid for eid in ids), (
            "Mark.15.32.unknown missing from pseudo-jerome -- rerouting not applied"
        )

    def test_pseudo_jerome_rerouted_entries_author_name(self):
        """Rerouted entries in pseudo-jerome.json must carry 'Pseudo-Jerome' as author."""
        entries = _load("pseudo-jerome")
        rerouted = [
            e for e in entries
            if e["entry_id"].endswith(".Mark.1.11.unknown")
            or e["entry_id"].endswith(".Mark.15.32.unknown")
        ]
        assert rerouted, "No rerouted entries found in pseudo-jerome.json"
        for e in rerouted:
            assert e["author"] == "Pseudo-Jerome", (
                f"Entry {e['entry_id']} has wrong author: {e['author']!r}"
            )


# ---------------------------------------------------------------------------
# Remigius of Rheims -> Remigius of Auxerre reroute
# (UPSTREAM_BUGS.md -- Carolingian naming collision resolved 2026-05-31)
# ---------------------------------------------------------------------------


class TestRemigiusReroute:
    def test_remigius_of_rheims_no_output_file(self):
        """remigius-of-rheims.json must not exist after the REROUTE_AUTHOR redirect.

        All 196 commentaries uploaded under 'Remigius of Rheims' are by Remigius
        of Auxerre (841-908). REROUTE_AUTHOR suppresses the source author's output
        entirely. UPSTREAM_BUGS.md 2026-04-15.
        """
        path = CHURCH_FATHERS_DIR / "remigius-of-rheims.json"
        assert not path.exists(), (
            "remigius-of-rheims.json must not exist -- all entries rerouted to remigius-of-auxerre"
        )

    def test_remigius_of_auxerre_receives_all_entries(self):
        """remigius-of-auxerre.json must receive all 196 rerouted entries."""
        entries = _load("remigius-of-auxerre")
        assert len(entries) == 196, (
            f"remigius-of-auxerre.json should have 196 entries, got {len(entries)}"
        )

    def test_remigius_of_auxerre_author_field(self):
        """All entries in remigius-of-auxerre.json must carry author='Remigius of Auxerre'."""
        entries = _load("remigius-of-auxerre")
        wrong = [e["entry_id"] for e in entries if e.get("author") != "Remigius of Auxerre"]
        assert not wrong, f"Entries with wrong author: {wrong[:5]}"
