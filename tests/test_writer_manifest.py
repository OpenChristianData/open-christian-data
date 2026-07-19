"""Tests for the shared writer-manifest emitter.

The emitter's job is provenance, so the load-bearing tests are the negative ones: a run
that fails must not leave a manifest claiming it succeeded, and a manifest that does not
validate must not land at all.
"""

from __future__ import annotations

import json

import pytest
from jsonschema import Draft7Validator

from build.lib import writer_manifest
from build.lib.paths import REPO_ROOT


@pytest.fixture()
def repo(tmp_path):
    """A fake repo root with a data/ tree and a manifests dir."""
    (tmp_path / "data" / "reference").mkdir(parents=True)
    (tmp_path / "review" / "writer-manifests").mkdir(parents=True)
    return tmp_path


def _manifests(repo):
    return sorted((repo / "review" / "writer-manifests").glob("*.json"))


def _emit(repo, target, *, payload, entries=1, fields=1, identity="naves_topical_parser", boom=False, run_id=None):
    with writer_manifest.run(
        writer_identity=identity,
        writer_version="build/parsers/naves_topical.py@v1.0.0",
        data_paths=[target],
        repo_root=repo,
        run_id=run_id,
        manifests_dir=repo / "review" / "writer-manifests",
    ) as run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload), encoding="utf-8")
        run.record_delta(target, entries_changed=entries, fields_changed=fields)
        if boom:
            raise RuntimeError("writer exploded mid-run")


def test_emits_schema_valid_manifest_for_a_new_file(repo):
    target = repo / "data" / "reference" / "thing.json"
    _emit(repo, target, payload={"meta": {}, "data": [1]})

    written = _manifests(repo)
    assert len(written) == 1
    body = json.loads(written[0].read_text(encoding="utf-8"))

    schema = json.loads((REPO_ROOT / "schemas" / "v1" / "writer_manifest.schema.json").read_text(encoding="utf-8"))
    assert list(Draft7Validator(schema).iter_errors(body)) == []

    assert body["writer"] == "parser"  # derived from the registry, not passed in
    assert body["writer_identity"] == "naves_topical_parser"
    assert body["data_paths"] == ["data/reference/thing.json"]
    assert body["partial_completion_policy"] == "all_or_nothing"
    assert body["allowed_field_paths"] == ["/meta", "/data"]


def test_before_hash_is_null_for_a_new_file_and_real_for_an_existing_one(repo):
    target = repo / "data" / "reference" / "thing.json"

    # Explicit run ids: the default is a random uuid, so globbing cannot tell the two
    # runs apart deterministically.
    _emit(repo, target, payload={"meta": {}, "data": [1]}, run_id="run-one")
    first = json.loads((repo / "review" / "writer-manifests" / "run-one.json").read_text(encoding="utf-8"))
    entry = first["checksums"]["data/reference/thing.json"]
    assert entry["before_sha256"] is None  # file did not exist
    after_first = entry["after_sha256"]

    _emit(repo, target, payload={"meta": {}, "data": [1, 2]}, run_id="run-two")
    body = json.loads((repo / "review" / "writer-manifests" / "run-two.json").read_text(encoding="utf-8"))
    entry = body["checksums"]["data/reference/thing.json"]

    # The before-hash of the second run must equal the after-hash of the first. This is
    # the property a post-hoc generator cannot establish, and the reason the emitter
    # wraps the write instead of following it.
    assert entry["before_sha256"] == after_first
    assert entry["after_sha256"] != entry["before_sha256"]


def test_hashes_are_bare_lowercase_hex_not_prefixed(repo):
    # Manifests in review/ disagree: some use a "sha256:" prefix, which the schema's
    # ^[0-9a-f]{64}$ pattern rejects. Pin the schema-correct form.
    target = repo / "data" / "reference" / "thing.json"
    _emit(repo, target, payload={"meta": {}, "data": [1]})
    body = json.loads(_manifests(repo)[0].read_text(encoding="utf-8"))
    digest = body["checksums"]["data/reference/thing.json"]["after_sha256"]
    assert not digest.startswith("sha256:")
    assert len(digest) == 64 and digest == digest.lower()


def test_failed_run_writes_no_manifest(repo):
    target = repo / "data" / "reference" / "thing.json"
    with pytest.raises(RuntimeError, match="exploded"):
        _emit(repo, target, payload={"meta": {}, "data": [1]}, boom=True)

    # all_or_nothing: a half-finished run must not leave provenance saying it completed.
    assert _manifests(repo) == []


def test_unregistered_identity_fails_fast(repo):
    target = repo / "data" / "reference" / "thing.json"
    with pytest.raises(ValueError, match="not registered"):
        _emit(repo, target, payload={"meta": {}, "data": []}, identity="totally_made_up_parser")
    assert _manifests(repo) == []


def test_missing_delta_claim_is_rejected(repo):
    target = repo / "data" / "reference" / "thing.json"
    with pytest.raises(ValueError, match="record_delta was not called"):
        with writer_manifest.run(
            writer_identity="naves_topical_parser",
            writer_version="build/parsers/naves_topical.py@v1.0.0",
            data_paths=[target],
            repo_root=repo,
            manifests_dir=repo / "review" / "writer-manifests",
        ):
            target.write_text('{"meta":{},"data":[]}', encoding="utf-8")
    assert _manifests(repo) == []


def test_declared_path_never_written_is_rejected(repo):
    target = repo / "data" / "reference" / "never.json"
    with pytest.raises(FileNotFoundError, match="was not written"):
        with writer_manifest.run(
            writer_identity="naves_topical_parser",
            writer_version="build/parsers/naves_topical.py@v1.0.0",
            data_paths=[target],
            repo_root=repo,
            manifests_dir=repo / "review" / "writer-manifests",
        ) as run:
            run.record_delta(target, entries_changed=0, fields_changed=0)
    assert _manifests(repo) == []


def test_record_delta_for_undeclared_path_is_rejected(repo):
    target = repo / "data" / "reference" / "thing.json"
    other = repo / "data" / "reference" / "other.json"
    with pytest.raises(ValueError, match="not declared in data_paths"):
        with writer_manifest.run(
            writer_identity="naves_topical_parser",
            writer_version="build/parsers/naves_topical.py@v1.0.0",
            data_paths=[target],
            repo_root=repo,
            manifests_dir=repo / "review" / "writer-manifests",
        ) as run:
            target.write_text('{"meta":{},"data":[]}', encoding="utf-8")
            run.record_delta(other, entries_changed=1, fields_changed=1)


def test_paths_outside_data_are_rejected(repo):
    stray = repo / "build" / "not-data.json"
    with pytest.raises(ValueError, match="must live under data/"):
        with writer_manifest.run(
            writer_identity="naves_topical_parser",
            writer_version="build/parsers/naves_topical.py@v1.0.0",
            data_paths=[stray],
            repo_root=repo,
            manifests_dir=repo / "review" / "writer-manifests",
        ):
            pass


def test_negative_delta_counts_are_rejected(repo):
    target = repo / "data" / "reference" / "thing.json"
    with pytest.raises(ValueError, match="non-negative"):
        with writer_manifest.run(
            writer_identity="naves_topical_parser",
            writer_version="build/parsers/naves_topical.py@v1.0.0",
            data_paths=[target],
            repo_root=repo,
            manifests_dir=repo / "review" / "writer-manifests",
        ) as run:
            target.write_text('{"meta":{},"data":[]}', encoding="utf-8")
            run.record_delta(target, entries_changed=-1, fields_changed=0)


def test_diff_counts_measures_real_changes():
    before = {"meta": {}, "data": [{"id": "a", "v": 1}, {"id": "b", "v": 2}]}
    after = {"meta": {}, "data": [{"id": "a", "v": 1}, {"id": "b", "v": 99}, {"id": "c", "v": 3}]}
    entries, fields = writer_manifest.diff_counts(before, after, key=lambda e: e["id"])
    # b modified -> 1 field; c added -> its 2 fields. a is untouched and must not count.
    assert (entries, fields) == (2, 3)


def test_diff_counts_treats_a_first_write_as_all_new():
    after = {"meta": {}, "data": [{"id": "a", "v": 1}, {"id": "b", "v": 2}]}
    entries, fields = writer_manifest.diff_counts(None, after, key=lambda e: e["id"])
    assert entries == 2


def test_diff_counts_rejects_a_non_unique_key():
    # The live Nave case: 'topic' repeats (REVERENCE, SIN) while 'entry_id' is unique.
    # Keying on the non-unique field collapses entries and silently under-reports the
    # delta, so it must fail rather than emit a wrong count.
    payload = {
        "meta": {},
        "data": [
            {"entry_id": "sin-1", "topic": "SIN"},
            {"entry_id": "sin-2", "topic": "SIN"},
        ],
    }
    with pytest.raises(ValueError, match="not unique"):
        writer_manifest.diff_counts(None, payload, key=lambda e: e["topic"])

    # The unique key works on the same payload.
    entries, _ = writer_manifest.diff_counts(None, payload, key=lambda e: e["entry_id"])
    assert entries == 2


def test_manifest_satisfies_the_pre_commit_gate_identity_check():
    # The gate reads writer_identity against the in-source allowlist; a manifest whose
    # identity is unregistered is exactly what it blocks.
    from build.lib.writer_identities import is_authorised

    assert is_authorised("naves_topical_parser")
    assert not is_authorised("totally_made_up_parser")
