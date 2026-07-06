from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

import jsonschema
import pytest
from lxml import etree

from build.lib.decision_store import DecisionStore
from build.lib.event_completeness import EventIncompleteError
from build.tei.check_je_ledger import check_receipt
from build.tei.drift_check import page_drift
from build.tei.materialize_je import (
    _read_json,
    _read_jsonl,
    materialize_page_document,
    resolve_edition_page_key,
)
from build.tei.project_je_hf import project_file
from build.tei.validate import validate_file as validate_xsd_file
from build.tei.validate_schematron import validate_file as validate_schematron_file
from build.tei.writer import TEI_NS, serialize

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "je_spine"
WCT_PATH = FIXTURE_DIR / "wct_page.json"
EVENTS_PATH = FIXTURE_DIR / "events.jsonl"
IA_MANIFEST_PATH = FIXTURE_DIR / "ia_manifest.json"
EXPECTED_TEI_PATH = FIXTURE_DIR / "expected.tei.xml"
WITNESSLESS_FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "witnessless_lemma_fixture.tei.xml"
LOSS_RECEIPT_SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "loss_receipt.schema.json"
RNG_PATH = REPO_ROOT / "build" / "tei" / "vendor" / "relaxng" / "tei_all.rng"
WORK_ID = "jewish-encyclopedia.vol_02"
VOLUME_ID = "vol_02"
NS = {"tei": TEI_NS}


@lru_cache(maxsize=1)
def _relaxng() -> etree.RelaxNG:
    return etree.RelaxNG(etree.parse(str(RNG_PATH)))


def _fixture_inputs() -> tuple[dict, list[dict], dict]:
    wct_page = _read_json(WCT_PATH)
    events = _read_jsonl(EVENTS_PATH)
    edition_page_key = resolve_edition_page_key(wct_page, _read_json(IA_MANIFEST_PATH))
    return wct_page, events, edition_page_key


def _materialize_to_path(path: Path) -> tuple[dict, list[dict], dict]:
    wct_page, events, edition_page_key = _fixture_inputs()
    tree = materialize_page_document(
        wct_page,
        events,
        work_id=WORK_ID,
        volume_id=VOLUME_ID,
        edition_page_key=edition_page_key,
    )
    serialize(tree, path)
    return wct_page, events, edition_page_key


def _load_record(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8").splitlines()[0])


def _write_record(path: Path, record: dict) -> None:
    path.write_text(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def test_materialized_fixture_validates_and_contains_attested_and_witnessless_lemmas(tmp_path: Path) -> None:
    materialized_path = tmp_path / "page_0010.tei.xml"
    _materialize_to_path(materialized_path)

    document = etree.parse(str(materialized_path))
    assert validate_schematron_file(materialized_path) == []

    lems = document.xpath("//tei:lem", namespaces=NS)
    assert any(lem.get("wit") for lem in lems)
    assert any(lem.get("resp") and lem.get("wit") is None for lem in lems)


@pytest.mark.slow
def test_materialized_fixture_validates_against_full_tei_schemas(tmp_path: Path) -> None:
    materialized_path = tmp_path / "page_0010.tei.xml"
    _materialize_to_path(materialized_path)

    assert validate_xsd_file(materialized_path) == []
    document = etree.parse(str(materialized_path))
    assert _relaxng().validate(document), "\n".join(str(error) for error in _relaxng().error_log)


def test_committed_expected_tei_is_canonical_and_drift_is_detected(tmp_path: Path) -> None:
    wct_page, events, edition_page_key = _fixture_inputs()

    assert page_drift(
        EXPECTED_TEI_PATH,
        wct_page,
        events,
        work_id=WORK_ID,
        volume_id=VOLUME_ID,
        edition_page_key=edition_page_key,
    ) == []

    edited_path = tmp_path / "expected-edited.tei.xml"
    edited_path.write_bytes(EXPECTED_TEI_PATH.read_bytes())
    tree = etree.parse(str(edited_path))
    lem = tree.xpath("//tei:lem[string-length(normalize-space(.)) > 0]", namespaces=NS)[0]
    lem.text = "hand-edit"
    tree.write(str(edited_path), encoding="UTF-8", xml_declaration=True, pretty_print=True)

    differences = page_drift(
        edited_path,
        wct_page,
        events,
        work_id=WORK_ID,
        volume_id=VOLUME_ID,
        edition_page_key=edition_page_key,
    )

    assert differences


def test_projection_receipt_validates_and_rejects_wrong_span_identity(tmp_path: Path) -> None:
    materialized_path = tmp_path / "ir" / "page_0010.tei.xml"
    _materialize_to_path(materialized_path)
    output_path = tmp_path / "hf" / "page_0010.jsonl"
    receipt_path = tmp_path / "hf" / "page_0010.loss.json"

    receipt = project_file(materialized_path, output_path, receipt_path=receipt_path, repo_root=tmp_path)
    schema = json.loads(LOSS_RECEIPT_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(receipt, schema)
    assert check_receipt(receipt_path, repo_root=tmp_path) == []

    totals_before = copy.deepcopy(receipt["totals"])
    projected = next(
        node
        for node in receipt["nodes"]
        if node["element"] == "lem" and node["target"]["char_end"] > node["target"]["char_start"]
    )
    target = projected["target"]
    record = _load_record(output_path)
    start = target["char_start"]
    end = target["char_end"]
    replacement = "Z" * (end - start)
    record["text"] = record["text"][:start] + replacement + record["text"][end:]
    _write_record(output_path, record)

    errors = check_receipt(receipt_path, repo_root=tmp_path)

    assert receipt["totals"] == totals_before
    assert any("span mismatch" in error for error in errors)


def test_ratification_completeness_gate_blocks_incomplete_fixture_event(tmp_path: Path) -> None:
    event = copy.deepcopy(_read_jsonl(EVENTS_PATH)[0])
    del event["evidence_seen"]["wct_page_sha256"]

    blocked_store = DecisionStore(
        base_dir=tmp_path / "blocked",
        volume=2,
        corpus_slug="jewish-encyclopedia",
        volume_id="vol_02",
    )
    with pytest.raises(EventIncompleteError):
        blocked_store.append_many([copy.deepcopy(event)], preserve_event_id=True, enforce_ratification_context=True)
    assert not blocked_store.store_path.exists()

    permissive_store = DecisionStore(
        base_dir=tmp_path / "permissive",
        volume=2,
        corpus_slug="jewish-encyclopedia",
        volume_id="vol_02",
    )
    permissive_store.append_many([copy.deepcopy(event)], preserve_event_id=True, enforce_ratification_context=False)

    assert permissive_store.store_path.exists()
    assert len(permissive_store.fold()) == 1


def test_batch05_witnessless_fixture_passes_critical_schematron() -> None:
    assert validate_schematron_file(WITNESSLESS_FIXTURE_PATH) == []
