from pathlib import Path

import pytest

from build.tools import prepare_expositors_sidecars as expositors
from build.tools import install_expositors_sidecars as installer
from ocd_kernel.library._common import PipelineError


ROOT = Path(__file__).resolve().parents[1]


def test_exact_pinned_member_and_directory_census() -> None:
    members, references = expositors.audit(ROOT)
    outside = expositors.outside_profile(ROOT, members)
    assert len(members) == 39
    assert len({row["work_id"] for row in members}) == 22
    assert len(references) == 8
    assert len(outside) == 8
    assert {row["path"] for row in outside if "held companion" in row["disposition"]} == {
        "raw/ccel/expositors-bible/dods_expositorjohn2.xml",
        "raw/ccel/expositors-bible/smith_ga_expositorisa1.xml",
        "raw/ccel/expositors-bible/stokes_expositoracts1.xml",
    }


def test_directory_census_rejects_missing_selected_member() -> None:
    members, _ = expositors.audit(ROOT)
    with pytest.raises(PipelineError, match="47-file retained directory"):
        expositors.outside_profile(ROOT, members[1:])


def test_source_header_mutation_rejects_profile_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    original = expositors._header

    def wrong_title(path: Path) -> dict[str, str]:
        header = original(path)
        header["title"] = "A different work"
        return header

    monkeypatch.setattr(expositors, "_header", wrong_title)
    with pytest.raises(PipelineError, match="header/profile identity differs"):
        expositors.audit(ROOT)


def test_credit_marks_held_companion_volume() -> None:
    members, _ = expositors.audit(ROOT)
    dods = [row for row in members if row["work_id"] == "expositors-bible--marcus-dods"]
    credit = expositors._credit("expositors-bible--marcus-dods", dods)
    assert "dods_expositorjohn2.xml" in credit
    assert "remains unaccounted" in credit


def _fixture_generation(tmp_path: Path) -> tuple[Path, Path, str, list[dict[str, str | None]]]:
    root, staged, wid = tmp_path / "root", tmp_path / "stage", "expositors-bible--fixture"
    relative = f"library/works/{wid}/work.json"
    current = root / relative
    proposed = staged / relative
    current.parent.mkdir(parents=True)
    proposed.parent.mkdir(parents=True)
    current.write_text('{"version":"old"}', encoding="utf-8")
    proposed.write_text('{"version":"new"}', encoding="utf-8")
    items = [{"path": relative, "before_sha256": installer.sha256_file(current),
              "proposed_sha256": installer.sha256_file(proposed)}]
    return root, staged, wid, items


def test_guarded_swap_installs_exact_stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, staged, wid, items = _fixture_generation(tmp_path)
    monkeypatch.setattr(installer, "validate_state", lambda *_args, **_kwargs: None)
    result = installer._install_one(root, staged, wid, items)
    assert installer.sha256_file(installer._file(root, items[0]["path"])) == items[0]["proposed_sha256"]
    assert installer._file(Path(result["operation"]), "operation.json").is_file()


def test_guarded_swap_restores_previous_on_validation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, staged, wid, items = _fixture_generation(tmp_path)

    def fail_validation(*_args: object, **_kwargs: object) -> None:
        raise PipelineError("synthetic validation failure")

    monkeypatch.setattr(installer, "validate_state", fail_validation)
    with pytest.raises(PipelineError, match="synthetic validation failure"):
        installer._install_one(root, staged, wid, items)
    assert installer.sha256_file(installer._file(root, items[0]["path"])) == items[0]["before_sha256"]
    journals = list((root / "library/.sidecar-operations").glob("*/operation.json"))
    assert len(journals) == 1
    assert installer.load_json(journals[0])["phase"] == "rolled-back"
