from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from lxml import etree
import pytest

from build.tei.ports_of_entry_missionary_herald_to_tei import (
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
    "ports-of-entry-missionary-herald/pg55955-images.html"
)
NS = {
    "tei": "http://www.tei-c.org/ns/1.0",
    "xml": "http://www.w3.org/XML/1998/namespace",
}


def _source() -> Path:
    path = resolve_repo_path(ROOT, RAW_RELATIVE.as_posix())
    if not path.exists():
        pytest.skip(f"retained Wave 2 source is not mounted: {path}")
    return path


def test_released_source_reconstructs_as_complete_nonaccepted_tei(tmp_path: Path) -> None:
    source = _source()
    output = tmp_path / "ports-of-entry-missionary-herald.tei.xml"
    result = convert(source, output, tmp_path / "reports")

    assert result.section_count == 5
    assert result.table_count == 7
    assert result.page_count == 30
    assert result.figure_count == 12
    assert result.carrier_count > 350
    assert validate_file(output) == []

    tree = etree.parse(str(output))
    assert tree.xpath("count(/tei:TEI/tei:text/tei:body/tei:div[@type='section'])", namespaces=NS) == 5
    assert tree.xpath("//tei:pb/@n", namespaces=NS) == [str(value) for value in range(1, 31)]
    assert tree.xpath("count(//tei:div[@type='contents']/tei:list/tei:item)", namespaces=NS) == 4
    assert tree.xpath("count(//tei:div[@type='transcribers-note'])", namespaces=NS) == 1
    text = " ".join("".join(tree.getroot().itertext()).split())
    assert "The Joint Committee of Six" in text
    assert "THE HOME MISSIONS COUNCIL" in text
    assert "Departed 1914–1915" in text
    assert "Obvious punctuation and spelling errors have been repaired." in text
    assert "*** END OF THE PROJECT GUTENBERG EBOOK PORTS OF ENTRY: MISSIONARY HERALD ***" in text


def test_accounting_rejects_a_mutated_source_carrier() -> None:
    parsed = parse_source(_source())
    tree, _stats = build_tree(parsed)
    carrier = tree.xpath(
        "//*[@xml:id and starts-with(@xml:id, 'poe-src-B')][50]",
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
                "build.tei.ports_of_entry_missionary_herald_to_tei",
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
