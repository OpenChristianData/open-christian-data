from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from lxml import etree
import pytest

from build.tei.singmaster_story_of_lutheran_missions_to_tei import (
    END_MARKER,
    EXPECTED_ARCHIVE_SHA256,
    EXPECTED_HTML_SHA256,
    EXPECTED_TEXT_SHA256,
    accounting_errors,
    build_tree,
    convert,
    parse_source,
)
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[1]
RAW_RELATIVE = Path(
    "raw/clean-ready-acquisition-to-tei/master-5/35/"
    "singmaster-story-of-lutheran-missions/pg55819-images.html"
)
NS = {
    "tei": "http://www.tei-c.org/ns/1.0",
    "xml": "http://www.w3.org/XML/1998/namespace",
}


def _source() -> Path:
    path = resolve_repo_path(ROOT, RAW_RELATIVE.as_posix())
    if not path.exists():
        pytest.skip(f"retained Wave 3 source is not mounted: {path}")
    return path


def test_released_source_reconstructs_as_complete_nonaccepted_tei(tmp_path: Path) -> None:
    source = _source()
    output = tmp_path / "singmaster-story-of-lutheran-missions.tei.xml"
    reports = tmp_path / "reports"
    result = convert(source, output, reports)

    assert result.carrier_count == 1010
    assert result.chapter_count == 6
    assert result.figure_count == 36
    assert result.page_count == 21
    assert result.table_count == 2
    assert result.note_count == 11
    assert validate_file(output) == []

    tree = etree.parse(str(output))
    assert tree.xpath(
        "count(/tei:TEI/tei:text/tei:front/tei:div)", namespaces=NS
    ) == 5
    assert tree.xpath(
        "count(/tei:TEI/tei:text/tei:body/tei:div[@type='chapter'])", namespaces=NS
    ) == 6
    assert tree.xpath("//tei:pb/@n", namespaces=NS) == [str(value) for value in range(1, 22)]
    assert tree.xpath("count(//tei:seg[@type='side-heading'])", namespaces=NS) == 251
    assert tree.xpath("count(//tei:note[@place='foot'])", namespaces=NS) == 11
    assert tree.xpath("count(//tei:ref[@type='note'])", namespaces=NS) == 11
    assert tree.xpath("count(//tei:table/tei:row)", namespaces=NS) == 24
    assert tree.xpath("count(//tei:table/tei:row/tei:cell)", namespaces=NS) == 41
    assert tree.xpath("count(//tei:figure/tei:figDesc)", namespaces=NS) == 35
    assert tree.xpath(
        "count(//tei:p[contains(concat(' ', normalize-space(@rend), ' '), ' authorial-scope ')])",
        namespaces=NS,
    ) == 1

    available_ids = set(tree.xpath("//@xml:id", namespaces=NS))
    for target in tree.xpath("//tei:ref[starts-with(@target, '#')]/@target", namespaces=NS):
        assert target.removeprefix("#") in available_ids

    text = " ".join("".join(tree.getroot().itertext()).split())
    assert "The Story of Lutheran Missions" in text
    assert "ELSIE SINGMASTER" in text
    assert "Co-operative Literature Committee Woman’s Missionary Societies" in text
    assert "SURVEY PUBLISHING CO., COLUMBIA, S. C." in text
    assert "This account of Lutheran missions cannot be exhaustive." in text
    assert "Typographical errors were silently corrected." in text
    assert END_MARKER in text

    accounting = json.loads((reports / "accounting.json").read_text(encoding="utf-8"))
    assert accounting["source_sha256"] == EXPECTED_HTML_SHA256
    assert accounting["source_carrier_count"] == accounting["candidate_carrier_count"] == 1010
    assert accounting["source_carrier_stream_sha256"] == (
        accounting["candidate_carrier_stream_sha256"]
    ) == "b00f8551c9c4a86a6e127162b627a3d0f65ed0dce52a24271148a28978111a92"
    assert accounting["omitted_source_carrier_ids"] == []
    assert accounting["duplicated_source_carrier_ids"] == []
    assert accounting["dangling_internal_references"] == []
    assert accounting["footnote_reference_count"] == 11
    assert accounting["transcriber_statement_count"] == 3

    receipt = json.loads((reports / "receipt.json").read_text(encoding="utf-8"))
    member_hashes = {item["name"]: item["sha256"] for item in receipt["source_members"]}
    assert member_hashes["pg55819-images.html"] == EXPECTED_HTML_SHA256
    assert member_hashes["pg55819.txt"] == EXPECTED_TEXT_SHA256
    assert member_hashes["pg55819-h.zip"] == EXPECTED_ARCHIVE_SHA256
    assert len(receipt["archive_members"]) == 37
    assert receipt["scope_statement"]["classification"] == (
        "authorial historical scope, not textual incompleteness"
    )


def test_accounting_rejects_a_mutated_source_carrier() -> None:
    parsed = parse_source(_source())
    tree, _stats = build_tree(parsed)
    carrier = tree.xpath(
        "(//*[@xml:id and starts-with(@xml:id, 'slm-src-B')])[400]",
        namespaces=NS,
    )[0]
    carrier.text = (carrier.text or "") + " invented"

    errors = accounting_errors(parsed, tree)

    assert errors
    assert "first source carrier mismatch" in errors[0]


def test_fresh_process_different_cwd_is_byte_deterministic(tmp_path: Path) -> None:
    source = _source()
    outputs: list[Path] = []
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    for ordinal in (1, 2):
        cwd = tmp_path / f"cwd-{ordinal}"
        cwd.mkdir()
        output = tmp_path / f"candidate-{ordinal}.tei.xml"
        reports = tmp_path / f"reports-{ordinal}"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build.tei.singmaster_story_of_lutheran_missions_to_tei",
                "--source",
                str(source),
                "--output",
                str(output),
                "--report-dir",
                str(reports),
            ],
            cwd=cwd,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        outputs.append(output)

    assert outputs[0].read_bytes() == outputs[1].read_bytes()
    assert (tmp_path / "reports-1/accounting.json").read_bytes() == (
        tmp_path / "reports-2/accounting.json"
    ).read_bytes()
    assert (tmp_path / "reports-1/receipt.json").read_bytes() == (
        tmp_path / "reports-2/receipt.json"
    ).read_bytes()
