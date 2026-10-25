from pathlib import Path
import hashlib

import pytest

from build.tools import prepare_two_lookup_volume_sidecars as lookup
from build.tools import install_two_lookup_volume_sidecars as installer
from ocd_kernel.library._common import PipelineError


ROOT = Path(__file__).resolve().parents[1]


def test_lookup_sources_cover_exact_two_books_and_eight_volume_files() -> None:
    rows = lookup._source_rows(ROOT)
    assert [row["label"] for row in rows] == [
        "mark", "exodus", "ia-01", "ia-02", "ia-03", "ia-04",
        "ia-05", "ia-06", "pg-07", "pg-08",
    ]
    assert all(not str(row["path"]).lower().endswith(".zip") for row in rows)


def test_lookup_source_binding_rejects_changed_member(monkeypatch: pytest.MonkeyPatch) -> None:
    original = lookup.sha256_file

    def changed_first_member(path: Path) -> str:
        if path.name == "chadwick_mark.xml":
            return "0" * 64
        return original(path)

    monkeypatch.setattr(lookup, "sha256_file", changed_first_member)
    with pytest.raises(PipelineError, match="retained source missing or changed"):
        lookup._source_rows(ROOT)


def test_guarded_install_restores_work_when_live_validation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wid = lookup.CHADWICK
    root = tmp_path / "root"
    staged = tmp_path / "staged"
    target = root / "library" / "works" / wid
    target.mkdir(parents=True)
    (target / "work.json").write_bytes(b"old-work")
    rel = f"library/works/{wid}/forms/en/editions/mark/acquisitions/mark.json"
    proposed = staged / rel
    proposed.parent.mkdir(parents=True)
    proposed.write_bytes(b"new-acquisition")
    digest = hashlib.sha256(proposed.read_bytes()).hexdigest()
    item = {"path": rel, "before_sha256": None, "proposed_sha256": digest}

    def reject_live(*_args: object, **_kwargs: object) -> None:
        raise PipelineError("forced live validation failure")

    monkeypatch.setattr(installer, "validate_acquisition", reject_live)
    with pytest.raises(PipelineError, match="forced live validation failure"):
        installer._install_one(root, staged, wid, [item])
    assert (target / "work.json").read_bytes() == b"old-work"
    assert not (target / "forms").exists()
    journals = list((root / "library" / ".sidecar-operations").glob("*/operation.json"))
    assert len(journals) == 1
    assert '"phase":"rolled-back"' in journals[0].read_text(encoding="utf-8")
