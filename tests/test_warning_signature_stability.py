from __future__ import annotations

from build.lib.warning_producers import discover_producers, run_all_producers
from ocd_kernel.lib.text_extractor import effective_resource_type
from pathlib import Path


SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas" / "v1"


def _record(text: str):
    return {
        "meta": {"schema_type": "commentary", "id": "sample"},
        "data": [{"entry_id": "e1", "commentary_text": text, "cross_references": []}],
    }


def _signatures(record):
    resource_type = effective_resource_type(record, SCHEMAS_DIR)
    meta = {"resource_id": record["meta"]["id"], "resource_type": resource_type, "record_path": "test"}
    return {
        producer_id: [(warning["code"], warning["signature"]) for warning in warnings]
        for producer_id, warnings in run_all_producers(record, meta, producers=discover_producers()).items()
    }


def test_producer_signatures_are_deterministic() -> None:
    record = _record('shew word- word " |||')

    assert _signatures(record) == _signatures(record)


def test_different_inputs_change_signature_for_same_code() -> None:
    first = _signatures(_record("word- first"))["text_suspicion"]
    second = _signatures(_record("word- second"))["text_suspicion"]

    first_sig = next(signature for code, signature in first if code == "possible_broken_hyphenation")
    second_sig = next(signature for code, signature in second if code == "possible_broken_hyphenation")
    assert first_sig != second_sig
