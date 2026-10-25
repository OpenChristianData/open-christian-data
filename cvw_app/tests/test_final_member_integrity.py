"""Final HTTP integrity after byte mutation; synthetic validation admission.

SourceManifest and CandidatePackage use their real loaders and byte checks.
Only validation-report admission is stubbed: this test does not attest a real
oracle, schema/fidelity validation, or governed candidate acceptance. Cached
Read/Compare observations are reported, not established as desirable behavior.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

import cvw_app.review_contract as contract
from cvw_app.launch_windows import launch
from cvw_app.review_service import make_server
from cvw_app.tests.test_launch_windows import _built_frontend
from cvw_app.tests.test_review_work_catalog import _candidate, _canonical, _work, _write_catalog
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, native_source: bool):
    repo = tmp_path / "repository"
    repo.mkdir()
    source = repo / ("source.png" if native_source else "source.html")
    source.write_bytes(
        (Path(__file__).resolve().parents[1] / "fixtures/review-v1/artifacts/binary-contract/facsimile.png").read_bytes()
        if native_source else b"<html><body><p>Faithful source text.</p></body></html>"
    )
    source_record = {
        "contract": "ocd-source-manifest-v1", "source_id": "source-fixture",
        "authorities": [{"name": "source", "role": "primary-source", "path": source.name,
                         "bytes": source.stat().st_size, "sha256": _sha(source.read_bytes())}],
    }
    for name in ("converter", "validator", "package_schema"):
        dependency = repo / (name + (".json" if name == "package_schema" else ".py"))
        dependency.write_bytes(b"{}\n" if name == "package_schema" else b"# fixture authority\n")
        source_record[name] = {
            "path" if name == "package_schema" else "implementation_path": dependency.name,
            "sha256" if name == "package_schema" else "implementation_sha256": _sha(dependency.read_bytes()),
        }
        if name != "package_schema":
            source_record[name].update(id=f"fixture-{name}", version="1", callable="fixture:run", import_closure_sha256="a" * 64)
    manifest = repo / "fixture.source-manifest.json"
    manifest.write_bytes(_canonical(source_record))
    loaded_source = SourceManifest.load(manifest, repository_root=repo)

    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    scaffold = _candidate(candidate_dir, "source-fixture", manifest.name, "b" * 64)
    package = scaffold.path
    for name in scaffold.member_names:
        if name != "manifest.json" and not (package / name).exists():
            (package / name).write_bytes(b"{}\n" if name.endswith(".json") else b"")
    member_files = sorted(path for path in package.iterdir() if path.name != "manifest.json")
    package_manifest = {
        "contract": "ocd-candidate-package-v1", "source_id": "source-fixture",
        "source_manifest": {"path": manifest.name, "sha256": loaded_source.sha256},
        "converter": {"id": "fixture-converter", "version": "1"},
        "package_schema": source_record["package_schema"],
        "members": [{"name": path.name, "bytes": path.stat().st_size, "sha256": _sha(path.read_bytes())} for path in member_files],
    }
    (package / "manifest.json").write_bytes(_canonical(package_manifest))
    loaded_candidate = CandidatePackage.load(package)
    monkeypatch.setattr(
        contract, "_load_validation_report",
        lambda candidate_path, source_manifest, candidate, **kwargs: SimpleNamespace(
            status="pass", sha256="d" * 64, candidate_sha256=candidate.sha256,
            source_manifest_sha256=source_manifest.sha256,
        ),
    )
    catalog = _write_catalog(repo, [_work("fixture", source_id="source-fixture", manifest=manifest.name)])
    return repo, catalog, candidate_dir, source, loaded_candidate


def _get(server, route):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    try:
        connection.request("GET", route)
        response = connection.getresponse()
        body = response.read()
        assert len(body) == int(response.getheader("Content-Length"))
        return response.status, response.getheader("X-CVW-Request-ID"), body
    finally:
        connection.close()


@pytest.mark.parametrize("target", ["candidate-exact", "source-native-bytes"])
def test_final_access_rejects_changed_member_after_initial_access(tmp_path, monkeypatch, target):
    repo, catalog, candidate_dir, source, candidate = _fixture(
        tmp_path, monkeypatch, native_source=target == "source-native-bytes",
    )
    stage_id, suffix = ("tei", "exact") if target == "candidate-exact" else ("source", "bytes")
    member = candidate.path / "content.tei.xml" if target == "candidate-exact" else source
    original = member.read_bytes()
    original_stat = member.stat()
    manifest_bytes = (candidate.path / "manifest.json").read_bytes()
    held = {}
    observation = {}

    def factory(*args, **kwargs):
        held["server"] = make_server(*args, **kwargs)
        return held["server"]

    def inspect_then_stop(url):
        server = held["server"]
        try:
            status, _, catalog_bytes = _get(server, "/api/review/v1/works")
            assert status == 200
            stages = {stage["id"]: stage["selected_artifact"] for stage in json.loads(catalog_bytes)["works"][0]["stages"]}
            selected = stages[stage_id]
            query = urlencode({"expected_artifact": selected["id"], "expected_version": selected["version"]})
            base = f"/api/review/v1/works/fixture/stages/{stage_id}"
            access_route = f"{base}/{suffix}?{query}"
            stage_route = f"{base}?{query}&location=start"
            compare_route = "/api/review/v1/works/fixture/compare?" + urlencode({
                "left_stage": "source", "left_artifact": stages["source"]["id"], "left_version": stages["source"]["version"], "left_location": "start",
                "right_stage": "tei", "right_artifact": stages["tei"]["id"], "right_version": stages["tei"]["version"], "right_location": "start",
                "linked": "false", "correspondence": "absent",
            })
            assert _get(server, access_route)[::2] == (200, original)
            initial_stage_status, _, initial_stage_bytes = _get(server, stage_route)
            assert initial_stage_status == 200
            assert json.loads(initial_stage_bytes)["artifact"]["sha256"] == _sha(original)
            assert _get(server, compare_route)[0] == 200
            mutated = original.replace(b"Faithful", b"Tampered", 1) if target == "candidate-exact" else original[:-1] + bytes([original[-1] ^ 1])
            assert len(mutated) == len(original) and _sha(mutated) != _sha(original)
            member.write_bytes(mutated)
            os.utime(member, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            assert member.stat().st_mtime_ns == original_stat.st_mtime_ns

            status, request_id, rejected = _get(server, access_route)
            assert status == 422
            error = json.loads(rejected)["error"]
            assert error["code"] == "artifact-invalid"
            # Both the initial artifact loader and the final byte reader may
            # detect this mutation. Preserve the rejection contract without
            # depending on which integrity check runs first.
            assert any(message in error["message"] for message in (
                "artifact bytes no longer match the declared sha256",
                "artifact bytes do not match declared sha256",
            ))
            assert error["request_id"] == request_id
            assert rejected not in (original, mutated)
            if target == "candidate-exact":
                assert b"Faithful candidate text" not in rejected
                assert b"Tampered candidate text" not in rejected
            assert (candidate.path / "manifest.json").read_bytes() == manifest_bytes
            assert candidate.sha256 == _sha(manifest_bytes)

            stage_status, _, stage_bytes = _get(server, stage_route)
            compare_status, _, compare_bytes = _get(server, compare_route)
            stage_after = json.loads(stage_bytes)
            compare_after = json.loads(compare_bytes)
            pane = compare_after.get("right" if stage_id == "tei" else "left", {})
            # Report cache behavior without enshrining stale Read/Compare as a
            # success requirement. The actual acceptance assertion is above.
            observation.update(
                target=target, admission="real SourceManifest/CandidatePackage byte checks; validation-report admission stubbed",
                member_byte_length=len(original), same_size=True, restored_mtime=True,
                original_member_sha256=_sha(original), mutated_member_sha256=_sha(mutated),
                nominal_candidate_sha256=candidate.sha256, final_route=suffix, final_status=status,
                final_error=error["message"], cached_stage_status=stage_status,
                cached_stage_availability=stage_after.get("availability"),
                cached_stage_original_digest=(stage_after.get("artifact") or {}).get("sha256") == _sha(original),
                cached_stage_cache_resident=(stage_after.get("paging") or {}).get("cache_resident"),
                cached_stage_contains_old_text=b"Faithful candidate text" in stage_bytes if stage_id == "tei" else None,
                cached_compare_status=compare_status, cached_compare_availability=pane.get("availability"),
                cached_compare_original_digest=(pane.get("artifact") or {}).get("sha256") == _sha(original),
                cached_compare_contains_old_text=b"Faithful candidate text" in compare_bytes if stage_id == "tei" else None,
            )
            assert (stage_after.get("artifact") or {}).get("sha256") != _sha(mutated)
            assert (pane.get("artifact") or {}).get("sha256") != _sha(mutated)
        finally:
            server.shutdown()
        return False

    launch(catalog, [candidate_dir], repository_root=repo, static_root=_built_frontend(tmp_path),
           server_factory=factory, browser_open=inspect_then_stop, output=lambda line: None)
    assert held["server"].socket.fileno() == -1
    print("CVW_MEMBER_INTEGRITY_OBSERVATION " + json.dumps(observation, sort_keys=True))
