from __future__ import annotations

from collections.abc import Iterator
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pytest

from build.tools.pre_commit_pytest import _pytest_temp_parent
from build.tei.fisher_marrow_decision import (
    DECISION_CONTRACT,
    FISHER_SOURCE_ID,
    FISHER_WORK_ID,
    catalog_decision,
    decision_path,
    decision_record,
    load_verified_review,
    load_decision,
    retained_member_census,
    serialize_decision,
    validate_decision,
)
from ocd_kernel.reconstruction.contract import SourceManifest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.xdist_group(name="fisher-marrow-decision")
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/puritan-fisher-marrow-of-modern-divinity.source-manifest.json'
RUNNER = ROOT / "build" / "tools" / "reconstruct_candidate.py"
_MANIFEST_RELATIVE = Path('tests/fixtures/reconstruction-runtime/puritan-fisher-marrow-of-modern-divinity.source-manifest.json')
_FISHER_REPOSITORY_FILES = (
    _MANIFEST_RELATIVE,
    Path("sources/structured-text/fisher-marrow-of-modern-divinity/fisher-marrow.reconstruction-profile.json"),
    Path("sources/structured-text/fisher-marrow-of-modern-divinity/fisher-marrow.validation-policy.json"),
    Path("sources/structured-text/fisher-marrow-of-modern-divinity/fisher-marrow.source-accountability.schema.json"),
    Path("raw/internet-archive/fisher-marrow/marrowmoderndiv00bostgoog_djvu.txt"),
    Path("build/__init__.py"),
    Path("build/tei/__init__.py"),
    Path("build/tei/fisher_marrow_reconstruction.py"),
    Path("build/tei/fisher_marrow_oracle.py"),
    Path("ocd_kernel/__init__.py"),
    Path("ocd_kernel/lib/__init__.py"),
    Path("ocd_kernel/lib/path_io.py"),
    Path("ocd_kernel/lib/storage_topology.py"),
    Path("ocd_kernel/reconstruction/__init__.py"),
    Path("ocd_kernel/reconstruction/contract.py"),
    Path("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"),
    Path("ocd_kernel/tei/__init__.py"),
    Path("ocd_kernel/tei/normalization.py"),
    Path("ocd_kernel/tei/projection_profile.py"),
    Path("ocd_kernel/tei/validate.py"),
    Path("ocd_kernel/tei/vendor/xsd/tei_all.xsd"),
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


@pytest.fixture(scope="module")
def fisher_evidence(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("fisher-e")
    destination = root / "generated"
    subprocess.run(
        [
            sys.executable,
            "-B",
            str(RUNNER),
            "--manifest",
            str(_MANIFEST_RELATIVE),
            "--destination",
            str(destination),
            "--repository-root",
            str(ROOT),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return destination


def _copy_fisher_repository(root: Path, fisher_evidence: Path) -> dict[str, Path]:
    repository = root / "r"
    for relative in _FISHER_REPOSITORY_FILES:
        source = ROOT / relative
        destination = repository / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    evidence = root / "e"
    shutil.copytree(fisher_evidence / "package", evidence / "package")
    shutil.copy2(fisher_evidence / "validation.json", evidence / "validation.json")
    shutil.copy2(fisher_evidence / "text-quality.json", evidence / "text-quality.json")
    manifest_path = repository / _MANIFEST_RELATIVE
    return {
        "root": root,
        "repository": repository,
        "manifest_path": manifest_path,
        "candidate_path": evidence / "package",
        "validation_path": evidence / "validation.json",
        "decision_path": decision_path(manifest_path),
    }


@pytest.fixture(scope="module")
def fisher_context(
    fisher_evidence: Path,
) -> Iterator[dict[str, Path | SourceManifest | object]]:
    short_root = Path(tempfile.mkdtemp(prefix="fm-", dir=_pytest_temp_parent()))
    try:
        context = _copy_fisher_repository(short_root, fisher_evidence)
        manifest = SourceManifest.load(
            context["manifest_path"], repository_root=context["repository"]
        )
        review = load_verified_review(
            manifest,
            candidate_path=context["candidate_path"],
            validation_path=context["validation_path"],
        )
        record = decision_record(
            manifest,
            review,
            disposition="accepted",
            rationale="The designated human reviewed the exact candidate and independent validation evidence.",
            decided_by="project-maintainer",
            decided_at="2026-08-27T00:00:00Z",
        )
        decision_file = Path(context["decision_path"])
        decision_file.parent.mkdir(parents=True, exist_ok=True)
        decision_file.write_bytes(serialize_decision(record))
        context["decision_path"] = decision_file
        context["manifest"] = manifest
        context["review"] = review
        yield context
    finally:
        shutil.rmtree(short_root)


@pytest.fixture
def fisher_case_root() -> Iterator[Path]:
    short_root = Path(tempfile.mkdtemp(prefix="fc-", dir=_pytest_temp_parent()))
    try:
        yield short_root
    finally:
        shutil.rmtree(short_root)


def _clone_fisher_context(
    root: Path,
    context: dict[str, Path | SourceManifest | object],
) -> dict[str, Path]:
    repository = root / "r"
    evidence = root / "e"
    shutil.copytree(context["repository"], repository)
    shutil.copytree(context["candidate_path"].parent, evidence)
    manifest_path = repository / _MANIFEST_RELATIVE
    return {
        "root": root,
        "repository": repository,
        "manifest_path": manifest_path,
        "candidate_path": evidence / "package",
        "validation_path": evidence / "validation.json",
        "decision_path": decision_path(manifest_path),
    }


@pytest.fixture(scope="module")
def fisher_manifest() -> SourceManifest:
    return SourceManifest.load(MANIFEST, repository_root=ROOT)


def test_retained_member_census_is_exact_and_reasoned(
    fisher_manifest: SourceManifest,
) -> None:
    census = retained_member_census(fisher_manifest)

    assert census["contract"] == "ocd-fisher-marrow-member-census-v1"
    assert census["source_id"] == FISHER_SOURCE_ID
    assert census["work_id"] == FISHER_WORK_ID
    assert census["counts"] == {"included": 1, "excluded": 8, "total": 9}
    assert [item["path"] for item in census["included"]] == [
        "raw/internet-archive/fisher-marrow/marrowmoderndiv00bostgoog_djvu.txt"
    ]
    assert all(item["reason"].strip() for item in census["included"])
    assert [item["path"] for item in census["excluded"]] == sorted(
        item["path"] for item in census["excluded"]
    )
    assert all(item["reason"].strip() for item in census["excluded"])
    assert len({item["path"] for item in census["included"] + census["excluded"]}) == 9


def test_decision_contract_binds_work_source_candidate_and_validation(
    fisher_context: dict[str, Path | SourceManifest | object],
) -> None:
    fisher_manifest = fisher_context["manifest"]
    review = fisher_context["review"]
    record = decision_record(
        fisher_manifest,
        review,
        disposition="accepted",
        rationale="The designated human reviewed the exact candidate and independent validation evidence.",
        decided_by="project-maintainer",
        decided_at="2026-08-27T00:00:00Z",
    )

    assert record["contract"] == DECISION_CONTRACT
    assert record["source_id"] == FISHER_SOURCE_ID
    assert record["work_id"] == FISHER_WORK_ID
    assert record["source_manifest_sha256"] == fisher_manifest.sha256
    assert record["candidate_sha256"] == review.candidate_sha256
    assert record["validation_sha256"] == review.validation.sha256
    assert validate_decision(record, fisher_manifest) == record
    assert serialize_decision(record).endswith(b"\n")
    decoded = json.loads(serialize_decision(record))
    assert serialize_decision(decoded) == serialize_decision(record)


def test_decision_record_rejects_unverified_digest_arguments(
    fisher_manifest: SourceManifest,
) -> None:
    with pytest.raises(TypeError):
        decision_record(
            fisher_manifest,
            candidate_sha256="a" * 64,
            validation_sha256="b" * 64,
            disposition="accepted",
            rationale="Unverified digest syntax is not a review.",
            decided_by="project-maintainer",
            decided_at="2026-08-27T00:00:00Z",
        )


def test_fisher_decision_rejects_unstructured_blocked_disposition(
    fisher_context: dict[str, Path | SourceManifest | object],
) -> None:
    with pytest.raises(ValueError, match="disposition is not supported"):
        decision_record(
            fisher_context["manifest"],
            fisher_context["review"],
            disposition="blocked",
            rationale="An unstructured rationale is not technical blocker evidence.",
            decided_by="project-maintainer",
            decided_at="2026-08-27T00:00:00Z",
        )


@pytest.mark.parametrize(
    "mutation",
    ["source", "candidate", "validation", "disposition", "decider"],
)
def test_decision_mutations_fail_closed(
    fisher_context: dict[str, Path | SourceManifest | object],
    mutation: str,
) -> None:
    fisher_manifest = fisher_context["manifest"]
    review = fisher_context["review"]
    record = decision_record(
        fisher_manifest,
        review,
        disposition="accepted",
        rationale="The designated human reviewed the exact candidate and independent validation evidence.",
        decided_by="project-maintainer",
        decided_at="2026-08-27T00:00:00Z",
    )
    changed = copy.deepcopy(record)
    if mutation == "source":
        changed["source_manifest_sha256"] = "c" * 64
    elif mutation == "candidate":
        changed["candidate_sha256"] = "c" * 64
    elif mutation == "validation":
        changed["validation_sha256"] = "c" * 64
    elif mutation == "disposition":
        changed["disposition"] = "machine-approved"
    else:
        changed["decided_by"] = ""

    with pytest.raises(ValueError):
        validate_decision(
            changed,
            fisher_manifest,
            candidate_sha256=review.candidate_sha256,
            validation_sha256=review.validation.sha256,
        )


def test_decision_path_is_source_local_and_loader_is_read_only(
    fisher_manifest: SourceManifest,
) -> None:
    expected = MANIFEST.parent / (
        f"{FISHER_SOURCE_ID}--{FISHER_WORK_ID}.decision.json"
    )
    assert decision_path(MANIFEST) == expected

    with pytest.raises(ValueError, match="source-local"):
        load_decision(MANIFEST, fisher_manifest)


def test_catalog_loads_only_a_bound_source_local_decision(
    fisher_context: dict[str, Path | SourceManifest | object],
) -> None:
    observed = catalog_decision(
        fisher_context["manifest_path"],
        repository_root=fisher_context["repository"],
        work_id=FISHER_WORK_ID,
        candidate_path=fisher_context["candidate_path"],
        validation_path=fisher_context["validation_path"],
    )

    decision_file = fisher_context["decision_path"]
    assert observed == {
        "path": decision_file.relative_to(fisher_context["repository"]).as_posix(),
        "sha256": _sha(decision_file.read_bytes()),
        "candidate_sha256": fisher_context["review"].candidate_sha256,
        "validation_sha256": fisher_context["review"].validation.sha256,
        "disposition": "accepted",
    }


def test_external_decision_path_is_rejected(
    fisher_context: dict[str, Path | SourceManifest | object],
) -> None:
    manifest = fisher_context["manifest"]
    external = fisher_context["root"] / "outside.decision.json"
    external.write_bytes(fisher_context["decision_path"].read_bytes())

    with pytest.raises(ValueError, match="source-local"):
        load_decision(external, manifest)


@pytest.mark.parametrize(
    "mutation",
    [
        "candidate_missing",
        "candidate_stale",
        "validation_missing",
        "validation_stale",
        "source_manifest",
        "decision",
    ],
)
def test_catalog_evidence_mutations_fail_closed(
    fisher_case_root: Path,
    fisher_context: dict[str, Path | SourceManifest | object],
    mutation: str,
) -> None:
    case = _clone_fisher_context(fisher_case_root, fisher_context)
    if mutation == "candidate_missing":
        case["candidate_path"] = case["root"] / "missing-package"
    elif mutation == "candidate_stale":
        stale = case["root"] / "stale-package"
        shutil.copytree(case["candidate_path"], stale)
        stale_content = (stale / "content.tei.xml").read_bytes() + b" "
        (stale / "content.tei.xml").write_bytes(stale_content)
        case["candidate_path"] = stale
    elif mutation == "validation_missing":
        case["validation_path"] = case["root"] / "missing-validation.json"
    elif mutation == "validation_stale":
        validation_path = case["validation_path"]
        validation = json.loads(validation_path.read_bytes())
        validation["candidate_sha256"] = "c" * 64
        report_record = {
            key: value for key, value in validation.items() if key != "report_sha256"
        }
        validation["report_sha256"] = _sha(_canonical(report_record))
        validation_path.write_bytes(_canonical(validation))
    elif mutation == "source_manifest":
        manifest_path = case["manifest_path"]
        manifest = json.loads(manifest_path.read_bytes())
        manifest["test_mutation"] = "stale-source-manifest"
        manifest_path.write_bytes(_canonical(manifest))
    else:
        decision = json.loads(case["decision_path"].read_bytes())
        decision["candidate_sha256"] = "c" * 64
        case["decision_path"].write_bytes(_canonical(decision))

    with pytest.raises(ValueError):
        catalog_decision(
            case["manifest_path"],
            repository_root=case["repository"],
            work_id=FISHER_WORK_ID,
            candidate_path=case["candidate_path"],
            validation_path=case["validation_path"],
        )


def _empty_fisher_work() -> dict[str, object]:
    return {
        "work_id": FISHER_WORK_ID,
        "reconstruction_state": {
            "retained_source": "not_assessed",
            "tei_candidate": "not_started",
            "validation": "not_run",
            "human_review": "not_started",
            "publication": "not_ready",
            "routes": [],
        },
    }


def test_work_catalog_derives_human_review_state_from_verified_decision(
    fisher_context: dict[str, Path | SourceManifest | object],
) -> None:
    import build.tools.count_dataset_records as catalog_module

    work = _empty_fisher_work()
    manifest = json.loads(fisher_context["manifest_path"].read_bytes())
    catalog_module._attach_reconstruction_route(
        work,
        manifest,
        fisher_context["manifest_path"],
        fisher_context["repository"] / "sources",
        association="source_hash",
        scope="work",
        verified=True,
        blocker=None,
        candidate_path=fisher_context["candidate_path"],
        validation_path=fisher_context["validation_path"],
    )

    state = work["reconstruction_state"]
    assert state["human_review"] == "accepted"
    assert state["publication"] == "not_ready"
    assert state["routes"][0]["decision"]["disposition"] == "accepted"


def test_work_catalog_requires_explicit_evidence_for_existing_decision(
    fisher_context: dict[str, Path | SourceManifest | object],
) -> None:
    import build.tools.count_dataset_records as catalog_module

    work = _empty_fisher_work()
    manifest = json.loads(fisher_context["manifest_path"].read_bytes())
    catalog_module._attach_reconstruction_route(
        work,
        manifest,
        fisher_context["manifest_path"],
        fisher_context["repository"] / "sources",
        association="source_hash",
        scope="work",
        verified=True,
        blocker=None,
    )

    state = work["reconstruction_state"]
    assert state["human_review"] == "blocked"
    assert state["publication"] == "not_ready"
    assert "explicit candidate and validation evidence" in state["routes"][0]["blocker"]
