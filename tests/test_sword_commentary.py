"""Regression tests for SWORD commentary position and coverage mapping."""

import json
import logging
import sys
from pathlib import Path

import pytest

import build.parsers.sword_commentary as sword_commentary
from build.parsers.sword_commentary import (
    ExpectedBookSetError,
    IncompleteSourceError,
    KJV_CANON,
    ModulePlan,
    StaleBookOutputError,
    SwordZComReader,
    build_verse_position_map,
    plan_module,
    reconcile_book_outputs,
    validate_expected_book_set,
    write_module_plans,
)


CALVIN_CONFIG = Path("sources/commentaries/calvin/config.json")
BARNES_CONFIG = Path("sources/commentaries/barnes/config.json")
WESLEY_CONFIG = Path("sources/commentaries/wesley/config.json")
CALVIN_MODULE_DIR = Path(
    "raw/sword_modules/CalvinCommentaries/modules/comments/zcom/calvincommentaries"
)

CALVIN_BOOKS = frozenset(
    {
        "Gen", "Exod", "Lev", "Num", "Deut", "Josh", "Ps", "Isa", "Jer", "Lam",
        "Ezek", "Dan", "Hos", "Joel", "Amos", "Obad", "Jonah", "Mic", "Nah", "Hab",
        "Zeph", "Hag", "Zech", "Mal", "Matt", "Mark", "Luke", "John", "Acts", "Rom",
        "1Cor", "2Cor", "Gal", "Eph", "Phil", "Col", "1Thess", "2Thess", "1Tim",
        "2Tim", "Titus", "Phlm", "Heb", "Jas", "1Pet", "2Pet", "1John", "Jude",
    }
)

EXPECTED_BOOKS = {
    "barnes": frozenset(osis for _name, osis, _lengths in KJV_CANON["nt"]),
    "calvin": CALVIN_BOOKS,
    "wesley": frozenset(
        osis
        for testament in KJV_CANON.values()
        for _name, osis, _lengths in testament
        if osis not in {"1Kgs", "Phlm"}
    ),
}

SOURCE_CONFIGS = {
    "barnes": BARNES_CONFIG,
    "calvin": CALVIN_CONFIG,
    "wesley": WESLEY_CONFIG,
}


BIBLE_TEXT_KJV = Path("data/bible-text/kjv")


def _kjv_versification_from_bible_text() -> dict[str, list[int]]:
    """Derive versification from the repo's own KJV text -- an independent primary source.

    KJV_CANON was hand-copied and nothing checked it, so it silently carried structural
    errors: Leviticus with 28 chapters (it has 27), Esther with 12 (it has 10), Romans
    with 20 (it has 16), wrong Ephesians verse counts from chapter 4, Psalms 140/142 off
    by one, and III John with 15 verses (it has 14). The table drives verse-position
    mapping for barnes, calvin and wesley, so an error shifts every later position and
    can attach commentary to the wrong verse.
    """
    versification: dict[str, list[int]] = {}
    for path in sorted(BIBLE_TEXT_KJV.rglob("*.json")):
        verses = json.loads(path.read_text(encoding="utf-8"))["data"]
        if not verses:
            continue
        book = verses[0]["osis"].split(".")[0]
        counts: dict[int, int] = {}
        for verse in verses:
            chapter = int(verse["chapter"])
            counts[chapter] = counts.get(chapter, 0) + 1
        versification[book] = [counts[i] for i in range(1, max(counts) + 1)]
    return versification


@pytest.mark.skipif(not BIBLE_TEXT_KJV.exists(), reason="KJV bible-text not present")
def test_kjv_canon_matches_the_repo_kjv_text_exactly():
    """Every book in KJV_CANON must match the KJV text, chapter for chapter.

    Do not weaken this against a non-KJV translation. Checking against ASV appears to
    show Matt, Mark, Luke, John, Acts and Rom "failing", but each of those is a known
    KJV-vs-critical-text omitted verse (Matt 17:21, Mark 7:16, John 5:4, Acts 8:37,
    Rom 16:24, and so on) -- ASV is simply the wrong yardstick for a KJV table.
    """
    expected = _kjv_versification_from_bible_text()
    table = {osis: list(lengths) for testament in KJV_CANON.values() for _name, osis, lengths in testament}

    mismatches = {
        book: {"kjv_text": expected[book], "table": table[book]}
        for book in expected
        if book in table and expected[book] != table[book]
    }
    assert mismatches == {}, (
        "KJV_CANON disagrees with data/bible-text/kjv for: "
        + ", ".join(sorted(mismatches))
    )


@pytest.mark.skipif(not BIBLE_TEXT_KJV.exists(), reason="KJV bible-text not present")
def test_kjv_canon_covers_every_book_in_the_kjv_text():
    expected = _kjv_versification_from_bible_text()
    table = {osis for testament in KJV_CANON.values() for _name, osis, _lengths in testament}
    assert set(expected) - table == set()


def _chapter_lengths(osis: str) -> list[int]:
    return next(
        lengths
        for testament in KJV_CANON.values()
        for _name, book_osis, lengths in testament
        if book_osis == osis
    )


def test_calvin_config_declares_settled_coverage() -> None:
    config = json.loads(CALVIN_CONFIG.read_text(encoding="utf-8"))

    assert config["coverage"].startswith("48 books (")
    assert "Acts" in config["coverage"]
    assert all("Acts" not in gap for gap in config["known_coverage_gaps"])
    assert any("2 John, 3 John, Revelation" in gap for gap in config["known_coverage_gaps"])


@pytest.mark.parametrize("module_name", ["barnes", "calvin", "wesley"])
def test_source_configs_declare_exact_expected_book_sets(module_name: str) -> None:
    config = json.loads(SOURCE_CONFIGS[module_name].read_text(encoding="utf-8"))

    assert set(config["expected_book_osis"]) == EXPECTED_BOOKS[module_name]


def test_expected_book_set_rejects_unexpected_missing_book() -> None:
    expected = EXPECTED_BOOKS["calvin"]

    with pytest.raises(ExpectedBookSetError, match="missing.*Acts"):
        validate_expected_book_set("calvin", expected - {"Acts"}, expected)


@pytest.mark.slow
@pytest.mark.parametrize("module_name", ["barnes", "calvin", "wesley"])
@pytest.mark.requires_local_artifacts
def test_plan_module_matches_source_derived_expected_book_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
) -> None:
    monkeypatch.setattr(sword_commentary, "OUTPUT_BASE", tmp_path / "data" / "commentaries")

    plan = plan_module(module_name)

    assert plan.produced_book_osis == EXPECTED_BOOKS[module_name]
    assert plan.expected_book_osis == EXPECTED_BOOKS[module_name]
    assert plan.outputs


@pytest.mark.slow
@pytest.mark.requires_local_artifacts
def test_plan_module_refuses_stale_output_after_complete_barnes_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_base = tmp_path / "data" / "commentaries"
    output_dir = output_base / "barnes"
    output_dir.mkdir(parents=True)
    stale = output_dir / "stale-book.json"
    stale.write_text("valid prior output", encoding="utf-8")
    monkeypatch.setattr(sword_commentary, "OUTPUT_BASE", output_base)

    with pytest.raises(StaleBookOutputError, match="stale-book.json"):
        plan_module("barnes")

    assert stale.read_text(encoding="utf-8") == "valid prior output"


def test_sword_reader_rejects_malformed_source_index(tmp_path: Path) -> None:
    module_dir = tmp_path / "module"
    module_dir.mkdir()
    (module_dir / "nt.bzs").write_bytes(b"malformed")
    (module_dir / "nt.bzv").write_bytes(b"")
    (module_dir / "nt.bzz").write_bytes(b"")

    with pytest.raises(IncompleteSourceError, match="BZS"):
        SwordZComReader(module_dir, "nt", "b")


@pytest.mark.parametrize("module_name", ["barnes", "calvin", "wesley"])
def test_reconcile_book_outputs_refuses_stale_json_for_each_sword_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
) -> None:
    output_dir = tmp_path / "data" / "commentaries" / module_name
    output_dir.mkdir(parents=True)
    current = output_dir / "matthew.json"
    stale = output_dir / "stale-book.json"
    current.write_text("{}", encoding="utf-8")
    stale.write_text("valid output", encoding="utf-8")
    monkeypatch.setattr(sword_commentary, "OUTPUT_BASE", tmp_path / "data" / "commentaries")

    with pytest.raises(StaleBookOutputError, match="stale-book.json"):
        reconcile_book_outputs(
            module_name,
            {"matthew"},
            source_read_complete=True,
        )

    assert stale.read_text(encoding="utf-8") == "valid output"


def test_reconcile_book_outputs_fails_closed_for_incomplete_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "data" / "commentaries" / "calvin"
    output_dir.mkdir(parents=True)
    stale = output_dir / "valid-existing-book.json"
    stale.write_text("valid output", encoding="utf-8")
    monkeypatch.setattr(sword_commentary, "OUTPUT_BASE", tmp_path / "data" / "commentaries")

    with pytest.raises(IncompleteSourceError, match="incomplete"):
        reconcile_book_outputs(
            "calvin",
            set(),
            source_read_complete=False,
        )

    assert stale.read_text(encoding="utf-8") == "valid output"


def test_reconcile_book_outputs_logs_discovered_produced_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    output_dir = tmp_path / "data" / "commentaries" / "barnes"
    output_dir.mkdir(parents=True)
    (output_dir / "matthew.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sword_commentary, "OUTPUT_BASE", tmp_path / "data" / "commentaries")

    with caplog.at_level(logging.INFO):
        reconcile_book_outputs(
            "barnes",
            {"matthew"},
            source_read_complete=True,
        )

    assert "Produced book-file set (1): matthew.json" in caplog.text


def test_extract_module_does_not_touch_output_after_incomplete_testament_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_root = tmp_path / "raw" / "CalvinCommentaries" / "modules" / "comments" / "zcom"
    module_dir = raw_root / "calvincommentaries"
    module_dir.mkdir(parents=True)
    output_dir = tmp_path / "data" / "commentaries" / "calvin"
    output_dir.mkdir(parents=True)
    stale = output_dir / "valid-existing-book.json"
    stale.write_text("valid output", encoding="utf-8")

    class IncompleteReader:
        def __init__(self, _module_dir: Path, testament: str, _prefix: str) -> None:
            if testament == "nt":
                raise FileNotFoundError("missing NT source files")

        def get_text_at_index(self, _bzv_index: int) -> bytes:
            return b""

    monkeypatch.setattr(sword_commentary, "SWORD_RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(sword_commentary, "OUTPUT_BASE", tmp_path / "data" / "commentaries")
    monkeypatch.setattr(sword_commentary, "SwordZComReader", IncompleteReader)

    with pytest.raises(IncompleteSourceError, match="NT"):
        sword_commentary.extract_module("calvin")

    assert stale.read_text(encoding="utf-8") == "valid output"


def _minimal_plan(module_name: str = "barnes") -> ModulePlan:
    return ModulePlan(
        module_name=module_name,
        outputs={"matthew.json": {"meta": {}, "data": []}},
        produced_book_osis=frozenset({"Matt"}),
        expected_book_osis=frozenset({"Matt"}),
        stats={
            "module": module_name,
            "books_written": 1,
            "entries_written": 0,
            "verses_empty": 0,
            "entries_failed": 0,
            "produced_book_files": ["matthew.json"],
            "word_count_stats": {},
            "entries_with_refs": 0,
        },
    )


def test_atomic_replacement_failure_preserves_existing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_base = tmp_path / "data" / "commentaries"
    output_dir = output_base / "barnes"
    output_dir.mkdir(parents=True)
    target = output_dir / "matthew.json"
    target.write_text(json.dumps({"meta": {"version": "old"}, "data": []}), encoding="utf-8")
    monkeypatch.setattr(sword_commentary, "OUTPUT_BASE", output_base)

    def fail_replace(_temp_file: Path, _out_file: Path) -> None:
        raise OSError("injected atomic replacement failure")

    monkeypatch.setattr(sword_commentary, "_replace_atomically", fail_replace)

    with pytest.raises(OSError, match="injected atomic replacement failure"):
        write_module_plans([_minimal_plan()])

    assert json.loads(target.read_text(encoding="utf-8"))["meta"]["version"] == "old"
    assert list(output_dir.glob(".matthew.json.*.tmp")) == []


def test_atomic_replacement_updates_target_and_keeps_writer_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_base = tmp_path / "data" / "commentaries"
    output_dir = output_base / "barnes"
    output_dir.mkdir(parents=True)
    target = output_dir / "matthew.json"
    target.write_text(json.dumps({"meta": {"version": "old"}, "data": []}), encoding="utf-8")
    monkeypatch.setattr(sword_commentary, "OUTPUT_BASE", output_base)

    new_output = {"meta": {"version": "new"}, "data": []}
    plan = _minimal_plan()
    plan.outputs["matthew.json"] = new_output
    write_module_plans([plan])

    assert json.loads(target.read_text(encoding="utf-8"))["meta"]["version"] == "new"
    manifests = list((tmp_path / "review" / "writer-manifests").glob("*.json"))
    assert len(manifests) == 1
    assert manifests[0].read_text(encoding="utf-8")
    assert list(output_dir.glob(".matthew.json.*.tmp")) == []


def test_batch_staging_failure_preserves_all_prior_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_base = tmp_path / "data" / "commentaries"
    for module_name in ("barnes", "calvin"):
        output_dir = output_base / module_name
        output_dir.mkdir(parents=True)
        (output_dir / "matthew.json").write_text(
            json.dumps({"meta": {"version": f"old-{module_name}"}, "data": []}),
            encoding="utf-8",
        )
    monkeypatch.setattr(sword_commentary, "OUTPUT_BASE", output_base)

    real_stage = sword_commentary._stage_book_output

    def fail_calvin_stage(out_file: Path, output: dict) -> Path:
        if out_file.parent.name == "calvin":
            raise OSError("injected Calvin staging failure")
        return real_stage(out_file, output)

    monkeypatch.setattr(sword_commentary, "_stage_book_output", fail_calvin_stage)

    with pytest.raises(OSError, match="injected Calvin staging failure"):
        write_module_plans([_minimal_plan("barnes"), _minimal_plan("calvin")])

    for module_name in ("barnes", "calvin"):
        target = output_base / module_name / "matthew.json"
        assert json.loads(target.read_text(encoding="utf-8"))["meta"]["version"] == f"old-{module_name}"
        assert list(target.parent.glob(".matthew.json.*.tmp")) == []


def test_main_all_preflights_every_module_before_any_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def fake_plan(module_name: str, *, dry_run: bool = False) -> ModulePlan:
        assert dry_run is False
        events.append(f"plan:{module_name}")
        return _minimal_plan(module_name)

    def fake_write(plans: list[ModulePlan]) -> None:
        events.append("write:" + ",".join(plan.module_name for plan in plans))

    monkeypatch.setattr(sword_commentary, "setup_logging", lambda: None)
    monkeypatch.setattr(sword_commentary, "report_quality", lambda _stats: None)
    monkeypatch.setattr(sword_commentary, "plan_module", fake_plan)
    monkeypatch.setattr(sword_commentary, "write_module_plans", fake_write)
    monkeypatch.setattr(sys, "argv", ["sword_commentary.py", "--all"])

    sword_commentary.main()

    assert events == [
        "plan:barnes",
        "plan:calvin",
        "plan:wesley",
        "write:barnes,calvin,wesley",
    ]


def test_main_all_planning_failure_never_starts_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def fake_plan(module_name: str, *, dry_run: bool = False) -> ModulePlan:
        assert dry_run is False
        events.append(f"plan:{module_name}")
        if module_name == "calvin":
            raise IncompleteSourceError("injected Calvin planning failure")
        return _minimal_plan(module_name)

    def fail_if_written(_plans: list[ModulePlan]) -> None:
        events.append("write")

    monkeypatch.setattr(sword_commentary, "setup_logging", lambda: None)
    monkeypatch.setattr(sword_commentary, "report_quality", lambda _stats: None)
    monkeypatch.setattr(sword_commentary, "plan_module", fake_plan)
    monkeypatch.setattr(sword_commentary, "write_module_plans", fail_if_written)
    monkeypatch.setattr(sys, "argv", ["sword_commentary.py", "--all"])

    with pytest.raises(SystemExit) as exc_info:
        sword_commentary.main()

    assert exc_info.value.code == 1
    assert events == ["plan:barnes", "plan:calvin", "plan:wesley"]


def test_kjv_position_table_matches_pysword_shapes() -> None:
    assert _chapter_lengths("Lev")[-10:] == [30, 37, 27, 24, 33, 44, 23, 55, 46, 34]
    assert _chapter_lengths("Esth") == [22, 23, 15, 17, 14, 14, 10, 17, 32, 3]
    assert len(_chapter_lengths("Ps")) == 150
    assert _chapter_lengths("Ps")[139:142] == [13, 10, 7]
    assert _chapter_lengths("Rom") == [32, 29, 31, 25, 21, 23, 25, 39, 33, 21, 36, 21, 14, 23, 33, 27]
    assert _chapter_lengths("Eph") == [23, 22, 21, 32, 33, 24]
    assert _chapter_lengths("3John") == [14]


@pytest.mark.slow
@pytest.mark.skipif(not CALVIN_MODULE_DIR.exists(), reason="raw Calvin SWORD module not downloaded")
def test_calvin_module_maps_to_settled_book_set() -> None:
    found_books: set[str] = set()

    for testament in ("ot", "nt"):
        reader = SwordZComReader(CALVIN_MODULE_DIR, testament, "b")
        position_map = build_verse_position_map(testament)
        for book_idx, (_name, osis, chapter_lengths) in enumerate(KJV_CANON[testament]):
            has_content = any(
                reader.get_text_at_index(position_map[(book_idx, chapter, verse)])
                for chapter, verse_count in enumerate(chapter_lengths, 1)
                for verse in range(1, verse_count + 1)
            )
            if has_content:
                found_books.add(osis)

    assert found_books == CALVIN_BOOKS
