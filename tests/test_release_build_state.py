"""Private profile builds pin inputs, reuse projections, and promote only ready bytes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.build_state import MANIFEST, READY, check_ready, capture_inputs, check_inputs
from ocd_kernel.release.profile import resolve_publication_profile
from ocd_kernel.release.verify import verify_release_v2
from tests.test_release_assembly_v2 import _item, _promoted_category


def _profile_fixture(tmp_path, monkeypatch):
    root, acceptance = _promoted_category(tmp_path, "quotations", "profile-build")
    identity = json.loads(acceptance.read_bytes())["identity"]
    work_path = root / "library/works" / identity["work_id"] / "work.json"
    work = json.loads(work_path.read_bytes())
    for form in work["textual_forms"]:
        for edition in form["editions"]:
            if edition["edition_id"] == identity["edition_id"]:
                edition["acquisition_ids"] = [identity["acquisition_id"]]
                edition["category"] = "quotations"
    work_path.write_bytes(canonical_bytes(work))
    # This older fixture retains an excerpt and names an unavailable upstream
    # full book. Scope these orchestration tests to its actual retained member;
    # profile source-path enforcement has separate real-path mutation tests.
    from ocd_kernel.release import profile as profile_module

    def fixture_sources(authority_root, accepted, _edition):
        return [profile_module._file(authority_root, member["path"])
                for member in accepted["scope"]["included_members"]]

    monkeypatch.setattr(profile_module, "_source_files", fixture_sources)
    item_id = f"{identity['work_id']}--{identity['edition_id']}"
    _item(root, item_id, "quotations", acceptance, license="CC0-1.0")
    profile = root / "library/publication-profiles/fixture.json"
    profile.parent.mkdir(parents=True)
    profile.write_bytes(canonical_bytes({"contract": "ocd-publication-profile-v1", "profile_id": "fixture",
        "audience": "public-candidate", "decision_provenance": "Synthetic local fixture decisions only",
        "works": [{"work_id": identity["work_id"], "disposition": "cohort"}],
        "items": [{"item_id": item_id, "work_id": identity["work_id"],
                   "textual_form_id": identity["textual_form_id"], "edition_id": identity["edition_id"],
                   "disposition": "selected"}]}))
    selection, _ = resolve_publication_profile(root, profile_path=profile, release_id="profile-build")
    return root, profile, selection


def test_profile_candidate_reuses_prior_checked_ranges_without_projecting(tmp_path, monkeypatch):
    root, profile, selection = _profile_fixture(tmp_path, monkeypatch)
    first = tmp_path / "first"
    assemble_release_v2(root, first, selection=selection, profile_path=profile, reader_check=True)
    check_ready(first)
    assert verify_release_v2(root, first, selection=selection) == {"status": "pass", "errors": []}
    import ocd_kernel.projection.categories.quotations as projector

    def forbidden(*args, **kwargs):
        raise AssertionError("unchanged projection was rebuilt")

    monkeypatch.setattr(projector, "project_accepted_quotations", forbidden)
    second = tmp_path / "second"
    assemble_release_v2(root, second, selection=selection, profile_path=profile,
                        previous_release=first, reader_check=True)
    check_ready(second)
    manifest = json.loads((second / MANIFEST).read_bytes())
    assert [item["reused"] for item in manifest["items"]] == [True]
    original = {p.relative_to(first / "public").as_posix(): p.read_bytes()
                for p in (first / "public").rglob("*") if p.is_file()}
    assert original == {p.relative_to(second / "public").as_posix(): p.read_bytes()
                        for p in (second / "public").rglob("*") if p.is_file()}
    assert not (second / ".work").exists()


@pytest.mark.parametrize("mutation", ["receipt", "profile", "image", "new-file", "catalog"])
def test_postverification_input_or_private_artifact_drift_prevents_readiness(tmp_path, monkeypatch, mutation):
    root, profile, selection = _profile_fixture(tmp_path, monkeypatch)
    asset = root / "library/works" / selection["items"][0]["work_id"] / "cover.jpg"
    asset.write_bytes(b"original source image")
    from build.tools import check_release_reader as reader
    actual = reader.check_reader

    def mutate_after_reader(*args, **kwargs):
        proof = actual(*args, **kwargs)
        if mutation == "receipt":
            path = next((args[1] / "internal/projection-receipts").glob("*.json"))
        elif mutation == "profile":
            path = profile
        elif mutation == "image":
            path = asset
        elif mutation == "new-file":
            path = asset.with_name("new-asset")
            path.write_bytes(b"new asset")
        else:
            path = root / "library/works/new-work/work.json"
            path.parent.mkdir()
            path.write_bytes(b"{}")
        path.write_bytes(path.read_bytes() + b"\n")
        return proof

    monkeypatch.setattr(reader, "check_reader", mutate_after_reader)
    output = tmp_path / "must-not-be-ready"
    with pytest.raises(PipelineError, match="changed"):
        assemble_release_v2(root, output, selection=selection, profile_path=profile, reader_check=True)
    assert not output.exists()
    stages = list(output.parent.glob(f".{output.name}-*"))
    assert len(stages) == 1 and not (stages[0] / READY).exists()


def test_profile_orchestration_resolves_once_and_final_check_only_hashes(tmp_path, monkeypatch):
    root, profile, _selection = _profile_fixture(tmp_path, monkeypatch)
    from ocd_kernel.release import profile as profiles
    actual = profiles.resolve_publication_profile
    calls = []

    def once(*args, **kwargs):
        calls.append(True)
        assert len(calls) == 1, "profile semantic resolution repeated"
        return actual(*args, **kwargs)

    monkeypatch.setattr(profiles, "resolve_publication_profile", once)
    output = tmp_path / "single-resolution"
    assemble_release_v2(root, output, profile_path=profile, release_id="profile-build", reader_check=True)
    assert calls == [True]
    check_ready(output)


def test_profile_build_rejects_missing_reader_gate(tmp_path, monkeypatch):
    root, profile, selection = _profile_fixture(tmp_path, monkeypatch)
    output = tmp_path / "missing-readers"
    with pytest.raises(PipelineError, match="both reader modes"):
        assemble_release_v2(root, output, selection=selection, profile_path=profile)
    assert not output.exists()


def test_pinned_input_closure_rejects_missing_groups_and_core_files(tmp_path, monkeypatch):
    from copy import deepcopy
    root, profile, selection = _profile_fixture(tmp_path, monkeypatch)
    inputs = capture_inputs(root, selection, profile)
    for group in ("support", "item_bindings", "work_bindings", "inventory"):
        changed = deepcopy(inputs)
        changed[group].clear()
        with pytest.raises(PipelineError, match="incomplete"):
            check_inputs(root, selection, changed)
    changed = deepcopy(inputs)
    changed["item_bindings"][0]["files"] = []
    with pytest.raises(PipelineError, match="incomplete pinned item"):
        check_inputs(root, selection, changed)
