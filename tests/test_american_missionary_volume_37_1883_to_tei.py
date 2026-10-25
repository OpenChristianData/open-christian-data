from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from lxml import etree

from build.tei.american_missionary_volume_37_1883_to_tei import ConversionError, convert
from ocd_kernel.tei.validate import validate_file

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "sources" / "structured-text" / "american-missionary-volume-37-1883" / "config.json"
RAW = Path(r"D:\Library\Open Christian Data\raw\clean-ready-acquisition-to-tei\master-5\35\american-missionary-volume-37-1883")
REPORT = Path(r"D:\Library\Open Christian Data\reports\clean-ready-acquisition-to-tei\master-5\35\american-missionary-volume-37-1883")
CANDIDATE = REPORT / "candidate" / "american-missionary-volume-37-1883.tei.xml"
NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.requires_local_artifacts
def test_complete_annual_candidate_accounting_and_validation() -> None:
    accounting = json.loads((REPORT / "accounting.json").read_text(encoding="utf-8"))
    receipt = json.loads((REPORT / "receipt.json").read_text(encoding="utf-8"))
    validation = json.loads((REPORT / "validation.json").read_text(encoding="utf-8"))
    tree = etree.parse(CANDIDATE)

    assert _sha256(CANDIDATE) == "87509ed34e067a206afcafc60028be97c1879f668a44eec7f543bba121172598"
    assert validate_file(CANDIDATE) == []
    assert validation["status"] == "technically_valid_nonaccepted_candidate"
    assert validation["tei_p5_xsd_valid"] is True
    assert accounting["issue_count"] == 12
    assert accounting["issue_order"] == [60298, 60314, 60476, 60697, 60775, 61012, 61015, 61019, 61820, 61846, 61866, 63146]
    assert accounting["issue_months"] == ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    assert accounting["source_carrier_count"] == accounting["candidate_carrier_count"] == 16571
    assert accounting["source_carrier_stream_sha256"] == accounting["candidate_carrier_stream_sha256"] == "6dd2fd20038b55e15b43214e86242ba4e138832cab2ead9b26ada270716c1644"
    assert accounting["omitted_source_carrier_ids"] == []
    assert accounting["duplicated_source_carrier_ids"] == []
    assert accounting["dangling_internal_references"] == []
    assert accounting["page_break_count"] == 404
    assert accounting["table_count"] == 493
    assert accounting["table_row_count"] == 6309
    assert accounting["table_cell_count"] == 11818
    assert accounting["graphic_count"] == 164
    assert accounting["heading_count"] == 424
    assert accounting["article_division_count"] == 341
    assert accounting["advertisement_division_count"] == 163
    assert len(receipt["issue_receipts"]) == 12
    assert sum(len(issue["members"]) for issue in receipt["issue_receipts"]) == 189
    assert len(receipt["raw_files"]) == 310
    assert tree.xpath("count(//tei:div[@type='issue'])", namespaces=NS) == 12
    issue_heads = tree.xpath("//tei:div[@type='issue']/tei:head/text()", namespaces=NS)
    assert issue_heads[0] == "Number 1: January 1883 (Project Gutenberg 60298)"
    assert issue_heads[-1] == "Number 12: December 1883 (Project Gutenberg 63146)"
    visible = " ".join(tree.xpath("//tei:text//text()", namespaces=NS))
    assert "Entered at the Post-Office at New York, N.Y., as second-class" in visible
    assert "A MISSION HOME." in visible
    assert "PROPOSED CONSTITUTION OF THE AMERICAN MISSIONARY ASSOCIATION." in visible
    assert "Transcriber’s Notes" in visible
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
            "build.tei.american_missionary_volume_37_1883_to_tei",
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
    assert hashlib.sha256(outputs[0][0]).hexdigest() == "87509ed34e067a206afcafc60028be97c1879f668a44eec7f543bba121172598"
