"""Editorial holds never grant rights or silently expand the public cohort."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError, canonical_bytes, io_path, _read_inputs
from ocd_kernel.library.identities import Work
from ocd_kernel.release import profile
from tests.test_derive_library_release_selection import _fixture, _json
from build.tools import derive_library_release_selection as tool


def _binding(root, reference, **extra):
    return {"path": reference, "sha256": hashlib.sha256((root / reference).read_bytes()).hexdigest(), **extra}


def _grant(root, selected):
    acceptance = json.loads((root / selected["acceptance_path"]).read_bytes())
    identity = acceptance["identity"]
    base = str(Path(selected["acceptance_path"]).parent.as_posix())
    decision = base + "/rights-subjects/decision.json"
    _json(root / decision, {"selected": selected})
    subject = {"schema_version": "2.1", "subject_id": "selected", "work_id": identity["work_id"],
               "edition_id": identity["edition_id"], "scope": "selected-text",
               "material": _binding(root, decision, pointer="/selected"), "components": [],
               "evidence": [_binding(root, selected["acceptance_path"])],
               "public_scope": {"include": [{"kind": "record-id", "values": ["chapter-1"]}], "exclude": []}}
    subject_path = base + "/rights-subjects/subject.json"
    _json(root / subject_path, subject)
    semantics = {"work_id": identity["work_id"], "edition_id": identity["edition_id"], "scope": "selected-text",
                 "rights_status": "licensed", "jurisdictions": ["worldwide"], "license_ids": ["CC0-1.0"],
                 "basis": "dedication", "condition": "unconditional"}
    normalization = {"contract": "ocd-rights-normalization-v1", "item_id": selected["item_id"],
                     "acceptance_path": selected["acceptance_path"], "effective_license": selected.get("license"),
                     "public_notices": [], "assessment": semantics, "subject_id": subject["subject_id"],
                     "components": [], "material": subject["material"], "subject_evidence": subject["evidence"],
                     "public_scope_sha256": hashlib.sha256(canonical_bytes(subject["public_scope"])).hexdigest()}
    proof_path = base + "/rights-subjects/normalization.json"
    _json(root / proof_path, {"finding": normalization})
    _json(root / base / "rights/selected.json", {"schema_version": "2.1", "record_id": "selected-assessment",
        **semantics, "subject": _binding(root, subject_path, id=subject["subject_id"]),
        "evidence": [_binding(root, proof_path, pointer="/finding")],
        "assessed_by": "Synthetic fixture grant", "assessed_on": "2026-10-21"})


@pytest.fixture
def current(tmp_path, monkeypatch):
    prior, master = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(profile, "discover_library", lambda root: tool.discover_library(root))
    monkeypatch.setattr(profile, "validate_work_cohort", lambda *_args: {})
    selected = json.loads(prior.read_bytes())["items"][0]
    selected["license"] = "CC0-1.0"
    _grant(tmp_path, selected)
    acquisition = master.parent / "acquisitions/source-member.json"
    retained = tmp_path / "raw/retained.txt"
    retained.parent.mkdir()
    retained.write_bytes(b"source")
    _json(acquisition, {"retained_files": [_binding(tmp_path, "raw/retained.txt")]})
    value = {"contract": profile.CONTRACT, "profile_id": "example", "audience": "public-candidate",
        "decision_provenance": "Explicit synthetic fixture decisions",
        "migration_source": {"path": "missing-historical-selection.json", "sha256": "a" * 64},
        "works": [{"work_id": "accepted-work", "disposition": "cohort"},
                  {"work_id": "ocr-work", "disposition": "private", "reason": "OCR hold"}],
        "items": [{"item_id": selected["item_id"], "work_id": "accepted-work", "textual_form_id": "english",
                   "edition_id": "electronic", "disposition": "selected"}]}
    path = tmp_path / "library/publication-profiles/example.json"
    _json(path, value)
    return tmp_path, path, value, master


def test_profile_derives_rights_and_sources_without_historical_selection(current):
    root, path, _, master = current
    selected, receipt = profile.resolve_publication_profile(root, profile_path=path, release_id="fresh")
    assert selected["items"][0]["license"] == "CC0-1.0"
    assert receipt["selected_text_items"] == 1
    files = {entry["path"] for entry in receipt["item_bindings"][0]["files"]}
    assert {"raw/retained.txt", master.relative_to(root).as_posix(), "library/works/accepted-work/work.json"} <= files
    assert any("rights/selected.json" in path for path in files)
    assert receipt["item_bindings"][0]["discovery"][0]["members"] == ["selected.json"]
    assert not (root / "missing-historical-selection.json").exists()


def test_rights_material_without_optional_license_does_not_create_null_license(current):
    root, _, _, master = current
    selected = {"item_id": "accepted-work--electronic", "work_id": "accepted-work", "category": "prose",
                "acceptance_path": master.with_name("acceptance.json").relative_to(root).as_posix()}
    _grant(root, selected)
    identity = json.loads(master.with_name("acceptance.json").read_bytes())["identity"]
    derived, _ = profile._rights_selection(root, selected, identity)
    assert derived == selected
    assert "license" not in derived
    assert "public_notices" not in derived


def test_rights_proof_payload_cache_is_released_after_each_edition(current, monkeypatch):
    root, path, _, master = current
    proof = io_path(master.parent / "rights-subjects/decision.json")
    proof_sha = hashlib.sha256(proof.read_bytes()).hexdigest()
    original = profile._source_files

    def checked(*args, **kwargs):
        cache = _read_inputs.get()
        assert ("bytes", proof) not in cache
        assert ("rights-json", proof_sha) not in cache
        return original(*args, **kwargs)

    monkeypatch.setattr(profile, "_source_files", checked)
    selection, _ = profile.resolve_publication_profile(root, profile_path=path, release_id="fresh")
    assert len(selection["items"]) == 1


def test_work_hold_overrides_selected_edition_and_new_editions_remain_private(current, monkeypatch):
    root, path, value, master = current
    value["works"][0]["hold_reason"] = "Private missionary work"
    _json(path, value)
    accepted, ocr = tool.discover_library(root)
    later = replace(accepted.editions[0], edition_id="future", path=master.parent.parent / "future/master.tei.xml")
    monkeypatch.setattr(profile, "discover_library", lambda _root: (replace(accepted, editions=accepted.editions + (later,)), ocr))
    selection, receipt = profile.resolve_publication_profile(root, profile_path=path, release_id="fresh")
    assert selection["items"][0]["exclude_reason"] == "Private missionary work"
    assert "license" not in selection["items"][0]
    assert receipt["selected_text_items"] == 0
    assert receipt["pending_private"][0]["item_id"] == "accepted-work--future"


def test_unknown_work_and_edition_are_pending_private(current, monkeypatch):
    root, path, _, master = current
    accepted, ocr = tool.discover_library(root)
    later = replace(accepted.editions[0], edition_id="future", path=master.parent.parent / "future/master.tei.xml")
    new_home = root / "library/works/new-work"
    _json(new_home / "work.json", {"work_id": "new-work"})
    _json(new_home / "state.json", {"work_id": "new-work"})
    new = Work("new-work", "New", new_home / "work.json", {}, ())
    monkeypatch.setattr(profile, "discover_library", lambda _root: (replace(accepted, editions=accepted.editions + (later,)), ocr, new))
    selection, receipt = profile.resolve_publication_profile(root, profile_path=path, release_id="fresh")
    assert len(selection["items"]) == 1
    assert {"work_id": "new-work", "reason": profile.PENDING_REASON} in selection["work_coverage"]["excluded_works"]
    assert len(receipt["pending_private"]) == 2


@pytest.mark.parametrize("damage", ["acceptance", "master", "rights", "source", "source-sha"])
def test_profile_selection_cannot_override_invalid_authority(current, damage):
    root, path, _, master = current
    if damage == "acceptance":
        master.with_name("acceptance.json").unlink()
    elif damage == "master":
        master.write_bytes(b"changed")
    elif damage == "rights":
        (master.parent / "rights/selected.json").unlink()
    elif damage == "source":
        (root / "raw/retained.txt").unlink()
    else:
        (root / "raw/retained.txt").write_bytes(b"changed source")
    with pytest.raises(PipelineError):
        profile.resolve_publication_profile(root, profile_path=path, release_id="fresh")


@pytest.mark.parametrize("damage", ["duplicate", "identity", "license"])
def test_profile_validation_rejects_ambiguity_and_rights_fields(current, damage):
    _, path, value, _ = current
    if damage == "duplicate":
        value["items"].append(value["items"][0])
    elif damage == "identity":
        value["items"][0]["edition_id"] = "wrong"
    else:
        value["items"][0]["license"] = "CC0-1.0"
    _json(path, value)
    with pytest.raises(PipelineError):
        profile.load_publication_profile(path)


def test_file_bindings_are_deduplicated_only_within_one_resolution(current, monkeypatch):
    root, _, _, _ = current
    opened = []
    original = Path.open

    def tracked(path, *args, **kwargs):
        if path.name == "retained.txt":
            opened.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracked)
    token = profile._file_cache.set({})
    try:
        first = profile._file(root, "raw/retained.txt")
        assert profile._file(root, "raw/retained.txt") == first
        assert len(opened) == 1
        (root / "raw/retained.txt").write_bytes(b"different source length")
    finally:
        profile._file_cache.reset(token)
    assert profile._file(root, "raw/retained.txt")["sha256"] != first["sha256"]
    assert len(opened) == 3  # First hash, mutation write, then fresh-phase hash.


def test_resolution_checks_consumed_file_stamps_before_return(current, monkeypatch):
    root, path, _, _ = current
    original = profile._source_files

    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        (root / "raw/retained.txt").write_bytes(b"changed during resolution")
        return result

    monkeypatch.setattr(profile, "_source_files", mutate)
    with pytest.raises(PipelineError, match="changed during resolution"):
        profile.resolve_publication_profile(root, profile_path=path, release_id="fresh")


def test_profile_cli_writes_existing_selection_contract(current, monkeypatch, capsys):
    root, path, _, _ = current
    destination = root / "derived"
    monkeypatch.setattr("sys.argv", ["derive", "--root", str(root), "--release-id", "fresh",
                                    "--profile", str(path), "--output-dir", str(destination)])
    tool.main()
    selection = json.loads((destination / "selection.json").read_bytes())
    receipt = json.loads((destination / "derivation.json").read_bytes())
    assert selection["schema_version"] == "2.0"
    assert receipt["contract"] == "ocd-profile-derivation-v1"
    assert "notice_selection" not in receipt
    assert json.loads(capsys.readouterr().out)["selected_text_items"] == 1
