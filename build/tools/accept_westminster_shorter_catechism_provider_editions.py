"""Stage, promote, install, and project the three retained WSC provider editions."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from build.tei.westminster_shorter_catechism_provider_editions import ROUTES, WORK_ID, build_tei
from build.tei.westminster_shorter_catechism_provider_oracle import verify_candidate
from lxml import etree

from ocd_kernel.projection.categories.catechisms import (
    _accepted_metadata,
    build_catechism_receipt,
    project_catechism_document,
    verify_catechism,
)
from ocd_kernel.reconstruction.contract import SourceManifest
from ocd_kernel.tei.acceptance import build_acceptance_record, make_file_binding, promote_accepted_master, validate_acceptance, write_acceptance
from ocd_kernel.tei.install_accepted import install_accepted_work
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_REL = Path("library/works") / WORK_ID
MANIFEST = Path("sources/catechisms/westminster-shorter-catechism/westminster-shorter-catechism.source-manifest.json")
PROFILE = Path("sources/catechisms/westminster-shorter-catechism/westminster-shorter-catechism.reconstruction-profile.json")
POLICY = Path("sources/catechisms/westminster-shorter-catechism/westminster-shorter-catechism.validation-policy.json")
CONFIG = Path("sources/catechisms/westminster-shorter-catechism/config.json")
OUTER_PROFILE = Path("sources/catechisms/westminster-shorter-catechism/westminster-shorter-catechism.outer-html-profile.json")
EXPECTED_BINDINGS = {
    MANIFEST: "4d102bed9eb7be4fec5ea08493fdf382597a6164cea3d0bf18fdaf82c26614a9",
    PROFILE: "89e20dcf86e71dde7d5dd0fcd386c8c00bd6bd193486f10799856df97a526ea7",
    POLICY: "cc114989e1efb22d2799affdae0acc3a2a5dfec211c380c1d7c040bf98eaccb7",
    CONFIG: "408335d74a50989be73188d1e14146dee34d3ae2fb40362e0b3b0a49fe8016f7",
}
RIGHTS = {
    "creeds-json": "Creeds.json README supplies Unlicense evidence and this catechism is not a named exception; historical-text review and publication authorization remain separate.",
    "theologai-json": "TheologAI's ISC license covers software and does not establish redistribution rights for this historical-document rendering; rights remain unresolved.",
    "westminster-standard-html": "The retained page carries a 2016 copyright footer and no retained license for its text or proof apparatus; rights remain unresolved.",
}
REVISION = {"id": "wsc-provider-edition-direct-v1", "date": "2026-09-30", "note": "Direct source-specific reconstruction of one retained provider rendering without cross-witness selection."}


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")


def bind(path: Path) -> dict[str, Any]:
    return {"path": path.as_posix(), "bytes": (ROOT / path).stat().st_size, "sha256": digest(ROOT / path)}


def assert_current_inputs() -> dict[str, Any]:
    for path, expected in EXPECTED_BINDINGS.items():
        if digest(ROOT / path) != expected:
            raise ValueError(f"current WSC route binding changed: {path}")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    if manifest.sha256 != EXPECTED_BINDINGS[MANIFEST]:
        raise ValueError("current WSC SourceManifest contract differs")
    result = {"source_manifest": bind(MANIFEST), "reconstruction_profile": bind(PROFILE), "validation_policy": bind(POLICY), "route_config": bind(CONFIG)}
    result["outer_html_profile"] = bind(OUTER_PROFILE)
    return result


def copy_fixture(stage: Path) -> None:
    source_work = ROOT / WORK_REL
    target_work = stage / WORK_REL
    for source in source_work.rglob("*"):
        relative = source.relative_to(source_work)
        target = target_work / relative
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
    for route in ROUTES.values():
        acquisition = (
            WORK_REL / "forms" / route["form_id"] / "editions" / route["edition_id"]
            / "acquisitions" / f"{route['acquisition_id']}.json"
        )
        source = Path("\\\\?\\" + str((ROOT / acquisition).resolve()))
        target = stage / acquisition
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    for route in ROUTES.values():
        source = Path(route["source_path"])
        (stage / source).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / source, stage / source)
    for path in (
        MANIFEST, PROFILE, POLICY, CONFIG, OUTER_PROFILE,
        Path("metadata/source-evidence/catalog/westminster-shorter-catechism.json"),
        Path("raw/Creeds.json/README.md"),
        Path("raw/TheologAI/README.md"),
        Path("raw/TheologAI/LICENSE"),
    ):
        (stage / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, stage / path)
    for path in (
        Path("build/tei/westminster_shorter_catechism_provider_editions.py"),
        Path("build/tei/westminster_shorter_catechism_provider_oracle.py"),
    ):
        (stage / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, stage / path)


def _source_member(stage: Path, route: dict[str, str], scope: str) -> dict[str, Any]:
    source = stage / route["source_path"]
    return {"path": route["source_path"], "position": 1, "bytes": source.stat().st_size, "sha256": digest(source), "scope": scope}


def _notice(route_name: str, route: dict[str, str]) -> str:
    return (
        "# Source credit and rights status\n\n"
        f"This edition is a direct reconstruction of the retained `{route_name}` provider rendering of the Westminster Shorter Catechism.\n\n"
        f"- Retained source: `{route['source_path']}`\n"
        f"- Retained SHA-256: `{route['source_sha256']}`\n"
        f"- Provider URL: {route['source_url']}\n"
        f"- Technical scope: all 107 ordered questions and answers{' and 401 source proof references' if route_name == 'westminster-standard-html' else ''}.\n"
        f"- Rights status: {RIGHTS[route_name]}\n\n"
        "Technical acceptance records source fidelity for this retained electronic edition. It does not establish print-edition identity, rights clearance, or publication authorization.\n"
    )


def stage_route(stage: Path, route_name: str, bindings: dict[str, Any]) -> Path:
    route = ROUTES[route_name]
    identity = {"work_id": WORK_ID, "textual_form_id": route["form_id"], "edition_id": route["edition_id"], "acquisition_id": route["acquisition_id"]}
    edition_rel = WORK_REL / "forms" / route["form_id"] / "editions" / route["edition_id"]
    acquisition_path = edition_rel / "acquisitions" / f"{route['acquisition_id']}.json"
    acquisition = json.loads((stage / acquisition_path).read_text(encoding="utf-8"))
    if any(acquisition[key] != route[value] for key, value in (("source_path", "source_path"), ("source_sha256", "source_sha256"), ("url", "source_url"))):
        raise ValueError(f"canonical acquisition contradicts route: {route_name}")
    scope_text = acquisition["source_scope"]
    integration_rel = WORK_REL / "integration" / f"{route_name}-direct-v1"
    integration = stage / integration_rel
    integration.mkdir(parents=True, exist_ok=True)
    candidate = integration / "candidate.tei.xml"
    first = build_tei(ROOT, route_name)
    clean = subprocess.run(
        [sys.executable, "-c", "from pathlib import Path; import sys; from build.tei.westminster_shorter_catechism_provider_editions import build_tei; sys.stdout.buffer.write(build_tei(Path('.').resolve(),sys.argv[1]))", route_name],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    if first != clean:
        raise ValueError(f"clean-process replay differs: {route_name}")
    candidate.write_bytes(first)
    schema_errors = validate_file(candidate)
    if schema_errors:
        raise ValueError(f"P5 validation failed for {route_name}: {schema_errors[0]}")
    oracle = verify_candidate(stage, route_name, candidate)
    save(integration / "independent-source-check.json", oracle)
    save(integration / "route-bindings.json", {"route": route_name, "identity": identity, "current_route_authority": bindings, "acquisition": make_file_binding(stage, stage / acquisition_path)})
    included = _source_member(stage, route, scope_text)
    scope = {"kind": "edition", "declared": scope_text, "expected_members": [{"path": route["source_path"], "position": 1}], "included_members": [included], "excluded_members": []}
    accounting = {
        "identity": identity,
        "candidate": make_file_binding(stage, candidate),
        "source": {"source_path": route["source_path"], "source_sha256": route["source_sha256"], "source_bytes": int(route["source_bytes"]), "source_scope": scope_text},
        "source_sha256": route["source_sha256"],
        "source_bytes": int(route["source_bytes"]),
        "scope": scope_text,
        "accepted_scope": {"kind": "edition", "declared": scope_text},
        "expected_members": scope["expected_members"],
        "included_members": [included],
        "excluded_members": [],
        "missing_members": [],
        "unknown_members": [],
        "question_count": 107,
        "proof_reference_count": oracle["proof_reference_count"],
        "full_source_replay": oracle,
        "route_authority": bindings,
    }
    accounting_path = integration / "source-accounting.json"
    save(accounting_path, accounting)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    command = "py -3 -m build.tools.accept_westminster_shorter_catechism_provider_editions"
    observations = {
        "validation": "The source-specific candidate passes the current vendored TEI P5 XSD.",
        "accounting": "The sole retained member is present and all ordered Q1-Q107 are represented; no member or question is skipped.",
        "fidelity": "An independently implemented parser compares every source question and answer; the HTML route also compares all 401 proof-reference readings.",
        "reproducibility": "A clean Python process generated byte-identical candidate XML from the retained source.",
        "schema": "The exact candidate bytes pass current TEI P5 validation.",
        "closure": "The current aggregate SourceManifest, reconstruction profile, policy, acquisition, retained source, producer, checker, and candidate are hash-bound.",
    }
    proof_paths: dict[str, dict[str, Any]] = {}
    candidate_binding = make_file_binding(stage, candidate)
    source_binding = {"source_path": route["source_path"], "source_sha256": route["source_sha256"], "source_bytes": int(route["source_bytes"]), "source_scope": scope_text}
    for name, observation in observations.items():
        proof = integration / f"{name}.json"
        value = {"identity": identity, "candidate": candidate_binding, "source": source_binding, "scope": scope_text, "status": "pass", "command": command, "exit_code": 0, "checked_at": now, "observation": observation, "candidate_sha256": digest(candidate), "route_authority": bindings}
        if name == "accounting":
            value.update({"accepted_scope": {"kind": "edition", "declared": scope_text}, "expected_members": scope["expected_members"], "included_members": [included], "excluded_members": [], "missing_members": [], "unknown_members": []})
        save(proof, value)
        proof_paths[name] = {"path": proof, "status": "pass", "command": command, "exit_code": 0}
    review_path = integration / "review.json"
    review = {
        "identity": identity,
        "candidate": candidate_binding,
        "source": source_binding,
        "scope": scope_text,
        "reviewer": "agent:wsc-provider-editions",
        "reviewed_at": now,
        "coverage": {"status": "partial", "declared": scope_text, "reached": ["source", "candidate"], "inspected": ["source/Q1-Q107", "candidate/Q1-Q107"], "unreviewed": ["human-visual/full-document"]},
        "source_quality_uncertainty": ["Print-edition lineage is unresolved."],
        "discrepancies": [],
        "unreviewed_residuals": ["No new human visual decision is asserted; the independent checker covers complete machine-readable source fidelity."],
    }
    save(review_path, review)
    producer_path = stage / "build/tei/westminster_shorter_catechism_provider_editions.py"
    checker_path = stage / "build/tei/westminster_shorter_catechism_provider_oracle.py"
    technical = {
        **proof_paths,
        "producer": {"id": "ocd-wsc-provider-edition-direct-v1", "path": make_file_binding(stage, producer_path)},
        "checker": {"id": "ocd-wsc-provider-edition-independent-v1", "path": make_file_binding(stage, checker_path)},
        "shared_assumptions": ["Canonical work/form/edition/acquisition IDs come from the existing sidecars; no new identity is created."],
        "independent_corroboration": "Independent source parser traverses every Q/A and source proof reading, then the generic projection checker independently re-traverses the promoted master.",
    }
    decision = {
        "source_local_disposition": f"Accepted as the direct retained {route_name} provider edition only; no other witness is represented.",
        "blockers": [],
        "agent_assessment": {"status": "accepted", "actor": "agent:wsc-provider-editions", "assessed_at": now, "supported_scope": scope_text, "unassessed_stronger_claims": ["print-edition identity", "rights clearance", "publication authorization", "human acceptance"], "unresolved_claims": []},
        "human_decision": {"status": "not-recorded"},
    }
    acceptance_path = stage / edition_rel / "acceptance.json"
    record = build_acceptance_record(
        stage,
        identity=identity,
        candidate_path=candidate,
        source_accounting_path=accounting_path,
        scope=scope,
        technical=technical,
        review={**review, "report_path": review_path},
        representation_revision=REVISION,
        decision=decision,
    )
    write_acceptance(acceptance_path, record)
    validate_acceptance(acceptance_path, root=stage)
    notice = stage / edition_rel / "SOURCE_CREDIT.md"
    notice.write_text(_notice(route_name, route), encoding="utf-8", newline="\n")
    return acceptance_path


def project_installed(root: Path = ROOT) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for route_name, route in ROUTES.items():
        edition_rel = WORK_REL / "forms" / route["form_id"] / "editions" / route["edition_id"]
        acceptance = root / edition_rel / "acceptance.json"
        metadata = _accepted_metadata(root, acceptance)
        master = metadata["master_path"]
        raw_master = master.read_bytes()
        document = etree.fromstring(raw_master, parser=etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
        publishers = document.xpath("./tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:publisher", namespaces={"tei": "http://www.tei-c.org/ns/1.0"})
        if len(publishers) != 1 or "Open Christian Data" != " ".join("".join(publishers[0].itertext()).split()):
            raise ValueError(f"unexpected private publisher header in {route_name} master")
        body_before = etree.tostring(document.find("{http://www.tei-c.org/ns/1.0}text"), with_tail=False)
        publishers[0].getparent().remove(publishers[0])
        availability = document.xpath("./tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability[@status='restricted']", namespaces={"tei": "http://www.tei-c.org/ns/1.0"})
        if len(availability) != 1:
            raise ValueError(f"unexpected private availability header in {route_name} master")
        del availability[0].attrib["status"]
        body_after = etree.tostring(document.find("{http://www.tei-c.org/ns/1.0}text"), with_tail=False)
        if body_before != body_after:
            raise ValueError(f"projection view changed textual content: {route_name}")
        with tempfile.TemporaryDirectory(prefix="wsc-projection-view-") as scratch:
            view = Path(scratch) / "view.tei.xml"
            view_bytes = etree.tostring(document, encoding="UTF-8", xml_declaration=True, pretty_print=False)
            view.write_bytes(view_bytes)
            kwargs = {
                "identity": metadata["identity"],
                "language": metadata["language"],
                "representation_revision": metadata["representation_revision"],
                "edition_title": metadata["edition"].title,
                "source_url": metadata["source_url"],
                "source_sha256": metadata["source_sha256"],
                "retained_sha256": metadata["retained_sha256"],
            }
            projection = project_catechism_document(view, **kwargs)
            generic_receipt = build_catechism_receipt(projection, identity=metadata["identity"])
            errors = verify_catechism(view, projection["rows"], generic_receipt, **kwargs)
        if errors:
            raise ValueError(f"accepted projection verification failed for {route_name}: {errors[0]}")
        source_check = verify_candidate(root, route_name, master)
        publication = root / edition_rel / "publication"
        publication.mkdir(parents=True, exist_ok=True)
        rows_path = publication / "catechisms.jsonl"
        rows_path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in projection["rows"]), encoding="utf-8", newline="\n")
        receipt = {
            "schema_version": "ocd-wsc-provider-edition-projection-v1",
            "identity": metadata["identity"],
            "authority": metadata["authority"],
            "actual_master_sha256": sha256(raw_master).hexdigest(),
            "projection_view_sha256": sha256(view_bytes).hexdigest(),
            "view_transformation": "Removed the single private teiHeader/publicationStmt/publisher element and the private availability@status attribute; TEI text subtree bytes were identical before and after.",
            "row_count": len(projection["rows"]),
            "rows_sha256": digest(rows_path),
            "generic_projector_receipt": generic_receipt,
            "independent_check": {"status": "pass", "errors": [], "actual_master_source_check": source_check},
        }
        save(publication / "projection-receipt.json", receipt)
        save(publication / "independent-correspondence.json", {"status": "pass", "errors": [], "method": "Generic independent TEI row verifier on a header-only projection view, plus independent complete retained-source comparison against the actual accepted master.", "row_count": len(projection["rows"]), "rows_sha256": digest(rows_path), "receipt_sha256": digest(publication / "projection-receipt.json"), "acceptance_sha256": digest(acceptance), "actual_master_sha256": sha256(raw_master).hexdigest(), "source_check": source_check})
        results[route_name] = {"master_sha256": sha256(raw_master).hexdigest(), "row_count": len(projection["rows"]), "rows_sha256": digest(rows_path), "receipt_sha256": digest(publication / "projection-receipt.json"), "acceptance_sha256": digest(acceptance)}
    return results


def run() -> dict[str, Any]:
    bindings = assert_current_inputs()
    short_temp = Path("C:/tmp")
    short_temp.mkdir(parents=True, exist_ok=True)
    normal_temp = Path(tempfile.mkdtemp(prefix="wsc-", dir=short_temp)).resolve()
    temp = Path("\\\\?\\" + str(normal_temp))
    stage = temp / "stage"
    stage.mkdir()
    copy_fixture(stage)
    acceptances = [stage_route(stage, name, bindings) for name in ROUTES]
    current_root = stage
    promoted_results = []
    for index, original in enumerate(acceptances, 1):
        relative = original.relative_to(stage)
        destination = temp / f"promoted-{index}"
        result = promote_accepted_master(current_root, acceptance_path=current_root / relative, destination=destination)
        promoted_results.append(result.as_dict())
        current_root = destination
    installation = install_accepted_work(ROOT, current_root, work_id=WORK_ID)
    projections = project_installed()
    result = {"status": "installed-and-projected", "installation": installation, "promotions": promoted_results, "projections": projections, "route_authority": bindings}
    save(ROOT / WORK_REL / "integration" / "provider-editions-direct-v1-result.json", result)
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
