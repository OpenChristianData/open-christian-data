"""Exercise new retained-source routes through the public reconstruction contract."""

import hashlib
from functools import cache
import json
from pathlib import Path
import shutil

import pytest

from build.tei.bcp_1549_oracle import _oracle as _bcp_1549_oracle
from build.tei.bcp_1549_reconstruction import _convert as _bcp_1549_convert
from build.tei.bcp_1559_oracle import _oracle as _bcp_1559_oracle
from build.tei.bcp_1559_reconstruction import _convert as _bcp_1559_convert
from build.tei.calvin_commentaries_oracle import _oracle as _calvin_oracle
from build.tei.calvin_commentaries_reconstruction import _convert as _calvin_convert
from build.tei.kjv_oracle import _oracle as _kjv_oracle
from build.tei.kjv_reconstruction import _convert as _kjv_convert
from build.tei.lib062_shorter_catechism_oracle import _oracle as _lib062_oracle
from build.tei.lib062_shorter_catechism_reconstruction import _convert as _lib062_convert
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct, validate
from ocd_kernel.reconstruction.closure_verification import _call_validator_closure
from ocd_kernel.lib.storage_topology import resolve_repo_path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_BINDINGS = json.loads(
    (ROOT / "tests/fixtures/reconstruction-runtime/next-binding-wsc.json").read_bytes()
)
ROUTES = (
    pytest.param(
        "bcp-1549",
        "tests/fixtures/reconstruction-runtime/bcp-1549.source-manifest.json",
        _bcp_1549_convert,
        _bcp_1549_oracle,
        id="bcp-1549",
    ),
    pytest.param(
        "bcp-1559",
        "tests/fixtures/reconstruction-runtime/bcp-1559.source-manifest.json",
        _bcp_1559_convert,
        _bcp_1559_oracle,
        id="bcp-1559",
    ),
    pytest.param(
        "calvin-commentaries",
        'tests/fixtures/reconstruction-runtime/calvin-commentaries.source-manifest.json',
        _calvin_convert,
        _calvin_oracle,
        id="calvin-commentaries",
    ),
    pytest.param(
        "kjv",
        "tests/fixtures/reconstruction-runtime/kjv.source-manifest.json",
        _kjv_convert,
        _kjv_oracle,
        id="kjv",
    ),
    pytest.param(
        "shorter-catechism-explained",
        "tests/fixtures/reconstruction-runtime/shorter-catechism-explained.source-manifest.json",
        _lib062_convert,
        _lib062_oracle,
        id="lib-062",
    ),
)


@pytest.mark.parametrize("binding", RUNTIME_BINDINGS, ids=[row["original"] for row in RUNTIME_BINDINGS])
def test_runtime_fixture_preserves_retained_authorities_and_only_updates_closure(binding):
    raw = (ROOT / binding["original"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == binding["original_sha256"]
    expected = json.loads(raw)
    validator = expected["validator"]
    validator["import_closure_sha256"] = _call_validator_closure(
        ROOT, validator["implementation_path"], expected,
        manifest_path=ROOT / binding["original"],
    )[0]
    assert json.loads((ROOT / binding["manifest"]).read_bytes()) == expected


@pytest.fixture(scope="module")
def route_candidate(tmp_path_factory: pytest.TempPathFactory):
    @cache
    def build(route_id: str, manifest_relative: str, converter):
        source = SourceManifest.load(ROOT / manifest_relative, repository_root=ROOT)
        destination = tmp_path_factory.mktemp("route-baseline") / route_id
        return source, reconstruct(source, destination, converter)

    return build


@pytest.mark.parametrize(
    ("route_id", "manifest_relative", "converter", "oracle"),
    ROUTES,
)
def test_source_manifest_route_reconstructs_and_validates(
    route_id: str,
    manifest_relative: str,
    converter,
    oracle,
    route_candidate,
) -> None:
    source, candidate = route_candidate(route_id, manifest_relative, converter)

    report = validate(source, candidate, oracle)

    assert report.status == "pass"


def test_bcp_retained_members_resolve_inside_configured_raw_root() -> None:
    raw_root = resolve_repo_path(ROOT, "raw").resolve(strict=True)
    for manifest_relative in (
        "tests/fixtures/reconstruction-runtime/bcp-1549.source-manifest.json",
        "tests/fixtures/reconstruction-runtime/bcp-1559.source-manifest.json",
        "tests/fixtures/reconstruction-runtime/bcp-1662.source-manifest.json",
    ):
        source = SourceManifest.load(ROOT / manifest_relative, repository_root=ROOT)
        members = [
            authority
            for authority in source.record["authorities"]
            if authority["role"] == "primary-source"
        ]
        assert members
        for authority in members:
            path = source.authority_path(str(authority["name"])).resolve(strict=True)
            assert path.is_relative_to(raw_root), (manifest_relative, authority["path"])


@pytest.mark.parametrize(("route_id", "manifest_relative", "converter", "oracle"), ROUTES[:3])
def test_source_route_oracle_rejects_resealed_content_mutation(
    tmp_path: Path, route_id: str, manifest_relative: str, converter, oracle, route_candidate,
) -> None:
    """Keep producer-independent content mutation rejection covered."""

    source, baseline = route_candidate(route_id, manifest_relative, converter)
    mutated_path = tmp_path / "mutated"
    shutil.copytree(baseline.path, mutated_path)

    content_path = mutated_path / "content.tei.xml"
    original = content_path.read_bytes()
    assert b"Book" in original
    mutated = original.replace(b"Book", b"Xook", 1)
    content_path.write_bytes(mutated)

    manifest_path = mutated_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    content_member = next(
        member for member in manifest["members"] if member["name"] == "content.tei.xml"
    )
    content_member["bytes"] = len(mutated)
    content_member["sha256"] = hashlib.sha256(mutated).hexdigest()
    manifest_path.write_bytes(
        (json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode(
            "utf-8"
        )
    )

    resealed = CandidatePackage.load(mutated_path)
    error = "Calvin mapped source text stream drifted" if route_id == "calvin-commentaries" else "candidate validation failed"
    with pytest.raises(ValueError, match=error):
        validate(source, resealed, oracle)
