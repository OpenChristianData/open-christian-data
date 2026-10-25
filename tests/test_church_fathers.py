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
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CHURCH_FATHERS_DIR = REPO_ROOT / "data" / "church-fathers"
pytestmark = pytest.mark.requires_local_artifacts


@pytest.fixture(scope="module", autouse=True)
def _load_retained_parser():
    global church_fathers
    from build.parsers import church_fathers


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


def _replay_author(tmp_path: Path, monkeypatch, author_name: str) -> list[dict]:
    monkeypatch.setattr(church_fathers, "OUTPUT_DIR", tmp_path)
    stats = church_fathers.process_author(church_fathers.RAW_DIR / author_name)
    assert stats["status"] == "ok"
    slug = church_fathers.author_to_slug(author_name)
    return json.loads((tmp_path / f"{slug}.json").read_text(encoding="utf-8"))["data"]


def test_parser_applies_source_verified_title_correction(tmp_path, monkeypatch):
    """A retained-source locator may carry independently recorded research."""
    entries = _replay_author(tmp_path, monkeypatch, "Alexander of Alexandria")
    entry = next(
        item
        for item in entries
        if item["entry_id"]
        == "alexander-of-alexandria.1Cor.2.9.epistles-on-the-arian-heresy-i5"
    )
    assert entry["source_title"] == "Epistles on the Arian Heresy, I.5"


def test_parser_extracts_retained_inline_source_citation(tmp_path, monkeypatch):
    entries = _replay_author(tmp_path, monkeypatch, "Ephrem the Syrian")
    entry = next(
        item
        for item in entries
        if item["entry_id"]
        == "ephrem-the-syrian.Job.2.11.commentary-on-job-211"
    )
    assert entry["source_title"] == "Commentary on Job 2:11"


def test_parser_derives_new_testament_book_source_titles(tmp_path, monkeypatch):
    """Book directories define their work title without a post-parse patch."""
    total_entries = 0
    for author_name, expected_title in church_fathers.NT_BOOK_SOURCE_TITLES.items():
        entries = _replay_author(tmp_path, monkeypatch, author_name)
        assert entries
        assert {entry["source_title"] for entry in entries} == {expected_title}
        total_entries += len(entries)

    assert total_entries == 300


def test_new_testament_book_source_title_rejects_retained_conflict():
    path = church_fathers.RAW_DIR / "Romans" / "Genesis 1_1.toml"
    block = {"quote": "Retained quotation", "source_title": "Different Work"}

    with pytest.raises(
        ValueError,
        match="Retained title contradicts New Testament source-directory identity",
    ):
        church_fathers._resolve_source_title(path, 0, block, "Romans")


def test_new_testament_book_source_title_rejects_effective_author_mismatch():
    path = church_fathers.RAW_DIR / "Romans" / "Genesis 1_1.toml"
    block = {"quote": "Retained quotation", "source_title": ""}

    with pytest.raises(
        ValueError,
        match="New Testament source-directory identity mismatch",
    ):
        church_fathers._resolve_source_title(path, 0, block, "Different Author")


def test_source_title_corrections_bind_exact_retained_blocks():
    """Every correction must remain independently bound to retained source bytes."""
    assert church_fathers.SOURCE_TITLE_CORRECTIONS
    for locator, correction in church_fathers.SOURCE_TITLE_CORRECTIONS.items():
        source_path, block_index = locator
        path = REPO_ROOT / source_path
        blocks = church_fathers.load_toml_file(path)
        block = blocks[block_index]
        quote = (block.get("quote") or "").strip()
        assert church_fathers._quote_sha256(quote) == correction.quote_sha256
        retained_title = church_fathers._normalize_source_title(
            (block.get("source_title") or "").strip()
        )
        assert not retained_title or retained_title == correction.source_title
        assert correction.confidence == "HIGH"
        assert correction.evidence_reference


def test_source_title_authority_is_the_reviewed_forward_only_boundary():
    locators = set(church_fathers.SOURCE_TITLE_CORRECTIONS)
    identity_changed = {
        ("raw/Commentaries-Database/Andreas of Caesarea/2 Thessalonians 1_8.toml", 0),
        ("raw/Commentaries-Database/Callistus I of Rome/Romans 3_3.toml", 0),
        ("raw/Commentaries-Database/Pope Anterus/Ephesians 4_29.toml", 0),
    }
    remigius = {
        (f"raw/Commentaries-Database/Remigius of Rheims/{stem}.toml", 0)
        for stem in (
            "Mark 5_20",
            "Matthew 13_9",
            "Matthew 15_11",
            "Matthew 15_31",
            "Matthew 16_28",
            "Matthew 17_9",
            "Matthew 24_41",
            "Matthew 3_3",
            "Matthew 8_13",
        )
    }
    rabanus = {
        (f"raw/Commentaries-Database/Rabanus Maurus/Matthew {reference}.toml", 0)
        for reference in (
            "4_4",
            "4_22",
            "5_19",
            "9_35",
            "10_4",
            "11_24",
            "14_12",
            "15_31",
            "19_22",
            "20_19",
            "26_35",
            "26_38",
        )
    }

    assert len(locators) == 406
    assert identity_changed | remigius | rabanus <= locators
    assert not any("/Erasmus of Rotterdam/" in path for path, _ in locators)
    assert not any("/Thietland of Einsiedeln/" in path for path, _ in locators)

    for source_path, _block_index in locators:
        path = Path(source_path)
        source_author = path.parent.name
        correction = church_fathers.ENTRY_CORRECTIONS.get(
            (source_author, path.stem)
        )
        assert correction is None or correction["action"] != "exclude"
        if source_author in church_fathers.REROUTE_AUTHOR:
            target = church_fathers.REROUTE_AUTHOR[source_author]
            assert (church_fathers.RAW_DIR / target).is_dir()


def test_source_title_correction_rejects_retained_quote_drift():
    locator, correction = next(iter(church_fathers.SOURCE_TITLE_CORRECTIONS.items()))
    source_path, block_index = locator
    path = REPO_ROOT / source_path
    blocks = church_fathers.load_toml_file(path)
    changed = dict(blocks[block_index])
    changed["quote"] = f"{changed['quote']} drift"

    with pytest.raises(ValueError, match="Retained quote changed"):
        church_fathers._resolve_source_title(
            path, block_index, changed, path.parent.name
        )

    assert correction.source_title


def _write_source_title_authority(
    tmp_path: Path,
    monkeypatch,
    *,
    source_path: str = "raw/Commentaries-Database/Test Author/Test 1_1.toml",
    block_index: int = 0,
    quote_sha256: str | None = None,
    retained_title: str = "",
) -> Path:
    repo_root = tmp_path / "repo"
    monkeypatch.setattr(church_fathers, "REPO_ROOT", repo_root)
    carrier_path = repo_root / source_path
    carrier_path.parent.mkdir(parents=True, exist_ok=True)
    carrier_path.write_text(
        "[[commentary]]\n"
        'quote = "Exact retained quotation"\n'
        f'source_title = "{retained_title}"\n',
        encoding="utf-8",
    )
    record = {
        "source_path": source_path,
        "block_index": block_index,
        "quote_sha256": quote_sha256
        or church_fathers._quote_sha256("Exact retained quotation"),
        "source_title": "Verified Work",
        "confidence": "HIGH",
        "evidence_reference": "test evidence",
    }
    authority_path = tmp_path / "source-title-corrections.json"
    authority_path.write_text(
        json.dumps(
            {
                "authority_kind": "retained-source-title-corrections",
                "records": [record],
            }
        ),
        encoding="utf-8",
    )
    return authority_path


def test_source_title_authority_rejects_missing_carrier(tmp_path, monkeypatch):
    authority_path = _write_source_title_authority(tmp_path, monkeypatch)
    (tmp_path / "repo" / "raw").rename(tmp_path / "repo" / "raw-missing")

    with pytest.raises(ValueError, match="Cannot read source-title correction carrier"):
        church_fathers._load_source_title_corrections(authority_path)


def test_source_title_authority_rejects_missing_block(tmp_path, monkeypatch):
    authority_path = _write_source_title_authority(
        tmp_path, monkeypatch, block_index=1
    )

    with pytest.raises(ValueError, match="Missing source-title correction block"):
        church_fathers._load_source_title_corrections(authority_path)


def test_source_title_authority_rejects_quote_drift(tmp_path, monkeypatch):
    authority_path = _write_source_title_authority(
        tmp_path, monkeypatch, quote_sha256="0" * 64
    )

    with pytest.raises(ValueError, match="Retained quote changed"):
        church_fathers._load_source_title_corrections(authority_path)


def test_source_title_authority_rejects_retained_title_conflict(
    tmp_path, monkeypatch
):
    authority_path = _write_source_title_authority(
        tmp_path, monkeypatch, retained_title="Different Work"
    )

    with pytest.raises(ValueError, match="Retained title contradicts"):
        church_fathers._load_source_title_corrections(authority_path)


def test_cli_exits_nonzero_when_an_author_fails(monkeypatch, capsys):
    monkeypatch.setattr(church_fathers, "setup_logging", lambda: None)
    monkeypatch.setattr(
        church_fathers,
        "process_author",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("source authority drift")
        ),
    )
    monkeypatch.setattr(sys, "argv", ["church_fathers.py", "--author", "Romans"])

    with pytest.raises(SystemExit) as exc_info:
        church_fathers.main()

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "source authority drift" in output
    assert "AUTHORS WITH EXCEPTIONS" in output


def test_parser_normalizes_retained_all_caps_source_titles(tmp_path, monkeypatch):
    """Parser output owns display normalization; no post-parse titlecase pass exists."""
    monkeypatch.setattr(church_fathers, "OUTPUT_DIR", tmp_path)

    stats = church_fathers.process_author(church_fathers.RAW_DIR / "Abba Poemen")

    assert stats["status"] == "ok"
    generated = json.loads(
        (tmp_path / "abba-poemen.json").read_text(encoding="utf-8")
    )
    entry = next(
        item
        for item in generated["data"]
        if item["entry_id"] == "abba-poemen.2Tim.2.20.sayings-of-the-fathers-100"
    )
    assert entry["source_title"] == "Sayings of the Fathers 100"


def test_current_parser_excludes_paterius_records_from_pacian(tmp_path, monkeypatch):
    entries = _replay_author(tmp_path, monkeypatch, "Pacian of Barcelona")
    ids = _id_set(entries)
    removed_ids = {
        f"pacian-of-barcelona.{book}.{reference}.unknown"
        for book, references in {
            "Exod": ("3.2", "5.20", "8.26", "20.24", "26.19", "26.32", "33.21", "34.7"),
            "Lev": ("1.6", "6.9", "7.3", "7.33", "13.57", "19.23"),
            "Num": (
                "6.18", "7.89", "8.7", "8.24", "9.8", "10.2", "10.29",
                "19.15", "24.15", "24.21", "32.4", "35.28",
            ),
        }.items()
        for reference in references
    }
    assert len(removed_ids) == 26
    assert ids.isdisjoint(removed_ids)


def test_current_parser_reroutes_isidore_of_seville_records(
    tmp_path, monkeypatch
):
    seville = _replay_author(tmp_path, monkeypatch, "Isidore of Seville")
    pelusium = _replay_author(tmp_path, monkeypatch, "Isidore of Pelusium")
    source_ids = {
        f"isidore-of-seville.Luke.{reference}.unknown"
        for reference in (
            "6.1", "6.43", "7.24", "8.1", "9.10", "10.3", "12.41",
            "18.31", "24.25",
        )
    }
    target_ids = {
        entry_id.replace("isidore-of-seville.", "isidore-of-pelusium.").replace(
            ".unknown", ".catena-aurea-by-aquinas"
        )
        for entry_id in source_ids
    }
    assert _id_set(seville).isdisjoint(source_ids)
    assert target_ids <= _id_set(pelusium)
    assert all(
        entry["author"] == "Isidore of Pelusium"
        and entry["source_title"] == "Catena Aurea by Aquinas"
        for entry in pelusium
        if entry["entry_id"] in target_ids
    )


def test_current_parser_excludes_athanasius_duplicate_of_vigilius(
    tmp_path, monkeypatch
):
    athanasius = _replay_author(tmp_path, monkeypatch, "Athanasius of Alexandria")
    vigilius = _replay_author(tmp_path, monkeypatch, "Vigilius of Thapsus")
    source_id = "athanasius-of-alexandria.Matt.1.1.unknown"
    assert source_id not in _id_set(athanasius)
    assert "vigilius-of-thapsus.Matt.1.1.unknown" not in _id_set(vigilius)
    target = next(
        entry
        for entry in vigilius
        if entry["entry_id"]
        == "vigilius-of-thapsus.Matt.1.1.catena-aurea-by-aquinas"
    )
    assert target["author"] == "Vigilius of Thapsus"
    assert "The audaciousness of this most insane error" in target["quote"]
