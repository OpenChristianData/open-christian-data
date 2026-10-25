"""Current NPNF source oracles in exact historical installer generations."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
from ocd_kernel.reconstruction import CandidatePackage
from ocd_kernel.tei.install_accepted import _files, _io_path


def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha(path):
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _runtime_record(original, fields):
    allowed = {"converter.implementation_sha256", "validator.implementation_sha256",
               "validator.import_closure_sha256", "producer_import_closure_sha256"}
    aggregate_key = "authorities.6.sha256"
    if aggregate_key in fields:
        assert original["source_id"] == "augustine-grace-and-free-will-npnf105-div1-v1"
        assert original["authorities"][6] == {
            "name": "aggregate-oracle", "path": "build/tei/npnf105_oracle.py",
            "role": "aggregate-source-oracle", "bytes": 49157,
            "sha256": "390f2a2fc3f6f3df7d9c71f17fe4190c8aa54021f8d285d52adeeb404e535e87",
        }
        allowed.add(aggregate_key)
    assert set(fields) <= allowed
    current = deepcopy(original)
    for key, value in fields.items():
        if key == aggregate_key:
            current["authorities"][6]["sha256"] = value
            continue
        section, dot, field = key.partition(".")
        if dot:
            current[section][field] = value
        else:
            current[key] = value
    restored = deepcopy(current)
    for key in fields:
        if key == aggregate_key:
            restored["authorities"][6]["sha256"] = original["authorities"][6]["sha256"]
            continue
        section, dot, field = key.partition(".")
        if dot:
            restored[section][field] = original[section][field]
        else:
            restored[key] = original[key]
    assert restored == original
    return current


def _current_candidate(tool_root, root, manifest_logical, retained_package, destination):
    retained = CandidatePackage.load(retained_package)
    result = subprocess.run(
        [sys.executable, "-m", "build.tools.reconstruct_candidate", "--repository-root", str(root),
         "--manifest", manifest_logical.as_posix(), "--destination", str(destination)],
        cwd=tool_root, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr or result.stdout
    assert json.loads(result.stdout)["status"] == "pass"
    current = CandidatePackage.load(destination / "package")
    assert current.member_names == retained.member_names
    for name in current.member_names:
        if name != "manifest.json":
            assert current.member_bytes(name) == retained.member_bytes(name), name
    assert current.manifest["source_manifest"]["path"] == manifest_logical.as_posix()
    assert current.manifest["status"] == "nonaccepted"
    return current


def _validation_policy(record):
    owner = (record["source_id"], record["converter"]["id"], record["validator"]["id"])
    corpus_policies = {
        ("npnf109-olympias-six-letter-corpus-v1", "ocd-npnf109-olympias-six-letter-corpus",
         "ocd-npnf109-olympias-six-letter-source-oracle"): "olympias-policy",
        ("npnf109-rome-four-letter-corpus-v1", "ocd-npnf109-rome-four-letter-corpus",
         "ocd-npnf109-rome-four-letter-source-oracle"): "rome-policy",
    }
    expected = corpus_policies.get(owner, "validation-policy")
    policies = [row for row in record["authorities"] if row["name"] == "validation-policy"
                or row.get("role") == "independent-validation-policy"]
    assert len(policies) == 1 and policies[0]["name"] == expected, "Missing, ambiguous, or unknown NPNF install policy authority"
    return policies[0]


def current_npnf_work_install_context(input_root, destination, *, receipt_path,
                                     receipt_sha256, preserved_before, runtime_fields,
                                     current_dependencies=(), npnf113_aggregate=False):
    raw = _io_path(receipt_path).read_bytes()
    assert sha256(raw).hexdigest() == receipt_sha256
    original = json.loads(raw)
    work_id = original["work_id"]
    assert work_id and all(c in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in work_id)
    work = Path("library/works") / work_id
    original_stage = Path(original["stage_root"])
    assert _files(original_stage / work) == original["after"]
    root, stage = destination / "root", destination / "stage"
    shutil.copytree(_io_path(original_stage), _io_path(root))
    shutil.copytree(_io_path(original_stage), _io_path(stage))
    target = _io_path(root / work)
    assert target.resolve(strict=True).is_relative_to(_io_path(root).resolve(strict=True))
    assert not target.is_symlink() and not target.is_junction()
    shutil.rmtree(target)
    before_home = input_root / preserved_before
    for relative, digest in original["before"].items():
        payload = _io_path(before_home / "work" / relative).read_bytes()
        assert sha256(payload).hexdigest() == digest
        target = _io_path(root / work / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    assert _files(root / work) == original["before"]
    manifest_logical = Path(original["manifest_path"])
    profile_logical = Path(original["profile_path"])
    before_manifest_raw = _io_path(before_home / "manifest-before.json").read_bytes()
    before_profile_raw = _io_path(before_home / "profile-before.json").read_bytes()
    assert sha256(before_manifest_raw).hexdigest() == original["source_manifest_before_sha256"]
    assert sha256(before_profile_raw).hexdigest() == original["profile_before_sha256"]
    _io_path(root / profile_logical).write_bytes(before_profile_raw)
    after_manifest_raw = _io_path(stage / manifest_logical).read_bytes()
    assert sha256(after_manifest_raw).hexdigest() == original["source_manifest_after_sha256"]
    assert _sha(stage / profile_logical) == original["profile_after_sha256"]
    records = [json.loads(before_manifest_raw), json.loads(after_manifest_raw)]
    for place, record, source_raw in zip((root, stage), records, (before_manifest_raw, after_manifest_raw), strict=True):
        runtime = _runtime_record(record, runtime_fields)
        if npnf113_aggregate:
            runtime = with_npnf113_runtime_aggregate(input_root, place, runtime)
        _io_path(place / manifest_logical).write_bytes(source_raw if runtime == record else _json(runtime))
        policy = _validation_policy(runtime)
        policy_record = json.loads(_io_path(place / policy["path"]).read_bytes())
        code_paths = {Path(p) for p in policy_record.get("closure_inputs", [])}
        code_paths.update(Path(p) for p in current_dependencies)
        code_paths.update(Path(p) for p in (
            "ocd_kernel/reconstruction/contract.py", "ocd_kernel/reconstruction/verifier.py",
            "ocd_kernel/reconstruction/__init__.py"))
        code_paths.update(Path(runtime[key]["implementation_path"]) for key in ("converter", "validator"))
        for relative in code_paths:
            payload = _io_path(input_root / relative).read_bytes()
            target = _io_path(place / relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            assert target.read_bytes() == _io_path(input_root / relative).read_bytes()
        for key in ("converter", "validator"):
            assert _sha(place / runtime[key]["implementation_path"]) == runtime[key]["implementation_sha256"]
    batch_path = Path(original["package_receipt"])
    batch_raw = _io_path(batch_path).read_bytes()
    assert sha256(batch_raw).hexdigest() == original["package_receipt_sha256"]
    batch = json.loads(batch_raw)
    corpus_contracts = {
        "ocd-npnf109-olympias-corpus-candidate-v1": ("chrysostom-letters-to-olympias", 6, "xvii"),
        "ocd-npnf109-rome-corpus-candidate-v1": ("chrysostom-correspondence-with-rome", 4, "xviii"),
    }
    is_corpus = batch.get("contract") in corpus_contracts
    if is_corpus:
        assert (work_id, batch["letter_count"], batch["source_root_id"]) == corpus_contracts[batch["contract"]]
        assert batch["work_id"] == work_id and "works" not in batch
        item = batch
        original_package = batch_path.parent / "package"
    else:
        selected = [row for row in batch["works"] if row["work_id"] == work_id]
        assert len(selected) == 1
        item = selected[0]
        original_package = Path(item["candidate_root"]) / "package"
    original_item = deepcopy(item)
    assert CandidatePackage.load(original_package).sha256 == item["candidate_sha256"]
    before_candidate_home = destination / "before-candidate"
    before_candidate = _current_candidate(input_root, root, manifest_logical, original_package, before_candidate_home)
    evidence = work / next(p for p in original["after"] if p.endswith("inputs/current/package/manifest.json")).split("/inputs/current/package/")[0]
    after_candidate_home = destination / "after-candidate"
    _current_candidate(input_root, stage, manifest_logical, original_stage / evidence / "inputs/current/package", after_candidate_home)
    current_package_manifest = evidence / "inputs/current/package/manifest.json"
    current_validation = evidence / "inputs/current/validation.json"
    _io_path(stage / current_package_manifest).write_bytes((after_candidate_home / "package/manifest.json").read_bytes())
    _io_path(stage / current_validation).write_bytes((after_candidate_home / "validation.json").read_bytes())
    after = _files(stage / work)
    changed = {p for p in original["after"] if after[p] != original["after"][p]}
    assert set(after) == set(original["after"])
    assert changed <= {current_package_manifest.relative_to(work).as_posix(), current_validation.relative_to(work).as_posix()}
    item.update(manifest_sha256=_sha(root / manifest_logical),
                candidate_sha256=before_candidate.sha256, validation_sha256=_sha(before_candidate_home / "validation.json"))
    if not is_corpus:
        item["candidate_root"] = before_candidate_home.as_posix()
    if "validation_report_sha256" in item:
        item["validation_report_sha256"] = json.loads((before_candidate_home / "validation.json").read_bytes())["report_sha256"]
    restored_item = deepcopy(item)
    for key in ("manifest_sha256", "candidate_root", "candidate_sha256", "validation_sha256", "validation_report_sha256"):
        if key in original_item:
            restored_item[key] = original_item[key]
    assert restored_item == original_item
    # All other batch members and every source/body/master claim are preserved.
    if is_corpus:
        assert restored_item == json.loads(batch_raw)
    else:
        restored_batch = deepcopy(batch)
        restored_batch["works"][batch["works"].index(item)] = original_item
        assert restored_batch == json.loads(batch_raw)
    current_batch_raw = _json(batch)
    # The actual corpus preflight owns its package beside its batch receipt.
    current_batch_path = (before_candidate_home / batch_path.name if is_corpus
                          else destination / "current-batch.json")
    current_batch_path.write_bytes(current_batch_raw)
    # The declared family batch path is the original package receipt's logical
    # source when it is repository-local, otherwise use the matching retained copy.
    matches = [Path(p) for p, digest in _files(original_stage).items()
               if digest == original["package_receipt_sha256"]]
    assert len(matches) <= 1, matches
    for relative in matches:
        for place in (root, stage):
            _io_path(place / relative).write_bytes(current_batch_raw)
    current = dict(original, canonical_root=root.as_posix(), stage_root=stage.as_posix(),
                   source_manifest_before_sha256=_sha(root / manifest_logical),
                   source_manifest_after_sha256=_sha(stage / manifest_logical),
                   package_receipt=current_batch_path.as_posix(),
                   package_receipt_sha256=sha256(current_batch_raw).hexdigest(), after=after)
    restored = deepcopy(current)
    for key in ("canonical_root", "stage_root", "source_manifest_before_sha256", "source_manifest_after_sha256",
                "package_receipt", "package_receipt_sha256", "after"):
        restored[key] = original[key]
    assert restored == original
    receipt = destination / Path(receipt_path).name
    receipt.write_bytes(_json(current))
    return root, receipt, current, sha256(current_batch_raw).hexdigest()


def with_npnf113_runtime_aggregate(input_root, place, original):
    """Use the existing proven aggregate route, preserving all other child fields."""
    metadata = json.loads((input_root / "tests/fixtures/reconstruction-runtime/next-binding-npnf-work-late.json").read_bytes())
    cases = [row for row in metadata if row["family"] == "npnf113"]
    assert len(cases) == 1
    case = cases[0]
    authority = next(row for row in original["authorities"] if row["name"] == "aggregate-source-manifest")
    assert authority == case["aggregate_original_authority"]
    aggregate_path = Path(case["runtime_aggregate"])
    raw = (input_root / aggregate_path).read_bytes()
    assert sha256(raw).hexdigest() == case["runtime_aggregate_sha256"]
    runtime = deepcopy(original)
    replacement = next(row for row in runtime["authorities"] if row["name"] == "aggregate-source-manifest")
    replacement.update(path=aggregate_path.as_posix(), sha256=sha256(raw).hexdigest(), bytes=len(raw))
    restored = deepcopy(runtime)
    restored["authorities"][runtime["authorities"].index(replacement)] = deepcopy(authority)
    assert restored == original
    aggregate = json.loads(raw)
    dependencies = [(aggregate_path, sha256(raw).hexdigest(), len(raw))]
    dependencies.extend((Path(row["path"]), row["sha256"], row["bytes"]) for row in aggregate["authorities"])
    dependencies.extend((Path(aggregate[key]["implementation_path"]), aggregate[key]["implementation_sha256"], None) for key in ("converter", "validator"))
    for relative, digest, size in dependencies:
        assert not relative.is_absolute() and ".." not in relative.parts
        payload = _io_path(input_root / relative).read_bytes()
        assert sha256(payload).hexdigest() == digest
        assert size is None or len(payload) == size
        target = _io_path(place / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        assert target.read_bytes() == payload
    return runtime
