"""Exercise staging with real contract handles and synthetic retained evidence."""

import importlib.util
import json
from pathlib import Path

import pytest

from cvw_app import stage_candidate as staging
from cvw_app.review_contract import _load_validation_report
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


@pytest.fixture
def packet(tmp_path):
    # Reuse the runner's synthetic fixture, never a production source/candidate.
    fixture_path = (
        Path(__file__).resolve().parents[2] / "tests/test_reconstruct_candidate.py"
    )
    spec = importlib.util.spec_from_file_location("staging_fixture", fixture_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    repo = module._synthetic_repository(tmp_path)
    built = tmp_path / "built"
    module.RUNNER_MODULE.run(
        manifest=module.MANIFEST, destination=str(built), repository_root=str(repo)
    )
    return dict(
        package=built / "package",
        validation=built / "validation.json",
        repository_root=repo,
        destination=tmp_path / "staged",
    )


def snapshot(root):
    return {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }


def test_exact_copy_reuses_record_without_running_producer_or_validator(
    packet, monkeypatch
):
    from ocd_kernel.reconstruction import contract

    def forbidden(*args, **kwargs):
        pytest.fail("staging must not reconstruct or validate anew")

    monkeypatch.setattr(contract, "reconstruct", forbidden)
    monkeypatch.setattr(contract, "validate", forbidden)
    before = snapshot(packet["repository_root"]), snapshot(packet["package"].parent)
    result = staging.stage_candidate(**packet)
    dest = packet["destination"]
    assert {p.name for p in dest.iterdir()} == {"package", "validation.json", "text-quality.json"}
    assert snapshot(dest) == before[1]
    assert (
        snapshot(packet["repository_root"]),
        snapshot(packet["package"].parent),
    ) == before
    candidate = CandidatePackage.load(dest / "package")
    source = SourceManifest.load(
        packet["repository_root"] / candidate.manifest["source_manifest"]["path"],
        repository_root=packet["repository_root"],
    )
    assert (
        _load_validation_report(dest, source, candidate).sha256
        == result["validation_report_sha256"]
    )


@pytest.mark.parametrize(
    "attack",
    [
        "member",
        "extra",
        "source",
        "manifest",
        "missing-record",
        "summary",
        "report-digest",
        "candidate-binding",
        "failed",
        "accepted",
        "source-id",
        "source-digest",
        "text-tampered",
        "text-missing",
        "text-unbound",
        "text-wrong-candidate",
        "text-wrong-input",
    ],
)
def test_mismatch_never_publishes_or_changes_inputs(packet, attack):
    if attack.startswith("text-"):
        import hashlib
        from cvw_app.review_contract import _canonical_json_bytes

        path = packet["validation"].with_name("text-quality.json")
        record = json.loads(packet["validation"].read_bytes())
        if attack == "text-tampered":
            path.write_bytes(path.read_bytes() + b" ")
        elif attack == "text-missing":
            path.unlink()
        elif attack == "text-unbound":
            record.pop("text_quality_sha256")
        else:
            text = json.loads(path.read_bytes())
            if attack == "text-wrong-candidate":
                text["candidate_sha256"] = "0" * 64
            else:
                text["inputs"][0]["sha256"] = "0" * 64
            path.write_bytes(_canonical_json_bytes(text))
            record["text_quality_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        packet["validation"].write_bytes(_canonical_json_bytes(record))
    elif attack == "member":
        (packet["package"] / "content.tei.xml").write_bytes(b"changed")
    elif attack == "extra":
        (packet["package"] / "extra").write_bytes(b"extra")
    elif attack == "source":
        (packet["repository_root"] / "sources/synthetic/source.txt").write_bytes(
            b"changed"
        )
    elif attack == "manifest":
        path = (
            packet["repository_root"]
            / "sources/synthetic/synthetic.source-manifest.json"
        )
        path.write_bytes(path.read_bytes() + b" ")
    elif attack == "missing-record":
        packet["validation"] = packet["validation"].with_name("absent.json")
    elif attack == "summary":
        packet["validation"].write_text('{"status":"pass"}', encoding="utf-8")
    elif attack in {"accepted", "source-id", "source-digest"}:
        path = packet["package"] / "manifest.json"
        record = json.loads(path.read_bytes())
        if attack == "accepted":
            record["status"] = "accepted"
        elif attack == "source-id":
            record["source_id"] = "another-source"
        else:
            record["source_manifest"]["sha256"] = "0" * 64
        path.write_text(json.dumps(record), encoding="utf-8")
    else:
        record = json.loads(packet["validation"].read_bytes())
        if attack == "report-digest":
            record["report_sha256"] = "0" * 64
        else:
            from cvw_app.review_contract import _canonical_json_bytes
            import hashlib

            record.pop("report_sha256")
            record[
                "candidate_sha256" if attack == "candidate-binding" else "status"
            ] = "0" * 64 if attack == "candidate-binding" else "fail"
            record["report_sha256"] = hashlib.sha256(
                _canonical_json_bytes(record)
            ).hexdigest()
        packet["validation"].write_bytes(
            staging.json.dumps(
                record, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ).encode()
            + b"\n"
        )
    before = snapshot(packet["package"].parent), snapshot(packet["repository_root"])
    with pytest.raises((ValueError, OSError)):
        staging.stage_candidate(**packet)
    assert not packet["destination"].exists()
    assert not list(packet["destination"].parent.glob(".staged.staging-*"))
    assert (
        snapshot(packet["package"].parent),
        snapshot(packet["repository_root"]),
    ) == before


@pytest.mark.parametrize("location", ["repository", "input", "existing"])
def test_destination_boundaries(packet, location):
    if location == "repository":
        packet["destination"] = packet["repository_root"] / "output"
    elif location == "input":
        packet["destination"] = packet["package"] / "output"
    else:
        packet["destination"].mkdir()
    with pytest.raises(ValueError):
        staging.stage_candidate(**packet)


def test_validation_changes_during_copy_are_rejected(packet, monkeypatch):
    original = staging._load_validation_report

    def change(*args, **kwargs):
        report = original(*args, **kwargs)
        packet["validation"].write_bytes(b"changed concurrently")
        return report

    monkeypatch.setattr(staging, "_load_validation_report", change)
    with pytest.raises(ValueError, match="changed during staging"):
        staging.stage_candidate(**packet)
    assert not packet["destination"].exists()


def test_historical_candidate_without_text_screen_remains_supported(packet):
    from cvw_app.review_contract import _canonical_json_bytes

    record = json.loads(packet["validation"].read_bytes())
    record.pop("text_quality_sha256")
    packet["validation"].write_bytes(_canonical_json_bytes(record))
    packet["validation"].with_name("text-quality.json").unlink()
    staging.stage_candidate(**packet)
    assert {p.name for p in packet["destination"].iterdir()} == {"package", "validation.json"}


def test_text_quality_changes_during_copy_are_rejected(packet, monkeypatch):
    original = staging._load_validation_report

    def change(*args, **kwargs):
        report = original(*args, **kwargs)
        packet["validation"].with_name("text-quality.json").write_bytes(b"changed concurrently")
        return report

    monkeypatch.setattr(staging, "_load_validation_report", change)
    with pytest.raises(ValueError, match="text-quality record changed"):
        staging.stage_candidate(**packet)
    assert not packet["destination"].exists()


def test_loader_rejects_text_quality_reparse_point(packet, monkeypatch):
    from cvw_app import review_contract

    target = packet["validation"].with_name("text-quality.json")
    original = review_contract._is_reparse_point
    monkeypatch.setattr(review_contract, "_is_reparse_point", lambda path: path == target or original(path))
    candidate = CandidatePackage.load(packet["package"])
    source = SourceManifest.load(packet["repository_root"] / candidate.manifest["source_manifest"]["path"], repository_root=packet["repository_root"])
    with pytest.raises(ValueError, match="text-quality report must not be a reparse point"):
        review_contract._load_validation_report(packet["package"].parent, source, candidate)


@pytest.mark.parametrize("member", ["package", "validation", "content.tei.xml", "text-quality.json"])
def test_reparse_inputs_rejected_before_copy(packet, monkeypatch, member):
    target = packet[member] if member in packet else (packet["package"].parent if member == "text-quality.json" else packet["package"]) / member
    original = staging._is_reparse_point
    monkeypatch.setattr(
        staging, "_is_reparse_point", lambda path: path == target or original(path)
    )
    with pytest.raises(ValueError, match="ordinary"):
        staging.stage_candidate(**packet)
    assert not packet["destination"].exists()


def test_late_destination_is_preserved(packet, monkeypatch):
    original = staging._load_validation_report

    def appear(*args, **kwargs):
        report = original(*args, **kwargs)
        packet["destination"].mkdir()
        (packet["destination"] / "owner.txt").write_bytes(b"owner data")
        return report

    monkeypatch.setattr(staging, "_load_validation_report", appear)
    with pytest.raises(ValueError, match="appeared"):
        staging.stage_candidate(**packet)
    assert snapshot(packet["destination"]) == {"owner.txt": b"owner data"}
    assert not list(packet["destination"].parent.glob(".staged.staging-*"))
