from __future__ import annotations

import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_STALE_BINDINGS: frozenset[str] = frozenset()
# These historical test mirrors use exact earlier work metadata, not today's catalog.
HISTORICAL_WORK_AUTHORITIES = {
    ("tests/fixtures/reconstruction-runtime/apostolic-tradition-current.source-manifest.json",
     "library/works/apostolic-tradition/work.json"):
        "tests/fixtures/historical-authority-mirrors/apostolic-tradition.work.json",
    ("tests/fixtures/reconstruction-runtime/bede-ecclesiastical-history-of-england-current.source-manifest.json",
     "library/works/bede-ecclesiastical-history-of-england/work.json"):
        "tests/fixtures/reconstruction-runtime/authorities/bede-original-work.json",
}
MATERIALIZATION_SAMPLE_PATHS = {
    "build/tei/john_owen_lib052_reconstruction.py",
    "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
    "ocd_kernel/tei/vendor/xsd/tei_all.xsd",
    "sources/structured-text/lib052-john-owen/README.md",
    "sources/structured-text/lib052-john-owen/work-bindings/john-owen-schism/config.json",
}


def _git(*args: str, input_bytes: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        input=input_bytes,
        stdout=subprocess.PIPE,
    ).stdout


def _manifest_records() -> list[tuple[Path, dict[str, object]]]:
    from ocd_kernel.reconstruction.closure_verification import discover_v1_source_manifests

    records: list[tuple[Path, dict[str, object]]] = []
    for path in discover_v1_source_manifests(ROOT):
        record = json.loads(path.read_bytes())
        assert isinstance(record, dict)
        assert record.get("contract") == "ocd-source-manifest-v1", path
        records.append((path, record))
    return records


def _current_manifest_records() -> list[tuple[Path, dict[str, object]]]:
    registry = ROOT / "tests/fixtures/reconstruction-runtime/maintained-closure-routes.json"
    if not registry.is_file():
        return _manifest_records()
    from tests import test_reconstruction_closure_corpus as owner

    assert owner.ROOT == ROOT
    # The complete retained inventory remains immutable, including records
    # whose historical code or notices no longer describe the current runtime.
    owner.test_retained_source_manifest_inventory_is_complete_and_unchanged()
    rows = owner._validate_routes(json.loads(registry.read_bytes()))
    records = []
    for row in rows:
        original = ROOT / row["original"]
        assert hashlib.sha256(original.read_bytes()).hexdigest() == row["original_sha256"], original
        path = ROOT / row["manifest"]
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == row["manifest_sha256"], path
        record = json.loads(content)
        assert isinstance(record, dict) and record.get("contract") == "ocd-source-manifest-v1", path
        records.append((path, record))
    return records


def _direct_declared_hashes() -> tuple[dict[str, set[str]], list[str]]:
    declared: dict[str, set[str]] = defaultdict(set)
    manifests: list[str] = []
    for manifest_path, record in _current_manifest_records():
        manifest_logical = manifest_path.relative_to(ROOT).as_posix()
        manifests.append(manifest_logical)
        authorities = record.get("authorities")
        assert isinstance(authorities, list)
        for authority in authorities:
            assert isinstance(authority, dict)
            logical = str(authority["path"])
            context = HISTORICAL_WORK_AUTHORITIES.get((manifest_logical, logical))
            if context is not None:
                assert authority["role"] == "work-identity-config"
                assert context.startswith("tests/fixtures/") and ".." not in Path(context).parts
                (ROOT / context).resolve(strict=True).relative_to(ROOT.resolve())
                content = (ROOT / context).read_bytes()
                assert len(content) == authority["bytes"]
                assert hashlib.sha256(content).hexdigest() == authority["sha256"]
                logical = context
            declared[logical].add(str(authority["sha256"]))
        for role in ("converter", "validator"):
            binding = record.get(role)
            assert isinstance(binding, dict)
            declared[str(binding["implementation_path"])].add(
                str(binding["implementation_sha256"])
            )
        package_schema = record.get("package_schema")
        assert isinstance(package_schema, dict)
        declared[str(package_schema["path"])].add(str(package_schema["sha256"]))
    return declared, manifests


def _batch_blobs(paths: list[str]) -> dict[str, bytes]:
    requests = b"".join(f":{path}\n".encode() for path in paths)
    output = _git("cat-file", "--batch", input_bytes=requests)
    blobs: dict[str, bytes] = {}
    offset = 0
    for path in paths:
        header_end = output.index(b"\n", offset)
        header = output[offset:header_end].decode().split()
        assert header[1] == "blob"
        size = int(header[2])
        start = header_end + 1
        blobs[path] = output[start : start + size]
        offset = start + size + 1
    assert offset == len(output)
    return blobs


def _materialized(path: str, *, autocrlf: bool) -> bytes:
    return _git(
        "-c",
        f"core.autocrlf={'true' if autocrlf else 'false'}",
        "cat-file",
        "--filters",
        f":{path}",
    )


def _attributes(paths: list[str], attribute: str = "eol") -> dict[str, str]:
    payload = b"\0".join(path.encode() for path in paths) + b"\0"
    output = _git("check-attr", "--cached", "-z", "--stdin", attribute, input_bytes=payload)
    fields = output.split(b"\0")
    assert fields[-1] == b""
    triples = fields[:-1]
    assert len(triples) % 3 == 0
    return {
        triples[index].decode(): triples[index + 2].decode()
        for index in range(0, len(triples), 3)
    }


def _crlf_projection(content: bytes) -> bytes:
    return content.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def _lf_projection(content: bytes) -> bytes:
    return content.replace(b"\r\n", b"\n")


def _changed_paths_from_head(repository_root: Path = ROOT) -> set[str]:
    output = subprocess.run(
        ["git", "diff", "HEAD", "--name-only", "-z"],
        cwd=repository_root,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    paths = set(output.decode().split("\0"))
    paths.discard("")
    return paths


def _assert_expected_stale_bindings(observed: set[str]) -> None:
    assert observed == EXPECTED_STALE_BINDINGS


@pytest.mark.requires_local_artifacts
def test_direct_manifest_text_bindings_declare_deterministic_checkout_eol() -> None:
    declared, manifests = _direct_declared_hashes()
    tracked = set(_git("ls-files", "-z").decode().split("\0"))
    tracked.discard("")
    paths = sorted(path for path in declared if path in tracked)
    attributes = _attributes(paths)
    text_attributes = _attributes(paths, "text")
    assert set(manifests) <= tracked
    # The index is the committed input even when checkout bytes are dirty.
    # Include designated manifest records themselves in this boundary check.
    blobs = _batch_blobs(sorted(set(paths) | set(manifests)))
    conflicts: set[str] = set()
    stale_bindings: set[str] = set()

    for path in paths:
        if text_attributes[path] == "unset":
            # -text preserves exact Git bytes, including mixed line endings.
            # Every declared binding must agree with those bytes; eol is inert.
            exact = blobs[path]
            assert declared[path] == {hashlib.sha256(exact).hexdigest()}, path
            assert (ROOT / path).read_bytes() == exact, path
            continue
        blob = blobs[path]
        # Git may already store a CRLF blob for paths committed before their
        # attributes were introduced. Compare normalized forms exactly once.
        lf_blob = _lf_projection(blob)
        if b"\n" not in lf_blob or b"\0" in lf_blob:
            assert declared[path] == {hashlib.sha256(blob).hexdigest()}, path
            assert (ROOT / path).read_bytes() == blob, path
            continue
        lf_sha256 = hashlib.sha256(lf_blob).hexdigest()
        crlf_sha256 = hashlib.sha256(_crlf_projection(lf_blob)).hexdigest()
        declared_hashes = declared[path]
        has_lf = lf_sha256 in declared_hashes
        has_crlf = crlf_sha256 in declared_hashes
        if has_lf and crlf_sha256 != lf_sha256 and has_crlf:
            conflicts.add(path)
        if has_lf:
            assert declared_hashes == {lf_sha256}, path
            assert attributes[path] == "lf", path
            assert (ROOT / path).read_bytes() == lf_blob, path
        elif has_crlf:
            assert declared_hashes == {crlf_sha256}, path
            assert attributes[path] == "crlf", path
            assert (ROOT / path).read_bytes() == _crlf_projection(lf_blob), path
        else:
            stale_bindings.add(path)
            assert attributes[path] == "unspecified", path

    assert not conflicts
    _assert_expected_stale_bindings(stale_bindings)
    manifest_attributes = _attributes(manifests)
    inventory = _retained_manifest_inventory()
    manifest_text_attributes = _attributes(manifests, "text")
    for logical, eol in manifest_attributes.items():
        content = (ROOT / logical).read_bytes()
        if manifest_text_attributes[logical] == "unset":
            assert content == blobs[logical], logical
        elif eol == "lf":
            assert content == _lf_projection(blobs[logical]), logical
        elif eol == "crlf":
            assert content == _crlf_projection(blobs[logical]), logical
        else:
            raise AssertionError(f"Manifest checkout policy is unspecified: {logical}")
        expected_digest = inventory.get(logical)
        if expected_digest is None:
            assert eol == "lf", logical
            continue
        content = (ROOT / logical).read_bytes()
        lf = _lf_projection(content)
        if hashlib.sha256(lf).hexdigest() == expected_digest:
            assert eol == "lf", logical
        elif hashlib.sha256(_crlf_projection(lf)).hexdigest() == expected_digest:
            assert eol == "crlf", logical
        else:
            # Mixed newline authorities must retain their exact frozen bytes.
            assert hashlib.sha256(content).hexdigest() == expected_digest, logical
            assert manifest_text_attributes[logical] == "unset", logical
            assert eol == "unspecified", logical


def test_changed_paths_from_head_includes_staged_and_unstaged(
    tmp_path: Path,
) -> None:
    def git(*args: str) -> bytes:
        return subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            check=True,
            stdout=subprocess.PIPE,
        ).stdout

    git("init", "--quiet")
    staged = tmp_path / "staged.txt"
    unstaged = tmp_path / "unstaged.txt"
    staged.write_text("baseline\n", encoding="utf-8")
    unstaged.write_text("baseline\n", encoding="utf-8")
    git("add", "staged.txt", "unstaged.txt")
    git(
        "-c",
        "user.name=Checkout Materialization Test",
        "-c",
        "user.email=checkout-materialization@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "baseline",
    )

    staged.write_text("staged change\n", encoding="utf-8")
    git("add", "staged.txt")
    unstaged.write_text("unstaged change\n", encoding="utf-8")

    assert _changed_paths_from_head(tmp_path) == {"staged.txt", "unstaged.txt"}
    assert git("diff", "--cached", "--name-only").decode().splitlines() == [
        "staged.txt"
    ]


@pytest.mark.parametrize("checkout_policy", [b"text eol=lf", b"-text"])
def test_checkout_eol_audit_accepts_new_staged_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    checkout_policy: bytes,
) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.name=Checkout Test",
         "-c", "user.email=checkout@example.invalid", "commit", "--quiet",
         "--allow-empty", "-m", "baseline"], check=True,
    )
    source = tmp_path / "sources" / "new"
    source.mkdir(parents=True)
    authority = source / "authority.txt"
    authority.write_bytes(b"New staged authority\n")
    relative = authority.relative_to(tmp_path).as_posix()
    digest = hashlib.sha256(authority.read_bytes()).hexdigest()
    record = {
        "contract": "ocd-source-manifest-v1",
        "authorities": [{"path": relative, "sha256": digest}],
        "converter": {"implementation_path": relative, "implementation_sha256": digest},
        "validator": {"implementation_path": relative, "implementation_sha256": digest},
        "package_schema": {"path": relative, "sha256": digest},
    }
    manifest = source / "new.source-manifest.json"
    manifest.write_text(json.dumps(record), encoding="utf-8")
    (tmp_path / ".gitattributes").write_bytes(
        b"sources/** text eol=lf\n" + relative.encode() + b" " + checkout_policy + b"\n"
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    test_direct_manifest_text_bindings_declare_deterministic_checkout_eol()
    authority.write_bytes(b"Changed authority\n")
    with pytest.raises(AssertionError):
        test_direct_manifest_text_bindings_declare_deterministic_checkout_eol()
    # The converse must fail too: index B cannot hide behind checkout A.
    _git("add", relative)
    authority.write_bytes(b"New staged authority\n")
    with pytest.raises(AssertionError):
        test_direct_manifest_text_bindings_declare_deterministic_checkout_eol()
    _git("add", relative)
    retained_attributes = (tmp_path / ".gitattributes").read_bytes()
    (tmp_path / ".gitattributes").write_bytes(b"sources/** text eol=crlf\n")
    _git("add", ".gitattributes")
    (tmp_path / ".gitattributes").write_bytes(retained_attributes)
    with pytest.raises(AssertionError):
        test_direct_manifest_text_bindings_declare_deterministic_checkout_eol()
    _git("add", ".gitattributes")
    retained_manifest = manifest.read_bytes()
    manifest.write_text(json.dumps({**record, "work_id": "staged-only"}), encoding="utf-8")
    _git("add", manifest.relative_to(tmp_path).as_posix())
    manifest.write_bytes(retained_manifest)
    with pytest.raises(AssertionError):
        test_direct_manifest_text_bindings_declare_deterministic_checkout_eol()


def test_expected_stale_bindings_reject_additional_path() -> None:
    observed = set(EXPECTED_STALE_BINDINGS)
    observed.add("sources/invented/additional-stale-binding.txt")

    with pytest.raises(AssertionError):
        _assert_expected_stale_bindings(observed)


@pytest.mark.requires_local_artifacts
def test_representative_bindings_materialize_identically_across_autocrlf_modes() -> None:
    declared, manifests = _direct_declared_hashes()
    manifest_path = manifests[0]
    assert MATERIALIZATION_SAMPLE_PATHS <= declared.keys()
    paths = sorted(MATERIALIZATION_SAMPLE_PATHS | {manifest_path})
    blobs = _batch_blobs(paths)

    for path in paths:
        blob = blobs[path]
        if path == manifest_path:
            expected = (ROOT / path).read_bytes()
            # The designated record's exact registry SHA was checked above.
        elif hashlib.sha256(blob).hexdigest() in declared[path]:
            expected = blob
        else:
            expected = _crlf_projection(blob)
            assert hashlib.sha256(expected).hexdigest() in declared[path]
        assert _materialized(path, autocrlf=True) == expected
        assert _materialized(path, autocrlf=False) == expected


def _retained_manifest_inventory() -> dict[str, str]:
    path = ROOT / "tests/fixtures/reconstruction-runtime/retained-manifest-inventory.json"
    return json.loads(path.read_bytes()) if path.is_file() else {}


@pytest.mark.parametrize("autocrlf", [False, True])
def test_frozen_manifest_and_closure_identities_survive_fresh_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, autocrlf: bool,
) -> None:
    from ocd_kernel.lib.path_io import io_path

    inventory = _retained_manifest_inventory()
    expected = {
        logical: (ROOT / logical).read_bytes()
        for logical, digest in inventory.items()
        if hashlib.sha256(_lf_projection((ROOT / logical).read_bytes())).hexdigest() != digest
    }
    assert expected
    for logical, content in expected.items():
        assert hashlib.sha256(content).hexdigest() == inventory[logical], logical
    lf_paths = [
        *(f"build/tei/guyon_short_method_24989_v{version}.py" for version in (13, 14, 15, 16)),
        "build/tei/manifest_pg_l772_l790.py",
        "build/tei/pta_l812_retained_tei_oracle_v3.py",
    ]
    for logical in lf_paths:
        content = (ROOT / logical).read_bytes()
        assert b"\r\n" not in content, logical
        expected[logical] = content
    mixed_code = "build/tei/pta_retained_tei.py"
    expected[mixed_code] = (ROOT / mixed_code).read_bytes()
    assert hashlib.sha256(expected[mixed_code]).hexdigest() == (
        "040cacdeeeb8febcfcebb9528f6bc399878d93dc0b31cfd68b053ba0d9d0360c"
    )
    shared_members = {
        "build/tei/anne_a22076_first_oracle_v1.py": "9125e9c05dd1bad1c791a937149f2b7488974c51321eb4d8b95069e55d8168ea",
        "build/tei/lib062_json_catechisms_oracle.py": "801eae6d85e766195851ec869bd995b2cd2daa046a95d66491af3df84792c3df",
        "build/tei/lib089_form_church_comments_reconstruction.py": "8d8c7396518d4faf9005574f74ae4f3093b63d823e20d6c2c2fb2a0aa8a21ba6",
        "build/tei/prayers_baths_for_cure_oracle.py": "fb7ef76539511e890f8c426510b9ec75f86baef7b2d5ced9687ad9ef4b3ab2e4",
        "sources/barnes-nt-notes/barnes-nt-notes.candidate-source-manifest-20260926.json": "b86ff5234dff59b0406adfedb2a5ef588538255719b43ec25f5963c6b3e9dcf6",
        "sources/manifest-acquisitions/peter-jones-life-and-journals-1860/reconstruction-source-manifest-v2.json": "5aad66adcc8772f6e6f5a369c0cf79ec2741b0f500d20cb3e2d0d8696cae13ad",
        "sources/strong-systematic-theology-vol-2/strong-systematic-theology-vol-2.source-manifest.l374-v2.json": "bc1ef4f02f95798c753d0ee582a8f3103e1769f0a7409bf62708fcd5a2873970",
        "sources/strong-systematic-theology-vol-2/strong-systematic-theology-vol-2.reconstruction-profile.l374-v2.json": "762fae17fe32e076c4d0e787ba513f20be01b7d075e75373f8981e66b48ca454",
        "sources/bede-ecclesiastical-history-of-england/oracle.py": "9eae3424bf8db6b631f7b69c423924c6c5189948745062292ca55ca9be16f9b1",
        "ocd_kernel/lib/path_io.py": "ace1648a7ae64713a4c3450a1cca8fa3b2f896f9cce68775083649c0930eeaa3",
        "ocd_kernel/library/acquisitions.py": "281ae80f19c1b0021d7e05b20dcd3f5eef4a6e29c1bea58f62cd094bbd60d08d",
        "schemas/v2/work.schema.json": "a30e4dc7f72209b2c26455d46a21e1f953f0ab382605c5bc4e15942edf3c9dbb",
        "schemas/v2/acquisition.schema.json": "fc7f46a1532bb35919ed6775477e86f4258ee66e4f35cbc11cdd432b5669dc38",
    }
    for logical, digest in shared_members.items():
        # This checkout exercise preserves the original authority, not today's implementation.
        source = ("tests/fixtures/reconstruction-runtime/authorities/watson-installed-acquisitions.py.bin"
                  if logical == "ocd_kernel/library/acquisitions.py" else logical)
        expected[source] = (ROOT / source).read_bytes()
        assert hashlib.sha256(expected[source]).hexdigest() == digest, source
        if source != logical:
            expected[logical] = (ROOT / logical).read_bytes()
    attributes = (ROOT / ".gitattributes").read_bytes()
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / ".gitattributes").write_bytes(attributes)
    for logical, content in expected.items():
        destination = io_path(repository / logical)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    monkeypatch.setitem(globals(), "ROOT", repository)
    _git("init", "--quiet")
    _git("config", "core.longpaths", "true")
    _git("-c", "core.autocrlf=false", "add", ".")
    _git("-c", "user.name=Checkout Identity Test", "-c",
         "user.email=checkout-identity@example.invalid", "commit", "--quiet", "-m", "fixture")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    _git("-c", f"core.autocrlf={'true' if autocrlf else 'false'}", "checkout-index",
         "--all", f"--prefix={checkout.as_posix()}/")
    for logical, content in expected.items():
        assert io_path(checkout / logical).read_bytes() == content, logical


def test_manifest_discovery_excludes_other_contract_and_rejects_malformed_v1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid = tmp_path / "sources/v1/source-manifest.json"
    foreign = tmp_path / "sources/retained/source-manifest.json"
    valid.parent.mkdir(parents=True)
    foreign.parent.mkdir(parents=True)
    binding = {"implementation_path": "authority.txt", "implementation_sha256": "0" * 64}
    record = {
        "contract": "ocd-source-manifest-v1",
        "authorities": [{"path": "authority.txt", "sha256": "0" * 64}],
        "converter": binding, "validator": binding,
        "package_schema": {"path": "authority.txt", "sha256": "0" * 64},
    }
    valid.write_text(json.dumps(record), encoding="utf-8")
    foreign.write_text(json.dumps({"contract": "ocd-retained-source-acquisition-v1"}), encoding="utf-8")
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    _, manifests = _direct_declared_hashes()
    assert manifests == ["sources/v1/source-manifest.json"]
    valid.write_bytes(b'{"contract":"ocd-source-manifest-v1",')
    with pytest.raises(json.JSONDecodeError):
        _manifest_records()
    record["authorities"] = None
    valid.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(AssertionError):
        _direct_declared_hashes()


@pytest.fixture
def designated_materialization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from tests import test_reconstruction_closure_corpus as owner

    def record(digest: str) -> dict:
        binding = {"implementation_path": "authority.txt", "implementation_sha256": digest}
        return {
            "contract": "ocd-source-manifest-v1",
            "authorities": [{"path": "authority.txt", "sha256": digest}],
            "converter": binding, "validator": binding,
            "package_schema": {"path": "authority.txt", "sha256": digest},
        }

    original = "sources/original/source-manifest.json"
    historical = "sources/history/source-manifest.json"
    manifest = "tests/fixtures/reconstruction-runtime/current.source-manifest.json"
    runtime = tmp_path / "tests/fixtures/reconstruction-runtime"
    runtime.mkdir(parents=True)
    inventory = {}
    for logical, digest in ((original, "1" * 64), (historical, "2" * 64)):
        path = tmp_path / logical
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(record(digest)), encoding="utf-8")
        inventory[logical] = hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path / "authority.txt").write_bytes(b"Current authority\n")
    digest = hashlib.sha256((tmp_path / "authority.txt").read_bytes()).hexdigest()
    current = tmp_path / manifest
    current.write_text(json.dumps(record(digest)), encoding="utf-8")
    proof = "tests/test_fixture_owner.py::test_complete_record_preserved"
    (tmp_path / "tests/test_fixture_owner.py").write_text(
        "def test_complete_record_preserved():\n    pass\n", encoding="utf-8"
    )
    row = {
        "original": original, "original_sha256": inventory[original],
        "manifest": manifest, "manifest_sha256": hashlib.sha256(current.read_bytes()).hexdigest(),
        "preservation_test": proof,
    }
    registry = runtime / "maintained-closure-routes.json"
    registry.write_text(json.dumps([row]), encoding="utf-8")
    (runtime / "retained-manifest-inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    expected = {manifest: (original, inventory[original], proof)}
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "sources"], check=True)
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    monkeypatch.setattr(owner, "ROOT", tmp_path)
    monkeypatch.setattr(owner, "_expected_routes", lambda: expected)
    return current, tmp_path / historical, registry, digest


def test_designated_manifest_rejects_tampered_raw_sha(designated_materialization) -> None:
    current, _, _, _ = designated_materialization
    _direct_declared_hashes()
    current.write_bytes(current.read_bytes() + b" ")
    with pytest.raises(AssertionError):
        _direct_declared_hashes()


def test_historical_conflicting_binding_stays_inventory_bound(designated_materialization) -> None:
    current, historical, _, digest = designated_materialization
    declared, manifests = _direct_declared_hashes()
    assert declared == {"authority.txt": {digest}}
    assert manifests == [current.relative_to(ROOT).as_posix()]
    historical.write_bytes(historical.read_bytes() + b" ")
    with pytest.raises(AssertionError):
        _direct_declared_hashes()


@pytest.mark.parametrize("mutation", ["omitted", "unproven"])
def test_designated_manifest_registry_rejects_missing_or_unproven_routes(
    designated_materialization, mutation: str,
) -> None:
    _, _, registry, _ = designated_materialization
    rows = json.loads(registry.read_bytes())
    if mutation == "omitted":
        rows.clear()
    else:
        rows[0]["preservation_test"] = "tests/test_fixture_owner.py::invented_proof"
    registry.write_text(json.dumps(rows), encoding="utf-8")
    with pytest.raises(AssertionError):
        _direct_declared_hashes()


def test_historical_work_checkout_context_requires_exact_original_bytes(tmp_path, monkeypatch):
    old = b"Original work metadata\n"
    current = tmp_path / "current-work.json"
    current.write_bytes(b"Current catalog metadata\n")
    retained = tmp_path / "tests/fixtures/original-work.json"
    retained.parent.mkdir(parents=True)
    retained.write_bytes(old)
    code = tmp_path / "code.py"
    code.write_bytes(b"pass\n")
    binding = {"implementation_path": "code.py", "implementation_sha256": hashlib.sha256(code.read_bytes()).hexdigest()}
    record = {"authorities": [{"path": "current-work.json", "role": "work-identity-config",
                               "bytes": len(old), "sha256": hashlib.sha256(old).hexdigest()}],
              "converter": binding, "validator": binding,
              "package_schema": {"path": "code.py", "sha256": binding["implementation_sha256"]}}
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    monkeypatch.setitem(globals(), "_current_manifest_records", lambda: [(tmp_path / "fixture.source-manifest.json", record)])
    monkeypatch.setitem(globals(), "HISTORICAL_WORK_AUTHORITIES", {
        ("fixture.source-manifest.json", "current-work.json"): "tests/fixtures/original-work.json",
    })
    declared, _ = _direct_declared_hashes()
    assert declared["tests/fixtures/original-work.json"] == {hashlib.sha256(old).hexdigest()}
    assert "current-work.json" not in declared
    assert current.read_bytes() == b"Current catalog metadata\n"
    retained.write_bytes(b"Altered original metadata\n")
    with pytest.raises(AssertionError):
        _direct_declared_hashes()
    retained.write_bytes(old)
    record["authorities"][0]["role"] = "primary-source"
    with pytest.raises(AssertionError):
        _direct_declared_hashes()
