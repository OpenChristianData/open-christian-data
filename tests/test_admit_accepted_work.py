from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tools import admit_accepted_work
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import read_accepted_work
from tests.test_tei_acceptance import (
    ACQUISITION_ID,
    WORK_ID,
    _candidate,
    _decision,
    _edition_root,
    _fixture_root,
    _identity,
    _master_path,
    _prepare_evidence,
    _scope,
    _source_facts,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
TORREY = REPO_ROOT / "tests/fixtures/library-pipeline/categories/topical-indexes"


def _jsonable(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _review_state(root: Path) -> None:
    state_path = root / "library/works" / WORK_ID / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["targets"][0].update(
        stage="review",
        reason="No accepted master is installed.",
        evidence=["work.json"],
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")


def _write_declaration(
    root: Path,
    *,
    candidate: Path,
    scope: dict,
    source_facts: dict,
) -> Path:
    accounting, technical, review = _prepare_evidence(
        root,
        candidate,
        scope=scope,
        source_facts=source_facts,
    )
    decision = _decision()
    decision["agent_assessment"]["supported_scope"] = scope["declared"]
    declaration = {
        "acceptance_path": (_edition_root(root) / "acceptance.json").relative_to(root).as_posix(),
        "identity": _identity(),
        "candidate_path": candidate.relative_to(root).as_posix(),
        "source_accounting_path": accounting.relative_to(root).as_posix(),
        "scope": scope,
        "technical": technical,
        "review": review,
        "representation_revision": {
            "id": "pipe-004-fixture-v1",
            "date": "2026-09-06",
            "note": "Bound fixture candidate for PIPE-004.",
        },
        "decision": decision,
    }
    path = root / "admission.json"
    path.write_text(json.dumps(_jsonable(declaration)), encoding="utf-8")
    return path


def _xml_caller(root: Path) -> Path:
    candidate = _candidate(root)
    source = etree.parse(str(root / "retained/npnf204.vii.ii.i.thml.xml"))
    selected = source.getroot()
    assert selected.tag == "div3" and selected.get("id") == "vii.ii.i"
    assert "Introductory." in "".join(selected.itertext())
    return _write_declaration(
        root,
        candidate=candidate,
        scope=_scope(),
        source_facts=_source_facts(),
    )


def _jsonl_caller(root: Path) -> Path:
    retained = root / "retained/torrey.retained.jsonl"
    retained.write_bytes((TORREY / "torrey.retained.jsonl").read_bytes())
    raw = root / "raw/retained/torrey.retained.jsonl"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(retained.read_bytes())
    digest = hashlib.sha256(retained.read_bytes()).hexdigest()
    source_scope = "Two retained JSONL topic records in source order."
    acquisition = _edition_root(root) / "acquisitions" / f"{ACQUISITION_ID}.json"
    acquired = json.loads(acquisition.read_text(encoding="utf-8"))
    acquired.update(
        provider="Retained JSONL fixture",
        url="https://example.invalid/retained-jsonl-fixture",
        source_path="raw/retained/torrey.retained.jsonl",
        source_sha256=digest,
        source_bytes=raw.stat().st_size,
        source_scope=source_scope,
        retained_files=[{
            "path": "retained/torrey.retained.jsonl",
            "sha256": digest,
            "bytes": retained.stat().st_size,
            "media_type": "application/x-ndjson",
            "scope": source_scope,
        }],
    )
    acquisition.write_text(json.dumps(acquired), encoding="utf-8")

    candidate = _candidate(root)
    candidate_tree = etree.parse(str(candidate))
    torrey_tree = etree.parse(str(TORREY / "torrey.tei.xml"))
    namespaces = {"tei": "http://www.tei-c.org/ns/1.0"}
    candidate_tree.xpath("//tei:sourceDesc//tei:ptr", namespaces=namespaces)[0].set(
        "target", acquired["url"]
    )
    for id_type, value in (
        ("sha256", digest),
        ("source_sha256", digest),
        ("source_bytes", str(raw.stat().st_size)),
    ):
        candidate_tree.xpath(
            f"//tei:sourceDesc//tei:idno[@type='{id_type}']", namespaces=namespaces
        )[0].text = value
    candidate_tree.xpath(
        "//tei:sourceDesc//tei:note[@type='source-location']", namespaces=namespaces
    )[0].text = acquired["source_path"]
    candidate_tree.xpath(
        "//tei:sourceDesc//tei:note[@type='source-scope']", namespaces=namespaces
    )[0].text = source_scope
    candidate_text = candidate_tree.find("{http://www.tei-c.org/ns/1.0}text")
    torrey_text = torrey_tree.find("{http://www.tei-c.org/ns/1.0}text")
    assert candidate_text is not None and torrey_text is not None
    candidate_text.getparent().replace(candidate_text, copy.deepcopy(torrey_text))
    candidate_tree.write(str(candidate), encoding="utf-8", xml_declaration=True)

    records = [json.loads(line) for line in retained.read_text(encoding="utf-8").splitlines()]
    topics = candidate_tree.xpath("//tei:div[@type='topic']", namespaces=namespaces)
    assert [topic.findtext("{http://www.tei-c.org/ns/1.0}head") for topic in topics] == [
        record["term"] for record in records
    ]
    assert [["".join(item.itertext()) for item in topic.xpath("tei:list/tei:item", namespaces=namespaces)] for topic in topics] == [
        record["definitions"] for record in records
    ]
    scope = {
        "kind": "member",
        "declared": source_scope,
        "expected_members": [{"path": "retained/torrey.retained.jsonl", "position": 1}],
        "included_members": [{
            "path": "retained/torrey.retained.jsonl",
            "position": 1,
            "bytes": retained.stat().st_size,
            "sha256": digest,
            "scope": source_scope,
        }],
        "excluded_members": [],
    }
    return _write_declaration(
        root,
        candidate=candidate,
        scope=scope,
        source_facts={
            "source_path": "raw/retained/torrey.retained.jsonl",
            "source_sha256": digest,
            "source_bytes": raw.stat().st_size,
            "source_scope": source_scope,
        },
    )


def _case(tmp_path: Path, shape: str) -> tuple[Path, Path, Path, Path]:
    root = _fixture_root(tmp_path)
    _review_state(root)
    declaration = _xml_caller(root) if shape == "xml" else _jsonl_caller(root)
    live = tmp_path / "live"
    shutil.copytree(root, live)
    _master_path(live).unlink()
    return root, declaration, tmp_path / "promoted", live


@pytest.mark.parametrize("shape", ["xml", "jsonl"])
def test_command_admits_contrasting_source_shapes(tmp_path, shape):
    root, declaration, promoted, live = _case(tmp_path, shape)
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "build/tools/admit_accepted_work.py"),
            "--root", str(root),
            "--declaration", str(declaration),
            "--promotion", str(promoted),
            "--install-root", str(live),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "admitted-and-validated"
    assert result["identity"]["work_id"] == WORK_ID
    assert read_accepted_work(live, work_id=WORK_ID) == live / "library/works" / WORK_ID
    assert _master_path(live).is_file()


def test_invalid_declaration_reports_identity_and_owning_reason(tmp_path):
    root, declaration, promoted, live = _case(tmp_path, "jsonl")
    request = json.loads(declaration.read_text(encoding="utf-8"))
    request["identity"]["work_id"] = "wrong-jsonl-work"
    declaration.write_text(json.dumps(request), encoding="utf-8")

    with pytest.raises(PipelineError, match=r"admission wrong-jsonl-work failed: missing JSON sidecar: .*wrong-jsonl-work[\\/]work\.json"):
        admit_accepted_work.admit(root, declaration, promoted, live)
    assert not _master_path(live).exists()


def test_stale_live_preimage_is_rejected_without_overwrite(tmp_path, monkeypatch):
    root, declaration, promoted, live = _case(tmp_path, "xml")
    work = live / "library/works" / WORK_ID / "work.json"
    original_promote = admit_accepted_work.promote_accepted_master

    def change_live(*args, **kwargs):
        result = original_promote(*args, **kwargs)
        work.write_bytes(work.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(admit_accepted_work, "promote_accepted_master", change_live)
    with pytest.raises(PipelineError, match="staging changes existing work authority: work.json"):
        admit_accepted_work.admit(root, declaration, promoted, live)
    assert work.read_bytes().endswith(b"\n")
    assert not _master_path(live).exists()


def test_interrupted_install_restores_previous_generation(tmp_path):
    root, declaration, promoted, live = _case(tmp_path, "xml")
    state = live / "library/works" / WORK_ID / "state.json"
    before = state.read_bytes()

    def interrupt(checkpoint: str) -> None:
        if checkpoint == "after-new-live":
            raise RuntimeError("fixture interruption")

    with pytest.raises(RuntimeError, match="fixture interruption"):
        admit_accepted_work.admit(root, declaration, promoted, live, fail_at=interrupt)
    assert state.read_bytes() == before
    assert not _master_path(live).exists()
    assert read_accepted_work(live, work_id=WORK_ID) == live / "library/works" / WORK_ID
