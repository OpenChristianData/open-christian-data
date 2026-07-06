from __future__ import annotations

from types import SimpleNamespace

from build.lib.warning_producers import run_all_producers


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"warnings": {"type": "array"}},
    "required": ["warnings"],
    "additionalProperties": False,
}


def _base(producer_id: str, consumes=None, run=None):
    return SimpleNamespace(
        PRODUCER_ID=producer_id,
        SIGNATURE_VERSION=1,
        WARNING_CODES={
            "fake_code": {
                "severity": "info",
                "description": "Fake.",
                "signature_fields": ["code"],
            }
        },
        APPLIES_TO_RESOURCE_TYPES=None,
        REQUIRES_CAPABILITIES={},
        CONSUMES=list(consumes or []),
        PRODUCES_SCHEMA=OUTPUT_SCHEMA,
        SCOPE="record_local",
        run=run or (lambda record, meta, upstream_outputs: {"warnings": []}),
    )


def test_invalid_upstream_output_marks_crash_for_consumer() -> None:
    """A-F1: the contract upgraded from silent None to a crash marker so
    downstream consumers can detect upstream failures rather than treating
    them as empty success."""
    seen = {}

    broken = _base("broken", run=lambda record, meta, upstream_outputs: {"wrong_key": 1})

    def consumer_run(record, meta, upstream_outputs):
        seen.update(upstream_outputs)
        return {"warnings": []}

    consumer = _base("consumer", consumes=["broken"], run=consumer_run)

    result = run_all_producers(
        {"meta": {"schema_type": "commentary", "id": "sample"}, "data": []},
        {"resource_type": "commentary"},
        producers=[broken, consumer],
    )

    assert seen["broken"] is not None
    assert seen["broken"].get("crashed") is True
    assert seen["broken"].get("crash_class") == "producer_output_schema_failed"
    assert result["broken"] == []
    assert result["consumer"] == []
