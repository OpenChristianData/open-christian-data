from collections import Counter
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ocd_kernel.reconstruction import closure_verification
from ocd_kernel.reconstruction.closure_verification import (
    check_producer_closures,
    discover_v1_source_manifests,
)


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "tests/fixtures/reconstruction-runtime"


def _expected_routes():
    expected = {}

    def add(original, digest, manifest, proof):
        assert manifest not in expected
        expected[manifest] = (original, digest, proof)

    for row in json.loads((RUNTIME / "closure-baselines.json").read_bytes()):
        add(row["original"], row["sha256"], row["fixture"],
            "tests/test_owned_runtime_closure_baselines.py::test_runtime_copy_preserves_the_complete_historical_record")
    for row in json.loads((RUNTIME / "runtime-binding-cases.json").read_bytes()):
        add(row["original"], row["original_sha256"], row["fixture"],
            "tests/test_runtime_manifest_binding_boundaries.py::test_runtime_manifest_preserves_frozen_source_scope_and_only_updates_declared_runtime")
    for name, (original, digest) in json.loads((RUNTIME / "missing-baseline-bindings.json").read_bytes()).items():
        add(original, digest, f"tests/fixtures/reconstruction-runtime/{name}.source-manifest.json",
            "tests/test_missing_baseline_runtime_manifests.py::test_runtime_fixture_preserves_complete_frozen_record_except_declared_runtime_bindings")
    for row in json.loads((RUNTIME / "newline-binding-cases.json").read_bytes()).values():
        add(row["original"], row["sha256"], row["fixture"],
            "tests/test_newline_runtime_manifests.py::test_runtime_fixture_changes_only_line_endings_and_current_validator_closure")
    for metadata in ("individual-runtime-bindings.json", "next-binding-henry.json",
                     "next-binding-wsc.json", "next-binding-puritan.json",
                     "next-binding-asv-lib072.json",
                     "next-binding-checkpoint-install-contexts.json",
                     "next-binding-edwards-fragments.json",
                     "next-binding-l596-web.json",
                     "next-binding-lib031-work-local.json",
                     "next-binding-lib054-work-local.json",
                     "next-binding-npnf103.json",
                     "next-binding-npnf103104.json",
                     "next-binding-npnf210-title.json",
                     "next-binding-npnf210-work.json",
                     "next-binding-se-four.json"):
        for row in json.loads((RUNTIME / metadata).read_bytes()):
            add(row["original"], row["original_sha256"], row["manifest"], row["preservation_test"])
    return expected


def _validate_routes(rows):
    import ast

    expected = _expected_routes()
    assert Counter(row["manifest"] for row in rows) == Counter({path: 1 for path in expected})
    proof_functions = {}
    for row in rows:
        assert (row["original"], row["original_sha256"], row["preservation_test"]) == expected[row["manifest"]]
        for logical in (row["original"], row["manifest"]):
            path = Path(logical)
            assert not path.is_absolute() and ".." not in path.parts and path.as_posix() == logical
            (ROOT / path).resolve(strict=True).relative_to(ROOT)
            assert json.loads((ROOT / path).read_bytes())["contract"] == "ocd-source-manifest-v1"
        proof_path, proof_name = row["preservation_test"].split("::")
        assert proof_path.startswith("tests/test_") and "/../" not in proof_path
        if proof_path not in proof_functions:
            tree = ast.parse((ROOT / proof_path).read_bytes())
            proof_functions[proof_path] = {node.name for node in tree.body
                                          if isinstance(node, ast.FunctionDef)}
        assert proof_name in proof_functions[proof_path]
    return rows



def test_retained_source_manifest_inventory_is_complete_and_unchanged() -> None:
    from hashlib import sha256
    import subprocess

    inventory = json.loads((ROOT / "tests/fixtures/reconstruction-runtime/retained-manifest-inventory.json").read_bytes())
    # Other tasks can add untracked candidates while this commit is being checked.
    tracked = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--", "sources"],
        check=True, capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    actual = {}
    for logical in tracked:
        if not logical.endswith("source-manifest.json"):
            continue
        content = (ROOT / logical).read_bytes()
        if json.loads(content).get("contract") == "ocd-source-manifest-v1":
            actual[logical] = sha256(content).hexdigest()
    assert actual == inventory


@pytest.mark.parametrize("change", ("untracked-addition", "staged-addition", "modified", "deleted"))
def test_manifest_inventory_checks_tracked_inputs_without_adopting_untracked_work(tmp_path, monkeypatch, change):
    from hashlib import sha256
    import subprocess
    import sys

    def git(*arguments):
        subprocess.run(["git", "-C", str(tmp_path), *arguments], check=True, capture_output=True)

    git("init")
    original = tmp_path / "sources/original/source-manifest.json"
    original.parent.mkdir(parents=True)
    original.write_text('{"contract":"ocd-source-manifest-v1"}', encoding="utf-8")
    inventory = tmp_path / "tests/fixtures/reconstruction-runtime/retained-manifest-inventory.json"
    inventory.parent.mkdir(parents=True)
    inventory.write_text(json.dumps({
        original.relative_to(tmp_path).as_posix(): sha256(original.read_bytes()).hexdigest(),
    }), encoding="utf-8")
    git("add", "sources")
    if change.endswith("addition"):
        added = tmp_path / "sources/new/source-manifest.json"
        added.parent.mkdir()
        added.write_bytes(original.read_bytes())
        if change == "staged-addition":
            git("add", "sources")
    elif change == "modified":
        original.write_text('{"contract":"ocd-source-manifest-v1","changed":true}', encoding="utf-8")
    else:
        original.unlink()
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    if change == "untracked-addition":
        test_retained_source_manifest_inventory_is_complete_and_unchanged()
    else:
        with pytest.raises((AssertionError, FileNotFoundError)):
            test_retained_source_manifest_inventory_is_complete_and_unchanged()


@pytest.mark.requires_local_artifacts
def test_previously_live_canonical_validator_subset_remains_live():
    from hashlib import sha256

    rows = json.loads((RUNTIME / "canonical-live-validator-bindings.json").read_bytes())
    successors = json.loads((RUNTIME / "canonical-live-runtime-successors.json").read_bytes())
    assert set(successors) <= set(rows)
    assert rows
    for logical, digest in rows.items():
        assert sha256((ROOT / logical).read_bytes()).hexdigest() == digest
        current = successors.get(logical, logical)
        if current != logical:
            assert current.startswith("tests/fixtures/reconstruction-runtime/canonical-live/")
            assert ".." not in Path(current).parts
            expected = json.loads((ROOT / logical).read_bytes())
            live, _ = closure_verification._call_validator_closure(
                ROOT, expected["validator"]["implementation_path"], expected,
                manifest_path=ROOT / current,
            )
            expected["validator"]["import_closure_sha256"] = live
            assert json.loads((ROOT / current).read_bytes()) == expected
        check = closure_verification.check_validator_manifest_closure(ROOT, current)
        assert check.matches, check


def test_frozen_installer_current_runtime_pins_are_live():
    from hashlib import sha256

    bindings = json.loads((RUNTIME / "authorities/frozen-install-runtime-bindings.json").read_bytes())
    assert bindings
    for owner, binding in bindings.items():
        pins = binding["runtime_schema_pins"]
        assert pins
        actual = {logical: sha256((ROOT / logical).read_bytes()).hexdigest() for logical in pins}
        assert actual == pins, owner


def _maintained_routes():
    return _validate_routes(json.loads((RUNTIME / "maintained-closure-routes.json").read_bytes()))


@pytest.mark.parametrize("mutation", ("omitted", "duplicate", "unproven", "traversal"))
@pytest.mark.requires_local_artifacts
def test_maintained_registry_rejects_incomplete_or_unproven_routes(mutation):
    rows = _maintained_routes()
    if mutation == "omitted":
        rows.pop()
    elif mutation == "duplicate":
        rows.append(dict(rows[0]))
    elif mutation == "unproven":
        rows[0]["preservation_test"] = "tests/test_reconstruction_closure_corpus.py::test_maintained_validator_closures_are_live"
    else:
        rows[0]["original"] = "../outside.source-manifest.json"
    with pytest.raises(AssertionError):
        _validate_routes(rows)


@pytest.mark.requires_local_artifacts
def test_maintained_validator_closures_are_live() -> None:
    from hashlib import sha256

    routes = _maintained_routes()
    assert routes and len({row["manifest"] for row in routes}) == len(routes)
    for row in routes:
        original = ROOT / row["original"]
        assert sha256(original.read_bytes()).hexdigest() == row["original_sha256"]
        path = ROOT / row["manifest"]
        assert sha256(path.read_bytes()).hexdigest() == row["manifest_sha256"]
        record = json.loads(path.read_bytes())
        live, _ = closure_verification._call_validator_closure(
            ROOT, record["validator"]["implementation_path"], record, manifest_path=path,
        )
        assert record["validator"]["import_closure_sha256"] == live, row["manifest"]


@pytest.mark.requires_local_artifacts
def test_maintained_declared_producer_closures_are_live() -> None:
    seen = []
    for row in _maintained_routes():
        path = ROOT / row["manifest"]
        record = json.loads(path.read_bytes())
        declarations = []
        if "producer_import_closure_sha256" in record:
            declarations.append((path, record["producer_import_closure_sha256"]))
        for authority in record["authorities"]:
            # Source JSON is data, not a declared producer-runtime profile.
            if authority["role"] == "primary-source":
                continue
            support_path = ROOT / authority["path"]
            if support_path.suffix != ".json":
                continue
            support = json.loads(support_path.read_bytes())
            if isinstance(support, dict) and "producer_import_closure_sha256" in support:
                declarations.append((support_path, support["producer_import_closure_sha256"]))
        if not declarations:
            continue
        live, _ = closure_verification._call_producer_closure(
            ROOT, record["converter"]["implementation_path"], record["validator"]["implementation_path"], record,
        )
        for declaration, expected in declarations:
            assert expected == live, (row["manifest"], str(declaration))
            seen.append(declaration)
    assert seen


def test_unknown_closure_semantics_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    implementation = tmp_path / "unknown.py"
    implementation.write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        closure_verification,
        "_module",
        lambda _root, _path: SimpleNamespace(__name__="unknown"),
    )
    record = {
        "work_id": "unknown",
        "authorities": [],
        "validator": {
            "implementation_sha256": "a" * 64,
            "import_closure_sha256": "b" * 64,
        },
    }
    with pytest.raises(NotImplementedError, match="no live validator closure adapter"):
        closure_verification._call_validator_closure(
            tmp_path, "unknown.py", record
        )


@pytest.mark.parametrize("changed_profile", (False, True))
def test_producer_closure_checks_profiles_without_decoding_source_json(
    tmp_path, monkeypatch, changed_profile,
):
    import sys

    module = sys.modules[__name__]
    expected = "a" * 64
    (tmp_path / "profile.json").write_text(json.dumps({
        "producer_import_closure_sha256": "b" * 64 if changed_profile else expected,
    }), encoding="utf-8")
    record = {
        "converter": {"implementation_path": "producer.py"},
        "validator": {"implementation_path": "observer.py"},
        "producer_import_closure_sha256": expected,
        "authorities": [
            {"role": "primary-source", "path": "unopened-source.json"},
            {"role": "reconstruction-profile", "path": "profile.json"},
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "_maintained_routes", lambda: [{"manifest": "manifest.json"}])
    monkeypatch.setattr(closure_verification, "_call_producer_closure", lambda *args: (expected, "test"))
    if changed_profile:
        with pytest.raises(AssertionError):
            test_maintained_declared_producer_closures_are_live()
    else:
        test_maintained_declared_producer_closures_are_live()


def test_six_catechisms_validator_uses_its_family_closure(tmp_path, monkeypatch):
    logical = "build/tei/lib062_six_catechisms_oracle.py"
    entry = tmp_path / logical
    entry.parent.mkdir(parents=True)
    entry.write_bytes(b"# oracle fixture\n")
    calls = []
    records = [{"path": logical, "sha256": "a" * 64}]

    def closure(root, implementation):
        calls.append((root, implementation))
        return records

    monkeypatch.setattr(closure_verification, "_module", lambda root, path: SimpleNamespace(
        family=SimpleNamespace(repository_import_closure=closure),
    ))
    digest, strategy = closure_verification._call_validator_closure(tmp_path, logical, {"authorities": []})
    assert calls == [(tmp_path, entry)]
    assert digest == closure_verification._digest(closure_verification._canonical(records))
    assert strategy == "LIB-062 family repository closure"
    records[0]["sha256"] = "b" * 64
    assert closure_verification._call_validator_closure(tmp_path, logical, {"authorities": []})[0] != digest


def test_project_validator_closure_uses_live_route_helper(monkeypatch):
    from build.tei import augustines_confessions_oracle

    monkeypatch.setattr(augustines_confessions_oracle, "_project_closure", lambda root: "a" * 64)
    digest, strategy = closure_verification._call_validator_closure(
        ROOT, "build/tei/augustines_confessions_oracle.py", {"authorities": []}
    )
    assert (digest, strategy) == ("a" * 64, "_project_closure(root)")


def test_bcp_native_validator_closure_tracks_live_dependency_bytes(tmp_path, monkeypatch):
    from build.tei import bcp1662_current_oracle as oracle

    logical = "build/tei/bcp1662_current_oracle.py"
    digest, strategy = closure_verification._call_validator_closure(ROOT, logical, {"authorities": []})
    assert (digest, strategy) == (oracle.closure_sha(ROOT), "closure_sha(root)")
    members = (
        logical, "build/tei/bcp_1662_oracle.py", "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/verifier.py", "ocd_kernel/reconstruction/__init__.py",
        "ocd_kernel/tei/validate.py", "ocd_kernel/lib/storage_topology.py",
    )
    for member in members:
        path = tmp_path / member
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / member).read_bytes())
    monkeypatch.setattr(closure_verification, "_module", lambda root, path: oracle)
    before, _ = closure_verification._call_validator_closure(tmp_path, logical, {"authorities": []})
    assert before == digest
    (tmp_path / "ocd_kernel/reconstruction/contract.py").write_bytes(b"# changed dependency\n")
    after, _ = closure_verification._call_validator_closure(tmp_path, logical, {"authorities": []})
    assert after != before
    assert after == oracle.closure_sha(tmp_path)


@pytest.mark.parametrize("function", (lambda: "a" * 64, lambda root, extra: "a" * 64,
                                      lambda repository_root: "a" * 64))
def test_root_only_closure_sha_rejects_unknown_signatures(tmp_path, monkeypatch, function):
    (tmp_path / "unknown.py").write_bytes(b"# unknown route\n")
    monkeypatch.setattr(closure_verification, "_module", lambda root, path: SimpleNamespace(closure_sha=function))
    with pytest.raises(NotImplementedError, match="no live validator closure adapter"):
        closure_verification._call_validator_closure(tmp_path, "unknown.py", {"authorities": []})


@pytest.mark.parametrize("result", (None, "bad", "g" * 64, ("bad", ())))
def test_root_only_closure_sha_rejects_invalid_digests(tmp_path, monkeypatch, result):
    def closure_sha(root):
        return result

    (tmp_path / "unknown.py").write_bytes(b"# unknown route\n")
    monkeypatch.setattr(closure_verification, "_module", lambda root, path: SimpleNamespace(closure_sha=closure_sha))
    with pytest.raises(TypeError, match="unsupported result"):
        closure_verification._call_validator_closure(tmp_path, "unknown.py", {"authorities": []})


@pytest.mark.parametrize("oracle_name", ("luther_galatians_oracle", "luther_galatians_native_v2_oracle"))
def test_luther_validator_closure_tracks_live_dependency_bytes(tmp_path, monkeypatch, oracle_name):
    import importlib
    oracle = importlib.import_module(f"build.tei.{oracle_name}")

    logical = f"build/tei/{oracle_name}.py"
    entry = tmp_path / logical
    entry.parent.mkdir(parents=True)
    entry.write_text("import dependency\n", encoding="utf-8")
    dependency = tmp_path / "dependency.py"
    dependency.write_bytes(b"VALUE = 1\n")
    monkeypatch.setattr(closure_verification, "_module", lambda root, path: oracle)
    records = oracle._closure(tmp_path, entry, ())
    expected = oracle._digest(oracle._stable(records))
    record = {"authorities": [], "validator": {"import_closure_sha256": "a" * 64}}
    digest, strategy = closure_verification._call_validator_closure(
        tmp_path, logical, record
    )
    assert (digest, strategy) == (expected, "Luther canonical closure records")
    assert digest != record["validator"]["import_closure_sha256"]
    dependency.write_bytes(b"VALUE = 2\n")
    changed, _ = closure_verification._call_validator_closure(
        tmp_path, logical, record
    )
    assert changed != digest
    assert changed == oracle._digest(oracle._stable(oracle._closure(tmp_path, entry, ())))


def test_hodge_vol3_validator_closure_hashes_live_bytes(tmp_path, monkeypatch):
    logical = "build/tei/hodge_systematic_theology_vol_3_oracle.py"
    implementation = tmp_path / logical
    implementation.parent.mkdir(parents=True)
    implementation.write_bytes(b"# changed live oracle bytes\n")
    monkeypatch.setattr(closure_verification, "_module", lambda root, path: SimpleNamespace())
    record = {"authorities": [], "validator": {
        "implementation_sha256": "a" * 64, "import_closure_sha256": "a" * 64,
    }}
    digest, strategy = closure_verification._call_validator_closure(tmp_path, logical, record)
    assert digest == closure_verification._digest(implementation.read_bytes())
    assert strategy == "self-only implementation"


def test_hodge_validator_closure_uses_live_route_helper(monkeypatch):
    from build.tei import hodge_systematic_theology_vol_2_oracle as oracle

    calls = []

    def closure(root, policy):
        calls.append((root, policy))
        return "f" * 64

    monkeypatch.setattr(oracle, "_local_closure", closure)
    digest, strategy = closure_verification._call_validator_closure(
        ROOT, "build/tei/hodge_systematic_theology_vol_2_oracle.py", {"authorities": []}
    )
    assert calls == [(ROOT, {})]
    assert (digest, strategy) == ("f" * 64, "_local_closure(root, policy)")


def test_flavel_validator_closure_uses_live_route_helper(monkeypatch):
    from build.tei import ccel_puritan_lib055_flavel_fountain_of_life_oracle as oracle

    calls = []

    def closure(repository_root):
        calls.append(repository_root)
        return "e" * 64

    monkeypatch.setattr(oracle, "_import_closure_sha256", closure)
    digest, strategy = closure_verification._call_validator_closure(
        ROOT, "build/tei/ccel_puritan_lib055_flavel_fountain_of_life_oracle.py", {"authorities": []}
    )
    assert calls == [ROOT]
    assert (digest, strategy) == ("e" * 64, "_import_closure_sha256(root)")


def test_robertson_validator_closure_uses_live_route_helper(monkeypatch):
    from build.tei import robertson_word_pictures_vol1_oracle

    calls = []

    def closure(root):
        calls.append(root)
        return "d" * 64

    monkeypatch.setattr(robertson_word_pictures_vol1_oracle, "closure", closure)
    digest, strategy = closure_verification._call_validator_closure(
        ROOT, "build/tei/robertson_word_pictures_vol1_oracle.py", {"authorities": []}
    )
    assert calls == [ROOT]
    assert (digest, strategy) == ("d" * 64, "closure(root)")


def test_strong_validator_closure_hashes_live_self_record(tmp_path, monkeypatch):
    from build.tei import strong_systematic_theology_vol_3_oracle as oracle

    logical = "build/tei/strong_systematic_theology_vol_3_oracle.py"
    implementation = tmp_path / logical
    implementation.parent.mkdir(parents=True)
    implementation.write_bytes(b"# changed live oracle bytes\n")
    monkeypatch.setattr(closure_verification, "_module", lambda root, path: oracle)
    expected = oracle._sha(oracle._canonical([
        {"path": logical, "sha256": oracle._sha(implementation.read_bytes())}
    ]))
    digest, strategy = closure_verification._call_validator_closure(
        tmp_path, logical, {"authorities": []}
    )
    assert (digest, strategy) == (expected, "self-only canonical implementation")


def test_producer_import_closure_uses_live_route_helper(monkeypatch):
    from build.tei import john_wesley_sermons_reconstruction

    monkeypatch.setattr(john_wesley_sermons_reconstruction, "_producer_import_closure_sha256", lambda: "b" * 64)
    digest, strategy = closure_verification._call_producer_closure(
        ROOT, "build/tei/john_wesley_sermons_reconstruction.py", "unused.py", {"authorities": []}
    )
    assert (digest, strategy) == ("b" * 64, "_producer_import_closure_sha256()")


def test_policy_first_validator_closure_uses_live_route_helper(monkeypatch):
    from build.tei import darby_oracle

    calls = []

    def closure(policy, repository_root):
        calls.append((policy, repository_root))
        return "c" * 64

    monkeypatch.setattr(darby_oracle, "_closure_digest", closure)
    digest, strategy = closure_verification._call_validator_closure(
        ROOT, "build/tei/darby_oracle.py", {"authorities": []}
    )
    assert calls == [({}, ROOT)]
    assert (digest, strategy) == ("c" * 64, "_closure_digest(policy, root)")


def test_malformed_supported_closure_result_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    implementation = tmp_path / "malformed.py"
    implementation.write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        closure_verification,
        "_module",
        lambda _root, _path: SimpleNamespace(
            __name__="malformed",
            _closure_digest=lambda: {"not": "a digest"},
        ),
    )
    record = {
        "work_id": "malformed",
        "authorities": [],
        "validator": {
            "implementation_sha256": "a" * 64,
            "import_closure_sha256": "b" * 64,
        },
    }
    with pytest.raises(TypeError, match="unsupported result"):
        closure_verification._call_validator_closure(
            tmp_path, "malformed.py", record
        )


@pytest.mark.parametrize("path_kind", ("traversal", "absolute"))
def test_policy_authority_paths_are_repository_confined(
    tmp_path: Path, path_kind: str
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    outside = tmp_path / "outside-policy.json"
    outside.write_text("{}\n", encoding="utf-8")
    logical = "../outside-policy.json" if path_kind == "traversal" else str(outside)
    record = {
        "work_id": "malicious-policy",
        "authorities": [
            {
                "role": "independent-validation-policy",
                "path": logical,
            }
        ],
    }
    with pytest.raises(ValueError, match="must be repository-relative|escapes repository"):
        closure_verification._policy(repository, record)


@pytest.mark.parametrize("path_kind", ("traversal", "absolute"))
def test_lib028_producer_member_paths_are_repository_confined(
    tmp_path: Path, path_kind: str
) -> None:
    repository = tmp_path / "repository"
    authority = repository / "sources" / "lib028-closure.json"
    authority.parent.mkdir(parents=True)
    outside = tmp_path / "outside-member.py"
    outside.write_text("VALUE = 1\n", encoding="utf-8")
    logical = "../outside-member.py" if path_kind == "traversal" else str(outside)
    authority.write_text(
        '{"producer_runtime":{"members":[{"path":'
        + json.dumps(logical)
        + ',"bytes":10,"sha256":"'
        + "0" * 64
        + '"}]}}\n',
        encoding="utf-8",
    )
    record = {
        "work_id": "malicious-lib028",
        "authorities": [
            {
                "name": "tei-p5-xsd-closure",
                "path": "sources/lib028-closure.json",
            }
        ],
    }
    with pytest.raises(ValueError, match="must be repository-relative|escapes repository"):
        closure_verification._lib028_producer_closure(repository, record)


def test_single_root_producer_closure_uses_route_implementation(tmp_path, monkeypatch):
    (tmp_path / "producer.py").write_text("# route fixture", encoding="utf-8")
    calls = []

    def closure(repository_root):
        calls.append(repository_root)
        return "a" * 64

    monkeypatch.setattr(closure_verification, "_module", lambda root, path: SimpleNamespace(_closure=closure))
    digest, strategy = closure_verification._call_producer_closure(
        tmp_path, "producer.py", "oracle.py", {}
    )
    assert calls == [tmp_path]
    assert digest == "a" * 64
    assert strategy == "_closure(root)"


def test_producer_audit_accounts_for_supported_routes_after_unsupported_ones(tmp_path, monkeypatch):
    sources = tmp_path / "sources"
    sources.mkdir()
    for name in ("a-unsupported", "b-supported", "c-unsupported"):
        (sources / f"{name}.source-manifest.json").write_text(json.dumps({
            "contract": "ocd-source-manifest-v1", "source_id": name,
            "producer_import_closure_sha256": "a" * 64,
            "converter": {"implementation_path": name + ".py"},
            "validator": {"implementation_path": "oracle.py"},
        }), encoding="utf-8")
    calls = []

    def closure(root, implementation, validator, record):
        calls.append(implementation)
        if "unsupported" in implementation:
            raise NotImplementedError("unrecognized closure interface")
        return "b" * 64, "fixture"

    monkeypatch.setattr(closure_verification, "_call_producer_closure", closure)
    with pytest.raises(closure_verification.ClosureAuditError) as caught:
        check_producer_closures(tmp_path)
    assert calls == ["a-unsupported.py", "b-supported.py", "c-unsupported.py"]
    assert len(caught.value.failures) == 2
    assert "a-unsupported.source-manifest.json" in caught.value.failures[0]
    assert "c-unsupported.source-manifest.json" in caught.value.failures[1]
    assert len(caught.value.checks) == 1
    assert caught.value.checks[0].work_id == "b-supported"
    assert not caught.value.checks[0].matches


def test_producer_discovery_accepts_unrelated_json_arrays_and_still_rejects_invalid_json(tmp_path):
    sources = tmp_path / "sources"
    sources.mkdir()
    path = sources / "context-bindings.json"
    path.write_text('[{"context": "retained"}]\n', encoding="utf-8")
    assert check_producer_closures(tmp_path) == ()
    path.write_text('{broken\n', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        check_producer_closures(tmp_path)


def test_route_registry_parses_each_shared_proof_once_but_checks_every_name(tmp_path, monkeypatch):
    import ast
    import sys
    module = sys.modules[__name__]
    rows = []
    expected = {}
    for index in range(2):
        original = f"source{index}.json"
        manifest = f"manifest{index}.json"
        for logical in (original, manifest):
            (tmp_path / logical).write_text('{"contract":"ocd-source-manifest-v1"}')
        proof = "tests/test_proof.py::test_present"
        expected[manifest] = (original, "digest", proof)
        rows.append({"manifest": manifest, "original": original,
                     "original_sha256": "digest", "preservation_test": proof})
    proof = tmp_path / "tests/test_proof.py"
    proof.parent.mkdir()
    proof.write_text("def test_present():\n    assert True\n")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "_expected_routes", lambda: expected)
    parse = ast.parse
    calls = []

    def counted(content, *args, **kwargs):
        calls.append(content)
        return parse(content, *args, **kwargs)

    monkeypatch.setattr(ast, "parse", counted)
    assert _validate_routes(rows) == rows
    assert len(calls) == 1
    # A different name in the same cached file must still be refused.
    rows[1]["preservation_test"] = "tests/test_proof.py::test_missing"
    expected["manifest1.json"] = ("source1.json", "digest", rows[1]["preservation_test"])
    with pytest.raises(AssertionError):
        _validate_routes(rows)
    assert len(calls) == 2
    rows[1]["preservation_test"] = rows[0]["preservation_test"]
    expected["manifest1.json"] = ("source1.json", "digest", rows[0]["preservation_test"])
    proof.write_text("def test_replaced():\n    assert True\n")
    with pytest.raises(AssertionError):
        _validate_routes(rows)
    assert len(calls) == 3
