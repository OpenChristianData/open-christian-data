"""Accepted-master entry points for the sermons and prayers categories."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from lxml import etree as E

from ocd_kernel.library._common import PipelineError, canonical_bytes


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "library-pipeline" / "categories"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
_CATEGORIES = {"sermons", "prayers"}


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def _case(category: str) -> tuple[Path, dict[str, Any]]:
    if category not in _CATEGORIES:
        raise ValueError(f"unsupported accepted fixture category: {category}")
    fixture = FIXTURE_ROOT / category
    manifest = json.loads((fixture / "manifest.json").read_text(encoding="utf-8"))
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise AssertionError(f"fixture manifest has no cases: {category}")
    return fixture, cases[0]


def accepted_fixture(tmp_path: Path, category: str, *, native_attribution: bool = False) -> tuple[Path, Path]:
    """Create one unpromoted, schema-valid accepted-master fixture.

    The returned root contains canonical library sidecars, a candidate TEI,
    retained source witness, and the complete acceptance evidence envelope.
    Promotion is deliberately left to the caller so entry points and release
    assembly exercise the same promotion boundary as production.
    """

    from ocd_kernel.tei.acceptance import (
        build_acceptance_record,
        make_file_binding,
        write_acceptance,
    )

    fixture, case = _case(category)
    context = case["context"]
    identity = {
        **context["identity"],
        "acquisition_id": f"fixture-{category}-accepted",
    }
    base = Path(tmp_path).resolve()
    edition = (
        base
        / "library"
        / "works"
        / identity["work_id"]
        / "forms"
        / identity["textual_form_id"]
        / "editions"
        / identity["edition_id"]
    )
    edition.mkdir(parents=True, exist_ok=True)

    title = context["edition_title"]
    work = {
        "schema_version": "2.0",
        "work_id": identity["work_id"],
        "title": title,
        "textual_forms": [
            {
                "textual_form_id": identity["textual_form_id"],
                "language": context["language"],
                "category": category,
                "editions": [
                    {
                        "edition_id": identity["edition_id"],
                        "title": title,
                        "language": context["language"],
                        "category": category,
                    }
                ],
            }
        ],
        "evidence": [f"fixture://{category}"],
    }
    _write_json(base / "library" / "works" / identity["work_id"] / "work.json", work)
    _write_json(
        base / "library" / "works" / identity["work_id"] / "state.json",
        {
            "schema_version": "2.0",
            "work_id": identity["work_id"],
            "targets": [
                {
                    "target_id": identity["edition_id"],
                    "target_type": "edition",
                    "stage": "review",
                    "updated_at": "2026-09-09T00:00:00Z",
                    "evidence": ["candidate.xml"],
                }
            ],
        },
    )

    retained_name = case["retained_file"]
    retained = base / "retained" / retained_name
    retained.parent.mkdir(parents=True, exist_ok=True)
    retained.write_bytes((fixture / retained_name).read_bytes())
    retained_bytes = retained.read_bytes()
    retained_binding = {
        "path": f"retained/{retained_name}",
        "sha256": _sha256(retained_bytes),
        "bytes": len(retained_bytes),
        "scope": f"selected {category} units represented by the fixture TEI",
    }
    source = {
        "source_path": f"raw/fixture/{category}/{retained_name}",
        "source_sha256": retained_binding["sha256"],
        "source_bytes": retained_binding["bytes"],
        "source_scope": retained_binding["scope"],
    }
    acquisition = {
        "schema_version": "2.0",
        "acquisition_id": identity["acquisition_id"],
        "edition_id": identity["edition_id"],
        "provider": "Open Christian Data category fixture",
        "url": f"fixture://{category}/{retained_name}",
        **source,
        "retained_files": [{**retained_binding, "media_type": "application/octet-stream"}],
        "route": "born-digital",
    }
    acquisition_path = edition / "acquisitions" / f"{identity['acquisition_id']}.json"
    _write_json(acquisition_path, acquisition)

    scope = {
        "kind": "member",
        "declared": retained_binding["scope"],
        "expected_members": [{"path": retained_binding["path"], "position": 1}],
        "included_members": [{**retained_binding, "position": 1}],
        "excluded_members": [],
    }

    tree = E.parse(str(fixture / case["tei_file"]))
    if native_attribution:
        if category != "sermons":
            raise ValueError("native attribution fixture requires sermons")
        text = tree.getroot().find(f"{{{TEI_NS}}}text")
        assert text is not None
        front = E.Element(f"{{{TEI_NS}}}front")
        E.SubElement(front, f"{{{TEI_NS}}}p").text = "Synthetic collection preface."
        text.insert(0, front)
        for sermon in text.findall(f"{{{TEI_NS}}}body/{{{TEI_NS}}}div"):
            opener = sermon.find(f"{{{TEI_NS}}}opener")
            assert opener is not None
            opener.tag = f"{{{TEI_NS}}}epigraph"
            label = E.Element(f"{{{TEI_NS}}}bibl")
            label.text = opener.text
            opener.text = None
            for child in list(opener):
                label.append(child)
            opener.append(label)
        unit = text.find(f"{{{TEI_NS}}}body/{{{TEI_NS}}}div")
        assert unit is not None
        note = E.SubElement(unit, f"{{{TEI_NS}}}note", type="source-attribution")
        E.SubElement(note, f"{{{TEI_NS}}}seg", type="source-title").text = "Synthetic entry source"
        E.SubElement(note, f"{{{TEI_NS}}}seg", type="source-credit").text = "Synthetic source provider"
        E.SubElement(note, f"{{{TEI_NS}}}ref", type="source-url", target="https://example.org/entry").text = "Entry source"
    header = tree.getroot().find(f"{{{TEI_NS}}}teiHeader")
    source_desc = header.find(f".//{{{TEI_NS}}}sourceDesc") if header is not None else None
    assert header is not None and source_desc is not None
    metadata = E.SubElement(source_desc, f"{{{TEI_NS}}}bibl")
    E.SubElement(metadata, f"{{{TEI_NS}}}ptr", target=acquisition["url"])
    facts = {
        **identity,
        "source_sha256": source["source_sha256"],
        "source_bytes": str(source["source_bytes"]),
        "sha256": retained_binding["sha256"],
        "representation_revision": context["representation_revision"],
    }
    for key, value in facts.items():
        E.SubElement(metadata, f"{{{TEI_NS}}}idno", type=key).text = str(value)
    E.SubElement(metadata, f"{{{TEI_NS}}}note", type="source-location").text = source["source_path"]
    E.SubElement(metadata, f"{{{TEI_NS}}}note", type="source-scope").text = scope["declared"]
    revision_desc = E.SubElement(header, f"{{{TEI_NS}}}revisionDesc")
    change = E.SubElement(
        revision_desc,
        f"{{{TEI_NS}}}change",
        when="2026-09-09",
    )
    change.set(f"{{{XML_NS}}}id", context["representation_revision"])
    change.text = "Bound category fixture."
    candidate = base / "candidate.xml"
    candidate.write_bytes(E.tostring(tree, encoding="utf-8", xml_declaration=True))
    candidate_binding = make_file_binding(base, candidate)

    accounting = {
        "contract": "ocd-source-accounting-v1",
        "identity": identity,
        "source": source,
        **source,
        "scope": source["source_scope"],
        "accepted_scope": {"kind": scope["kind"], "declared": scope["declared"]},
        "expected_members": scope["expected_members"],
        "included_members": scope["included_members"],
        "excluded_members": scope["excluded_members"],
        "missing_members": [],
        "unknown_members": [],
    }
    source_accounting = base / "evidence" / "source-accounting.json"
    _write_json(source_accounting, accounting)

    technical: dict[str, Any] = {
        "producer": {"id": "producer:category-fixture"},
        "checker": {"id": "checker:category-fixture"},
        "shared_assumptions": ["Synthetic acceptance labels test authority binding only."],
        "independent_corroboration": "The category fixture tests preserve the selected TEI source units.",
    }
    proof_names = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")
    for name in proof_names:
        path = base / "evidence" / f"{name}.json"
        document = {
            "contract": f"ocd-tei-{name}-v1",
            "identity": identity,
            "source": source,
            "candidate": candidate_binding,
            "scope": scope["declared"],
            "status": "pass",
            "command": "simulated-acceptance-api-fixture",
            "exit_code": 0,
            "expected_members": scope["expected_members"],
            "included_members": scope["included_members"],
            "excluded_members": scope["excluded_members"],
            "missing_members": [],
            "unknown_members": [],
        }
        if name == "accounting":
            document["accepted_scope"] = {
                "kind": scope["kind"],
                "declared": scope["declared"],
            }
        _write_json(path, document)
        technical[name] = {
            "path": path,
            "status": "pass",
            "command": "simulated-acceptance-api-fixture",
            "exit_code": 0,
        }

    coverage = {
        "status": "partial",
        "declared": scope["declared"],
        "reached": [scope["declared"]],
        "inspected": [f"{scope['declared']}/API-fixture"],
        "unreviewed": ["visual acceptance"],
    }
    review = {
        "reviewer": "agent:category-fixture",
        "reviewed_at": "2026-09-09T00:00:00Z",
        "coverage": coverage,
        "source_quality_uncertainty": ["outside selected fixture scope"],
        "discrepancies": [],
        "unreviewed_residuals": ["visual acceptance not performed"],
    }
    review_path = base / "evidence" / "review.json"
    _write_json(
        review_path,
        {
            "contract": "ocd-tei-review-v1",
            "identity": identity,
            "source": source,
            "candidate": candidate_binding,
            "scope": scope["declared"],
            **review,
        },
    )
    decision = {
        "source_local_disposition": "API simulation only",
        "blockers": [],
        "agent_assessment": {
            "status": "accepted",
            "actor": "agent:category-fixture",
            "assessed_at": "2026-09-09T00:00:00Z",
            "supported_scope": scope["declared"],
            "unassessed_stronger_claims": ["real acceptance"],
            "unresolved_claims": [],
        },
        "human_decision": {"status": "not-recorded"},
    }
    record = build_acceptance_record(
        base,
        identity=identity,
        candidate_path=candidate,
        source_accounting_path=source_accounting,
        scope=scope,
        technical=technical,
        review={**review, "report_path": review_path},
        representation_revision={
            "id": context["representation_revision"],
            "date": "2026-09-09",
            "note": "Bound category fixture.",
        },
        decision=decision,
        missing_members=[],
        unknown_members=[],
    )
    acceptance_path = edition / "acceptance.json"
    write_acceptance(acceptance_path, record)
    return base, acceptance_path


@pytest.fixture
def tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Keep acceptance fixture paths short on Windows."""

    return tmp_path_factory.mktemp("sp")


@pytest.mark.parametrize("category", ["sermons", "prayers"])
def test_accepted_entry_projects_and_verifies_each_category(tmp_path: Path, category: str) -> None:
    from ocd_kernel.projection.categories import prayers, sermons
    from ocd_kernel.tei.acceptance import promote_accepted_master

    root, acceptance = accepted_fixture(tmp_path / "f", category)
    module = sermons if category == "sermons" else prayers
    project = getattr(module, f"project_accepted_{category}")
    verify = getattr(module, f"verify_accepted_{category}")
    with pytest.raises(PipelineError, match="promoted"):
        project(root, acceptance_path=acceptance)
    promoted = promote_accepted_master(root, acceptance_path=acceptance, destination=tmp_path / "p")
    output = project(promoted.destination_root, acceptance_path=promoted.acceptance_path)
    assert output["rows"]
    assert all(row["category"] == category for row in output["rows"])
    assert output["receipt"]["scope"] == "tei-document; context derived from validated acceptance"
    assert set(output["receipt"]["authority"]) == {"acceptance", "work", "master", "acquisition"}
    assert verify(
        promoted.destination_root,
        acceptance_path=promoted.acceptance_path,
        rows=output["rows"],
        receipt=output["receipt"],
    ) == []


@pytest.mark.parametrize("category", ["sermons", "prayers"])
def test_checker_rejects_stale_master_and_forged_authority(tmp_path: Path, category: str) -> None:
    from ocd_kernel.projection.categories import prayers, sermons
    from ocd_kernel.tei.acceptance import promote_accepted_master

    root, acceptance = accepted_fixture(tmp_path / "f", category)
    promoted = promote_accepted_master(root, acceptance_path=acceptance, destination=tmp_path / "p")
    module = sermons if category == "sermons" else prayers
    project = getattr(module, f"project_accepted_{category}")
    verify = getattr(module, f"verify_accepted_{category}")
    output = project(promoted.destination_root, acceptance_path=promoted.acceptance_path)
    forged = json.loads(json.dumps(output))
    forged["receipt"]["authority"]["master"]["sha256"] = "0" * 64
    assert verify(
        promoted.destination_root,
        acceptance_path=promoted.acceptance_path,
        rows=forged["rows"],
        receipt=forged["receipt"],
    )
    promoted.master_path.write_bytes(promoted.master_path.read_bytes() + b"\n")
    assert verify(
        promoted.destination_root,
        acceptance_path=promoted.acceptance_path,
        rows=output["rows"],
        receipt=output["receipt"],
    )


@pytest.mark.parametrize("category", ["sermons", "prayers"])
def test_checker_does_not_call_category_producer(tmp_path: Path, category: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from ocd_kernel.projection.categories import prayers, sermons
    from ocd_kernel.tei.acceptance import promote_accepted_master

    root, acceptance = accepted_fixture(tmp_path / "f", category)
    promoted = promote_accepted_master(root, acceptance_path=acceptance, destination=tmp_path / "p")
    module = sermons if category == "sermons" else prayers
    project = getattr(module, f"project_accepted_{category}")
    verify = getattr(module, f"verify_accepted_{category}")
    output = project(promoted.destination_root, acceptance_path=promoted.acceptance_path)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("accepted checker called category producer")

    monkeypatch.setattr(module, f"project_{category}_document", forbidden)
    assert verify(
        promoted.destination_root,
        acceptance_path=promoted.acceptance_path,
        rows=output["rows"],
        receipt=output["receipt"],
    ) == []


@pytest.mark.parametrize("category", ["sermons", "prayers"])
def test_accepted_entry_rejects_canonical_category_mismatch(tmp_path: Path, category: str) -> None:
    from ocd_kernel.projection.categories import prayers, sermons
    from ocd_kernel.tei.acceptance import promote_accepted_master

    root, acceptance = accepted_fixture(tmp_path / "f", category)
    promoted = promote_accepted_master(root, acceptance_path=acceptance, destination=tmp_path / "p")
    identity = json.loads(promoted.acceptance_path.read_text(encoding="utf-8"))["identity"]
    work_path = promoted.destination_root / "library" / "works" / identity["work_id"] / "work.json"
    work = json.loads(work_path.read_text(encoding="utf-8"))
    work["textual_forms"][0]["editions"][0]["category"] = "prose"
    _write_json(work_path, work)
    module = sermons if category == "sermons" else prayers
    project = getattr(module, f"project_accepted_{category}")
    verify = getattr(module, f"verify_accepted_{category}")
    with pytest.raises(PipelineError, match="category"):
        project(promoted.destination_root, acceptance_path=promoted.acceptance_path)
    assert verify(
        promoted.destination_root,
        acceptance_path=promoted.acceptance_path,
        rows=[],
        receipt={},
    )


@pytest.mark.parametrize("category", ["sermons", "prayers"])
def test_ordinary_route_rejects_acceptance_header_and_accepted_mode_rejects_unknown_tags(
    tmp_path: Path, category: str
) -> None:
    from ocd_kernel.projection.categories import prayers, sermons

    root, acceptance = accepted_fixture(tmp_path / "f", category)
    record = json.loads(acceptance.read_text(encoding="utf-8"))
    module = sermons if category == "sermons" else prayers
    project = getattr(module, f"project_{category}_document")
    context = {
        "identity": {key: record["identity"][key] for key in ("work_id", "textual_form_id", "edition_id")},
        "language": "en",
        "representation_revision": record["representation_revision"]["id"],
        "edition_title": "fixture",
    }
    candidate = root / "candidate.xml"
    with pytest.raises(PipelineError):
        project(candidate, **context)

    tree = E.parse(str(candidate))
    body = tree.getroot().find(f".//{{{TEI_NS}}}body")
    assert body is not None
    E.SubElement(body, f"{{{TEI_NS}}}unknown-carrier").text = "unexpected"
    bad_body = tmp_path / "bad-body.xml"
    bad_body.write_bytes(E.tostring(tree, encoding="utf-8", xml_declaration=True))
    with pytest.raises(PipelineError):
        project(bad_body, **context, _allow_acceptance_metadata=True)

    tree = E.parse(str(candidate))
    title_stmt = tree.getroot().find(f".//{{{TEI_NS}}}titleStmt")
    assert title_stmt is not None
    E.SubElement(title_stmt, f"{{{TEI_NS}}}unknown-header").text = "unexpected"
    bad_header = tmp_path / "bad-header.xml"
    bad_header.write_bytes(E.tostring(tree, encoding="utf-8", xml_declaration=True))
    with pytest.raises(PipelineError):
        project(bad_header, **context, _allow_acceptance_metadata=True)


@pytest.mark.parametrize("category", ["sermons", "prayers"])
def test_accepted_context_uses_matching_form_metadata(tmp_path: Path, category: str) -> None:
    from ocd_kernel.projection.categories import prayers, sermons
    from ocd_kernel.tei.acceptance import promote_accepted_master

    root, acceptance = accepted_fixture(tmp_path / "f", category)
    record = json.loads(acceptance.read_text(encoding="utf-8"))
    work_path = root / "library" / "works" / record["identity"]["work_id"] / "work.json"
    work = json.loads(work_path.read_text(encoding="utf-8"))
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    form["language"] = edition.pop("language")
    form["category"] = edition.pop("category")
    _write_json(work_path, work)

    promoted = promote_accepted_master(root, acceptance_path=acceptance, destination=tmp_path / "p")
    module = sermons if category == "sermons" else prayers
    output = getattr(module, f"project_accepted_{category}")(
        promoted.destination_root,
        acceptance_path=promoted.acceptance_path,
    )
    assert output["rows"]
    assert all(row["language"] == "en" and row["category"] == category for row in output["rows"])


@pytest.mark.parametrize("tag", ["note", "title"])
def test_ordinary_prayer_header_rejects_unknown_roles(tmp_path: Path, tag: str) -> None:
    from ocd_kernel.projection.categories.prayers import project_prayers_document, verify_prayers_document

    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/library-pipeline/categories/prayers"
    case = json.loads((fixture / "manifest.json").read_text(encoding="utf-8"))["cases"][0]
    source = fixture / case["tei_file"]
    baseline = project_prayers_document(source, **case["context"])
    tree = E.parse(str(source))
    bibl = tree.getroot().find(f".//{{{TEI_NS}}}sourceDesc/{{{TEI_NS}}}bibl")
    assert bibl is not None
    E.SubElement(bibl, f"{{{TEI_NS}}}{tag}", type="unknown").text = "unsupported role"
    mutated = tmp_path / "unknown-role.xml"
    mutated.write_bytes(E.tostring(tree, encoding="utf-8", xml_declaration=True))
    with pytest.raises(PipelineError, match=f"{tag} role"):
        project_prayers_document(mutated, **case["context"])
    errors = verify_prayers_document(mutated, baseline["rows"], baseline["receipt"], **case["context"])
    assert any(f"{tag} role" in error for error in errors)
