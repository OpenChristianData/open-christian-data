import json
from pathlib import Path

import pytest

from build.tools import install_expositors_companions as installer
from build.tools import install_expositors_sidecars as base_installer
from build.tools import prepare_expositors_companions as companions
from build.tools.prepare_expositors_sidecars import _credit, _header
from ocd_kernel.library._common import PipelineError, sha256_file


ROOT = Path(__file__).resolve().parents[1]


def test_packet_binds_three_direct_xml_companions() -> None:
    packet = json.loads((ROOT / companions.PACKET_REL).read_text(encoding="utf-8"))
    previous = json.loads((ROOT / companions.PREVIOUS_PACKET_REL).read_text(encoding="utf-8"))
    assert len(packet["source_members"]) == 3
    assert {row["work_id"] for row in packet["source_members"]} == set(companions.COMPANIONS)
    for row in packet["source_members"]:
        assert row["path"].endswith(".xml")
        source = ROOT / row["path"]
        assert source.stat().st_size == row["bytes"]
        assert sha256_file(source) == row["sha256"]
        assert _header(source)["title"] == row["source_title"]
        assert any(item["work_id"] == row["work_id"]
                   and item["source_author"] == row["source_author"]
                   for item in previous["source_members"])
        assert "Same-author retained member omitted" in row["profile_exclusion_reason"]


def test_companion_credit_removes_old_held_notice() -> None:
    packet = json.loads((ROOT / companions.PACKET_REL).read_text(encoding="utf-8"))
    previous = json.loads((ROOT / companions.PREVIOUS_PACKET_REL).read_text(encoding="utf-8"))
    for row in packet["source_members"]:
        old = _credit(row["work_id"], [item for item in previous["source_members"]
                                        if item["work_id"] == row["work_id"]])
        updated = companions._updated_credit(old, row)
        assert row["path"] in updated
        assert "remains unaccounted in this stage" not in updated
        assert "CCEL.org" in updated


def test_companion_installer_restores_previous_after_failed_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wid = "expositors-bible--fixture"
    relative = f"library/works/{wid}/work.json"
    root, staged = tmp_path / "root", tmp_path / "stage"
    current = root / relative
    proposed = staged / relative
    current.parent.mkdir(parents=True)
    proposed.parent.mkdir(parents=True)
    current.write_text('{"version":"old"}', encoding="utf-8")
    proposed.write_text('{"version":"new"}', encoding="utf-8")
    before = sha256_file(current)
    item = {"path": relative, "before_sha256": before,
            "proposed_sha256": sha256_file(proposed)}

    def fail_validation(*_args: object, **_kwargs: object) -> None:
        raise PipelineError("synthetic validation failure")

    monkeypatch.setattr(base_installer, "validate_state", fail_validation)
    with pytest.raises(PipelineError, match="synthetic validation failure"):
        installer._install_one(root, staged, wid, [item])
    assert sha256_file(current) == before
    journals = list((root / "library/.sidecar-operations").glob("*/operation.json"))
    assert len(journals) == 1
    assert base_installer.load_json(journals[0])["phase"] == "rolled-back"
