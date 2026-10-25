"""Actual accepted-master projection and independent correspondence for LIB062."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json

import pytest

from build.tools.project_1695_baptist_catechism import ACCEPTANCE, PUBLICATION, ROOT, prepare, run, verify_correspondence
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.catechisms import _validate_rows, project_accepted_catechisms, verify_accepted_catechisms
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.selection import load_release_selection


def test_accepted_master_projection_and_mutation_rejection() -> None:
    prepared = prepare()
    rows = prepared["rows"]
    context = prepared["context"]
    master_bytes = prepared["master_bytes"]
    source_rows = context["document"]["Data"]
    assert len(rows) == len(source_rows) == 114
    assert [row["item_id"] for row in rows] == [str(source["Number"]) for source in source_rows]
    assert rows[0]["question"] == source_rows[0]["Question"]
    assert rows[42]["answer_with_proofs"] == source_rows[42]["AnswerWithProofs"]
    assert rows[-1]["proofs"][-1]["references"][-1]["raw"] == source_rows[-1]["Proofs"][-1]["References"][-1]
    for index in (43, 59, 60):
        assert source_rows[index - 1]["Answer"] == ""
        assert rows[index - 1]["answer"] == ""
        assert rows[index - 1]["answer_with_proofs"] == source_rows[index - 1]["AnswerWithProofs"]
        assert rows[index - 1]["text"] == f"Q: {source_rows[index - 1]['Question']} A: {source_rows[index - 1]['AnswerWithProofs']}"
    assert verify_correspondence(context, rows, master_bytes) == []

    damaged_rows = deepcopy(rows)
    damaged_rows[42]["answer"] = source_rows[42]["AnswerWithProofs"]
    assert verify_correspondence(context, damaged_rows, master_bytes)

    damaged_master = master_bytes.replace(
        source_rows[0]["Question"].encode("utf-8"), b"Changed first question?", 1
    )
    assert damaged_master != master_bytes
    assert verify_correspondence(context, rows, damaged_master)

    result = run()
    publication = ROOT / PUBLICATION
    rows_bytes = (publication / "catechisms.jsonl").read_bytes()
    saved_rows = [json.loads(line) for line in rows_bytes.splitlines()]
    assert saved_rows == rows
    assert sha256(rows_bytes).hexdigest() == result["receipt"]["rows_sha256"]
    assert result["check"]["status"] == "pass"
    assert result["receipt"]["rights"] == "uncleared"
    assert result["receipt"]["publication"] == "unauthorized"
    assert b"NonlinearFruit/Creeds.json" in (publication / "SOURCE_CREDIT.md").read_bytes()


def test_empty_plain_answer_requires_nonempty_proof_answer() -> None:
    rows = prepare()["rows"]
    _validate_rows(rows)
    for proof_answer in ("", None):
        damaged = deepcopy(rows[42])
        damaged["answer_with_proofs"] = proof_answer
        with pytest.raises(PipelineError, match="invalid catechism public row"):
            _validate_rows([damaged])
    missing = deepcopy(rows[42])
    del missing["answer_with_proofs"]
    with pytest.raises(PipelineError, match="invalid catechism public row"):
        _validate_rows([missing])
    standard = deepcopy(rows[41])
    standard["answer_with_proofs"] = None
    _validate_rows([standard])
    with_subquestion = deepcopy(standard)
    with_subquestion["sub_questions"] = [
        {"item_id": "42a", "question": "A source-backed subquestion?", "answer": "A plain answer.", "proofs": []}
    ]
    _validate_rows([with_subquestion])
    with_subquestion["sub_questions"][0]["answer"] = ""
    with pytest.raises(PipelineError, match="invalid catechism public row"):
        _validate_rows([with_subquestion])


def test_exact_release_route_and_bound_public_notice() -> None:
    acceptance_path = ROOT / ACCEPTANCE
    projection = project_accepted_catechisms(ROOT, acceptance_path=acceptance_path)
    rows, receipt = projection["rows"], projection["receipt"]
    assert len(rows) == receipt["row_count"] == 114
    assert receipt["rights"] == "uncleared"
    assert receipt["publication"] == "unauthorized"
    assert verify_accepted_catechisms(ROOT, acceptance_path=acceptance_path, rows=rows, receipt=receipt) == []

    damaged_rows = deepcopy(rows)
    damaged_rows[42]["answer"] = rows[42]["answer_with_proofs"]
    assert verify_accepted_catechisms(
        ROOT, acceptance_path=acceptance_path, rows=damaged_rows, receipt=receipt
    )
    damaged_receipt = deepcopy(receipt)
    damaged_receipt["actual_master_sha256"] = "0" * 64
    assert verify_accepted_catechisms(
        ROOT, acceptance_path=acceptance_path, rows=rows, receipt=damaged_receipt
    ) == ["1695 Baptist Catechism release receipt differs"]

    selection = load_release_selection(ROOT / PUBLICATION / "offline-release-selection.json")
    item = selection["items"][0]
    assert len(selection["items"]) == 1
    with pytest.raises(PipelineError, match="source notice SHA-256 mismatch"):
        notice_texts_for_item(ROOT, item, acceptance_path)

    from ocd_kernel.library.record_read import RecordRead
    from ocd_kernel.library.rights import collect_rights
    identity = json.loads(acceptance_path.read_bytes())["identity"]
    rights = collect_rights(RecordRead(ROOT), identity['work_id'], identity['textual_form_id'], identity['edition_id'])
    assert rights['health'] == 'valid'
    normalized = next(record['normalization'] for record in rights['records']
                      if record['normalization'] is not None and record['record']['scope'] == 'selected-text')
    item = {'item_id': normalized['item_id'], 'work_id': identity['work_id'],
            'acceptance_path': normalized['acceptance_path'], 'license': normalized['effective_license'],
            'public_notices': normalized['public_notices']}
    notice = notice_texts_for_item(ROOT, item, acceptance_path)
    assert len(notice) == 1
    assert "NonlinearFruit/Creeds.json" in notice[0]
    assert "rights clearance" in notice[0]


def _historical_notice(raw: bytes, expected_sha256: str) -> bytes:
    lf = raw.replace(b"\r\n", b"\n")
    marker = b"\n## Current rights disposition (2026-10-09)\n"
    candidates = [lf]
    if lf.count(marker) == 1:
        candidates.append(lf.split(marker, 1)[0])
    for candidate in candidates:
        if sha256(candidate).hexdigest() == expected_sha256:
            return candidate
    raise AssertionError("Historical notice complete original SHA differs")


def test_original_release_notices_replay_exact_historical_prefix_privately(tmp_path):
    acceptance_path = ROOT / ACCEPTANCE
    selection = load_release_selection(ROOT / PUBLICATION / "offline-release-selection.json")
    item = selection["items"][0]
    assert len(selection["items"]) == 1
    notice_root = tmp_path / "historical-notices"
    mirrored_acceptance = notice_root / ACCEPTANCE
    mirrored_acceptance.parent.mkdir(parents=True)
    mirrored_acceptance.write_bytes(acceptance_path.read_bytes())
    assert mirrored_acceptance.read_bytes() == acceptance_path.read_bytes()
    current_notices = {}
    for binding in item["public_notices"]:
        for role in ("source", "notice"):
            relative = binding[role + "_path"]
            current = (ROOT / relative).read_bytes()
            current_notices[relative] = current
            historical = _historical_notice(current, binding[role + "_sha256"])
            with pytest.raises(AssertionError, match="Historical notice"):
                _historical_notice(b"!" + current[1:], binding[role + "_sha256"])
            destination = notice_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(historical)
    notice = notice_texts_for_item(notice_root, item, mirrored_acceptance)
    assert len(notice) == 1
    assert "NonlinearFruit/Creeds.json" in notice[0]
    assert "rights clearance" in notice[0]
    assert all((ROOT / relative).read_bytes() == raw for relative, raw in current_notices.items())
