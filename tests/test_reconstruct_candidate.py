from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "build/tools/reconstruct_candidate.py"
MANIFEST = "sources/synthetic/synthetic.source-manifest.json"
_CLOSURE = "a" * 64


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("_ocd_reconstruct_candidate_test", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER_MODULE = _load_runner_module()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8", newline="\n")
    else:
        path.write_bytes(content)


def _synthetic_repository(tmp_path: Path) -> Path:
    repo = tmp_path / "authority-repository"
    source = repo / "sources/synthetic/source.txt"
    profile = repo / "sources/synthetic/profile.json"
    policy = repo / "sources/synthetic/policy.json"
    xsd = repo / "sources/synthetic/tei.xsd"
    package_schema = repo / "sources/synthetic/candidate-package.schema.json"
    converter = repo / "build/tei/synthetic_converter.py"
    oracle = repo / "build/tei/synthetic_oracle.py"
    _write(source, "faithful retained text\n")
    _write(profile, "{}\n")
    _write(policy, "{}\n")
    _write(xsd, "<schema/>\n")
    package_schema.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        ROOT / "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
        package_schema,
    )
    _write(
        converter,
        '''from __future__ import annotations
import json

CONVERTER_ID = "synthetic-converter"
CONVERTER_VERSION = "1"

def _convert(source_manifest):
    source = source_manifest.authority_path("source").read_bytes()
    accountability = {"source_sha256": __import__("hashlib").sha256(source).hexdigest()}
    return {
        "README.source.md": b"# Synthetic candidate\\n\\nNonaccepted; human review required.\\n",
        "content.tei.xml": b"<TEI xmlns=\\"http://www.tei-c.org/ns/1.0\\"><text><body><p>faithful retained text</p></body></text></TEI>\\n",
        "provenance.json": json.dumps({"status":"nonaccepted"}, separators=(",",":"), sort_keys=True).encode()+b"\\n",
        "source-accountability.json": json.dumps(accountability, separators=(",",":"), sort_keys=True).encode()+b"\\n",
        "unresolved.jsonl": b"",
    }

_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
''',
    )
    _write(
        oracle,
        f'''from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import platform
import sys

ORACLE_ID = "synthetic-oracle"
ORACLE_VERSION = "1"
CLOSURE = "{_CLOSURE}"

def _canonical(value):
    return (json.dumps(value, ensure_ascii=False, separators=(",",":"), sort_keys=True)+"\\n").encode()

def _sha(content):
    return hashlib.sha256(content).hexdigest()

def _oracle(source_manifest, candidate):
    result = {{
        "status":os.environ.get("OCD_TEST_VALIDATION_STATUS", "pass"),
        "oracle_id":ORACLE_ID,
        "oracle_version":ORACLE_VERSION,
        "implementation_sha256":_sha(Path(__file__).read_bytes()),
        "import_closure_sha256":CLOSURE,
        "runtime":f"{{platform.python_implementation()}} {{platform.python_version()}} ({{Path(sys.executable).resolve(strict=True)}})",
        "source_manifest_sha256":source_manifest.sha256,
        "candidate_sha256":candidate.sha256,
        "profile_sha256":_sha(source_manifest.authority_path("profile").read_bytes()),
        "package_schema_sha256":_sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256":_sha(source_manifest.authority_path("source").read_bytes()),
        "xsd_sha256":_sha(source_manifest.authority_path("xsd").read_bytes()),
        "policy_sha256":_sha(source_manifest.authority_path("policy").read_bytes()),
        "findings":[],
    }}
    result["result_sha256"] = _sha(_canonical(result))
    return result

_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
''',
    )
    authorities = [
        ("source", "primary-source", source),
        ("profile", "complete-source-feature-profile", profile),
        ("policy", "independent-validation-policy", policy),
        ("xsd", "tei-validation-schema", xsd),
        ("candidate-package-schema", "candidate-package-schema", package_schema),
    ]
    record = {
        "contract": "ocd-source-manifest-v1",
        "source_id": "synthetic-retained-source",
        "authorities": [
            {
                "name": name,
                "role": role,
                "path": path.relative_to(repo).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha(path),
            }
            for name, role, path in authorities
        ],
        "converter": {
            "id": "synthetic-converter",
            "version": "1",
            "callable": "_convert",
            "implementation_path": converter.relative_to(repo).as_posix(),
            "implementation_sha256": _sha(converter),
        },
        "validator": {
            "id": "synthetic-oracle",
            "version": "1",
            "callable": "_oracle",
            "implementation_path": oracle.relative_to(repo).as_posix(),
            "implementation_sha256": _sha(oracle),
            "import_closure_sha256": _CLOSURE,
        },
        "package_schema": {
            "path": package_schema.relative_to(repo).as_posix(),
            "sha256": _sha(package_schema),
        },
    }
    manifest = repo / MANIFEST
    _write(manifest, json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
    return repo


def _run(repo: Path, destination: Path, *extra: str, env: dict[str, str] | None = None):
    return subprocess.run(
        [
            sys.executable,
            "-B",
            str(RUNNER),
            "--manifest",
            MANIFEST,
            "--destination",
            str(destination),
            "--repository-root",
            str(repo),
            *extra,
        ],
        cwd=repo.parent,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _manifest(repo: Path) -> dict[str, object]:
    return json.loads((repo / MANIFEST).read_text(encoding="utf-8"))


def _replace_manifest(repo: Path, record: dict[str, object]) -> None:
    _write(repo / MANIFEST, json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")


def test_successful_handoff_is_deterministic_and_explicitly_nonaccepted(tmp_path: Path) -> None:
    repo = _synthetic_repository(tmp_path)
    first = _run(repo, tmp_path / "candidate-a")
    second = _run(repo, tmp_path / "candidate-b")
    assert first.returncode == second.returncode == 0, first.stderr + second.stderr
    assert first.stdout == second.stdout
    summary = json.loads(first.stdout)
    assert summary["status"] == "pass"
    assert summary["acceptance_status"] == "nonaccepted"
    assert summary["human_review_required"] is True
    assert summary["publication_status"] == "not-authorized"
    assert summary["candidate"]["sha256"] == summary["digests"]["candidate"]
    assert summary["validation_report"]["sha256"] == summary["digests"]["validation_report"]
    assert summary["validation_report"]["path"] == "validation.json"
    assert first.stdout == json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    for name in ("candidate-a", "candidate-b"):
        candidate_dir = tmp_path / name
        assert {path.name for path in candidate_dir.iterdir()} == {
            "package",
            "validation.json",
            "text-quality.json",
        }
        package = candidate_dir / "package"
        assert {path.name for path in package.iterdir()} == {
            "README.source.md",
            "content.tei.xml",
            "manifest.json",
            "provenance.json",
            "source-accountability.json",
            "unresolved.jsonl",
        }
        assert json.loads((package / "manifest.json").read_bytes())["status"] == "nonaccepted"
        sidecar = candidate_dir / "validation.json"
        validation = json.loads(sidecar.read_bytes())
        assert validation["report_sha256"] == summary["digests"]["validation_report"]
        assert _sha(sidecar) == summary["digests"]["validation_sidecar"]
        assert sidecar.read_bytes() == (
            json.dumps(validation, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            + "\n"
        ).encode("utf-8")
        quality = candidate_dir / "text-quality.json"
        screen = json.loads(quality.read_bytes())
        assert _sha(quality) == summary["text_quality"]["sha256"]
        assert validation["text_quality_sha256"] == _sha(quality)
        assert screen["candidate_sha256"] == summary["candidate"]["sha256"]
        assert screen["text_correctness"] == "not_assessed"
        assert screen["inputs"][-1]["path"] == "package/content.tei.xml"


def test_failed_validation_leaves_no_candidate_or_sidecar(tmp_path: Path) -> None:
    repo = _synthetic_repository(tmp_path)
    destination = tmp_path / "failed-validation"
    env = {**os.environ, "OCD_TEST_VALIDATION_STATUS": "fail"}

    completed = _run(repo, destination, env=env)

    assert completed.returncode != 0
    assert not destination.exists()


@pytest.mark.parametrize("name", ["data", "ir", "reports", "exports", "acceptance", "publication"])
def test_governed_or_repository_destination_is_rejected(tmp_path: Path, name: str) -> None:
    repo = _synthetic_repository(tmp_path)
    destination = repo / name / "candidate"
    destination.parent.mkdir(parents=True, exist_ok=True)
    completed = _run(repo, destination)
    assert completed.returncode != 0
    assert not destination.exists()


@pytest.mark.parametrize("name", ["raw", "reports", "exports"])
def test_absolute_junction_target_destination_is_rejected_without_creation(
    name: str,
) -> None:
    if not (ROOT / name).exists():
        pytest.skip(f"{name} storage is absent in this checkout")
    governed_root = (ROOT / name).resolve(strict=True)
    if governed_root == ROOT / name:
        pytest.skip(f"{name} is not junction-backed in this checkout")
    destination = governed_root / ".ocd-reconstruction-preflight-test-must-not-exist"
    assert not destination.exists()

    with pytest.raises(ValueError, match="governed storage"):
        RUNNER_MODULE._destination_policy().preflight_destination(
            ROOT,
            destination,
            appeared_empty="replace",
            repository_lexical="allow_resolved_escape",
        )

    assert not destination.exists()


def test_nonempty_destination_is_rejected_without_overwrite(tmp_path: Path) -> None:
    repo = _synthetic_repository(tmp_path)
    destination = tmp_path / "occupied"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("owned", encoding="utf-8")
    completed = _run(repo, destination)
    assert completed.returncode != 0
    assert sentinel.read_text(encoding="utf-8") == "owned"
    assert list(destination.iterdir()) == [sentinel]


@pytest.mark.parametrize("flag", ["--accept", "--publish"])
def test_acceptance_and_publication_flags_are_rejected_without_side_effects(tmp_path: Path, flag: str) -> None:
    repo = _synthetic_repository(tmp_path)
    sentinels = []
    for name in ("data", "ir", "reports", "acceptance", "publication"):
        path = repo / name / "sentinel.txt"
        _write(path, "owned")
        sentinels.append(path)
    destination = tmp_path / "must-not-exist"
    completed = _run(repo, destination, flag)
    assert completed.returncode != 0
    assert not destination.exists()
    assert all(path.read_text(encoding="utf-8") == "owned" for path in sentinels)


@pytest.mark.parametrize("attack", ["wrong-callable", "wrong-module", "closure-drift"])
def test_bound_callable_and_closure_attacks_fail_closed(tmp_path: Path, attack: str) -> None:
    repo = _synthetic_repository(tmp_path)
    record = _manifest(repo)
    if attack == "wrong-callable":
        record["converter"]["callable"] = "missing_converter"
    elif attack == "wrong-module":
        oracle = repo / record["validator"]["implementation_path"]
        record["converter"]["implementation_path"] = oracle.relative_to(repo).as_posix()
        record["converter"]["implementation_sha256"] = _sha(oracle)
    else:
        record["validator"]["import_closure_sha256"] = "b" * 64
    _replace_manifest(repo, record)
    destination = tmp_path / attack
    completed = _run(repo, destination)
    assert completed.returncode != 0
    assert not destination.exists()


def test_imported_callable_shadow_is_rejected(tmp_path: Path) -> None:
    repo = _synthetic_repository(tmp_path)
    original = repo / "build/tei/synthetic_converter.py"
    shadow = repo / "shadow_impl.py"
    shutil.copy2(original, shadow)
    reexport = repo / "build/tei/reexport_converter.py"
    _write(reexport, "from shadow_impl import _convert\n")
    record = _manifest(repo)
    record["converter"]["implementation_path"] = reexport.relative_to(repo).as_posix()
    record["converter"]["implementation_sha256"] = _sha(reexport)
    _replace_manifest(repo, record)
    destination = tmp_path / "shadowed"
    completed = _run(repo, destination)
    assert completed.returncode != 0
    assert not destination.exists()


def test_manifest_and_implementation_hash_drift_fail_before_destination_write(tmp_path: Path) -> None:
    repo = _synthetic_repository(tmp_path)
    converter = repo / "build/tei/synthetic_converter.py"
    converter.write_text(converter.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
    destination = tmp_path / "drifted"
    completed = _run(repo, destination)
    assert completed.returncode != 0
    assert not destination.exists()


def test_pythonpath_contract_shadow_cannot_replace_reviewed_runtime(tmp_path: Path) -> None:
    repo = _synthetic_repository(tmp_path)
    shadow = tmp_path / "python-shadow"
    _write(shadow / "ocd_kernel/__init__.py", "")
    _write(shadow / "ocd_kernel/reconstruction/__init__.py", "raise RuntimeError('shadow loaded')\n")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(shadow)
    completed = _run(repo, tmp_path / "shadow-resistant", env=env)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "pass"


def test_progress_is_stderr_only_and_deterministic_stdout_is_unchanged(tmp_path: Path) -> None:
    repo = _synthetic_repository(tmp_path)
    plain = _run(repo, tmp_path / "plain")
    observed = _run(repo, tmp_path / "observed", "--progress")
    assert plain.returncode == observed.returncode == 0, observed.stderr
    assert plain.stdout == observed.stdout
    events = [json.loads(line) for line in observed.stderr.splitlines()]
    assert [event["stage"] for event in events] == ["preflight", "reconstruct", "validate", "screen-text", "complete"]
    assert all(event["event"] == "candidate-stage" and event["at"].endswith("+00:00") for event in events)


def test_shared_corrupted_correction_map_is_screened_independently_of_oracle(tmp_path):
    repo = _synthetic_repository(tmp_path)
    profile = repo / "sources/synthetic/profile.json"
    _write(profile, json.dumps({"replacements": [{"scan_reading": "Christ\u00c3\u00a2\u20ac\u2122s"}]}))
    record = _manifest(repo)
    authority = next(a for a in record["authorities"] if a["name"] == "profile")
    authority.update(bytes=profile.stat().st_size, sha256=_sha(profile))
    _replace_manifest(repo, record)
    destination = tmp_path / "screened-map"
    completed = _run(repo, destination)
    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["validation_report"]["status"] == "pass"
    assert summary["text_quality"]["review_status"] == "required"
    screen = json.loads((destination / "text-quality.json").read_bytes())
    selected = next(r for r in screen["inputs"] if r["path"] == authority["path"])
    assert selected["observations"][0]["locator"] == "/replacements/0/scan_reading"
    assert selected["observations"][0]["rule"] == "encoding_sequence_present"
    assert screen["inputs"][-1]["observations"] == []
    assert next(r for r in screen["inputs"] if r["role"] == "tei-validation-schema")["status"] == "not_screened"
    assert screen["coverage"] == "partial"


def test_failed_automatic_screen_cannot_promote_handoff(tmp_path, monkeypatch):
    from build.lib import reconstruction_text_screen
    repo = _synthetic_repository(tmp_path)
    destination = tmp_path / "failed-screen"

    def fail(*args):
        raise ValueError("Candidate TEI character screening failed")

    monkeypatch.setattr(reconstruction_text_screen, "screen_reconstruction", fail)
    with pytest.raises(ValueError, match="screening failed"):
        RUNNER_MODULE.run(manifest=MANIFEST, destination=str(destination), repository_root=str(repo))
    assert not destination.exists()
    assert not list(destination.parent.glob(".failed-screen.staging-*"))
