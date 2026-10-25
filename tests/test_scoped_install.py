import copy
import json
from pathlib import Path
import shutil

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.views import _build_snapshot
from ocd_kernel.library.records import lookup_library_record
from ocd_kernel.tei.acceptance import make_file_binding, promote_accepted_master, validate_acceptance
from ocd_kernel.tei.install_accepted import _files, add_accepted_scope
from tests.test_tei_acceptance import (
    ACQUISITION_ID, EDITION_ID, FORM_ID, WORK_ID, _fixture_root,
    _write_valid_acceptance, _edition_root,
)


SECOND = "ccel-npnf204-second-copy"


def _prepare(tmp_path: Path):
    source = _fixture_root(tmp_path)
    pending, _ = _write_valid_acceptance(source)
    live = promote_accepted_master(source, acceptance_path=pending, destination=tmp_path / "live").destination_root
    edition = _edition_root(live)
    first_sidecar = edition / "acquisitions" / f"{ACQUISITION_ID}.json"
    second_sidecar = edition / "acquisitions" / f"{SECOND}.json"
    second_sidecar.write_text(first_sidecar.read_text(encoding="utf-8").replace(ACQUISITION_ID, SECOND), encoding="utf-8")
    work_path = live / "library" / "works" / WORK_ID / "work.json"
    work = json.loads(work_path.read_text(encoding="utf-8"))
    work["textual_forms"][0]["editions"][0]["acquisition_ids"] = [ACQUISITION_ID, SECOND]
    work_path.write_text(json.dumps(work), encoding="utf-8")
    state_path = live / "library" / "works" / WORK_ID / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["targets"].append({
        "target_id": SECOND, "target_type": "acquisition", "stage": "acquired",
        "updated_at": "2026-09-06T09:00:00Z",
        "evidence": [second_sidecar.relative_to(live).as_posix()],
    })
    state_path.write_text(json.dumps(state), encoding="utf-8")
    original = _files(live / "library" / "works" / WORK_ID)
    stage = tmp_path / "stage"
    shutil.copytree(live, stage)
    old = json.loads((_edition_root(stage) / "acceptance.json").read_text(encoding="utf-8"))
    new = copy.deepcopy(old)
    new["identity"]["acquisition_id"] = SECOND
    new["acceptance_id"] = f"{EDITION_ID}-acceptance-{SECOND}"
    new["source"]["source_manifest"] = make_file_binding(stage, _edition_root(stage) / "acquisitions" / f"{SECOND}.json")
    old_candidate = stage / old["technical"]["candidate"]["path"]
    new_evidence = stage / "acceptance-second"
    new_evidence.mkdir()
    candidate = new_evidence / "candidate.tei.xml"
    candidate.write_text(old_candidate.read_text(encoding="utf-8").replace(ACQUISITION_ID, SECOND), encoding="utf-8")
    new["technical"]["candidate"] = make_file_binding(stage, candidate)
    for key in ("source", "technical", "review"):
        names = ("accounting",) if key == "source" else (
            "validation", "accounting", "fidelity", "reproducibility", "schema", "closure"
        ) if key == "technical" else ("report",)
        for name in names:
            binding = old[key][name]
            source_path = stage / binding["path"]
            destination = new_evidence / source_path.name
            if key == "source":
                destination = new_evidence / "source-accounting.json"
            document = json.loads(source_path.read_text(encoding="utf-8"))
            document["identity"]["acquisition_id"] = SECOND
            if key != "source":
                document["candidate"] = new["technical"]["candidate"]
            destination.write_text(json.dumps(document), encoding="utf-8")
            new[key][name] = make_file_binding(stage, destination) | {
                k: v for k, v in binding.items() if k not in {"path", "bytes", "sha256"}
            }
    scope_root = _edition_root(stage) / "scopes" / SECOND
    scope_root.mkdir(parents=True)
    master = scope_root / "master.tei.xml"
    shutil.copyfile(candidate, master)
    new["promotion"]["master"] = make_file_binding(stage, master)
    acceptance = scope_root / "acceptance.json"
    acceptance.write_text(json.dumps(new), encoding="utf-8")
    state_path = stage / "library" / "works" / WORK_ID / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    edition_target = next(t for t in state["targets"] if t["target_id"] == EDITION_ID)
    edition_target["evidence"].extend([master.relative_to(stage).as_posix(), acceptance.relative_to(stage).as_posix()])
    state_path.write_text(json.dumps(state), encoding="utf-8")
    shutil.copytree(new_evidence, live / "acceptance-second")
    return live, stage, original, acceptance


def _add(live, stage, original, **kwargs):
    return add_accepted_scope(
        live, stage, work_id=WORK_ID, textual_form_id=FORM_ID,
        edition_id=EDITION_ID, acquisition_id=SECOND, expected_old=original, **kwargs,
    )


def test_scoped_acceptance_adds_second_acquisition_without_changing_first(tmp_path):
    live, stage, original, acceptance = _prepare(tmp_path)
    validate_acceptance(acceptance, root=stage)
    result = _add(live, stage, original)
    assert result["status"] == "scope-added-and-validated"
    installed = _files(live / "library" / "works" / WORK_ID)
    assert all(installed[path] == digest for path, digest in original.items() if path != "state.json")
    assert len(installed) == len(original) + 2


def test_scoped_addition_rejects_stale_preimage(tmp_path):
    live, stage, original, _ = _prepare(tmp_path)
    original["work.json"] = "0" * 64
    with pytest.raises(PipelineError, match="expected-old"):
        _add(live, stage, original)


def test_scoped_addition_rolls_back_after_live_swap(tmp_path):
    live, stage, original, _ = _prepare(tmp_path)
    def interrupt(point):
        if point == "after-new-live":
            raise RuntimeError("fixture interruption")
    with pytest.raises(RuntimeError, match="fixture interruption"):
        _add(live, stage, original, fail_at=interrupt)
    assert _files(live / "library" / "works" / WORK_ID) == original


def test_library_view_accounts_for_scoped_acceptance(tmp_path):
    live, stage, original, _ = _prepare(tmp_path)
    _add(live, stage, original)
    snapshot = _build_snapshot(live)["manifest"]
    scoped = [item for item in snapshot["acceptances"] if item.get("acquisition_id") == SECOND]
    assert len(scoped) == 1 and scoped[0]["status"] == "promoted"
    assert not [item for item in snapshot["issues"] if item["kind"] == "invalid-scoped-acceptance"]
    record = lookup_library_record(live, {"kind": "work", "namespace": "ocd", "id": WORK_ID}, connections=False)
    holdings = record["sections"]["holdings"]["data"]["editions"][0]["scoped_holdings"]
    assert [item["acquisition_id"] for item in holdings] == [SECOND]
