"""Focused raw census, TEI, projection, and stability checks for Batch 08."""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from build.tei.check_ledger import check_receipt
from build.tei.project_hf import project_file
from build.tei.spurgeon_mtp_to_tei import (
    census_spurgeon_mtp,
    convert_spurgeon_mtp_to_tei,
)
from build.lib.paths import REPO_ROOT

NS = {"tei": "http://www.tei-c.org/ns/1.0"}

pytestmark = pytest.mark.requires_local_artifacts


@pytest.fixture(scope="module")
def proof_artifacts(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    root = tmp_path_factory.mktemp("spurgeon-proof")
    census = census_spurgeon_mtp()
    tei_path = root / "spurgeon-mtp.proof-wave.tei.xml"
    convert_spurgeon_mtp_to_tei(output_path=tei_path, census=census)
    output_path = root / "spurgeon-mtp.proof-wave.jsonl"
    receipt_path = root / "spurgeon-mtp.proof-wave.jsonl.loss.json"
    project_file(tei_path, output_path, receipt_path=receipt_path, repo_root=root)
    return {
        "root": root,
        "census": census,
        "tei_path": tei_path,
        "output_path": output_path,
        "receipt_path": receipt_path,
    }


def test_family_census_is_raw_and_selection_is_bounded(proof_artifacts: dict[str, object]) -> None:
    census = proof_artifacts["census"]
    assert census["source"]["file_count"] == 3547
    assert census["source"]["scope"]["selected_sermons"] == [1, 15, 317]
    assert census["family_census"]["list_elements"] == {"ol": 3766, "ul": 0, "li": 3767}
    assert census["family_census"]["files_with_article_lists"] == 3403
    assert census["family_census"]["files_without_article_ol_ul"] == 144
    assert census["family_census"]["nested_list_elements"] == 9
    assert census["features"]["ordered_lists"]["count"] == 5
    assert census["features"]["bulleted_lists"]["count"] == 0


def test_tei_carries_censused_list_boundaries_and_validates(
    proof_artifacts: dict[str, object],
) -> None:
    tei_path = proof_artifacts["tei_path"]
    census = proof_artifacts["census"]
    tree = etree.parse(str(tei_path))
    relaxng = etree.RelaxNG(
        etree.parse(str(REPO_ROOT / "ocd_kernel" / "tei" / "vendor" / "relaxng" / "tei_all.rng"))
    )
    assert relaxng.validate(tree), str(relaxng.error_log)
    assert len(tree.xpath("//tei:div[@type='sermon']", namespaces=NS)) == 3
    assert len(tree.xpath("//tei:list", namespaces=NS)) == census["features"]["ordered_lists"]["count"]
    assert len(tree.xpath("//tei:list[@type='ordered']", namespaces=NS)) == 5
    assert len(tree.xpath("//tei:list[@type='bulleted']", namespaces=NS)) == 0
    assert len(tree.xpath("//tei:item", namespaces=NS)) == census["features"]["list_items"]["count"]
    assert len(tree.xpath("//tei:list/tei:item/tei:list", namespaces=NS)) == 1
    assert all(node.get("rend") == "a" for node in tree.xpath("//tei:list", namespaces=NS))


def test_projection_and_ledger_pass_and_keep_list_text(
    proof_artifacts: dict[str, object],
) -> None:
    output = Path(proof_artifacts["output_path"])
    receipt = Path(proof_artifacts["receipt_path"])
    assert check_receipt(receipt, repo_root=Path(proof_artifacts["root"])) == []
    projected = output.read_text(encoding="utf-8")
    assert "First of all, we have set before us" in projected
    assert "SPURGEON" in projected
    assert '"id":"spurgeon-mtp/proof-wave/spurgeon-mtp-15"' in projected


def test_conversion_is_byte_stable(proof_artifacts: dict[str, object]) -> None:
    root = Path(proof_artifacts["root"])
    second = root / "second.tei.xml"
    convert_spurgeon_mtp_to_tei(
        output_path=second,
        census=proof_artifacts["census"],
    )
    assert second.read_bytes() == Path(proof_artifacts["tei_path"]).read_bytes()
