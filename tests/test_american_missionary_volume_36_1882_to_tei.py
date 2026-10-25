from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from lxml import etree

from build.tei.american_missionary_volume_36_1882_to_tei import ConversionError, convert
from ocd_kernel.tei.validate import validate_file

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "sources" / "structured-text" / "american-missionary-volume-36-1882" / "config.json"
RAW = Path(r"D:\Library\Open Christian Data\raw\clean-ready-acquisition-to-tei\master-5\35\american-missionary-volume-36-1882")
NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.requires_local_artifacts
def test_complete_annual_candidate_accounting_and_validation(tmp_path: Path) -> None:
    report = tmp_path / "report"
    candidate_path = report / "candidate.xml"
    convert(CONFIG, RAW, candidate_path, report)
    accounting = json.loads((report / "accounting.json").read_text(encoding="utf-8"))
    receipt = json.loads((report / "receipt.json").read_text(encoding="utf-8"))
    validation = json.loads((report / "validation.json").read_text(encoding="utf-8"))
    tree = etree.parse(candidate_path)

    assert _sha256(candidate_path) == "dd5a32ffd070badcd110227e61635a97a0f20962b8278cda79d67946b40958c2"
    assert validate_file(candidate_path) == []
    assert validation["status"] == "technically_valid_nonaccepted_candidate"
    assert validation["tei_p5_xsd_valid"] is True
    assert accounting["issue_count"] == 12
    assert accounting["issue_order"] == [57445, 57446, 57510, 57591, 57859, 57974, 58038, 58050, 58051, 58126, 58127, 58128]
    assert accounting["issue_months"] == ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    assert accounting["source_carrier_count"] == accounting["candidate_carrier_count"] == 18242
    assert accounting["source_carrier_stream_sha256"] == accounting["candidate_carrier_stream_sha256"] == "2b1f2ae0371e03eb46ebe0f3f4db7af5acb2218a1117a768c68df2a8b418ca66"
    assert accounting["omitted_source_carrier_ids"] == []
    assert accounting["duplicated_source_carrier_ids"] == []
    assert accounting["dangling_internal_references"] == []
    assert accounting["page_break_count"] == 393
    assert accounting["table_count"] == 472
    assert accounting["table_row_count"] == 7420
    assert accounting["table_cell_count"] == 14163
    assert accounting["graphic_count"] == 136
    assert accounting["heading_count"] == 400
    assert accounting["article_division_count"] == 316
    assert accounting["advertisement_division_count"] == 159
    assert len(receipt["issue_receipts"]) == 12
    assert sum(len(issue["members"]) for issue in receipt["issue_receipts"]) == 159
    assert len(receipt["raw_files"]) == 280
    assert tree.xpath("count(//tei:div[@type='issue'])", namespaces=NS) == 12
    issue_heads = tree.xpath("//tei:div[@type='issue']/tei:head/text()", namespaces=NS)
    assert issue_heads[0] == "Number 1: January 1882 (Project Gutenberg 57445)"
    assert issue_heads[-1] == "Number 12: December 1882 (Project Gutenberg 58128)"
    visible = " ".join(tree.xpath("//tei:text//text()", namespaces=NS))
    january_text = " ".join(tree.xpath("//tei:div[@type='issue'][@n='1']//text()", namespaces=NS))
    february_text = " ".join(tree.xpath("//tei:div[@type='issue'][@n='2']//text()", namespaces=NS))
    assert "There will be many important events occurring during the coming year" in january_text
    assert "Do you know, for instance, that a sober and Christian young man" in january_text
    assert "There will be many important events occurring during the coming year" in february_text
    assert "Do you know now, for instance, that a sober and Christian young man" in february_text
    assert "Entered at the Post-Office at New York, N.Y., as second-class" in visible
    assert "Constitution of the American Missionary Association" in visible
    assert "PEEPING THROUGH (Cut)" in visible
    assert "END OF THE PROJECT GUTENBERG EBOOK THE AMERICAN MISSIONARY" in visible
    assert "public domain in the USA" in etree.tostring(tree.getroot(), encoding="unicode")


@pytest.mark.requires_local_artifacts
def test_source_hash_mutation_is_rejected(tmp_path: Path) -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    config["issues"][0]["html_sha256"] = "0" * 64
    mutated = tmp_path / "mutated-config.json"
    mutated.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ConversionError, match="Retained source hash mismatch"):
        convert(mutated, RAW, tmp_path / "candidate.xml", tmp_path / "report")


@pytest.mark.requires_local_artifacts
def test_fresh_process_different_cwd_determinism(tmp_path: Path) -> None:
    outputs: list[tuple[bytes, bytes, bytes, bytes]] = []
    for index, cwd in enumerate((REPO, RAW), start=1):
        report = tmp_path / f"report-{index}"
        candidate = report / "candidate.xml"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO)
        command = [
            sys.executable,
            "-m",
            "build.tei.american_missionary_volume_36_1882_to_tei",
            "--config",
            str(CONFIG),
            "--raw-root",
            str(RAW),
            "--output",
            str(candidate),
            "--report-dir",
            str(report),
        ]
        subprocess.run(command, cwd=cwd, env=env, check=True, capture_output=True, text=True)
        outputs.append((candidate.read_bytes(), (report / "receipt.json").read_bytes(), (report / "accounting.json").read_bytes(), (report / "validation.json").read_bytes()))
    assert outputs[0] == outputs[1]
    assert hashlib.sha256(outputs[0][0]).hexdigest() == "dd5a32ffd070badcd110227e61635a97a0f20962b8278cda79d67946b40958c2"
