"""Accepted-master release coverage for hymns, poetry, and liturgies."""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

from ocd_kernel.library._common import PipelineError


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "library-pipeline" / "categories"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = f"{{{TEI_NS}}}"
XML_ID = f"{{{XML_NS}}}id"
CATEGORIES = ("hymns", "poetry", "liturgies")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _set_idno(parent: ET.Element, kind: str, value: Any) -> None:
    parents = {child: holder for holder in parent.iter() for child in holder}
    matches = [
        child for child in parent.iter()
        if _local(child.tag) == "idno" and child.get("type") == kind
    ]
    if matches:
        matches[0].text = str(value)
        for duplicate in matches[1:]:
            parents[duplicate].remove(duplicate)
    else:
        ET.SubElement(parent, f"{NS}idno", type=kind).text = str(value)


def _set_note(parent: ET.Element, kind: str, value: str) -> None:
    matches = [
        child for child in list(parent)
        if _local(child.tag) == "note" and child.get("type") == kind
    ]
    if matches:
        matches[0].text = value
        for duplicate in matches[1:]:
            parent.remove(duplicate)
    else:
        ET.SubElement(parent, f"{NS}note", type=kind).text = value


def _source_info(category: str, manifest: dict[str, Any]) -> tuple[str, int, str, str]:
    context = manifest["context"]
    source_path = manifest.get("source_path") or manifest.get("source_root")
    source_bytes = manifest.get("source_bytes")
    source_sha256 = manifest.get("source_sha256")
    if isinstance(manifest.get("source"), dict):
        source_path = source_path or manifest["source"].get("path")
        source_bytes = source_bytes or manifest["source"].get("bytes")
        source_sha256 = source_sha256 or manifest["source"].get("sha256")
    if not source_path and manifest.get("source_files"):
        source_path = manifest["source_files"][0]["path"]
    if category == "hymns":
        source_path = Path(source_path).with_name(manifest["source_member"]).as_posix()
        source_sha256 = manifest["payload_sha256"]
        source_bytes = (ROOT / source_path).stat().st_size
    if not source_bytes:
        files = manifest.get("source_files")
        if isinstance(files, list) and files:
            source_bytes = sum((ROOT / item["path"]).stat().st_size for item in files)
        else:
            source_bytes = (ROOT / source_path).stat().st_size
    source_path = str(source_path)
    source_bytes = int(source_bytes)
    source_sha256 = str(source_sha256 or context["source_sha256"])
    scope = {
        "hymns": "selected complete Hymnary source rows in the retained fixture",
        "poetry": "selected source-native poem divisions in the retained fixture",
        "liturgies": "selected Daily Office service units in the retained fixture",
    }[category]
    return source_path, source_bytes, source_sha256, scope


def accepted_fixture(tmp_path: Path, category: str) -> tuple[Path, Path]:
    """Build an unpromoted accepted fixture from the retained category source.

    The helper intentionally uses compact synthetic identities and a temporary
    library. It copies only the retained fixture witness and sidecars; source
    URLs, source hashes, and source byte counts come from the existing
    category manifests and retained files.
    """

    if category not in CATEGORIES:
        raise ValueError(f"unsupported accepted verse category: {category}")
    fixture = FIXTURES / category
    manifest = json.loads((fixture / "manifest.json").read_text(encoding="utf-8"))
    context = manifest["context"]
    slug = {"hymns": "h", "poetry": "p", "liturgies": "l"}[category]
    identity = {
        "work_id": f"w-{slug}",
        "textual_form_id": f"f-{slug}",
        "edition_id": f"e-{slug}",
        "acquisition_id": f"a-{slug}",
    }
    base = Path(tmp_path).resolve()
    edition = (
        base / "library" / "works" / identity["work_id"] / "forms"
        / identity["textual_form_id"] / "editions" / identity["edition_id"]
    )
    edition.mkdir(parents=True, exist_ok=True)
    work_root = edition.parents[3]
    source_path, source_bytes, source_sha256, source_scope = _source_info(category, manifest)
    source_url = context["source_url"]
    title = context["edition_title"]
    retained = base / "retained" / "r.xml"
    retained.parent.mkdir(parents=True, exist_ok=True)
    retained.write_bytes((fixture / "retained.xml").read_bytes())
    retained_binding = {
        "path": "retained/r.xml",
        "position": 1,
        "bytes": retained.stat().st_size,
        "sha256": _sha256(retained),
        "scope": source_scope,
    }
    acquisition = {
        "schema_version": "2.0",
        "acquisition_id": identity["acquisition_id"],
        "edition_id": identity["edition_id"],
        "provider": "offline retained category fixture",
        "url": source_url,
        "source_path": source_path,
        "source_bytes": source_bytes,
        "source_sha256": source_sha256,
        "source_scope": source_scope,
        "retained_files": [
            {key: retained_binding[key] for key in ("path", "bytes", "sha256", "scope")}
            | {"media_type": "application/xml"}
        ],
        "route": "born-digital",
    }
    edition_record = {
        "edition_id": identity["edition_id"],
        "title": title,
        "acquisition_ids": [identity["acquisition_id"]],
    }
    form_record = {
        "textual_form_id": identity["textual_form_id"],
        "language": context["language"],
        "category": category,
        "editions": [edition_record],
    }
    work = {
        "schema_version": "2.0",
        "work_id": identity["work_id"],
        "title": title,
        "evidence": [source_url],
        "textual_forms": [form_record],
    }
    _write_json(work_root / "work.json", work)
    _write_json(
        work_root / "state.json",
        {
            "schema_version": "2.0",
            "work_id": identity["work_id"],
            "targets": [{
                "target_id": identity["edition_id"],
                "target_type": "edition",
                "stage": "review",
                "updated_at": "2026-09-08T00:00:00Z",
                "evidence": ["c.xml"],
            }],
        },
    )
    acquisition_path = edition / "acquisitions" / f"{identity['acquisition_id']}.json"
    _write_json(acquisition_path, acquisition)

    tree = ET.parse(str(fixture / "master.tei.xml"))
    header = tree.getroot().find(f"{NS}teiHeader")
    if header is None:
        raise PipelineError(f"fixture has no TEI header: {category}")
    source_desc = header.find(f".//{NS}sourceDesc")
    if source_desc is None:
        raise PipelineError(f"fixture has no sourceDesc: {category}")
    source_node = source_desc.find(f"{NS}bibl") if category == "poetry" else source_desc
    if source_node is None:
        raise PipelineError(f"fixture has no poetry source bibl")
    ptr = next((child for child in source_node.iter() if _local(child.tag) == "ptr"), None)
    if ptr is None:
        ptr = ET.SubElement(source_node, f"{NS}ptr", type="source")
    ptr.set("target", source_url)
    for key, value in {
        **identity,
        "source_sha256": source_sha256,
        "source_bytes": source_bytes,
        "sha256": retained_binding["sha256"],
        "representation_revision": context["representation_revision"],
    }.items():
        _set_idno(source_node, key, value)
    _set_note(source_node, "source-location", source_path)
    _set_note(source_node, "source-scope", source_scope)
    revision = header.find(f"{NS}revisionDesc")
    if revision is None:
        revision = ET.SubElement(header, f"{NS}revisionDesc")
    for child in list(revision):
        revision.remove(child)
    change = ET.SubElement(revision, f"{NS}change", when="2026-09-08")
    change.set(XML_ID, context["representation_revision"])
    change.text = "Bound category fixture."
    candidate = base / "c.xml"
    candidate.write_bytes(ET.tostring(tree.getroot(), encoding="utf-8", xml_declaration=True))

    scope = {
        "kind": "member",
        "declared": source_scope,
        "expected_members": [{key: retained_binding[key] for key in ("path", "position")}],
        "included_members": [retained_binding],
        "excluded_members": [],
    }
    source = {
        "source_path": source_path,
        "source_sha256": source_sha256,
        "source_bytes": source_bytes,
        "source_scope": source_scope,
    }
    from ocd_kernel.tei.acceptance import build_acceptance_record, make_file_binding, write_acceptance

    candidate_binding = make_file_binding(base, candidate)
    accounting_path = base / "e" / "source-accounting.json"
    _write_json(
        accounting_path,
        {
            "contract": "ocd-source-accounting-v1",
            "identity": identity,
            "source": source,
            "source_sha256": source_sha256,
            "source_bytes": source_bytes,
            "scope": source_scope,
            "accepted_scope": {"kind": "member", "declared": source_scope},
            "expected_members": scope["expected_members"],
            "included_members": scope["included_members"],
            "excluded_members": [],
            "missing_members": [],
            "unknown_members": [],
        },
    )
    technical: dict[str, dict[str, Any]] = {
        "producer": {"id": f"producer:{category}-fixture"},
        "checker": {"id": f"checker:{category}-fixture"},
        "shared_assumptions": ["Synthetic acceptance evidence is fixture-only."],
        "independent_corroboration": "Retained source-derived category tests remain separate.",
    }
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof_path = base / "e" / f"{name}.json"
        proof = {
            "contract": f"ocd-tei-{name}-v1",
            "identity": identity,
            "source": source,
            "candidate": candidate_binding,
            "scope": source_scope,
            "status": "pass",
            "command": "simulated-accepted-category-fixture",
            "exit_code": 0,
            "expected_members": scope["expected_members"],
            "included_members": scope["included_members"],
            "excluded_members": [],
            "missing_members": [],
            "unknown_members": [],
        }
        if name == "accounting":
            proof["accepted_scope"] = {"kind": "member", "declared": source_scope}
        _write_json(proof_path, proof)
        technical[name] = {
            "path": proof_path,
            "status": "pass",
            "command": "simulated-accepted-category-fixture",
            "exit_code": 0,
        }
    coverage = {
        "status": "partial",
        "declared": source_scope,
        "reached": [source_scope],
        "inspected": [source_scope],
        "unreviewed": ["human acceptance"],
    }
    review = {
        "reviewer": f"agent:{category}-fixture",
        "reviewed_at": "2026-09-08T00:00:00Z",
        "coverage": coverage,
        "source_quality_uncertainty": ["fixture scope only"],
        "discrepancies": [],
        "unreviewed_residuals": ["human acceptance not performed"],
    }
    review_path = base / "e" / "review.json"
    _write_json(
        review_path,
        {
            "contract": "ocd-tei-review-v1",
            "identity": identity,
            "source": source,
            "candidate": candidate_binding,
            "scope": source_scope,
            **review,
        },
    )
    decision = {
        "source_local_disposition": "Offline fixture simulation only",
        "blockers": [],
        "agent_assessment": {
            "status": "accepted",
            "actor": f"agent:{category}-fixture",
            "assessed_at": "2026-09-08T00:00:00Z",
            "supported_scope": source_scope,
            "unassessed_stronger_claims": ["real acceptance"],
            "unresolved_claims": [],
        },
        "human_decision": {"status": "not-recorded"},
    }
    record = build_acceptance_record(
        base,
        identity=identity,
        candidate_path=candidate,
        source_accounting_path=accounting_path,
        scope=scope,
        technical=technical,
        review={**review, "report_path": review_path},
        representation_revision={
            "id": context["representation_revision"],
            "date": "2026-09-08",
            "note": "Bound category fixture.",
        },
        decision=decision,
        missing_members=[],
        unknown_members=[],
    )
    acceptance_path = edition / "acceptance.json"
    write_acceptance(acceptance_path, record)
    return base, acceptance_path


@pytest.mark.parametrize("category", CATEGORIES)
def test_accepted_verse_route_requires_promotion_and_binds_authority(tmp_path: Path, category: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from ocd_kernel.tei.acceptance import promote_accepted_master

    root, acceptance = accepted_fixture(tmp_path / "f", category)
    module = __import__(f"ocd_kernel.projection.categories.{category}", fromlist=["*"])
    project = getattr(module, f"project_accepted_{category}")
    verify = getattr(module, f"verify_accepted_{category}")
    with pytest.raises(PipelineError, match="promoted"):
        project(root, acceptance_path=acceptance)
    assert any("promoted" in error for error in verify(root, acceptance_path=acceptance, rows=[], receipt={}))
    promoted = promote_accepted_master(root, acceptance_path=acceptance, destination=tmp_path / "p")
    output = project(promoted.destination_root, acceptance_path=promoted.acceptance_path)
    assert output["rows"]
    assert all(row["category"] == category for row in output["rows"])
    authority = output["receipt"]["authority"]
    assert set(authority) == {"acceptance", "work", "master", "acquisition"}
    assert all(set(value) == {"path", "sha256"} for value in authority.values())
    assert verify(
        promoted.destination_root,
        acceptance_path=promoted.acceptance_path,
        rows=output["rows"],
        receipt=output["receipt"],
    ) == []
    monkeypatch.setattr(module, f"project_{category}_document", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("producer called")))
    assert verify(
        promoted.destination_root,
        acceptance_path=promoted.acceptance_path,
        rows=output["rows"],
        receipt=output["receipt"],
    ) == []


@pytest.mark.parametrize("category", CATEGORIES)
def test_accepted_verse_route_rejects_forged_authority_and_category_change(tmp_path: Path, category: str) -> None:
    from ocd_kernel.tei.acceptance import promote_accepted_master

    root, acceptance = accepted_fixture(tmp_path / "f", category)
    promoted = promote_accepted_master(root, acceptance_path=acceptance, destination=tmp_path / "p")
    module = __import__(f"ocd_kernel.projection.categories.{category}", fromlist=["*"])
    project = getattr(module, f"project_accepted_{category}")
    verify = getattr(module, f"verify_accepted_{category}")
    output = project(promoted.destination_root, acceptance_path=promoted.acceptance_path)
    forged = dict(output["receipt"])
    forged["authority"] = dict(output["receipt"]["authority"])
    forged["authority"]["master"] = dict(forged["authority"]["master"])
    forged["authority"]["master"]["sha256"] = "0" * 64
    assert any("authority" in error for error in verify(promoted.destination_root, acceptance_path=promoted.acceptance_path, rows=output["rows"], receipt=forged))
    work_path = promoted.destination_root / output["receipt"]["authority"]["work"]["path"]
    work = json.loads(work_path.read_text(encoding="utf-8"))
    work["textual_forms"][0]["editions"][0]["category"] = "poetry" if category != "poetry" else "hymns"
    _write_json(work_path, work)
    diagnostics = verify(promoted.destination_root, acceptance_path=promoted.acceptance_path, rows=output["rows"], receipt=output["receipt"])
    assert diagnostics
