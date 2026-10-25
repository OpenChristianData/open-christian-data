from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import build.tei.build_hf_release as release_module
from build.tei.build_hf_release import build_release


TEI_BYTES = b"""<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><fileDesc><titleStmt><title>Fixture Work</title><author>Author</author></titleStmt><sourceDesc><bibl><ptr target="https://example.test/source"/></bibl></sourceDesc></fileDesc></teiHeader>
  <text><body><div type="chapter" xml:id="chapter-1"><head>Chapter One</head><p>Hello faithful text.</p></div></body></text>
</TEI>
"""


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _selection(repo: Path, candidate: Path, validation: Path) -> dict[str, object]:
    return {
        "contract": "ocd-tei-hf-release-selection-v1",
        "release_id": "fixture-release",
        "config_name": "tei-clean-text",
        "split": "train",
        "language": "en",
        "license_id": "cc0-1.0",
        "release_timestamp": "2026-08-30T01:02:03Z",
        "publication": {
            "authorized_by": "project-maintainer",
            "authorized_at": "2026-08-30T00:00:00Z",
            "attribution_reviewed": True,
            "rationale": "Fixture publication authorization.",
        },
        "items": [
            {
                "work_id": "fixture-work",
                "rendering_id": "fixture-rendering",
                "source_manifest_path": "sources/fixture.source-manifest.json",
                "candidate_path": str(candidate),
                "validation_path": str(validation),
                "attribution_text": "Fixture attribution",
            }
        ],
    }


def _write_selection(path: Path, selection: dict[str, object]) -> None:
    path.write_text(json.dumps(selection), encoding="utf-8", newline="\n")


@pytest.fixture
def release_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    repo = tmp_path / "repo"
    source_path = repo / "sources" / "fixture.source-manifest.json"
    version_path = repo / "ocd_kernel" / "tei" / "vendor" / "VERSION.txt"
    source_path.parent.mkdir(parents=True)
    version_path.parent.mkdir(parents=True)
    source_path.write_text("{}\n", encoding="utf-8")
    version_path.write_text(
        "Edition: TEI P5 Version 4.11.0 (fixture)\n", encoding="utf-8"
    )
    candidate_path = tmp_path / "candidate"
    candidate_path.mkdir()
    candidate_members = {
        "content.tei.xml": TEI_BYTES,
        "source-accountability.json": b"{}\n",
        "provenance.json": b"{}\n",
        "unresolved.jsonl": b"",
        "README.source.md": b"# Fixture source\n",
    }
    for name, content in candidate_members.items():
        (candidate_path / name).write_bytes(content)
    candidate_manifest = {
        "contract": "ocd-candidate-package-v1",
        "status": "nonaccepted",
        "source_id": "fixture-source",
        "members": [
            {"name": name, "bytes": len(content), "sha256": _sha(content)}
            for name, content in sorted(candidate_members.items())
        ],
    }
    (candidate_path / "manifest.json").write_text(
        json.dumps(candidate_manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    validation_path = tmp_path / "validation.json"
    validation_path.write_text('{"fixture":true}\n', encoding="utf-8")
    selection_path = tmp_path / "selection.json"
    selection = _selection(repo, candidate_path, validation_path)
    _write_selection(selection_path, selection)

    source = SimpleNamespace(
        record={
            "source_id": "fixture-source",
            "work_id": "fixture-work",
        },
        sha256="1" * 64,
    )

    real_candidate_load = release_module.CandidatePackage.load
    candidate = real_candidate_load(candidate_path)
    calls: list[tuple[str, object]] = []

    def load_source(path: Path, *, repository_root: Path) -> object:
        calls.append(("source", (Path(path), Path(repository_root))))
        return source

    def load_candidate(path: Path) -> object:
        calls.append(("candidate", Path(path)))
        return real_candidate_load(path)

    def accepted_decision(manifest_path: Path, **kwargs: object) -> dict[str, object]:
        calls.append(("decision", (Path(manifest_path), kwargs)))
        return {
            "path": "sources/fixture--fixture-work.decision.json",
            "sha256": "3" * 64,
            "candidate_sha256": candidate.sha256,
            "validation_sha256": "4" * 64,
            "disposition": "accepted",
        }

    monkeypatch.setattr(release_module.SourceManifest, "load", load_source)
    monkeypatch.setattr(release_module.CandidatePackage, "load", load_candidate)
    monkeypatch.setattr(release_module, "catalog_decision", accepted_decision)
    monkeypatch.setattr(release_module, "repository_revision", lambda root: "a" * 40)
    return {
        "repo": repo,
        "source_path": source_path,
        "candidate_path": candidate_path,
        "validation_path": validation_path,
        "selection_path": selection_path,
        "selection": selection,
        "source": source,
        "candidate": candidate,
        "calls": calls,
        "accepted_decision": accepted_decision,
    }


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_accepted_selection_builds_exact_deterministic_release(
    release_context: dict[str, object], tmp_path: Path
) -> None:
    repo = release_context["repo"]
    selection_path = release_context["selection_path"]
    assert isinstance(repo, Path) and isinstance(selection_path, Path)
    first = tmp_path / "release-one"
    second = tmp_path / "release-two"

    manifest = build_release(selection_path, first, repository_root=repo)
    build_release(selection_path, second, repository_root=repo)

    expected = {
        "README.md",
        "release-manifest.json",
        "tei/fixture-work.fixture-rendering.tei.xml",
        "data/fixture-work.fixture-rendering.jsonl",
        "receipts/fixture-work.fixture-rendering.jsonl.loss.json",
    }
    assert set(_tree(first)) == expected
    assert _tree(first) == _tree(second)
    assert (first / "tei/fixture-work.fixture-rendering.tei.xml").read_bytes() == TEI_BYTES
    records = [
        json.loads(line)
        for line in (first / "data/fixture-work.fixture-rendering.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert records and {record["language"] for record in records} == {"en"}
    assert {record["source"]["license"] for record in records} == {"cc0-1.0"}
    card = (first / "README.md").read_text(encoding="utf-8")
    assert "license: \"cc0-1.0\"" in card
    assert "Fixture attribution" in card
    serialized_manifest = (first / "release-manifest.json").read_text(encoding="utf-8")
    assert str(release_context["candidate_path"]) not in serialized_manifest
    assert str(release_context["validation_path"]) not in serialized_manifest
    assert manifest["repository_revision"] == "a" * 40
    assert manifest["tooling"]["tei_version"] == "4.11.0"
    assert manifest["items"][0]["receipt"]["check"] == {
        "status": "pass",
        "errors": [],
    }
    call_names = [name for name, _ in release_context["calls"]]
    assert call_names.count("source") == 2
    assert call_names.count("candidate") == 2
    assert call_names.count("decision") == 2


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda value: value.update(contract="wrong"), "contract"),
        (lambda value: value.update(extra=True), "unknown"),
        (lambda value: value.update(release_timestamp="2026-08-30"), "timestamp"),
        (
            lambda value: value["publication"].update(attribution_reviewed=False),
            "attribution_reviewed",
        ),
        (lambda value: value.update(items=[]), "nonempty"),
        (lambda value: value["items"][0].update(work_id="unsafe/id"), "identifier"),
    ],
)
def test_selection_contract_fails_closed(
    release_context: dict[str, object],
    tmp_path: Path,
    mutation: object,
    match: str,
) -> None:
    selection = json.loads(json.dumps(release_context["selection"]))
    mutation(selection)
    selection_path = tmp_path / f"invalid-{match}.json"
    _write_selection(selection_path, selection)
    with pytest.raises(ValueError, match=match):
        build_release(selection_path, tmp_path / f"out-{match}", repository_root=release_context["repo"])


def test_duplicate_json_keys_are_rejected(
    release_context: dict[str, object], tmp_path: Path
) -> None:
    path = tmp_path / "duplicate-key.json"
    path.write_text('{"contract":"a","contract":"b"}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        build_release(path, tmp_path / "out", repository_root=release_context["repo"])


def test_duplicate_item_identity_is_rejected(
    release_context: dict[str, object], tmp_path: Path
) -> None:
    selection = json.loads(json.dumps(release_context["selection"]))
    selection["items"].append(dict(selection["items"][0]))
    path = tmp_path / "duplicate-item.json"
    _write_selection(path, selection)
    with pytest.raises(ValueError, match="duplicate work_id/rendering_id"):
        build_release(path, tmp_path / "out", repository_root=release_context["repo"])


def test_case_variant_output_identity_is_rejected_before_collision(
    release_context: dict[str, object], tmp_path: Path
) -> None:
    selection = json.loads(json.dumps(release_context["selection"]))
    variant = dict(selection["items"][0])
    variant["work_id"] = "Fixture-work"
    selection["items"].append(variant)
    path = tmp_path / "case-variant.json"
    _write_selection(path, selection)
    with pytest.raises(ValueError, match="lowercase safe identifier"):
        build_release(path, tmp_path / "out", repository_root=release_context["repo"])


@pytest.mark.parametrize(
    ("field", "value"),
    [("language", "la"), ("license_id", "cc-by-4.0")],
)
def test_v1_profile_rejects_other_language_or_license(
    release_context: dict[str, object], tmp_path: Path, field: str, value: str
) -> None:
    selection = json.loads(json.dumps(release_context["selection"]))
    selection[field] = value
    path = tmp_path / f"profile-{field}.json"
    _write_selection(path, selection)
    with pytest.raises(ValueError, match="requires language en and license_id cc0-1.0"):
        build_release(path, tmp_path / "out", repository_root=release_context["repo"])


def test_source_manifest_escape_is_rejected(
    release_context: dict[str, object], tmp_path: Path
) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    selection = json.loads(json.dumps(release_context["selection"]))
    selection["items"][0]["source_manifest_path"] = "../outside.json"
    path = tmp_path / "escape.json"
    _write_selection(path, selection)
    with pytest.raises(ValueError, match="escapes repository root"):
        build_release(path, tmp_path / "out", repository_root=release_context["repo"])


def test_destination_must_be_fresh_and_outside_repository(
    release_context: dict[str, object], tmp_path: Path
) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="must not exist"):
        build_release(
            release_context["selection_path"], existing, repository_root=release_context["repo"]
        )
    with pytest.raises(ValueError, match="outside repository root"):
        build_release(
            release_context["selection_path"],
            release_context["repo"] / "release",
            repository_root=release_context["repo"],
        )


def test_destination_rejects_lexical_and_resolved_protected_roots(
    release_context: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = release_context["repo"]
    reports = repo / "reports"
    reports.mkdir()
    with pytest.raises(ValueError, match="lexically outside repository root"):
        build_release(
            release_context["selection_path"],
            reports / "release",
            repository_root=repo,
        )

    resolved_reports = tmp_path / "resolved-reports"
    resolved_reports.mkdir()
    monkeypatch.setattr(
        release_module,
        "_protected_resolved_roots",
        lambda root: (resolved_reports.resolve(strict=True),),
    )
    with pytest.raises(ValueError, match="protected canonical storage"):
        build_release(
            release_context["selection_path"],
            resolved_reports / "release",
            repository_root=repo,
        )


def test_evidence_paths_must_be_absolute_and_not_overlap_destination(
    release_context: dict[str, object], tmp_path: Path
) -> None:
    selection = json.loads(json.dumps(release_context["selection"]))
    selection["items"][0]["candidate_path"] = "relative-candidate"
    relative_path = tmp_path / "relative-evidence.json"
    _write_selection(relative_path, selection)
    with pytest.raises(ValueError, match="candidate_path must be an absolute path"):
        build_release(
            relative_path, tmp_path / "out-relative", repository_root=release_context["repo"]
        )

    with pytest.raises(ValueError, match="paths overlap"):
        build_release(
            release_context["selection_path"],
            release_context["candidate_path"] / "release",
            repository_root=release_context["repo"],
        )


@pytest.mark.parametrize("manifest_work_id", [None, ["fixture-work"], "other-work"])
def test_source_manifest_requires_exact_scalar_work_id(
    release_context: dict[str, object],
    tmp_path: Path,
    manifest_work_id: object,
) -> None:
    source = release_context["source"]
    source.record["work_id"] = manifest_work_id
    with pytest.raises(ValueError, match="exact selected scalar work_id"):
        build_release(
            release_context["selection_path"],
            tmp_path / "out",
            repository_root=release_context["repo"],
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("source_id", "other-source"), ("work_id", "other-work"), ("rendering_id", "other-rendering")],
)
def test_candidate_identity_mismatch_is_rejected(
    release_context: dict[str, object], tmp_path: Path, field: str, value: str
) -> None:
    manifest_path = release_context["candidate_path"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = value
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(ValueError, match="candidate"):
        build_release(
            release_context["selection_path"],
            tmp_path / "out",
            repository_root=release_context["repo"],
        )


def test_captured_tei_bytes_must_match_candidate_member_binding(
    release_context: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = release_module.CandidatePackage.member_bytes

    def drift_after_integrity_check(candidate: object, name: str) -> bytes:
        return original(candidate, name) + b"drift"

    monkeypatch.setattr(
        release_module.CandidatePackage, "member_bytes", drift_after_integrity_check
    )
    with pytest.raises(ValueError, match="captured content.tei.xml bytes"):
        build_release(
            release_context["selection_path"],
            tmp_path / "out",
            repository_root=release_context["repo"],
        )


@pytest.mark.parametrize("decision", [None, {"disposition": "rejected"}, {"disposition": "needs-correction"}])
def test_nonaccepted_decision_is_rejected_and_destination_absent(
    release_context: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    decision: object,
) -> None:
    monkeypatch.setattr(release_module, "catalog_decision", lambda *args, **kwargs: decision)
    destination = tmp_path / "out"
    with pytest.raises(ValueError, match="verified accepted decision"):
        build_release(
            release_context["selection_path"], destination, repository_root=release_context["repo"]
        )
    assert not destination.exists()


@pytest.mark.parametrize("failure", ["projector", "receipt"])
def test_projection_or_receipt_failure_cleans_temporary_release(
    release_context: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    destination = tmp_path / f"failed-{failure}"
    if failure == "projector":
        monkeypatch.setattr(
            release_module,
            "project_file",
            lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("projector failed")),
        )
        match = "projector failed"
    else:
        monkeypatch.setattr(release_module, "check_receipt", lambda *args, **kwargs: ["bad receipt"])
        match = "loss receipt check failed"
    with pytest.raises(ValueError, match=match):
        build_release(
            release_context["selection_path"], destination, repository_root=release_context["repo"]
        )
    assert not destination.exists()
    assert not list(tmp_path.glob(f".{destination.name}.tmp-*"))


def test_late_destination_creation_is_not_overwritten(
    release_context: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "late-destination"
    real_check = release_module.check_receipt

    def check_then_create_destination(*args: object, **kwargs: object) -> list[str]:
        errors = real_check(*args, **kwargs)
        destination.mkdir()
        (destination / "owner.txt").write_text("preserve me\n", encoding="utf-8")
        return errors

    monkeypatch.setattr(release_module, "check_receipt", check_then_create_destination)
    with pytest.raises(ValueError, match="destination appeared during assembly"):
        build_release(
            release_context["selection_path"],
            destination,
            repository_root=release_context["repo"],
        )
    assert (destination / "owner.txt").read_text(encoding="utf-8") == "preserve me\n"
    assert not list(tmp_path.glob(f".{destination.name}.tmp-*"))
