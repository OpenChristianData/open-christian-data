"""Exact NPNF211 stage boundaries and guarded install preflight."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from lxml import etree

from build.tools import install_npnf211_electronic_acceptances as installer
from build.tools.install_npnf211_electronic_acceptances import (
    RECEIPT_SHA256, STAGE, WORKS, _category_only, preflight,
)
from ocd_kernel.library._common import PipelineError
from tests.npnf_acquired_historical_fixture import historical_npnf_root
from ocd_kernel.tei.install_accepted import _files, _io_path


CURRENT_ROOT = installer.ROOT


@pytest.fixture(scope="module", autouse=True)
def historical_acquired_context(tmp_path_factory):
    """Exercise the real installer against exact retained acquired bytes."""
    root = historical_npnf_root(installer.STAGE, tmp_path_factory.mktemp("npnf-historical"))
    receipt = json.loads(_io_path(installer.STAGE / "stage-receipt.json").read_bytes())
    before = {row["work_id"]: _files(CURRENT_ROOT / "library/works" / row["work_id"]) for row in receipt["works"]}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(installer, "ROOT", root)
        from functools import partial
        patch.setitem(globals(), "preflight", partial(installer.preflight, root=root))
        yield root
    assert all(_files(CURRENT_ROOT / "library/works" / work_id) == saved for work_id, saved in before.items())


def test_current_generation_is_not_the_retained_acquired_preimage():
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(installer, "ROOT", CURRENT_ROOT)
        with pytest.raises(PipelineError, match="preimage|generation"):
            installer.preflight("vincent-of-lerins-commonitory", root=CURRENT_ROOT)


def _read(path: Path) -> bytes:
    return _io_path(path).read_bytes()


def test_three_work_stage_has_exact_source_boundaries_and_preflight() -> None:
    receipt = json.loads(_read(STAGE / "stage-receipt.json"))
    assert hashlib.sha256(_read(STAGE / "stage-receipt.json")).hexdigest() == RECEIPT_SHA256
    assert {row["work_id"] for row in receipt["works"]} == WORKS
    expected = {"ii": ("sulpitius-severus-selected-works", 2213, 6),
                "iii": ("vincent-of-lerins-commonitory", 829, 37),
                "iv": ("john-cassian-selected-works", 11908, 7)}
    assert sum(row["source_element_count"] for row in receipt["works"]) == 14950
    for row in receipt["works"]:
        scope = row["source_root_id"]
        assert (row["work_id"], row["source_element_count"], row["division_count"]) == expected[scope]
        assert preflight(row["work_id"])["projection_rows"] == 1
        work = STAGE / "library/works" / row["work_id"]
        boundaries = json.loads(_read(work / "integration/npnf211-electronic-v1/source-boundaries.json"))
        assert boundaries["source_root_id"] == scope
        assert len(boundaries["constituent_divisions"]) == row["division_count"]
        master = next(_io_path(work).rglob("master.tei.xml"))
        tree = etree.fromstring(master.read_bytes())
        tei_divs = tree.xpath("/t:TEI/t:text/t:body/t:div/t:div", namespaces={"t": "http://www.tei-c.org/ns/1.0"})
        assert [node.get("{http://www.w3.org/XML/1998/namespace}id") for node in tei_divs] == [
            division["tei_id"] for division in boundaries["constituent_divisions"]
        ]


def test_only_prose_category_can_be_added_to_work_identity(tmp_path: Path) -> None:
    original = {"work_id": "vincent-of-lerins-commonitory", "textual_forms": [{"editions": [{"edition_id": "e"}]}]}
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text(json.dumps(original), encoding="utf-8")
    changed = json.loads(old.read_text(encoding="utf-8"))
    changed["textual_forms"][0]["editions"][0]["category"] = "prose"
    new.write_text(json.dumps(changed), encoding="utf-8")
    _category_only(old, new, work_id="vincent-of-lerins-commonitory")
    changed["title"] = "invented title"
    new.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(PipelineError, match="more than edition prose category"):
        _category_only(old, new, work_id="vincent-of-lerins-commonitory")


@pytest.fixture
def isolated_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, str, dict[str, object]]:
    """Copy the pinned edition and its external dependencies into short local roots."""
    work_id = "vincent-of-lerins-commonitory"
    root, stage = tmp_path / "r", tmp_path / "s"
    relative_work = Path("library/works") / work_id
    original_root, original_stage = installer.ROOT, installer.STAGE

    def copy_tree(source: Path, destination: Path) -> None:
        base = _io_path(source)
        for path in base.rglob("*"):
            if path.is_file():
                target = _io_path(destination / path.relative_to(base))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())

    copy_tree(original_root / relative_work, root / relative_work)
    copy_tree(original_stage / relative_work, stage / relative_work)
    for path in _io_path(original_stage).rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(_io_path(original_stage))
        if relative.parts[:2] == ("library", "works"):
            continue
        destination = _io_path(stage / relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(path.read_bytes())
        if relative.as_posix() != "stage-receipt.json":
            mirror = _io_path(root / relative)
            mirror.parent.mkdir(parents=True, exist_ok=True)
            mirror.write_bytes(path.read_bytes())
    receipt = json.loads(_read(stage / "stage-receipt.json"))
    row = next(item for item in receipt["works"] if item["work_id"] == work_id)
    monkeypatch.setattr(installer, "ROOT", root)
    monkeypatch.setattr(installer, "STAGE", stage)
    assert hashlib.sha256(_read(stage / "stage-receipt.json")).hexdigest() == RECEIPT_SHA256
    assert installer.preflight(work_id, root=root)["status"] == "preflight-pass"
    return root, stage, work_id, row


def test_isolated_pinned_install_commits_and_journals(isolated_install: tuple[Path, Path, str, dict[str, object]]) -> None:
    root, stage, work_id, row = isolated_install
    result = installer.install(work_id)
    assert result["status"] == "installed-and-validated"
    assert _files(root / "library/works" / work_id) == row["after"]
    assert _files(stage / "library/works" / work_id) == row["after"]
    journal = json.loads(_read(Path(result["operation"]) / "operation.json"))
    assert journal["phase"] == "complete"


def test_isolated_install_rolls_back_after_new_live(isolated_install: tuple[Path, Path, str, dict[str, object]]) -> None:
    root, stage, work_id, row = isolated_install

    def fail_after_new_live(phase: str) -> None:
        if phase == "after-new-live":
            raise RuntimeError("injected after-new-live failure")

    with pytest.raises(RuntimeError, match="injected after-new-live failure"):
        installer.install(work_id, fail_at=fail_after_new_live)
    assert _files(root / "library/works" / work_id) == row["before"]
    assert _files(stage / "library/works" / work_id) == row["after"]
    journals = list((root / ".tmp_audit").rglob("operation.json"))
    assert len(journals) == 1
    assert json.loads(_read(journals[0]))["phase"] == "rolled-back"


def test_isolated_install_rejects_stale_canonical_preimage(isolated_install: tuple[Path, Path, str, dict[str, object]]) -> None:
    root, _stage, work_id, row = isolated_install
    work = root / "library/works" / work_id
    state = work / "state.json"
    _io_path(state).write_bytes(_read(state) + b" ")
    with pytest.raises(PipelineError, match="canonical preimage"):
        installer.install(work_id)
    assert _files(work) != row["after"]
    assert not (root / ".tmp_audit").exists()
