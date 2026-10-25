from __future__ import annotations

from pathlib import Path

from build.parsers.westminster_witnesses import parse_wsc_witness_document


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "raw/westminster-standard-org/westminster-shorter-catechism.html"


def test_one_pass_wsc_document_contains_readings_and_all_proof_witnesses() -> None:
    document = parse_wsc_witness_document(HTML)

    assert len(document.rows) == 107
    assert document.parse_errors == {}
    assert document.questions_without_proofs == ()
    assert sum(len(row.proofs) for row in document.rows) == 401
    assert document.rows[36].question
    assert document.rows[36].answer
    assert document.rows[36].proofs[-1] == {
        "raw": "Job 19:26-27",
        "osis": ["Job.19.26-Job.19.27"],
    }
