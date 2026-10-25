from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.drummond_greatest_thing_37c135_oracle import (
    _oracle,
    _oracle_marker_census,
    _oracle_source_rows,
)
from build.tei.drummond_greatest_thing_37c135_reconstruction import (
    _source_marker_spans,
    _source_rows,
)
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "raw/gutenberg/pg16739.txt"
MANIFEST = (
    ROOT
    / "sources/structured-text/lib071-gutenberg-evangelical/work-bindings/"
    "drummond-greatest-thing/37c-135-source-underscore-emphasis-v2.source-manifest.json"
)
TEI = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _generate_in_clean_process(destination: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "build.tools.reconstruct_candidate",
            "--manifest",
            MANIFEST.relative_to(ROOT).as_posix(),
            "--destination",
            str(destination),
            "--repository-root",
            str(ROOT),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError("candidate generator did not return a JSON object")
    return value


def _reseal(package: Path) -> None:
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for member in manifest["members"]:
        content = (package / member["name"]).read_bytes()
        member["bytes"] = len(content)
        member["sha256"] = _sha(content)
    manifest_path.write_bytes(_canonical(manifest))


def _mutate_tei(package: Path, mutation: str) -> None:
    path = package / "content.tei.xml"
    root = etree.fromstring(path.read_bytes())
    if mutation == "remove-delimiter":
        marker = root.xpath(
            ".//tei:c[@type='emphasis-delimiter']",
            namespaces=NS,
        )[0]
        marker.getparent().remove(marker)
    elif mutation == "change-rend":
        root.xpath(
            ".//tei:hi[@ana='#source-underscore']",
            namespaces=NS,
        )[0].set("rend", "bold")
    elif mutation == "detach-continuation":
        root.xpath(
            ".//tei:hi[@corresp]",
            namespaces=NS,
        )[0].set("corresp", "#wrong-span")
    else:
        raise ValueError(f"unknown test mutation: {mutation}")
    path.write_bytes(
        etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=False,
        )
    )
    _reseal(package)


def test_source_underscore_census_is_complete_and_independent() -> None:
    content = SOURCE.read_bytes()
    assert _sha(content) == "12f442db074bfd81db981dfb7c423120e830feb2019b2c0db253692e23624048"

    producer_rows = _source_rows(content)
    producer_spans, producer_events = _source_marker_spans(content, producer_rows)
    oracle_rows = _oracle_source_rows(content)
    oracle_spans, oracle_events = _oracle_marker_census(content, oracle_rows)

    assert len(producer_rows) == len(oracle_rows) == 3922
    assert producer_spans == oracle_spans
    assert sum(map(len, producer_events.values())) == 362
    assert sum(map(len, oracle_events.values())) == 362
    assert len(producer_spans) == 181
    assert sum(span["start_line"] != span["end_line"] for span in producer_spans) == 17
    assert all(
        span["content"] != "" and "_" not in span["content"]
        for span in producer_spans
    )
    assert not any(
        any(
            producer_rows[index - 1]["text"] == ""
            for index in range(span["start_line"] + 1, span["end_line"])
        )
        for span in producer_spans
    )
    long_span = next(span for span in producer_spans if len(span["content"]) == 71)
    assert (long_span["start_line"], long_span["end_line"]) == (3306, 3307)
    assert [
        (span["span_id"], span["start_line"])
        for span in producer_spans
        if "summum bonum" in span["content"]
    ] == [
        ("drummond-underscore-00001", 122),
        ("drummond-underscore-00002", 151),
        ("drummond-underscore-00005", 188),
        ("drummond-underscore-00018", 286),
    ]


def test_unmatched_empty_nested_and_blank_line_markers_fail_closed() -> None:
    for malformed in (
        b"unclosed_\r\n",
        b"__\r\n",
        b"_outer_inner_\r\n",
        b"_first\r\n\r\nlast_\r\n",
    ):
        with pytest.raises(ValueError, match="underscore|emphasis"):
            _source_marker_spans(malformed, _source_rows(malformed))


def test_local_manifest_binds_the_ticket_adapter_and_checker() -> None:
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    assert manifest.record["ticket_id"] == "37c-135"
    assert manifest.record["work_id"] == "drummond-greatest-thing"
    assert manifest.record["converter"]["implementation_path"] == (
        "build/tei/drummond_greatest_thing_37c135_reconstruction.py"
    )
    assert manifest.record["validator"]["implementation_path"] == (
        "build/tei/drummond_greatest_thing_37c135_oracle.py"
    )
    authorities = {
        item["name"]: item for item in manifest.record["authorities"]
    }
    assert authorities["base-converter-implementation"]["sha256"] == (
        "2940b4339b118a7f77fc546c3e9fe884a5f0d9754d0525356de0ed1a2b2b899a"
    )
    assert authorities["base-oracle-implementation"]["sha256"] == (
        "b42e48bef11f21cabafacb153fd3adb187874bd82130b57b2e1a855283bbad2e"
    )


def test_candidate_is_deterministic_and_marker_mutations_are_rejected(
    tmp_path: Path,
) -> None:
    first_destination = tmp_path / "a"
    second_destination = tmp_path / "b"
    first_receipt = _generate_in_clean_process(first_destination)
    second_receipt = _generate_in_clean_process(second_destination)
    assert first_receipt["status"] == second_receipt["status"] == "pass"
    assert first_receipt["acceptance_status"] == "nonaccepted"
    assert first_receipt["candidate"]["sha256"] == second_receipt["candidate"]["sha256"]

    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    baseline = CandidatePackage.load(first_destination / "package")
    report = validate(manifest, baseline, _oracle)
    assert report.status == "pass"
    assert baseline.manifest["status"] == "nonaccepted"

    tei_root = etree.fromstring(baseline.member_bytes("content.tei.xml"))
    assert len(
        tei_root.xpath(
            ".//tei:c[@type='emphasis-delimiter']",
            namespaces=NS,
        )
    ) == 362
    assert len(
        tei_root.xpath(
            ".//tei:hi[@ana='#source-underscore' and @xml:id]",
            namespaces=NS,
        )
    ) == 181
    assert len(
        tei_root.xpath(
            ".//tei:hi[@ana='#source-underscore' and @corresp]",
            namespaces=NS,
        )
    ) == 17
    assert tei_root.xpath(
        ".//tei:seg[@type='source-line' and @n='122']//tei:hi[@xml:id='drummond-underscore-00001']",
        namespaces=NS,
    )

    for mutation in ("remove-delimiter", "change-rend", "detach-continuation"):
        mutated_dir = tmp_path / f"mut-{mutation}"
        shutil.copytree(first_destination / "package", mutated_dir)
        _mutate_tei(mutated_dir, mutation)
        with pytest.raises(ValueError, match="underscore|carrier|continuation"):
            validate(manifest, CandidatePackage.load(mutated_dir), _oracle)

    mutated_account_dir = tmp_path / "mut-accountability"
    shutil.copytree(first_destination / "package", mutated_account_dir)
    account_path = mutated_account_dir / "source-accountability.json"
    account = json.loads(account_path.read_text(encoding="utf-8"))
    account["works"][0]["source_underscore_markup"]["spans"][0][
        "start_column"
    ] += 1
    account_path.write_bytes(_canonical(account))
    _reseal(mutated_account_dir)
    with pytest.raises(ValueError, match="accountability locator"):
        validate(
            manifest,
            CandidatePackage.load(mutated_account_dir),
            _oracle,
        )
