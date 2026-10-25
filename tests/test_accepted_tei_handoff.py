from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from pathlib import Path

import jsonschema
import pytest
from lxml import etree


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "boundary" / "accepted-tei-handoff" / "v1" / "accepted-tei-handoff.schema.json"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "accepted-tei-handoff" / "v1" / "valid"
TEI_NS = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_NS}
PROOF_NAMES = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")


def _schema() -> dict[str, object]:
    return _load_json(SCHEMA_PATH)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        assert key not in result, f"duplicate JSON key: {key}"
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    assert isinstance(value, dict), f"expected JSON object: {path}"
    return value


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")


def _handoff(package: Path) -> dict[str, object]:
    return _load_json(package / "handoff.json")


def _copy_fixture(tmp_path: Path) -> Path:
    package = tmp_path / "package"
    package.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FIXTURE_ROOT, package)
    return package


def _validate_schema(package: Path) -> dict[str, object]:
    handoff = _handoff(package)
    validator = jsonschema.Draft202012Validator(
        _schema(), format_checker=jsonschema.FormatChecker()
    )
    errors = sorted(validator.iter_errors(handoff), key=lambda error: list(error.path))
    assert not errors, "; ".join(error.message for error in errors)
    return handoff


def _assert_schema_rejects(package: Path) -> None:
    handoff = _handoff(package)
    validator = jsonschema.Draft202012Validator(
        _schema(), format_checker=jsonschema.FormatChecker()
    )
    assert list(validator.iter_errors(handoff)), "mutation unexpectedly passed schema"


def _binding(package: Path, binding: dict[str, object]) -> Path:
    reference = binding.get("path")
    assert isinstance(reference, str), "binding path is not text"
    assert ":" not in reference and all(
        part not in {"", ".", ".."} for part in reference.split("/")
    ), f"binding path is not portable: {reference}"
    relative = Path(reference)
    assert not relative.is_absolute(), f"binding path is absolute: {reference}"
    assert "\\" not in reference, f"binding path uses a backslash: {reference}"
    assert ".." not in relative.parts, f"binding path escapes package: {reference}"
    current = package
    assert not _is_reparse(current), f"package root is a reparse point: {current}"
    for part in relative.parts:
        current = current / part
        assert not _is_reparse(current), f"binding path uses a reparse point: {reference}"
    target = (package / Path(*relative.parts)).resolve()
    try:
        target.relative_to(package.resolve())
    except ValueError as exc:
        raise AssertionError(f"binding path escapes package: {reference}") from exc
    assert target.is_file(), f"binding target does not exist: {reference}"
    payload = target.read_bytes()
    assert len(payload) == binding.get("bytes"), f"binding byte mismatch: {reference}"
    assert hashlib.sha256(payload).hexdigest() == binding.get("sha256"), f"binding hash mismatch: {reference}"
    return target


def _is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _member_index(items: list[dict[str, object]], *, field: str) -> dict[str, dict[str, object]]:
    paths = [item["path"] for item in items]
    positions = [item["position"] for item in items]
    assert len(paths) == len(set(paths)), f"{field} contains duplicate member paths"
    assert len(positions) == len(set(positions)), f"{field} contains duplicate member positions"
    return {str(item["path"]): item for item in items}


def _refresh_binding(package: Path, binding: dict[str, object]) -> None:
    target = package / Path(*str(binding["path"]).split("/"))
    payload = target.read_bytes()
    binding["bytes"] = len(payload)
    binding["sha256"] = hashlib.sha256(payload).hexdigest()


def _rebind_accepted_tei_claims(package: Path, handoff: dict[str, object]) -> None:
    _refresh_binding(package, handoff["accepted_tei"])
    for name in PROOF_NAMES:
        proof = handoff["technical"][name]
        evidence_path = package / str(proof["evidence"]["path"])
        document = _load_json(evidence_path)
        document["accepted_tei"] = handoff["accepted_tei"]
        _write_json(evidence_path, document)
        _refresh_binding(package, proof["evidence"])
    review = handoff["review"]
    review_path = package / str(review["report"]["path"])
    review_document = _load_json(review_path)
    review_document["accepted_tei"] = handoff["accepted_tei"]
    _write_json(review_path, review_document)
    _refresh_binding(package, review["report"])
    _write_json(package / "handoff.json", handoff)


def _source_claim(source: dict[str, object]) -> dict[str, object]:
    return {
        "source_path": source["source_path"],
        "source_sha256": source["source_sha256"],
        "source_bytes": source["source_bytes"],
        "source_scope": source["source_scope"],
    }


def _scope_claim(scope: dict[str, object]) -> dict[str, object]:
    return {"kind": scope["kind"], "declared": scope["declared"]}


def _within(locus: str, parents: set[str]) -> bool:
    return any(locus == parent or locus.startswith(parent.rstrip("/") + "/") for parent in parents)


def _overlap(left: str, right: str) -> bool:
    return (
        left == right
        or left.startswith(right.rstrip("/") + "/")
        or right.startswith(left.rstrip("/") + "/")
    )


def _validate_handoff(package: Path) -> dict[str, object]:
    handoff = _validate_schema(package)
    identity = handoff["identity"]
    accepted_tei = handoff["accepted_tei"]
    source = handoff["source"]
    scope = handoff["scope"]
    assert isinstance(identity, dict)
    assert isinstance(accepted_tei, dict)
    assert isinstance(source, dict)
    assert isinstance(scope, dict)
    _binding(package, accepted_tei)

    expected = _member_index(scope["expected_members"], field="scope.expected_members")
    included = _member_index(scope["included_members"], field="scope.included_members")
    excluded = _member_index(scope["excluded_members"], field="scope.excluded_members")
    assert included, "accepted handoff must include a source member"
    assert not set(included) & set(excluded), "scope member is both included and excluded"
    assert set(included) | set(excluded) == set(expected), "scope envelope is not closed"
    for path, item in included.items():
        assert expected[path]["position"] == item["position"], f"scope position mismatch: {path}"
        assert item["scope"] == scope["declared"], f"scope claim mismatch: {path}"
        _binding(
            package,
            {"path": path, "bytes": item["bytes"], "sha256": item["sha256"]},
        )
    for path, item in excluded.items():
        assert expected[path]["position"] == item["position"], f"scope position mismatch: {path}"
    source_expected = _member_index(source["expected_members"], field="source.expected_members")
    source_included = _member_index(source["included_members"], field="source.included_members")
    source_excluded = _member_index(source["excluded_members"], field="source.excluded_members")
    assert source_expected == expected, "source expected envelope drifted"
    assert source_included == included, "source included envelope drifted"
    assert source_excluded == excluded, "source excluded envelope drifted"
    unavailable = set(source["missing_members"]) | set(source["unknown_members"])
    assert unavailable <= set(expected), "missing or unknown member is outside expected envelope"
    assert unavailable <= set(excluded), "missing or unknown member is not explicitly excluded"
    assert not unavailable & set(included), "included member is unavailable"
    assert not set(source["missing_members"]) & set(source["unknown_members"]), "member is both missing and unknown"
    if scope["kind"] in {"work", "edition"}:
        assert not excluded and not unavailable, "whole scope hides excluded or unavailable members"

    source_file = source["source_file"]
    assert isinstance(source_file, dict)
    source_target = _binding(package, source_file)
    assert source_file["path"] == source["source_path"]
    assert source_file["bytes"] == source["source_bytes"]
    assert source_file["sha256"] == source["source_sha256"]
    assert source_target.name == Path(str(source["source_path"])).name

    for field in ("acquisition_record", "source_manifest", "accounting"):
        assert isinstance(source[field], dict)
        _binding(package, source[field])
    acquisition = _load_json(package / str(source["acquisition_record"]["path"]))
    assert acquisition["identity"] == identity, "acquisition identity drifted"
    assert acquisition["source"] == _source_claim(source), "acquisition source binding drifted"
    assert acquisition["source_file"] == source_file, "acquisition file binding drifted"
    retained = _member_index(acquisition["retained_members"], field="acquisition.retained_members")
    assert set(retained) <= set(expected), "acquisition retained member is outside expected envelope"
    assert not set(retained) & unavailable, "a retained member cannot be missing or unknown"
    for path, item in retained.items():
        assert expected[path]["position"] == item["position"], f"acquisition position mismatch: {path}"
        assert item["scope"] == scope["declared"], f"acquisition scope mismatch: {path}"
        _binding(
            package,
            {"path": path, "bytes": item["bytes"], "sha256": item["sha256"]},
        )
        if path in included:
            assert item["bytes"] == included[path]["bytes"]
            assert item["sha256"] == included[path]["sha256"]
    manifest = _load_json(package / str(source["source_manifest"]["path"]))
    accounting = _load_json(package / str(source["accounting"]["path"]))
    for document in (manifest, accounting):
        assert document["identity"] == identity, "source evidence identity drifted"
        assert document["source"] == _source_claim(source), "source evidence binding drifted"
        assert document["accepted_scope"] == _scope_claim(scope), "source evidence scope drifted"
        assert document["expected_members"] == scope["expected_members"]
        assert document["included_members"] == scope["included_members"]
        assert document["excluded_members"] == scope["excluded_members"]
        assert document["missing_members"] == source["missing_members"]
        assert document["unknown_members"] == source["unknown_members"]

    for name in PROOF_NAMES:
        proof = handoff["technical"][name]
        assert isinstance(proof, dict)
        proof_target = _binding(package, proof["evidence"])
        document = _load_json(proof_target)
        assert document["identity"] == identity, f"{name} identity drifted"
        assert document["accepted_tei"] == accepted_tei, f"{name} TEI binding drifted"
        assert document["source"] == _source_claim(source), f"{name} source binding drifted"
        assert document["scope"] == _scope_claim(scope), f"{name} scope binding drifted"
        assert document["status"] == proof["status"] == "pass"
        assert document["command"] == proof["command"]
        assert document["exit_code"] == proof["exit_code"] == 0
        if name == "accounting":
            assert document["accepted_scope"] == _scope_claim(scope)
            assert document["expected_members"] == scope["expected_members"]
            assert document["included_members"] == scope["included_members"]
            assert document["excluded_members"] == scope["excluded_members"]
            assert document["missing_members"] == source["missing_members"]
            assert document["unknown_members"] == source["unknown_members"]

    review = handoff["review"]
    assert isinstance(review, dict)
    review_target = _binding(package, review["report"])
    review_document = _load_json(review_target)
    assert review_document["identity"] == identity, "review identity drifted"
    assert review_document["accepted_tei"] == accepted_tei, "review TEI binding drifted"
    assert review_document["source"] == _source_claim(source), "review source binding drifted"
    assert review_document["scope"] == _scope_claim(scope), "review scope binding drifted"
    for key in ("reviewer", "reviewed_at", "coverage", "source_quality_uncertainty", "discrepancies", "unreviewed_residuals"):
        assert review_document[key] == review[key], f"review {key} drifted"
    coverage = review["coverage"]
    assert coverage["declared"] == scope["declared"], "review coverage scope drifted"
    reached = set(coverage["reached"])
    inspected = set(coverage["inspected"])
    unreviewed = set(coverage["unreviewed"])
    assert all(_within(locus, reached) for locus in inspected), "inspected locus is outside reached coverage"
    assert not any(_overlap(left, right) for left in inspected for right in unreviewed), "inspected locus is unreviewed"
    if coverage["status"] == "partial":
        assert coverage["unreviewed"] or review["unreviewed_residuals"]
    if coverage["status"] == "complete":
        assert not coverage["unreviewed"], "complete review cannot carry unreviewed loci"
        assert not review["unreviewed_residuals"], "complete review cannot carry unreviewed residuals"

    tei_path = package / str(accepted_tei["path"])
    tree = etree.parse(str(tei_path))
    root = tree.getroot()
    assert etree.QName(root).localname == "TEI"
    headers = root.xpath("./tei:teiHeader", namespaces=NS)
    assert len(headers) == 1
    idnos: dict[str, str] = {}
    for node in headers[0].xpath(".//tei:idno[@type]", namespaces=NS):
        kind = str(node.get("type"))
        value = "".join(node.itertext()).strip()
        if kind in idnos and idnos[kind] != value:
            raise AssertionError(f"conflicting TEI header idno values: {kind}")
        idnos[kind] = value
    for key, value in identity.items():
        assert idnos[key] == value, f"TEI {key} drifted"
    assert idnos["source_sha256"] == source["source_sha256"]
    assert idnos["source_bytes"] == str(source["source_bytes"])
    assert idnos["representation_revision"] == handoff["representation_revision"]["id"]
    pointers = [
        str(node.get("target"))
        for node in headers[0].xpath(".//tei:sourceDesc//tei:ptr[@target]", namespaces=NS)
    ]
    assert len(set(pointers)) <= 1, "conflicting TEI header sourceDesc pointers"
    acquisition_url = acquisition.get("url")
    assert pointers and pointers[0] == acquisition_url, "TEI sourceDesc pointer does not bind acquisition"
    changes = headers[0].xpath("./tei:revisionDesc/tei:change", namespaces=NS)
    revision = handoff["representation_revision"]
    matching_changes = [
        change
        for change in changes
        if change.get("{http://www.w3.org/XML/1998/namespace}id") == revision["id"]
    ]
    assert len(matching_changes) == 1, "TEI current revision must occur exactly once"
    assert any(
        change.get("{http://www.w3.org/XML/1998/namespace}id") == revision["id"]
        and change.get("when") == revision["date"]
        and "".join(change.itertext()).strip() == revision["note"]
        for change in changes
    ), "TEI revision is not bound"
    notes: dict[str, str] = {}
    for node in headers[0].xpath(".//tei:note[@type]", namespaces=NS):
        kind = str(node.get("type"))
        value = "".join(node.itertext()).strip()
        if kind in notes and notes[kind] != value:
            raise AssertionError(f"conflicting TEI header note values: {kind}")
        notes[kind] = value
    assert notes["source-location"] == source["source_path"]
    assert notes["source-scope"] == scope["declared"]

    decision = handoff["decision"]
    agent = decision["agent_assessment"]
    human = decision["human_decision"]
    if agent["status"] == "accepted":
        assert agent["supported_scope"] == scope["declared"]
    if human["status"] != "not-recorded":
        for key in ("actor", "decided_at", "scope", "note"):
            assert human.get(key), f"recorded human decision lacks {key}"
        if human["status"] == "accepted":
            assert human["scope"] == scope["declared"]
    if (
        agent["status"] == "accepted"
        and human["status"] in {"rejected", "blocked"}
    ):
        raise AssertionError("human decision conflicts with accepted agent assessment")
    assert agent["status"] == "accepted" or human["status"] == "accepted", (
        "handoff requires an accepted agent or human decision"
    )
    if decision["blockers"] and (agent["status"] == "accepted" or human["status"] == "accepted"):
        raise AssertionError("accepted handoff cannot carry blockers")
    return handoff


def test_synthetic_handoff_schema_and_evidence_bindings_are_portable() -> None:
    handoff = _validate_handoff(FIXTURE_ROOT)
    assert handoff["decision"]["human_decision"]["status"] == "not-recorded"


def test_stale_tei_bytes_are_rejected(tmp_path: Path) -> None:
    package = _copy_fixture(tmp_path)
    target = package / "accepted.tei.xml"
    target.write_bytes(target.read_bytes() + b"\n")

    with pytest.raises(AssertionError, match="binding (byte|hash) mismatch"):
        _validate_handoff(package)


def test_missing_evidence_is_rejected(tmp_path: Path) -> None:
    package = _copy_fixture(tmp_path)
    (package / "evidence" / "validation.json").unlink()

    with pytest.raises(AssertionError, match="binding target does not exist"):
        _validate_handoff(package)


def test_path_escape_and_closed_properties_are_rejected_by_schema(tmp_path: Path) -> None:
    package = _copy_fixture(tmp_path)
    handoff = _handoff(package)
    handoff["technical"]["validation"]["evidence"]["path"] = "../validation.json"
    _write_json(package / "handoff.json", handoff)
    _assert_schema_rejects(package)

    package = _copy_fixture(tmp_path / "closed")
    handoff = _handoff(package)
    handoff["unexpected"] = True
    _write_json(package / "handoff.json", handoff)
    _assert_schema_rejects(package)


@pytest.mark.parametrize("bad_path", ["a:b.json", "a//b.json", "a/./b.json", "a/../b.json", "a/"])
def test_package_paths_reject_ads_empty_and_dot_segments(tmp_path: Path, bad_path: str) -> None:
    package = _copy_fixture(tmp_path)
    handoff = _handoff(package)
    handoff["technical"]["validation"]["evidence"]["path"] = bad_path
    _write_json(package / "handoff.json", handoff)
    _assert_schema_rejects(package)
    with pytest.raises(AssertionError, match="not portable"):
        _binding(package, {"path": bad_path, "bytes": 0, "sha256": "0" * 64})


@pytest.mark.parametrize("document", ["handoff", "proof"])
def test_duplicate_json_fields_are_rejected(tmp_path: Path, document: str) -> None:
    package = _copy_fixture(tmp_path)
    handoff = _handoff(package)
    if document == "handoff":
        path = package / "handoff.json"
        content = path.read_text(encoding="utf-8")
        path.write_text(content.replace('"schema_version":', '"schema_version":"invalid","schema_version":', 1), encoding="utf-8")
    else:
        binding = handoff["technical"]["validation"]["evidence"]
        path = package / binding["path"]
        content = path.read_text(encoding="utf-8")
        path.write_text(content.replace('"status":', '"status":"blocked","status":', 1), encoding="utf-8")
        _refresh_binding(package, binding)
        _write_json(package / "handoff.json", handoff)
    with pytest.raises(AssertionError, match="duplicate JSON key"):
        _validate_handoff(package)


def test_member_paths_and_positions_cannot_be_overwritten(tmp_path: Path) -> None:
    package = _copy_fixture(tmp_path)
    handoff = _handoff(package)
    handoff["scope"]["expected_members"].append({"path": "source-member.xml", "position": 2})
    _write_json(package / "handoff.json", handoff)
    with pytest.raises(AssertionError, match="duplicate member paths"):
        _validate_handoff(package)

    package = _copy_fixture(tmp_path / "position")
    handoff = _handoff(package)
    handoff["scope"]["expected_members"].append({"path": "another-member.xml", "position": 1})
    _write_json(package / "handoff.json", handoff)
    with pytest.raises(AssertionError, match="duplicate member positions"):
        _validate_handoff(package)


def test_reparse_point_evidence_path_is_rejected(tmp_path: Path) -> None:
    package = _copy_fixture(tmp_path)
    link = package / "linked.tei.xml"
    try:
        os.symlink("accepted.tei.xml", link)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    handoff = _handoff(package)
    handoff["accepted_tei"]["path"] = "linked.tei.xml"
    _refresh_binding(package, handoff["accepted_tei"])
    _write_json(package / "handoff.json", handoff)

    with pytest.raises(AssertionError, match="reparse point"):
        _validate_handoff(package)


def test_identity_scope_and_review_drift_are_rejected_after_rebinding_bytes(tmp_path: Path) -> None:
    package = _copy_fixture(tmp_path)
    handoff = _handoff(package)
    document_path = package / "evidence" / "validation.json"
    document = _load_json(document_path)
    document["identity"]["edition_id"] = "different-edition"
    _write_json(document_path, document)
    _refresh_binding(package, handoff["technical"]["validation"]["evidence"])
    _write_json(package / "handoff.json", handoff)

    with pytest.raises(AssertionError, match="identity drifted"):
        _validate_handoff(package)

    package = _copy_fixture(tmp_path / "review")
    handoff = _handoff(package)
    document_path = package / "evidence" / "review.json"
    document = _load_json(document_path)
    document["coverage"]["declared"] = "div1[@id='other']"
    _write_json(document_path, document)
    _refresh_binding(package, handoff["review"]["report"])
    _write_json(package / "handoff.json", handoff)

    with pytest.raises(AssertionError, match="review coverage( scope)? drifted"):
        _validate_handoff(package)


def test_tei_header_conflicts_and_duplicate_current_revision_are_rejected(tmp_path: Path) -> None:
    package = _copy_fixture(tmp_path / "idno")
    target = package / "accepted.tei.xml"
    text = target.read_text(encoding="utf-8")
    text = text.replace(
        '<idno type="edition_id">synthetic-edition</idno>',
        '<idno type="edition_id">synthetic-edition</idno><idno type="edition_id">other-edition</idno>',
    )
    target.write_text(text, encoding="utf-8", newline="\n")
    handoff = _handoff(package)
    _rebind_accepted_tei_claims(package, handoff)
    with pytest.raises(AssertionError, match="conflicting TEI header idno"):
        _validate_handoff(package)

    package = _copy_fixture(tmp_path / "note")
    target = package / "accepted.tei.xml"
    text = target.read_text(encoding="utf-8")
    text = text.replace(
        '<note type="source-scope">div1[@id=\'unit\']</note>',
        '<note type="source-scope">div1[@id=\'unit\']</note><note type="source-scope">other-scope</note>',
    )
    target.write_text(text, encoding="utf-8", newline="\n")
    handoff = _handoff(package)
    _rebind_accepted_tei_claims(package, handoff)
    with pytest.raises(AssertionError, match="conflicting TEI header note"):
        _validate_handoff(package)

    package = _copy_fixture(tmp_path / "pointer")
    target = package / "accepted.tei.xml"
    text = target.read_text(encoding="utf-8")
    text = text.replace(
        '<ptr target="https://example.invalid/synthetic-source.xml"/>',
        '<ptr target="https://example.invalid/synthetic-source.xml"/><ptr target="https://example.invalid/other.xml"/>',
    )
    target.write_text(text, encoding="utf-8", newline="\n")
    handoff = _handoff(package)
    _rebind_accepted_tei_claims(package, handoff)
    with pytest.raises(AssertionError, match="conflicting TEI header sourceDesc pointers"):
        _validate_handoff(package)

    package = _copy_fixture(tmp_path / "revision")
    target = package / "accepted.tei.xml"
    text = target.read_text(encoding="utf-8")
    text = text.replace(
        '<change xml:id="handoff-v1" when="2026-09-06">Synthetic accepted handoff fixture.</change>',
        '<change xml:id="handoff-v1" when="2026-09-07">Conflicting current revision.</change>',
    )
    target.write_text(text, encoding="utf-8", newline="\n")
    handoff = _handoff(package)
    _rebind_accepted_tei_claims(package, handoff)
    with pytest.raises(AssertionError, match="revision is not bound"):
        _validate_handoff(package)


def test_complete_review_cannot_carry_unreviewed_coverage_or_residuals(tmp_path: Path) -> None:
    package = _copy_fixture(tmp_path / "coverage")
    handoff = _handoff(package)
    review_path = package / "evidence" / "review.json"
    review_document = _load_json(review_path)
    review_document["coverage"]["status"] = "complete"
    _write_json(review_path, review_document)
    _refresh_binding(package, handoff["review"]["report"])
    handoff["review"]["coverage"] = review_document["coverage"]
    _write_json(package / "handoff.json", handoff)
    with pytest.raises(AssertionError, match="complete review cannot carry unreviewed loci"):
        _validate_handoff(package)

    package = _copy_fixture(tmp_path / "residual")
    handoff = _handoff(package)
    review_path = package / "evidence" / "review.json"
    review_document = _load_json(review_path)
    review_document["coverage"]["status"] = "complete"
    review_document["coverage"]["unreviewed"] = []
    _write_json(review_path, review_document)
    _refresh_binding(package, handoff["review"]["report"])
    handoff["review"]["coverage"] = review_document["coverage"]
    _write_json(package / "handoff.json", handoff)
    with pytest.raises(AssertionError, match="complete review cannot carry unreviewed residuals"):
        _validate_handoff(package)


def test_partial_human_scope_and_human_acceptance_are_supported(tmp_path: Path) -> None:
    package = _copy_fixture(tmp_path / "partial")
    handoff = _handoff(package)
    handoff["decision"]["human_decision"] = {
        "status": "partial",
        "actor": "human:synthetic",
        "decided_at": "2026-09-06T10:10:00Z",
        "scope": "div1[@id='unit']/head",
        "note": "Synthetic partial review of a narrower locus.",
    }
    _write_json(package / "handoff.json", handoff)
    _validate_handoff(package)

    package = _copy_fixture(tmp_path / "human")
    handoff = _handoff(package)
    handoff["decision"]["agent_assessment"]["status"] = "partial"
    handoff["decision"]["agent_assessment"]["supported_scope"] = "div1[@id='unit']/head"
    handoff["decision"]["human_decision"] = {
        "status": "accepted",
        "actor": "human:synthetic",
        "decided_at": "2026-09-06T10:10:00Z",
        "scope": handoff["scope"]["declared"],
        "note": "Synthetic human acceptance for the declared fixture scope.",
    }
    _write_json(package / "handoff.json", handoff)
    _validate_handoff(package)


@pytest.mark.parametrize("status", ["rejected", "blocked"])
def test_narrow_human_rejection_conflicts_with_agent_acceptance(tmp_path: Path, status: str) -> None:
    package = _copy_fixture(tmp_path)
    handoff = _handoff(package)
    handoff["decision"]["human_decision"] = {
        "status": status,
        "actor": "human:synthetic",
        "decided_at": "2026-09-06T10:10:00Z",
        "scope": handoff["scope"]["declared"] + "/head",
        "note": "Synthetic conflicting decision on a narrower locus.",
    }
    _write_json(package / "handoff.json", handoff)
    with pytest.raises(AssertionError, match="human decision conflicts"):
        _validate_handoff(package)


def test_source_envelope_and_decision_boundaries_are_rejected(tmp_path: Path) -> None:
    package = _copy_fixture(tmp_path)
    handoff = _handoff(package)
    handoff["source"]["missing_members"] = ["source-member.xml"]
    _write_json(package / "handoff.json", handoff)

    with pytest.raises(AssertionError, match="explicitly excluded"):
        _validate_handoff(package)

    package = _copy_fixture(tmp_path / "decision")
    handoff = _handoff(package)
    handoff["decision"]["human_decision"] = {
        "status": "rejected",
        "actor": "human:synthetic",
        "decided_at": "2026-09-06T10:10:00Z",
        "scope": handoff["scope"]["declared"],
        "note": "Synthetic contradiction for conformance testing."
    }
    _write_json(package / "handoff.json", handoff)

    with pytest.raises(AssertionError, match="human decision conflicts"):
        _validate_handoff(package)


def test_retained_acquisition_members_cannot_be_called_missing(tmp_path: Path) -> None:
    package = _copy_fixture(tmp_path)
    handoff = _handoff(package)
    second_path = "retained-member-2.xml"
    second_payload = b"<source>retained second member</source>\n"
    (package / second_path).write_bytes(second_payload)
    second = {
        "path": second_path,
        "position": 2,
        "bytes": len(second_payload),
        "sha256": hashlib.sha256(second_payload).hexdigest(),
        "scope": handoff["scope"]["declared"],
    }
    second_reference = {"path": second_path, "position": 2}
    second_excluded = {
        "path": second_path,
        "position": 2,
        "reason": "Synthetic member is outside the selected accepted scope.",
    }
    for record in (handoff["scope"], handoff["source"]):
        record["expected_members"].append(second_reference)
        record["excluded_members"].append(second_excluded)
    handoff["source"]["missing_members"] = [second_path]
    acquisition_binding = handoff["source"]["acquisition_record"]
    acquisition_path = package / str(acquisition_binding["path"])
    acquisition = _load_json(acquisition_path)
    acquisition["retained_members"].append(second)
    _write_json(acquisition_path, acquisition)
    _refresh_binding(package, acquisition_binding)

    evidence_records = [
        handoff["source"]["source_manifest"],
        handoff["source"]["accounting"],
        handoff["technical"]["accounting"]["evidence"],
    ]
    for binding in evidence_records:
        evidence_path = package / str(binding["path"])
        document = _load_json(evidence_path)
        document["expected_members"] = handoff["scope"]["expected_members"]
        document["included_members"] = handoff["scope"]["included_members"]
        document["excluded_members"] = handoff["scope"]["excluded_members"]
        document["missing_members"] = handoff["source"]["missing_members"]
        document["unknown_members"] = handoff["source"]["unknown_members"]
        _write_json(evidence_path, document)
        _refresh_binding(package, binding)
    _write_json(package / "handoff.json", handoff)

    with pytest.raises(AssertionError, match="retained member cannot be missing"):
        _validate_handoff(package)
