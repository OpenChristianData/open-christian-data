"""Request-scoped, read-only records over the existing library authorities."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from ocd_kernel.lib.storage_topology import storage_read_phase
from ocd_kernel.tei.acceptance import load_acceptance
from ._common import PipelineError, canonical_bytes, safe_identifier, sha256_bytes, inspection_read_phase
from .acquisitions import load_acquisition
from .identities import _schema_path, load_work, validate_record
from .state import load_state
from .record_read import RecordRead


CONTRACT = "ocd-library-record-v1"
ADAPTERS = {"canonical": "records-and-presence-v1", "normalization": "v1", "research": "lead-2.1-tfr-v2", "coordination": "explicit-references-v3", "metadata": "projection-v1"}
SECTIONS = ("identity", "holdings", "research", "metadata", "selection", "coordination")


def _selector(value: dict) -> dict:
    validate_record("library-record", {
        "contract": CONTRACT, "selector": value, "resolution": None,
        "collection": "partial", "inspection_level": "records-and-presence",
        "sections": {}, "inputs": [], "discovery": [], "observations": [],
        "diagnostics": [], "update_routes": [], "adapter_versions": ADAPTERS,
        "routing": [], "fingerprint": "0" * 64, "execution": {"observed_at": datetime.now(timezone.utc).isoformat(), "attempts": 1},
    }, context="selector")
    for key in ("id", "work_id", "textual_form_id", "edition_id"):
        if key in value:
            safe_identifier(value[key], field=key)
    return dict(value)


def _canonical(read: RecordRead, selector: dict, sections: dict) -> str | None:
    kind = selector["kind"]
    work_id = selector["id"] if kind == "work" else selector["work_id"]
    population = read.members("library/works", "*", "identity")
    if read.discovery[("library/works", "*")]["health"] != "valid":
        return None
    if work_id not in population:
        return "not_found"
    base = f"library/works/{work_id}"
    work = read.record(f"{base}/work.json", "identity", load_work)
    if work is None:
        return None
    if work["work_id"] != work_id:
        read.issue("identity", "invalid", f"{base}/work.json", "work ID does not match its directory")
        return None
    forms = work["textual_forms"]
    if kind != "work":
        form_id = selector["id"] if kind == "textual_form" else selector["textual_form_id"]
        forms = [form for form in forms if form["textual_form_id"] == form_id]
        if not forms:
            return "not_found"
    editions = [(form["textual_form_id"], edition) for form in forms for edition in form["editions"]]
    if kind in {"edition", "acquisition"}:
        edition_id = selector["id"] if kind == "edition" else selector["edition_id"]
        editions = [(form, edition) for form, edition in editions if edition["edition_id"] == edition_id]
        if not editions:
            return "not_found"
    if kind == "acquisition" and selector["id"] not in editions[0][1].get("acquisition_ids", []):
        return "not_found"
    sections["identity"]["data"] = {"owner": f"{base}/work.json", "work": work,
                                      "selected_forms": [form["textual_form_id"] for form in forms],
                                      "selected_editions": [edition["edition_id"] for _, edition in editions]}
    sections["identity"]["health"] = "valid"
    state_ref = f"{base}/state.json"
    state = None
    if editions or read.observe(state_ref)["present"]:
        state = read.record(state_ref, "holdings", load_state)
        if state and state["work_id"] != work_id:
            read.issue("holdings", "invalid", state_ref, "state work ID contradicts the identity")
        if state:
            declared_editions = {edition["edition_id"] for form in work["textual_forms"] for edition in form["editions"]}
            declared_acquisitions = {identifier for form in work["textual_forms"] for edition in form["editions"] for identifier in edition.get("acquisition_ids", [])}
            for target in state["targets"]:
                declared = declared_editions if target["target_type"] == "edition" else declared_acquisitions
                if target["target_id"] not in declared:
                    read.issue("holdings", "invalid", state_ref, f"state target has no declared identity: {target['target_id']}")
    holdings = []
    for form_id, edition in editions:
        edition_id = edition["edition_id"]
        edition_ref = f"{base}/forms/{form_id}/editions/{edition_id}"
        acquisition_ref = f"{edition_ref}/acquisitions"
        sidecars = read.members(acquisition_ref, "*.json", "holdings", optional=not edition.get("acquisition_ids"))
        declared = set(edition.get("acquisition_ids", []))
        actual = {name[:-5] for name in sidecars}
        if "acquisition_ids" in edition and actual != declared:
            read.issue("holdings", "invalid", acquisition_ref, f"acquisition membership differs: declared={sorted(declared)}, observed={sorted(actual)}")
        acquisitions = []
        for name in sidecars:
            if kind == "acquisition" and name[:-5] != selector["id"]:
                continue
            reference = f"{acquisition_ref}/{name}"
            acquisition = read.record(reference, "holdings", load_acquisition)
            if acquisition is None:
                continue
            if acquisition["edition_id"] != edition_id or acquisition["acquisition_id"] != name[:-5]:
                read.issue("holdings", "invalid", reference, "acquisition identity/parent contradicts its path")
                continue
            retained = []
            for member in acquisition["retained_files"]:
                observed = read.observe(member["path"])
                retained.append({"declared": member, "observed_presence": observed, "current_integrity": "not_assessed"})
                if observed["health"] != "valid" or not observed["present"]:
                    read.issue("holdings", "unavailable", member["path"], "declared retained member cannot be observed")
                elif observed["bytes"] != member["bytes"]:
                    read.issue("holdings", "stale", member["path"], "observed size differs from the declaration; integrity was not checked")
            acquisitions.append({"owner": reference, "record": acquisition, "retained": retained})
        master = read.observe(f"{edition_ref}/master.tei.xml")
        acceptance_ref = f"{edition_ref}/acceptance.json"
        acceptance_present = read.observe(acceptance_ref)
        acceptance = read.record(acceptance_ref, "holdings", load_acceptance) if acceptance_present["present"] else None
        targets = [target for target in (state or {}).get("targets", [])
                   if target["target_id"] == edition_id or target["target_id"] in {a['record']['acquisition_id'] for a in acquisitions}]
        if any(target["target_id"] == edition_id and target["stage"] == "accepted" for target in targets):
            if not master["present"] or acceptance is None:
                read.issue("holdings", "unavailable", edition_ref, "accepted state lacks an observable master or acceptance record")
        if acceptance:
            expected = {"work_id": work_id, "textual_form_id": form_id, "edition_id": edition_id}
            identity = acceptance.get("identity", acceptance)
            if any(identity.get(key) != value for key, value in expected.items()):
                read.issue("holdings", "invalid", acceptance_ref, "acceptance identity contradicts the selected edition")
        scoped_holdings = []
        for acquisition_id in read.members(f"{edition_ref}/scopes", "*", "holdings", optional=True):
            scope_ref = f"{edition_ref}/scopes/{acquisition_id}"
            scoped_master = read.observe(f"{scope_ref}/master.tei.xml")
            scoped_acceptance_ref = f"{scope_ref}/acceptance.json"
            scoped_acceptance = read.record(scoped_acceptance_ref, "holdings", load_acceptance)
            if acquisition_id not in declared or not scoped_master["present"] or scoped_acceptance is None:
                read.issue("holdings", "invalid", scope_ref, "scoped master and acceptance require a declared acquisition")
            elif scoped_acceptance["identity"].get("acquisition_id") != acquisition_id:
                read.issue("holdings", "invalid", scoped_acceptance_ref, "scoped acceptance acquisition contradicts its path")
            scoped_holdings.append({"acquisition_id": acquisition_id, "master_presence": scoped_master,
                                    "historical_acceptance": {"owner": scoped_acceptance_ref, "record": scoped_acceptance,
                                    "current_byte_applicability": "not_assessed"}})
        holdings.append({"textual_form_id": form_id, "edition_id": edition_id, "state_owner": state_ref,
                         "recorded_targets": targets, "acquisitions": acquisitions,
                         "scoped_holdings": scoped_holdings,
                         "master_presence": master, "historical_acceptance": {"owner": acceptance_ref, "record": acceptance,
                         "current_byte_applicability": "not_assessed"}, "current_integrity": "not_assessed"})
    sections["holdings"].update(health="valid", data={"editions": holdings, "state_owner": state_ref,
                                                    "state_recorded": state is not None})
    sections["metadata"].update(health="valid", data={"adopted_identity_owner": f"{base}/work.json",
                                                      "detailed_edition_header": "accepted TEI; not read by default lookup",
                                                      "source_observations": []})
    from .labels import PROFILE, profile, work_labels, label, metadata_decisions, acquisition_description, edition_coverage, coverage_summary
    from .rights import collect_rights
    read.bytes('@runtime/metadata-labels.json', 'metadata', physical=PROFILE)
    for name in ('metadata-labels', 'rights-record', 'rights-subject'):
        read.bytes(f'@runtime/schemas/v2/{name}.schema.json', 'metadata', physical=_schema_path(name))
    vocabulary = profile()
    data = sections['metadata']['data']
    data['normalized'] = work_labels(work, vocabulary)
    data['normalized']['source_metadata'] = metadata_decisions(read, work)
    data['normalized']['providers'] = [label('providers', acquisition['record']['provider'], vocabulary=vocabulary)
                                      for holding in holdings for acquisition in holding['acquisitions']]
    data['rights'] = []
    for form_id, edition in editions:
        rights = collect_rights(read, work_id, form_id, edition['edition_id'])
        data['rights'].append({'edition_id': edition['edition_id'], **rights})
        for issue in rights['issues']:
            read.issue('metadata', 'invalid', issue['path'], issue['code'] + ': ' + issue['message'])
    coverage_editions = []
    for holding in holdings:
        edition_id = holding['edition_id']
        description = next(item for item in data['normalized']['editions'] if item['edition_id'] == edition_id)
        description['sources'] = [acquisition_description(item['record'], vocabulary) for item in holding['acquisitions']]
        stage = next((target['stage'] for target in holding['recorded_targets']
                      if target['target_type'] == 'edition' and target['target_id'] == edition_id), None)
        master = holding['master_presence']['present'] is True
        accepted = holding['historical_acceptance']['record'] is not None
        description['coverage'] = edition_coverage(master, accepted, stage)
        coverage_editions.append({'edition_id': edition_id, 'language': description['language'],
                                  'rights': next(item for item in data['rights'] if item['edition_id'] == edition_id),
                                  'observed_master_presence': master, 'observed_acceptance_presence': accepted,
                                  'recorded_stage': stage})
    data['normalized']['coverage'] = coverage_summary([{'work_id': work_id, 'form_count': len(work['textual_forms']),
                                                       'normalized': data['normalized'], 'editions': coverage_editions}])
    data['normalized']['coverage']['scope'] = 'work description and selected declared editions only'
    return "found"


def _routes(selector: dict) -> list[dict]:
    return [
        {"fact": "identity", "owner_kind": "work sidecar", "operation": "validate_identity_update; owning staged workflow",
         "scope": selector, "support": "owning_workflow", "prerequisites": ["evidenced identity", "immutable parent IDs", "staged validation and before-hash check"]},
        {"fact": "metadata", "owner_kind": "authored metadata decision", "operation": "build.tools.review_source_metadata",
         "scope": selector, "support": "supported", "prerequisites": ["source-bound decision", "owning review/adoption authorization", "current input bindings"]},
        {"fact": "acceptance", "owner_kind": "accepted-work installation", "operation": "build.tools.install_accepted_work",
         "scope": selector, "support": "supported", "prerequisites": ["exact declared source and identity", "validated candidate and acceptance evidence", "guarded staging/recovery", "existing authorization requirements"]},
        {"fact": "research or task decision", "owner_kind": "research record or owning tracker", "operation": "owning research/task workflow",
         "scope": selector, "support": "owning_workflow", "prerequisites": ["exact evidence and target scope", "retain previous decision", "no universal writer provided"]},
        {"fact": "lead source rebinding", "owner_kind": "structured research queue and immutable migration witnesses", "operation": "build.tools.repair_manifest_leads; dry run then --apply",
         "scope": selector, "support": "supported", "prerequisites": ["bounded explicit batch", "exact before hashes", "conserve existing identity and editorial decisions", "changed claims remain on hold"]},
        {"fact": "publication", "owner_kind": "release selection and publication workflow", "operation": "existing selected release assembly/public-mirror route",
         "scope": selector, "support": "owning_workflow", "prerequisites": ["accepted-master release contract", "rights and release selection", "explicit publication authorization"]},
    ]


def lookup_library_record(root: Path, selector: dict, *, connections: bool = True) -> dict:
    """Return one bound result; deeper verification and all writes have other owners."""
    root = Path(root)
    try:
        selector = _selector(selector)
    except (PipelineError, TypeError) as exc:
        request = {key: value for key, value in selector.items() if key in {"kind", "namespace", "id", "work_id", "textual_form_id", "edition_id"} and isinstance(value, str)} if isinstance(selector, dict) else {}
        return _result(RecordRead(root), request, {}, "invalid_request", 1, error=str(exc))
    for attempt in (1, 2):
        read = RecordRead(root)
        with inspection_read_phase(), storage_read_phase():
            for name in ("work", "state", "acquisition", "acceptance", "library-record"):
                read.bytes(f"@runtime/schemas/v2/{name}.schema.json", "identity", physical=_schema_path(name))
            if read.observe(".ocd-storage.json")["present"]:
                read.bytes(".ocd-storage.json", "holdings")
            sections = {name: {"health": "not_assessed", "inspection_basis": ["records-and-presence"], "data": {}} for name in SECTIONS}
            if selector["kind"] in {"work", "textual_form", "edition", "acquisition"}:
                outcome = _canonical(read, selector, sections)
            else:
                outcome = None
            if connections:
                from .record_connections import collect_connections
                outcome = collect_connections(read, selector, sections, outcome)
            result = _result(read, selector, sections, outcome, attempt)
            validate_record("library-record", result, context="library lookup result")
        # The final observation has fresh routing inputs and reads every bound file again.
        with storage_read_phase():
            stable = read.stable()
        if stable:
            return result
    read.issue("identity", "unstable", "", "inputs or matching membership changed on both bounded attempts")
    result = _result(read, selector, sections, outcome, 2)
    result["collection"] = "unstable"
    result["fingerprint"] = sha256_bytes(canonical_bytes({key: value for key, value in result.items() if key not in {"execution", "fingerprint"}}))
    return result


def _result(read: RecordRead, selector: dict, sections: dict, outcome: str | None, attempts: int,
            *, error: str | None = None) -> dict:
    if error:
        read.issue("identity", "invalid_request", "", error)
    diagnostics = sorted(read.diagnostics, key=lambda item: (item["section"], item["path"], item["code"], item["message"]))
    for name, section in sections.items():
        failures = [diagnostic["code"] for diagnostic in diagnostics if diagnostic["section"] == name and diagnostic["severity"] == "error"]
        if failures:
            section["health"] = next((health for health in ("unavailable", "invalid", "stale") if health in failures), "invalid")
    coordination_coverage = sections.get("coordination", {}).get("data", {}).get("coverage")
    incomplete_required_coverage = coordination_coverage in {"incomplete", "unavailable"}
    result = {"contract": CONTRACT, "selector": selector, "resolution": outcome,
              "collection": "partial" if incomplete_required_coverage or any(item["severity"] == "error" for item in diagnostics) else "complete_declared_scope",
              "inspection_level": "records-and-presence", "sections": sections,
              "inputs": [read.inputs[key] for key in sorted(read.inputs)],
              "discovery": [read.discovery[key] for key in sorted(read.discovery)],
              "observations": [read.observations[key] for key in sorted(read.observations)],
              "routing": [{"path": key, "route_sha256": read.routing[key]} for key in sorted(read.routing)],
              "diagnostics": diagnostics, "update_routes": _routes(selector), "adapter_versions": ADAPTERS,
              "execution": {"observed_at": datetime.now(timezone.utc).isoformat(), "attempts": attempts}}
    result["fingerprint"] = sha256_bytes(canonical_bytes({key: value for key, value in result.items() if key != "execution"}))
    return result


def lookup_exit_code(result: dict) -> int:
    if result["resolution"] == "invalid_request":
        return 2
    if result["resolution"] == "ambiguous":
        return 5
    if result["collection"] != "complete_declared_scope":
        return 3
    if result["resolution"] == "not_found":
        return 4
    return 0 if result["resolution"] == "found" else 3


def render_library_record(result: dict) -> str:
    """Concise projection; the JSON result retains every bound input and fact."""
    lines = ["# Library record", "", f"Selector: {json.dumps(result['selector'], ensure_ascii=False, sort_keys=True)}",
             f"Resolution: {result['resolution'] or 'unavailable'}; collection: {result['collection']}.",
             "Inspection: small records and presence/size; current text-byte integrity is not assessed.",
             "Coverage: declared identities and explicitly named research/tracker populations; undeclared retained holdings and global task availability are not assessed.",
             f"Fingerprint: {result['fingerprint']}"]
    sections = result["sections"]
    identity = sections.get("identity", {}).get("data", {})
    work = identity.get("work", {})
    if work:
        lines.extend([f"Work: {work['title']} ({work['work_id']})", f"Identity: {identity['owner']}"])
    holdings = sections.get("holdings", {}).get("data", {})
    editions = holdings.get("editions", [])
    if work and not editions:
        lines.append("Holdings: no editions declared; recorded state is not inferred.")
    if len(editions) > 1:
        lines.append("Alternatives: multiple declared editions; no edition selected automatically.")
    for edition in editions:
        lines.extend(["", f"Edition: {edition['edition_id']} (form {edition['textual_form_id']})",
                      f"Recorded state: {edition['state_owner']}"])
        for target in edition["recorded_targets"]:
            lines.append(f"  {target['target_id']}: {target['stage']}" + (f"; {target['reason']}" if target.get("reason") else ""))
        if not edition["recorded_targets"]:
            lines.append("  stage not recorded")
        master = edition["master_presence"]
        lines.append(f"Master: {master['path']} (presence: {master['present']})")
        accept = edition["historical_acceptance"]
        if accept["record"]:
            record = accept["record"]
            lines.append(f"Acceptance: {accept['owner']} (historical; current bytes not assessed)")
            lines.append(f"Extent: {record.get('scope', {}).get('declared', 'not recorded')}")
            decision = record.get("decision", {})
            for blocker in decision.get("blockers", []):
                lines.append(f"Hold: {blocker}")
            assessment = decision.get("agent_assessment", {})
            for field in ("unresolved_claims", "unassessed_stronger_claims"):
                if assessment.get(field):
                    lines.append(f"{field.replace('_', ' ').title()}: " + "; ".join(assessment[field]))
        for acquisition in edition["acquisitions"]:
            lines.append(f"Source: {acquisition['owner']} ({acquisition['record']['provider']})")
        for scope in edition.get("scoped_holdings", []):
            lines.append(f"Acquisition scope: {scope['acquisition_id']}; master: {scope['master_presence']['path']}; acceptance: {scope['historical_acceptance']['owner']}")
    for name in ("research", "metadata", "selection", "coordination"):
        section = sections.get(name)
        if not section:
            continue
        data = section["data"]
        lines.append(f"{name.title()}: {section['health']}")
        if name == 'metadata':
            for edition in data.get('rights', []):
                lines.append(f"Rights: {edition['edition_id']}; {edition['health']}; {edition['coverage']}")
                for item in edition['records'] if edition['health'] == 'valid' else []:
                    record = item['record']
                    lines.append(f"  {record['subject']['id']}: {record['rights_status']}; {record['scope']}; "
                                 f"{','.join(record['jurisdictions']) or 'territory unspecified'}; "
                                 f"{record['basis']}; {record['condition']}")
        for field, label, identifier, owner in (
            ("leads", "Lead", "lead_id", None), ("catalog_entries", "Catalog alternative", "tfr_entry_id", None),
            ("claim_holds", "Claim hold", "status", "migration_owner"),
            ("source_observations", "Metadata", "subject", "owner"),
            ("tasks", "Task", "task", "tracker"),
            ("current_decisions", "Decision", "status", "owner"),
        ):
            for item in data.get(field, []):
                detail = str(item.get(identifier, "unknown"))
                if owner:
                    detail += f"; {item.get(owner, 'unknown')}"
                if field == "tasks":
                    detail += f"; {item['applicability']}; owner: {item.get('owner') or 'unknown'}; status: {item['status']}"
                    if item.get("next_action"):
                        detail += f"; next: {item['next_action']}"
                lines.append(f"  {label}: {detail}")
                if field == 'leads' and item.get('cataloging'):
                    note = item['cataloging']
                    lines.append(f"    Cataloging: {note['path']}")
                    for key, heading in (('title', 'Title'), ('author', 'Author'), ('publication', 'Publication'), ('open_questions', 'Still to check')):
                        if note['fields'][key]:
                            lines.append(f"    {heading}: {note['fields'][key]}")
                if field == "tasks":
                    for route in item.get("dependencies", []) + item.get("successors", []):
                        lines.append(f"    Follow: {route.get('tracker', route['reference'])} ({route['health']})")
        if data.get("release_record"):
            lines.append(f"  Selection: {data['release_record']['owner']} (current readiness not assessed)")
        if name == "coordination":
            lines.append(f"  Coverage: {data.get('coverage', 'not assessed')}; availability to start: not assessed")
            if data.get('coverage') == 'complete_explicit_scope':
                lines.append('  Explicit tracker references inspected; free-form project prose is not interpreted as task assignments.')
    for diagnostic in result["diagnostics"]:
        lines.append(f"{diagnostic['severity'].title()}: {diagnostic['section']}/{diagnostic['code']}: {diagnostic['path']}: {diagnostic['message']}")
    lines.append("Details and update routes: repeat the lookup with --json.")
    return "\n".join(lines)
