"""Forward-only collection tests for the George Whitefield sermon parser."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from build.parsers import ccel_whitefield_sermon as parser


@pytest.mark.raw_required(parser.CCEL_RAW_FILE)
@pytest.mark.raw_required(parser.PG_RAW_FILE)
def test_parser_writes_complete_mixed_source_collection(tmp_path: Path) -> None:
    output_path = tmp_path / "george-whitefield-sermons.json"
    logger = logging.getLogger("test-whitefield-parser")

    parser.write_collection(
        ccel_path=parser.CCEL_RAW_FILE,
        pg_path=parser.PG_RAW_FILE,
        config_path=parser.CONFIG_PATH,
        output_path=output_path,
        processing_date="2026-08-15",
        logger=logger,
    )

    collection = json.loads(output_path.read_text(encoding="utf-8"))
    assert [entry["sermon_id"] for entry in collection["data"]] == [
        str(number) for number in range(1, 62)
    ]
    assert collection["meta"]["provenance"]["source_hash"] == (
        "sha256:755b268a63b566d78db29c5fc0fc771c417640db5b849f4fb48b21c94ca936ee"
    )
    assert collection["meta"]["provenance"]["source_url"] == (
        "https://www.ccel.org/ccel/whitefield/sermons.xml"
    )
    assert collection["meta"]["provenance"]["download_date"] == "2026-04-17"
    assert collection["meta"]["provenance"]["processing_date"] == "2026-08-15"

    supplemental = collection["data"][-2:]
    assert [entry["title"] for entry in supplemental] == [
        "Peter's Denial of his Lord",
        "The True Way of Beholding the Lamb of God",
    ]
    assert [entry["word_count"] for entry in supplemental] == [6462, 7172]
    assert [entry["primary_reference"]["raw"] for entry in supplemental] == [
        "Matthew 26:75",
        "John 1:35-36",
    ]
    assert all(
        entry["provenance"]["source_url"]
        == "https://www.gutenberg.org/ebooks/77041"
        for entry in supplemental
    )
    assert all(
        "b952725e8731399d4fd7fbe319aa9f57660d887f7cc6dd3937da91754e4ce08e"
        in entry["provenance"]["notes"]
        for entry in supplemental
    )

    schema = json.loads(
        (
            parser.REPO_ROOT
            / "ocd_kernel"
            / "schemas"
            / "v1"
            / "sermon.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(collection)


@pytest.mark.raw_required(parser.CCEL_RAW_FILE)
@pytest.mark.raw_required(parser.PG_RAW_FILE)
def test_parser_rejects_unpinned_source_bytes(tmp_path: Path) -> None:
    changed_pg = tmp_path / "pg77041.txt"
    changed_pg.write_bytes(parser.PG_RAW_FILE.read_bytes() + b"\nsource drift\n")

    with pytest.raises(ValueError, match="Project Gutenberg source hash mismatch"):
        parser.write_collection(
            ccel_path=parser.CCEL_RAW_FILE,
            pg_path=changed_pg,
            config_path=parser.CONFIG_PATH,
            output_path=tmp_path / "output.json",
            processing_date="2026-08-15",
            logger=logging.getLogger("test-whitefield-parser-drift"),
        )
