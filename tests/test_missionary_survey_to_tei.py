from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from lxml import etree
import pytest

from build.tei.missionary_survey_to_tei import accounting_errors, build_tree, convert, parse_source
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[1]
RAW_RELATIVE = Path(
    "raw/clean-ready-acquisition-to-tei/master-5/35/missionary-survey/pg13360.txt"
)
NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def _source() -> Path:
    path = resolve_repo_path(ROOT, RAW_RELATIVE.as_posix())
    if not path.exists():
        pytest.skip(f"retained released-pilot source is not mounted: {path}")
    return path


def test_released_source_reconstructs_as_complete_nonaccepted_tei(tmp_path: Path) -> None:
    source = _source()
    output = tmp_path / "missionary-survey.tei.xml"
    result = convert(source, output, tmp_path / "reports")

    assert result.chapter_count == 11
    assert result.table_count > 40
    assert result.source_line_carrier_count > 3_500
    assert validate_file(output) == []

    tree = etree.parse(str(output))
    assert tree.xpath("count(/tei:TEI/tei:text/tei:body/tei:div[@type='chapter'])", namespaces=NS) == 11
    assert tree.xpath("count(//tei:ab[@type='table-transcription'])", namespaces=NS) == result.table_count
    assert tree.xpath("count(//tei:ref[@type='note'])", namespaces=NS) >= tree.xpath(
        "count(//tei:note[@place='end'])", namespaces=NS
    )
    targets = {target.removeprefix("#") for target in tree.xpath("//tei:ref[@type='note']/@target", namespaces=NS)}
    note_ids = set(tree.xpath("//tei:note[@place='end']/@xml:id", namespaces={**NS, "xml": "http://www.w3.org/XML/1998/namespace"}))
    assert targets == note_ids
    text = " ".join("".join(tree.getroot().itertext()).split())
    assert "tables have been transposed, i.e. rows are columns and vice versa." in text
    assert "THOS. COCHRANE." in text
    assert "that is the crying need." in text


def test_accounting_rejects_a_mutated_source_line() -> None:
    parsed = parse_source(_source())
    tree, _stats = build_tree(parsed)
    carrier = tree.xpath("//tei:seg[@type='source-line'][text()]", namespaces=NS)[100]
    carrier.text = (carrier.text or "") + " invented"

    errors = accounting_errors(parsed, tree)

    assert errors
    assert "first source-line mismatch" in errors[0]


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
                "build.tei.missionary_survey_to_tei",
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
