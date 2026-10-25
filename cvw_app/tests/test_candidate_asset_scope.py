"""Source-declared asset scope and stable identity across work views."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
import pytest
from cvw_app.review_contract import ReviewContractError, _scoped_primary_authorities, _materialize_candidate_binding


def test_source_scope_keeps_shared_authorities_and_allows_multiple_works():
    shared = {"name": "shared"}
    image = {"name": "image", "work_ids": ("gregory", "leo")}
    assert _scoped_primary_authorities("gregory", [image, shared]) == [image, shared]
    assert _scoped_primary_authorities("leo", [image, shared]) == [image, shared]
    assert _scoped_primary_authorities("jerome", [image, shared]) == [shared]


@pytest.mark.parametrize("value", [None, [], (), {}, "gregory", [""], ["gregory", "gregory"], [3]])
def test_source_scope_rejects_malformed_declared_work_ids(value):
    with pytest.raises(ReviewContractError):
        _scoped_primary_authorities("gregory", [{"name": "image", "work_ids": value}])


def test_source_scope_rejects_duplicates_even_when_hidden():
    with pytest.raises(ReviewContractError, match="duplicate primary-source"):
        _scoped_primary_authorities("jerome", [{"name": "image", "work_ids": ["gregory"]}] * 2)


def _binding(tmp_path, count=2):
    authorities = []
    for index in range(count):
        path = tmp_path / f"source-{index}.txt"
        content = f"source {index}".encode()
        path.write_bytes(content)
        authority = {"name": f"source-{index}", "role": "primary-source", "path": path.name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        if index == 0:
            authority["work_ids"] = ("gregory",)
        authorities.append(authority)
    package = tmp_path / "package"
    package.mkdir()
    def member_bytes(name):
        # Candidate-generated scoping metadata is deliberately not consulted.
        assert name == "content.tei.xml"
        return b"<TEI/>"
    candidate = SimpleNamespace(path=package, sha256="a" * 64, member_bytes=member_bytes)
    manifest = SimpleNamespace(sha256="b" * 64, repository_root=tmp_path, record={"authorities": tuple(authorities)})
    return {"review": SimpleNamespace(source_manifest=manifest), "candidate": candidate, "validation": SimpleNamespace(sha256="c" * 64), "route": {"scope": "work"}}


@pytest.mark.parametrize("count", [2, 3])
def test_filter_preserves_original_authority_ids_versions_and_order(tmp_path, count):
    binding = _binding(tmp_path, count)
    gregory_roots, jerome_roots = {}, {}
    gregory_approved, jerome_approved = [], []
    gregory = _materialize_candidate_binding("gregory", binding, gregory_roots, gregory_approved)[0]
    jerome = _materialize_candidate_binding("jerome", binding, jerome_roots, jerome_approved)[0]
    assert [a["name"] for a in gregory] == [f"source-{i}" for i in range(count)]
    assert [a["name"] for a in jerome] == [f"source-{i}" for i in range(1, count)]
    assert jerome == gregory[1:]
    assert jerome[0]["id"].endswith("-2")
    assert jerome[0]["version"] == jerome[0]["sha256"]
    for artifact in jerome:
        root_id = artifact["root"]
        assert jerome_roots[root_id] == gregory_roots[root_id]
        assert next(row for row in jerome_approved if row["id"] == root_id) == next(row for row in gregory_approved if row["id"] == root_id)


def test_materialization_reports_missing_authority_name_as_contract_error(tmp_path):
    binding = _binding(tmp_path)
    del binding["review"].source_manifest.record["authorities"][0]["name"]
    with pytest.raises(ReviewContractError, match="primary-source authority name"):
        _materialize_candidate_binding("gregory", binding, {}, [])


def test_source_scoping_cannot_leave_a_work_without_any_authority(tmp_path):
    binding = _binding(tmp_path, 1)
    with pytest.raises(ReviewContractError, match="no primary-source authority"):
        _materialize_candidate_binding("jerome", binding, {}, [])
