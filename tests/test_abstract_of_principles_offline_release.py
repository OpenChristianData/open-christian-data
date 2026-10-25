from __future__ import annotations

from hashlib import sha256
import json

import pytest
from pathlib import Path

from build.tools.project_abstract_of_principles import (
    ACCEPTANCE,
    EXPECTED_ACCEPTANCE_SHA256,
    EXPECTED_MASTER_SHA256,
    MASTER,
    ROOT as REPOSITORY_ROOT,
)
from build.tools.rehearse_abstract_of_principles_release import (
    EXPECTED_SOURCE_NOTE_SHA256,
    EXPECTED_PUBLIC_NOTICE_SHA256,
    NOTICE_BINDING,
    SOURCE_NOTE,
    PUBLIC_NOTICE,
    _isolated_authority,
    rehearse_release,
    verify_rehearsal,
)


RIGHTS_APPENDIX = b"\n## Current rights disposition (2026-10-09)\n"


def _historical_notice(raw: bytes, expected_sha256: str) -> bytes:
    lf = raw.replace(b"\r\n", b"\n")
    for candidate in (raw, lf, lf.replace(b"\n", b"\r\n")):
        if sha256(candidate).hexdigest() == expected_sha256:
            return candidate
        if candidate.count(RIGHTS_APPENDIX) == 1:
            original, _appendix = candidate.split(RIGHTS_APPENDIX, 1)
            if sha256(original).hexdigest() == expected_sha256:
                return original
    raise AssertionError("Historical notice complete original SHA differs")


@pytest.fixture
def historical_root():
    """Replay frozen rehearsal notices without changing later rights updates."""
    originals = {p: (REPOSITORY_ROOT / p).read_bytes() for p in (SOURCE_NOTE, PUBLIC_NOTICE)}
    with _isolated_authority(REPOSITORY_ROOT) as isolated:
        for relative, digest in ((SOURCE_NOTE, EXPECTED_SOURCE_NOTE_SHA256),
                                 (PUBLIC_NOTICE, EXPECTED_PUBLIC_NOTICE_SHA256)):
            target = isolated / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_historical_notice(originals[relative], digest))
        schema = Path("schemas/v2/public-row.schema.json")
        (isolated / schema).parent.mkdir(parents=True, exist_ok=True)
        (isolated / schema).write_bytes((REPOSITORY_ROOT / schema).read_bytes())
        binding_path = isolated / NOTICE_BINDING
        binding = json.loads(binding_path.read_bytes())
        expected = json.loads(binding_path.read_bytes())
        assert len(binding["public_notices"]) == 1
        notice = binding["public_notices"][0]
        assert notice["source_path"] == SOURCE_NOTE.as_posix()
        assert notice["notice_path"] == PUBLIC_NOTICE.as_posix()
        notice["source_sha256"] = EXPECTED_SOURCE_NOTE_SHA256
        notice["notice_sha256"] = EXPECTED_PUBLIC_NOTICE_SHA256
        expected["public_notices"][0].update(
            source_sha256=EXPECTED_SOURCE_NOTE_SHA256,
            notice_sha256=EXPECTED_PUBLIC_NOTICE_SHA256,
        )
        assert binding == expected
        binding_path.write_bytes((json.dumps(binding, sort_keys=True, separators=(",", ":")) + "\n").encode())
        yield isolated
    assert all((REPOSITORY_ROOT / p).read_bytes() == b for p, b in originals.items())


@pytest.mark.parametrize("relative,digest", (
    (SOURCE_NOTE, EXPECTED_SOURCE_NOTE_SHA256),
    (PUBLIC_NOTICE, EXPECTED_PUBLIC_NOTICE_SHA256),
))
def test_historical_notice_original_prefix_cannot_be_changed(relative, digest):
    raw = (REPOSITORY_ROOT / relative).read_bytes()
    assert sha256(_historical_notice(raw, digest)).hexdigest() == digest
    with pytest.raises(AssertionError):
        _historical_notice(b"!" + raw[1:], digest)


def test_single_work_release_and_tamper_rejection(tmp_path: Path, historical_root: Path) -> None:
    ROOT = historical_root
    master_before = (ROOT / MASTER).read_bytes()
    acceptance_before = (ROOT / ACCEPTANCE).read_bytes()
    evidence = tmp_path / "evidence"
    result = rehearse_release(ROOT, evidence_dir=evidence)
    assert result["status"] == "offline-verified-not-authorized-for-publication"
    assert result["row_count"] == 20
    assert result["item_status"] == "included"
    assert result["independent_check"] == {"status": "pass", "errors": []}
    assert result["reader_status"] == "pass"
    assert result["reader_normal_and_streaming"] == "pass"
    assert result["adapter"] == {
        "removed_field": "provenance.source_location",
        "removed_occurrences": 20,
        "text_or_structure_changes": 0,
        "canonical_safe_source_field_retained": "provenance.source_url",
        "private_paths_remaining": 0,
    }
    assert result["rights_clearance"] == "not-recorded"
    assert result["publication_authorization"] == "not-recorded"
    assert result["publication_performed"] is False

    selection = json.loads((evidence / "selection.json").read_bytes())
    release = evidence / "release-evidence"
    rows = release / "public/data/doctrinal_documents/train.jsonl"
    assert "raw/" not in rows.read_text(encoding="utf-8")
    values = [json.loads(line) for line in rows.read_text(encoding="utf-8").splitlines()]
    values[0]["text"] += " altered"
    rows.write_text(
        "".join(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for value in values
        ),
        encoding="utf-8",
        newline="\n",
    )
    tampered = verify_rehearsal(ROOT, release, selection)
    assert tampered["status"] == "fail"
    assert tampered["errors"]

    assert sha256((ROOT / MASTER).read_bytes()).hexdigest() == EXPECTED_MASTER_SHA256
    assert sha256((ROOT / ACCEPTANCE).read_bytes()).hexdigest() == EXPECTED_ACCEPTANCE_SHA256
    assert (ROOT / MASTER).read_bytes() == master_before
    assert (ROOT / ACCEPTANCE).read_bytes() == acceptance_before
