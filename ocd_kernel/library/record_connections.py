"""Concrete research, metadata, and tracker connections; no new fact owners."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re

from ._common import PipelineError, _reject_duplicate_keys, sha256_bytes, safe_identifier, read_input_lines
from .acquisitions import load_acquisition, load_acquisition_leads
from .identities import _schema_path, load_work, validate_record
from .research_leads import migration_path, _queue

CATALOG = "research/the-faith-received/source/the-faith-received-complete-works-20260930.md"
LINKS = "research/library-record-links.json"
QUEUE = "library/acquisition-leads.jsonl"
SCOPE = "research/the-faith-received/english-non-machine-scope-20261001.md"
WORKLIST = "plans/2026-09-23-acquisition-manifest-source-to-tei/WORKLIST.md"
LEDGER = "plans/2026-08-31-library-pipeline-redesign/04-ticket-ledger.md"
COMPLETION = "plans/2026-08-31-library-pipeline-redesign/18-unified-ocd-completion-plan.md"


def _json(read, reference, section):
    body = read.bytes(reference, section)
    if body is None:
        return None
    try:
        return json.loads(body, object_pairs_hook=_reject_duplicate_keys)
    except (ValueError, UnicodeError) as exc:
        raise PipelineError(f"invalid JSON at {reference}: {exc}") from exc


def _bind(read, binding, section):
    body = read.bytes(binding["path"], section)
    if body is None:
        raise PipelineError(f"unavailable evidence: {binding['path']}")
    if sha256_bytes(body) != binding["sha256"]:
        raise PipelineError(f"stale evidence: {binding['path']}")
    if "line_start" in binding:
        lines = read_input_lines(read.paths[binding["path"]], body=body)
        start, end = binding["line_start"], binding["line_end"]
        if not 1 <= start <= end <= len(lines):
            raise PipelineError(f"invalid extent: {binding['path']}")
        return "\n".join(lines[start-1:end])
    return body.decode("utf-8")


def _leads(read):
    body = read.bytes(QUEUE, "research")
    if body is None:
        return []
    read.bytes("research/MANIFEST.md", "research")
    raw = _queue(body)
    maps = {}
    for record in raw:
        # The existing validator may read evidence. Pre-bind its entire small-record
        # population and reject text bodies before invoking it.
        _bind(read, record["evidence"], "research")
        if record.get("migration_id") not in maps and "migration_id" in record:
            identifier = record["migration_id"]
            document = _json(read, migration_path(identifier), "research")
            validate_record("lead-migration", document, context=identifier)
            home = migration_path(identifier).rsplit("/", 1)[0]
            if document["queue_before"]["path"] != home + "/queue-before.jsonl" or document["claims_before"]["path"] != home + "/claims-before.txt":
                raise PipelineError("migration witnesses escape their immutable scope")
            for name in ("queue_before", "claims_before", "manifest_current"):
                _bind(read, document[name], "research")
            maps[identifier] = document
        if record.get("disposition") == "promoted":
            read.bytes(f"library/works/{record['work_id']}/work.json", "research")
    return load_acquisition_leads(read.paths[QUEUE], root=read.root)


def _catalog(read):
    if read.bytes(CATALOG, "research") is None:
        return []
    parser_path = Path(__file__).resolve().parents[2] / "research/the-faith-received/reconcile_catalog.py"
    read.bytes("@runtime/research/the-faith-received/reconcile_catalog.py", "research", physical=parser_path)
    spec = importlib.util.spec_from_file_location("ocd_retained_tfr_parser", parser_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    records, _, _ = module.parse_catalog(read.paths[CATALOG], allow_duplicate_ids=True)
    return records


def _endpoint(read, endpoint, leads, catalog):
    for field in ("id", "work_id", "textual_form_id", "edition_id"):
        if field in endpoint:
            safe_identifier(endpoint[field], field=field)
    kind, identifier = endpoint["kind"], endpoint["id"]
    if kind in {"research_lead", "source_catalog_entry"}:
        records, field = (leads, "lead_id") if kind == "research_lead" else (catalog, "tfr_entry_id")
        if sum(record[field] == identifier for record in records) != 1:
            raise PipelineError(f"relationship endpoint is missing or ambiguous: {kind}:{identifier}")
        return
    work_id = identifier if kind == "work" else endpoint["work_id"]
    base = f"library/works/{work_id}"
    work = read.record(f"{base}/work.json", "research", load_work)
    if work is None or work["work_id"] != work_id:
        raise PipelineError(f"relationship endpoint work unavailable or inconsistent: {work_id}")
    if kind == "work":
        return
    form_id = identifier if kind == "textual_form" else endpoint["textual_form_id"]
    form = next((item for item in work["textual_forms"] if item["textual_form_id"] == form_id), None)
    if form is None:
        raise PipelineError(f"relationship endpoint form is undeclared: {identifier}")
    if kind == "textual_form":
        return
    edition_id = identifier if kind == "edition" else endpoint["edition_id"]
    edition = next((item for item in form["editions"] if item["edition_id"] == edition_id), None)
    if edition is None or kind == "acquisition" and identifier not in edition.get("acquisition_ids", []):
        raise PipelineError(f"relationship endpoint hierarchy is undeclared: {identifier}")
    if kind == "acquisition":
        reference = f"{base}/forms/{form_id}/editions/{edition_id}/acquisitions/{identifier}.json"
        acquisition = read.record(reference, "research", load_acquisition)
        if acquisition is None or acquisition["acquisition_id"] != identifier or acquisition["edition_id"] != edition_id:
            raise PipelineError(f"relationship endpoint acquisition unavailable or inconsistent: {reference}")


def _relationships(read, leads, catalog):
    document = _json(read, LINKS, "research")
    if document is None:
        return {"relationships": [], "associations": []}
    validate_record("library-record-links", document)
    if len({link["relationship_id"] for link in document["relationships"]}) != len(document["relationships"]):
        raise PipelineError("duplicate relationship identity")
    for link in document["relationships"]:
        for evidence in link["evidence"]:
            _bind(read, evidence, "research")
        target = link["target"]
        for endpoint in (link["source"], target):
            _endpoint(read, endpoint, leads, catalog)
        required_kind = {"same_work": "work", "same_textual_form": "textual_form", "same_edition": "edition", "same_acquisition": "acquisition"}.get(link["relation"])
        if required_kind and target["kind"] != required_kind:
            raise PipelineError(f"relationship strength exceeds its target: {link['relationship_id']}")
        if link["decision_status"] == "reviewed" and (not link["reviewer"] or not link["decided_at"] or not link["judgment"]):
            raise PipelineError(f"reviewed relationship lacks attributed judgment: {link['relationship_id']}")
        if (required_kind or link["relation"] == "partial_component") and link["current_applicability"] == "supported" and link["decision_status"] != "reviewed":
            raise PipelineError(f"supported identity relationship requires reviewed judgment: {link['relationship_id']}")
        if link["relation"] == "partial_component" and link["extent"] is None:
            raise PipelineError(f"partial relationship lacks directional boundary: {link['relationship_id']}")
        if link["extent"]:
            endpoint = link["source"] if link["extent"]["direction"] == "source_contains_target" else link["target"]
            containing = link["extent"]["containing_identity"]
            if containing["kind"] not in {"work", "textual_form"} or (endpoint.get("work_id") or endpoint["id"]) != (containing.get("work_id") or containing["id"]):
                raise PipelineError(f"containment identity disagrees with its direction: {link['relationship_id']}")
            _endpoint(read, containing, leads, catalog)
            endpoint_form = endpoint["id"] if endpoint["kind"] == "textual_form" else endpoint.get("textual_form_id")
            if containing["kind"] == "textual_form" and endpoint_form and endpoint_form != containing["id"]:
                raise PipelineError(f"containment form disagrees with its endpoint: {link['relationship_id']}")
            for evidence in link["extent"]["evidence"]:
                _bind(read, evidence, "research")
        if link["source"]["id"] == "1928-bcp" and target["id"] == "bcp-1928-collects" and link["current_applicability"] == "supported":
            raise PipelineError("the corrected English Deposited Book comparison cannot establish American containment")
    return document


def _task_subjects(text):
    subjects = []
    labels = {"work": "Work ID", "textual_form": "Textual form ID", "edition": "Edition ID", "acquisition": "Acquisition ID",
              "research_lead": "(?:Research lead ID|Lead ID)", "source_catalog_entry": "(?:Source catalog entry|TFR entry ID)"}
    fields = {kind: re.findall(rf"\*\*{label}:\*\*\s*`([^`]+)`", text, flags=re.IGNORECASE) for kind, label in labels.items()}
    for kind, namespace in (("research_lead", "research"), ("source_catalog_entry", "tfr")):
        subjects.extend({"kind": kind, "namespace": namespace, "id": identifier} for identifier in fields[kind])
    kind = next((kind for kind in ("acquisition", "edition", "textual_form", "work") if fields[kind]), None)
    if kind:
        parents = {"work": (), "textual_form": ("work",), "edition": ("work", "textual_form"), "acquisition": ("work", "textual_form", "edition")}[kind]
        if any(len(fields[parent]) != 1 for parent in parents):
            raise PipelineError(f"task {kind} subject requires unique parent IDs: {', '.join(parents)}")
        for identifier in fields[kind]:
            subjects.append({"kind": kind, "namespace": "ocd", "id": identifier,
                             **{f"{parent}_id": fields[parent][0] for parent in parents}})
    pattern = r"library/works/([A-Za-z0-9._-]+)(?:/forms/([A-Za-z0-9._-]+)(?:/editions/([A-Za-z0-9._-]+)(?:/acquisitions/([A-Za-z0-9._-]+)\.json)?)?)?"
    for match in re.finditer(pattern, text):
        work, form, edition, acquisition = match.groups()
        kind, identifier = ("acquisition", acquisition) if acquisition else ("edition", edition) if edition else ("textual_form", form) if form else ("work", work)
        subjects.append({"kind": kind, "namespace": "ocd", "id": identifier,
                         **({"work_id": work} if form else {}), **({"textual_form_id": form} if edition else {}),
                         **({"edition_id": edition} if acquisition else {})})
    from .records import _selector
    return [_selector(subject) for subject in subjects]


def _ticket_tasks(read, selector, populations):
    tasks = []
    documents = []
    by_id = {}
    task_homes = []
    campaigns = read.members("plans", "????-??-??-*", "coordination", optional=True)
    for campaign in campaigns:
        campaign_path = f"plans/{campaign}"
        if read.observe(campaign_path)["kind"] != "directory":
            continue
        retirement = f"{campaign_path}/RETIREMENT.md"
        retired = read.observe(retirement)["present"] is True
        if retired:
            read.bytes(retirement, "coordination")
        for kind in ("issues", "tickets"):
            owner = f"{campaign_path}/{kind}"
            if read.observe(owner)["kind"] != "directory":
                continue
            task_homes.append((owner, "historical" if retired else "unknown"))
            for name in read.members(owner, "*", "coordination", optional=True):
                nested = f"{owner}/{name}"
                if read.observe(nested)["kind"] == "directory":
                    task_homes.append((nested, "historical" if retired or name == "_archive" else "unknown"))
    for reference, applicability in task_homes:
        pattern = "*.md"
        names = read.members(reference, pattern, "coordination", optional=True)
        for name in names:
            body = read.bytes(f"{reference}/{name}", "coordination")
            if body is not None:
                try:
                    text = body.decode("utf-8")
                except UnicodeDecodeError as exc:
                    try:
                        text = body.decode("cp1252")
                        encoding = "Windows-1252"
                    except UnicodeDecodeError:
                        text = body.decode("utf-8", errors="replace")
                        encoding = "UTF-8 with replacement characters"
                    read.issue("coordination", "legacy-encoding", f"{reference}/{name}",
                               f"decoded as {encoding} after invalid UTF-8 at byte {exc.start}; raw-byte hash is retained",
                               severity="warning")
                ticket = re.search(r"(?mi)^(?:ticket|issue):\s*([A-Z0-9-]+)\s*$|^\*\*(?:Ticket|Issue) ID:\*\*\s*([A-Z0-9-]+)\s*$", text)
                fallback = re.match(r"(?:[A-Z]+-\d+(?:-\d+)?|37c-\d+)", name)
                if ticket is None and fallback is None:
                    continue
                identifier = next(value for value in ticket.groups() if value) if ticket else fallback[0]
                path = f"{reference}/{name}"
                documents.append((identifier, path, text, applicability))
                by_id.setdefault(identifier, []).append(path)
        populations.append({"owner": reference, "coverage": "complete_named_population" if read.discovery[(reference, pattern)]["health"] == "valid" else "unavailable",
            "support": "supported", "applicability": applicability,
            "reason": f"Canonical task home ({pattern}); only explicit typed IDs and library hierarchy paths attach tasks to records"
                      + ("; historical population does not assert a current owner" if applicability == "historical" else "")})
    identifiers = r"\b(?:[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+|37c-\d{3})\b"
    for identifier, path, text, applicability in documents:
        subjects = _task_subjects(text)
        if selector not in subjects:
            continue
        subject = next(subject for subject in subjects if subject == selector)
        status = re.search(r"\*\*Status(?:[^*]*):\*\*\s*([^\n]+)|\*\*Status:\s*([^*]+)\*\*", text)
        owner = re.search(r"\*\*(?:Work owner|Owner):\*\*\s*([^\n]+)", text)
        blocked = re.search(r"\*\*Blocked by:\*\*\s*([^\n]+)", text)
        refs = re.findall(identifiers, blocked[1] if blocked else "")
        def references(values):
            return [{"reference": item,
                     "health": "resolved" if len(by_id.get(item, [])) == 1 else "invalid" if item in by_id else "unavailable",
                     **({"tracker": by_id[item][0]} if len(by_id.get(item, [])) == 1 else {})}
                    for item in values]
        dependencies = references(refs)
        dependency_coverage = "assessed" if refs or blocked and blocked[1].startswith("None") else "not_recorded"
        explicit = re.search(r"(?m)^\*\*Task applicability:\*\*\s*(current|historical|unknown)\s*$", text)
        next_action = re.search(r"(?m)^\*\*Next action:\*\*\s*([^\n]+)", text)
        successor = re.search(r"(?m)^\*\*Successors?:\*\*\s*([^\n]+)", text)
        from .identities import schema_enum
        typed = {}
        for field, title, definition in (('triage_label', 'Triage label', 'triage_label'), ('lifecycle', 'Lifecycle', 'task_lifecycle')):
            match = re.search(rf'(?m)^\*\*{title}:\*\*\s*([^\n]+)', text)
            typed[field] = match[1].strip() if match else None
            if typed[field] is not None and typed[field] not in schema_enum('library-record', definition):
                raise PipelineError(f'{path}: unsupported {field}: {typed[field]}')
        task_status = next((value.strip() for value in status.groups() if value), "unknown") if status else "unknown"
        current_applicability = explicit[1] if explicit and applicability != "historical" else applicability
        terminal = typed['lifecycle'] in ('complete', 'superseded', 'canceled')
        if terminal or successor:
            current_applicability = "historical"
        tasks.append({"tracker": path, "task": identifier, "subject": subject,
            "owner": owner[1].strip() if owner else None, "status": task_status, **typed,
            "applicability": current_applicability, "dependencies": dependencies, "dependency_coverage": dependency_coverage,
            "next_action": next_action[1].strip() if next_action else None,
            "successors": references(re.findall(identifiers, successor[1])) if successor else [],
            "evidence_sha256": read.inputs[path]["sha256"]})
    return tasks


def _coordination(read, selector, sections, work_id, associations):
    populations, tasks, decisions = [], [], []
    # Inspect anchor-selected authorities explicitly. Textual title matching is
    # deliberately absent; unsupported prose populations stay incomplete.
    for reference in ("PROJECT_STATE.md", WORKLIST, LEDGER, COMPLETION):
        observed = read.observe(reference)
        if not observed["present"]:
            populations.append({"owner": reference, "coverage": "unavailable", "support": "unsupported", "applicability": "unknown", "reason": "owning anchor is unavailable"})
            read.issue("coordination", "unavailable", reference, "current tracker population is unavailable")
            continue
        body = read.bytes(reference, "coordination")
        if body is None:
            continue
        text = body.decode("utf-8")
        populations.append({"owner": reference, "coverage": "incomplete", "support": "partial", "applicability": "current", "reason": "explicit record references supported; prose-only subjects and unmodeled sections unsupported"})
        if reference == "PROJECT_STATE.md":
            current = text.split("| Current work | Owner | Next verification |", 1)
            if len(current) == 2:
                for line in current[1].splitlines():
                    if not line.startswith("|"):
                        if line.strip():
                            break
                        continue
                    cells = line.strip("|").split("|")
                    subjects = _task_subjects(cells[0])
                    if selector in subjects:
                        if len(cells) != 3:
                            raise PipelineError("invalid current-owner table row")
                        owner = cells[1].strip() or None
                        subject = next(subject for subject in subjects if subject == selector)
                        tasks.append({"tracker": reference, "task": f"{subject['kind']}:{subject['id']}", "subject": subject, "owner": owner,
                                      "status": "unknown", "applicability": "current", "dependencies": [],
                                      "dependency_coverage": "not_recorded", "evidence_sha256": read.inputs[reference]["sha256"]})
        if reference == WORKLIST:
            current = text.split("## Current dispositions", 1)
            if len(current) != 2:
                raise PipelineError("current worklist section missing")
            for association in associations:
                subject = {"kind": "work", "namespace": "ocd", "id": association["work_id"]}
                if subject != selector or association["tracker"] != reference:
                    continue
                needle = f"| {association['task']} |"
                rows = [line for line in current[1].splitlines() if line.startswith(needle)]
                if len(rows) != 1:
                    raise PipelineError(f"task association has no unique current row: {association['task']}")
                row = rows[0]
                if sha256_bytes(row.encode("utf-8")) != association["row_sha256"]:
                    raise PipelineError(f"task association row changed: {association['task']}")
                cells = row.strip("|").split("|")
                if len(cells) != 3:
                    raise PipelineError("invalid worklist disposition row")
                decisions.append({"owner": reference, "target": subject, "task": association["task"],
                                  "status": cells[1].strip(), "claim": cells[2].strip(),
                                  "applicability": "current", "evidence_sha256": read.inputs[reference]["sha256"]})
                tasks.append({"tracker": reference, "task": association["task"], "subject": subject,
                              "owner": None, "status": cells[1].strip(), "applicability": "current",
                              "dependencies": [], "dependency_coverage": "not_recorded", "evidence_sha256": read.inputs[reference]["sha256"]})
    tasks.extend(_ticket_tasks(read, selector, populations))
    complete_explicit_scope = (all(item['coverage'] != 'unavailable' for item in populations)
                               and not any(item['section'] == 'coordination' and item['code'] == 'legacy-encoding'
                                           for item in read.diagnostics))
    owners = {task["owner"] for task in tasks if task["applicability"] == "current" and task["owner"]}
    sections["coordination"].update(health="valid", data={"tasks": tasks, "populations": populations,
        "ownership": "conflicted" if len(owners) > 1 else "recorded" if owners else "unknown",
        "coverage": "complete_explicit_scope" if complete_explicit_scope else "incomplete", "availability_to_start": "not_assessed"})
    sections["selection"]["data"].update(current_decisions=decisions, current_intent="recorded" if decisions else "unknown" if any(item["coverage"] == "unavailable" for item in populations) else "not_recorded_in_supported_scope", release_selection="not_assessed")


def _metadata(read, sections, work_id, associations):
    from build.lib.source_metadata import decision_owner, lookup_sidecar, sidecar_relative_path, MetadataError, SCHEMA_PATH, _validate_schema
    index = "metadata/source-evidence/index.json"
    if not read.observe(index)["present"]:
        return
    read.bytes("@runtime/metadata-source-evidence.schema.json", "metadata", physical=SCHEMA_PATH)
    payload = _json(read, index, "metadata")
    try:
        _validate_schema(payload, kind="index")
    except MetadataError as exc:
        raise PipelineError(str(exc)) from exc
    subjects = [{"kind": "catalog", "id": work_id}] + [item["metadata_subject"] for item in associations if item["work_id"] == work_id and "metadata_subject" in item]
    observations = []
    for subject in subjects:
        if not any(entry["subject"] == subject for entry in payload["subjects"]):
            continue
        relative = sidecar_relative_path(subject)
        if read.bytes(relative, "metadata") is None:
            continue
        try:
            sidecar = lookup_sidecar(read.root, subject["kind"], subject["id"])
        except MetadataError as exc:
            raise PipelineError(str(exc)) from exc
        authored_owner = decision_owner(read.root, subject["kind"], subject["id"], sidecar=sidecar)
        if read.bytes(authored_owner, "metadata") is None:
            raise PipelineError(f"metadata decision owner is unavailable: {authored_owner}")
        observations.append({"owner": relative, "projection_sha256": read.inputs[relative]["sha256"], "subject": subject,
            "record": sidecar, "authored_owner": authored_owner,
            "inspection": "validated metadata projection; source evidence and adoption not reverified"})
    sections["metadata"]["data"]["source_observations"] = observations


def _release(read, sections, work_id):
    from ocd_kernel.release.selection import load_release_selection
    reference = f"library/works/{work_id}/publication/selection.json"
    observed = read.observe(reference)
    if observed["health"] != "valid":
        read.issue("selection", "unavailable", reference, "release selection cannot be observed")
    if not observed["present"]:
        sections["selection"]["data"].update(release_selection="not_recorded_in_work_scope")
        return
    schema = Path(__file__).resolve().parents[2] / "schemas/v2/release-selection.schema.json"
    read.bytes("@runtime/schemas/v2/release-selection.schema.json", "selection", physical=schema)
    record = read.record(reference, "selection", load_release_selection)
    if record:
        prefix = f"library/works/{work_id}/forms/"
        if any(not item["acceptance_path"].startswith(prefix) for item in record["items"]):
            raise PipelineError("work-level release selection includes another work")
        sections["selection"]["data"].update(release_selection="recorded", release_record={"owner": reference, "record": record, "current_readiness": "not_assessed", "publication_authorization": "not_assessed"})


def collect_connections(read, selector, sections, outcome):
    work_id = sections["identity"]["data"].get("work", {}).get("work_id")
    catalog = []
    catalog_valid = False
    try:
        catalog = _catalog(read)
        catalog_valid = CATALOG in read.paths
        if selector["kind"] == "source_catalog_entry":
            matches = [entry for entry in catalog if entry["tfr_entry_id"] == selector["id"]]
            outcome = "ambiguous" if len(matches) > 1 else "found" if matches else "not_found" if CATALOG in read.paths else None
    except (PipelineError, ValueError, UnicodeError, OSError) as exc:
        read.issue("research", "invalid", CATALOG, exc)
    sections["research"].update(health="valid", data={"leads": [], "catalog_entries": [entry for entry in catalog if selector["kind"] == "source_catalog_entry" and entry["tfr_entry_id"] == selector["id"]],
        "relationships": [], "lead_population": None, "catalog_population": len(catalog) if catalog_valid else None, "production_observations": [], "claim_holds": []})
    try:
        for name in ("library-record-links", "lead-migration"):
            read.bytes(f"@runtime/schemas/v2/{name}.schema.json", "research", physical=_schema_path(name))
        leads = _leads(read)
        from .cataloging import load_note
        requested = [lead for lead in leads if selector['kind'] == 'research_lead' and lead['lead_id'] == selector['id']]
        for lead in requested:
            note = load_note(read.root, lead, read=read)
            if note is not None:
                lead['cataloging'] = note
        # A stale relationship elsewhere must not hide an independently bound lead note.
        sections['research']['data']['leads'] = requested
        document = _relationships(read, leads, catalog)
        all_links = document["relationships"]
        links = [link for link in all_links if (link["source"] == selector or (work_id and (link["target"].get("work_id") or link["target"]["id"]) == work_id))]
        lead_ids = {lead['lead_id'] for lead in leads}
        for association in document["associations"]:
            if association["lead_id"] not in lead_ids:
                raise PipelineError(f"association references a missing lead: {association['lead_id']}")
        linked_leads = {association["lead_id"] for association in document["associations"] if association["work_id"] == work_id}
        discovery_links = document.get("source_leads", [])
        for association in discovery_links:
            if association["lead_id"] not in lead_ids or association["entry_id"] not in {entry['tfr_entry_id'] for entry in catalog}:
                raise PipelineError("discovery association names a missing lead or catalog entry")
            _bind(read, association["evidence"], "research")
        discovery_links = [item for item in discovery_links if item["entry_id"] == (selector["id"] if selector["kind"] == "source_catalog_entry" else None)
                           or item["lead_id"] == (selector["id"] if selector["kind"] == "research_lead" else None)]
        linked_leads.update(item["lead_id"] for item in discovery_links)
        source_leads = {link["source"]["id"] for link in links if link["source"]["kind"] == "research_lead"}
        selected = [lead for lead in leads if lead["lead_id"] == (selector["id"] if selector["kind"] == "research_lead" else None) or lead.get("work_id") == work_id and work_id or lead["lead_id"] in linked_leads | source_leads]
        source_ids = {link["source"]["id"] for link in links if link["source"]["kind"] == "source_catalog_entry"}
        source_ids.update(item["entry_id"] for item in discovery_links)
        entries = [entry for entry in catalog if entry["tfr_entry_id"] in source_ids or selector["kind"] == "source_catalog_entry" and entry["tfr_entry_id"] == selector["id"]]
        if selector["kind"] == "research_lead":
            outcome = "found" if selected else "not_found" if QUEUE in read.paths else None
            if len(selected) == 1 and selected[0]["disposition"] == "promoted":
                from .records import _canonical
                work_id = selected[0]["work_id"]
                _canonical(read, {"kind": "work", "namespace": "ocd", "id": work_id}, sections)
        for lead in selected:
            note = lead.get('cataloging') or load_note(read.root, lead, read=read)
            if note is not None:
                lead['cataloging'] = note
        sections["research"].update(health="valid", data={"leads": selected, "catalog_entries": entries, "relationships": links,
            "lead_population": len(leads) if QUEUE in read.paths else None, "catalog_population": len(catalog) if catalog_valid else None, "production_observations": [], "claim_holds": [], "source_lead_connections": discovery_links})
        for lead in selected:
            if "migration_id" in lead:
                owner = migration_path(lead["migration_id"])
                migration = _json(read, owner, "research")
                entry = next(item for item in migration["entries"] if item["lead_id"] == lead["lead_id"])
                if entry["status"].endswith("_hold"):
                    sections["research"]["data"]["claim_holds"].append({"lead_id": lead["lead_id"], "status": entry["status"], "migration_owner": owner, "current_candidate": entry["current_evidence"]})
        if read.observe(SCOPE)["present"]:
            note = read.bytes(SCOPE, "research")
            for number, row in enumerate(note.decode("utf-8").splitlines() if note else [], 1):
                if row.startswith("| `") and any(f"| `{entry['tfr_entry_id']}` |" in row for entry in entries):
                    sections["research"]["data"]["production_observations"].append({"owner": SCOPE, "line": number, "observed_on": "2026-10-01", "claim": row,
                        "basis": "dated first-party UI observation", "translation": "source_claim_only", "ocr": "not_assessed", "later_processing": "unknown"})
        sections["selection"].update(health="valid", data={"historical_intent": [{"lead_id": lead["lead_id"], "owner": QUEUE,
            "intent": lead["acquisition_intent"], "disposition": lead["disposition"], "observed_claim": lead["observed_claim"]} for lead in selected]})
    except (PipelineError, ValueError, UnicodeError, KeyError, TypeError, OSError) as exc:
        read.issue("research", "stale" if "stale" in str(exc) else "invalid", LINKS, exc)
        if selector["kind"] == "research_lead":
            outcome = None
        document = {"associations": []}
    try:
        _coordination(read, selector, sections, work_id, document["associations"])
    except (PipelineError, UnicodeError, KeyError, TypeError) as exc:
        read.issue("coordination", "invalid", "", exc)
    if work_id:
        try:
            _metadata(read, sections, work_id, document["associations"])
        except (PipelineError, ValueError, KeyError, TypeError, OSError) as exc:
            read.issue("metadata", "invalid", "metadata/source-evidence", exc)
        try:
            _release(read, sections, work_id)
        except (PipelineError, ValueError, OSError) as exc:
            read.issue("selection", "invalid", "publication/selection.json", exc)
    return outcome
