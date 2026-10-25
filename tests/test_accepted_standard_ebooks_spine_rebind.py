"""Focused accepted-source rebind, public acceptance, and swap rollback tests."""
from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path

import pytest

import build.tools.install_accepted_standard_ebooks_spine_rebind as installer
from build.tools.prepare_accepted_standard_ebooks_spine_rebind import IDS, PACKET_REL, _body
from ocd_kernel.library._common import PipelineError, canonical_bytes, load_json, write_json
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _io_path
from hashlib import sha256


ROOT = Path(__file__).resolve().parents[1]
STAGE = Path("C:/Scratch/ocd-se3-spine-stage-20260926-v5")

METADATA_CONTEXT = ROOT / "tests/fixtures/reconstruction-runtime/authorities/standard-ebooks-three-metadata-successor.json"
METADATA_CONTEXT_SHA256 = "aa89ce51f06c367586dbb46b77868c3ac3e5de68e16c11d054895cf9eb381c88"
RIGHTS_NORMALIZATIONS = {
    "imitation-of-christ": "7a3fdde11a37f11fb7a41c54d3048fbe85c195dc92f92c262572317774083233",
    "paradise-lost": "b43bc4d7b14b703102e4de3d94600579abd6f807091ecd59ef4cffede46e4ad3",
    "pilgrims-progress": "e6b98ed3b4b051cc9dbbbb64bdaf56f65cf07c9e3e6c05758b81d6879387e174",
}


def _before_rights_normalization(work_id: str, content: bytes) -> bytes:
    record = json.loads(content)
    evidence = record["evidence"][-1]
    expected_path = f"library/works/{work_id}/publication/us-rights-20261023/{record['record_id']}-normalization.json"
    assert evidence == {"path": expected_path, "pointer": "", "sha256": RIGHTS_NORMALIZATIONS[work_id]}
    raw = (ROOT / expected_path).read_bytes()
    assert sha256(raw).hexdigest() == RIGHTS_NORMALIZATIONS[work_id]
    normalization = json.loads(raw)
    assert all(record[key] == value for key, value in normalization["assessment"].items())
    assert record["assessed_by"] == "OCD U.S.-first evidence reconciliation; independently reviewed"
    assert record["assessed_on"] == "2026-10-23"
    assert record["scope_note"] == normalization["disposition"]
    assert record["evidence"][-2] == {
        "path": "plans/2026-10-02-v1-public-information-drafts/artifacts/targeted-rights-research-20261023/us-priority/DECISIONS.json",
        "pointer": f"/findings/{work_id}",
        "sha256": "17dbfe9b4a7c315f0aa97bd4c9047dfddf3b760801a93c52da65d9cdb894f6df",
    }
    record.update(assessed_by="Existing reviewed release/rights evidence; mechanical migration candidate",
                  assessed_on="2026-10-20", jurisdictions=[], scope_note=normalization["effective_license"],
                  evidence=[*record["evidence"][:-2], normalization["supersedes"]])
    return canonical_bytes(record)


def _retained_installed_tree(work_id: str, proposed: dict, current: dict) -> dict:
    raw = METADATA_CONTEXT.read_bytes()
    assert sha256(raw).hexdigest() == METADATA_CONTEXT_SHA256
    context = json.loads(raw)
    assert set(context["works"]) == set(IDS)
    row = context["works"][work_id]
    current_work = (ROOT / "library/works" / work_id / "work.json").read_bytes()
    assert len(current_work) == row["current_work"]["bytes"]
    assert sha256(current_work).hexdigest() == current["work.json"] == row["current_work"]["sha256"]
    original_work = (STAGE / "library/works" / work_id / "work.json").read_bytes()
    assert sha256(original_work).hexdigest() == proposed["work.json"] == row["original_work_sha256"]
    restored = json.loads(current_work)
    original = json.loads(original_work)
    assert "creators" not in original and restored["creators"]
    del restored["creators"]
    assert restored == original
    rights = row["rights_additions"]
    assert len(rights) == 6
    assert {name for name in set(current) - set(proposed) if not name.startswith("publication/")} == set(rights)
    for name, pin in rights.items():
        assert "/rights/" in name or "/rights-subjects/" in name
        content = (ROOT / "library/works" / work_id / name).read_bytes()
        assert sha256(content).hexdigest() == current[name]
        if name.endswith("-selected-assessment.json"):
            content = _before_rights_normalization(work_id, content)
        assert len(content) == pin["bytes"]
        assert sha256(content).hexdigest() == pin["sha256"]
    retained = {name: pin for name, pin in current.items() if name not in rights}
    retained["work.json"] = row["original_work_sha256"]
    return retained


def test_opf_sources_and_complete_checkout_support() -> None:
    packet = load_json(ROOT / PACKET_REL)
    counts = dict(zip(IDS, ((126, 16), (16, 17), (11, 15)), strict=True))
    for row in packet["works"]:
        source, support = row["ordered_text_members"], row["support_members"]
        assert (len(source), len(support)) == counts[row["work_id"]]
        assert all(item["path"].endswith(".xhtml") for item in source)
        assert row["opf"]["path"] in {item["path"] for item in support}
        assert not {item["path"] for item in source} & {item["path"] for item in support}


def test_all_three_public_acceptance_records_preflight_with_unchanged_text() -> None:
    receipt = load_json(ROOT / installer.RECEIPT_REL)
    installed = True
    for row in receipt["works"]:
        current = installer._tree(ROOT / "library/works" / row["work_id"])
        current = _retained_installed_tree(row["work_id"], row["proposed_tree"], current)
        # Later publication records do not undo an exact retained installed edition.
        assert all(name.startswith("publication/") for name in set(current) - set(row["proposed_tree"]))
        installed = installed and all(current.get(name) == digest for name, digest in row["proposed_tree"].items())
    if not installed:
        assert len(installer.preflight(ROOT, STAGE)["works"]) == 3
    for row in receipt["works"]:
        work_id = row["work_id"]
        assert len(row["changed_files"]) == 16
        edition = next((STAGE / "library/works" / work_id).rglob("master.tei.xml"))
        original = STAGE / "library/works" / work_id / "integration/reviewed-standard-ebooks-v1/original-package/content.tei.xml"
        assert _body(_io_path(original).read_bytes()) == _body(_io_path(edition).read_bytes())
        staged_acceptance = next((STAGE / "library/works" / work_id).rglob("acceptance.json"))
        new_acceptance = json.loads(_io_path(staged_acceptance).read_text())
        assert new_acceptance["identity"]["work_id"] == work_id
        assert new_acceptance["decision"]["human_decision"]["status"] == "not-recorded"
        assert new_acceptance["decision"]["agent_assessment"]["status"] == "accepted"
        if installed:
            canonical_acceptance = next((ROOT / "library/works" / work_id).rglob("acceptance.json"))
            validate_acceptance(canonical_acceptance, root=ROOT)
            assert json.loads(_io_path(canonical_acceptance).read_text()) == new_acceptance
        else:
            old_acceptance = next((ROOT / "library/works" / work_id).rglob("acceptance.json"))
            before = json.loads(_io_path(old_acceptance).read_text())
            assert before["identity"] == new_acceptance["identity"]
            assert before["decision"]["human_decision"] == new_acceptance["decision"]["human_decision"]
            assert before["decision"]["agent_assessment"]["status"] == new_acceptance["decision"]["agent_assessment"]["status"]


def test_post_swap_failure_restores_exact_previous_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, staged, work_id = tmp_path / "repo", tmp_path / "stage", "pilgrims-progress"
    current = root / "library/works" / work_id / "work.json"
    proposed = staged / "library/works" / work_id / "work.json"
    current.parent.mkdir(parents=True)
    proposed.parent.mkdir(parents=True)
    current.write_text("before", encoding="utf-8")
    proposed.write_text("after", encoding="utf-8")
    before, after = installer._tree(current.parent), installer._tree(proposed.parent)
    row = {"work_id": work_id, "before_tree_sha256": sha256(canonical_bytes(before)).hexdigest(),
           "proposed_tree": after}
    monkeypatch.setattr(installer, "preflight", lambda *_args: {"works": [row]})
    monkeypatch.setattr(installer, "acquire_jsonl_lock", lambda *_args, **_kwargs: nullcontext())
    packet = root / installer.PACKET_REL
    packet.parent.mkdir(parents=True)
    write_json(packet, {"works": [{"work_id": work_id, "paths": {
        "acceptance": f"library/works/{work_id}/acceptance.json"}}]})
    monkeypatch.setattr(installer, "validate_acceptance", lambda *_args, **_kwargs:
                        (_ for _ in ()).throw(PipelineError("injected acceptance failure")))
    with pytest.raises(PipelineError, match="injected acceptance failure"):
        installer.install_one(root, staged, work_id)
    assert current.read_text(encoding="utf-8") == "before"
    journals = list((root / "library/.sidecar-operations").glob("*/operation.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_text(encoding="utf-8"))["phase"] == "rolled-back"


def test_interrupt_between_renames_restores_previous_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, staged, work_id = tmp_path / "repo", tmp_path / "stage", "paradise-lost"
    current = root / "library/works" / work_id / "work.json"
    proposed = staged / "library/works" / work_id / "work.json"
    current.parent.mkdir(parents=True)
    proposed.parent.mkdir(parents=True)
    current.write_text("before", encoding="utf-8")
    proposed.write_text("after", encoding="utf-8")
    before, after = installer._tree(current.parent), installer._tree(proposed.parent)
    row = {"work_id": work_id, "before_tree_sha256": sha256(canonical_bytes(before)).hexdigest(),
           "proposed_tree": after}
    monkeypatch.setattr(installer, "preflight", lambda *_args: {"works": [row]})
    monkeypatch.setattr(installer, "acquire_jsonl_lock", lambda *_args, **_kwargs: nullcontext())
    original_rename = Path.rename
    interrupted = False

    def interrupt_incoming(self: Path, target: Path) -> Path:
        nonlocal interrupted
        if self.name == "incoming" and not interrupted:
            interrupted = True
            raise KeyboardInterrupt("injected between renames")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", interrupt_incoming)
    with pytest.raises(KeyboardInterrupt, match="injected between renames"):
        installer.install_one(root, staged, work_id)
    assert interrupted
    assert current.read_text(encoding="utf-8") == "before"
    journals = list((root / "library/.sidecar-operations").glob("*/operation.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_text(encoding="utf-8"))["phase"] == "rolled-back"


@pytest.mark.parametrize("change", ["rights", "normalized-rights", "work", "extra"])
def test_later_metadata_accounting_rejects_unreviewed_generation_changes(change: str) -> None:
    row = load_json(ROOT / installer.RECEIPT_REL)["works"][0]
    current = installer._tree(ROOT / "library/works" / row["work_id"])
    assert _retained_installed_tree(row["work_id"], row["proposed_tree"], current)
    if change == "rights":
        path = next(name for name in current if "/rights/" in name)
        current[path] = "0" * 64
    elif change == "normalized-rights":
        path = next(name for name in current if name.endswith("-selected-assessment.json"))
        current[path] = "0" * 64
    elif change == "work":
        current["work.json"] = "0" * 64
    else:
        current["unreviewed.json"] = "0" * 64
    with pytest.raises(AssertionError):
        _retained_installed_tree(row["work_id"], row["proposed_tree"], current)


def test_current_installed_generation_is_not_reaccepted_as_historical_before() -> None:
    with pytest.raises(PipelineError, match="complete retained checkout differs from accepted acquisition"):
        installer.preflight(ROOT, STAGE)
