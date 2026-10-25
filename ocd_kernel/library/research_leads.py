"""Conserve lead identity and decisions while rebinding exact source observations."""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock, _replace_with_retry, write_json_atomic
from ocd_kernel.lib.path_io import io_path
from ocd_kernel.lib.storage_topology import StorageTopologyError, resolve_repo_path
from ._common import PipelineError, _reject_duplicate_keys, canonical_bytes, load_json, safe_identifier, sha256_bytes, sha256_file, read_input_bytes, read_input_lines
from .acquisitions import load_acquisition_leads, manifest_research
from .identities import _schema, validate_record


EDITORIAL_FIELDS = ("acquisition_intent", "disposition", "work_id", "resolution")
OBSERVATION_FIELDS = ("observed_claim", "evidence", "context", "columns")


def migration_path(identifier: str) -> str:
    return f"research/lead-history/{safe_identifier(identifier, field='migration_id')}/migration.json"


def _queue(raw: bytes) -> list[dict]:
    records = []
    seen: set[str] = set()
    for number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        try:
            record = json.loads(line, object_pairs_hook=_reject_duplicate_keys)
        except json.JSONDecodeError as exc:
            raise PipelineError(f"invalid historical lead queue at line {number}") from exc
        if not isinstance(record, dict) or not isinstance(record.get("lead_id"), str):
            raise PipelineError(f"invalid historical lead identity at line {number}")
        safe_identifier(record["lead_id"], field="lead_id")
        if not isinstance(record.get("observed_claim"), str) or not isinstance(record.get("evidence"), dict) or not isinstance(record.get("context"), list):
            raise PipelineError(f"invalid historical claim/evidence/context: {record['lead_id']}")
        if record.get("schema_version") not in {"2.0", "2.1", "2.2"} or not isinstance(record.get("acquisition_intent"), str) or record.get("disposition") not in {"unresolved", "promoted", "closed"}:
            raise PipelineError(f"invalid historical editorial record: {record['lead_id']}")
        if record["lead_id"] in seen:
            raise PipelineError(f"duplicate historical lead: {record['lead_id']}")
        seen.add(record["lead_id"])
        records.append(record)
    return records


def _bound_bytes(root: Path, binding: dict) -> bytes:
    body = read_input_bytes(resolve_repo_path(root, binding["path"]))
    if sha256_bytes(body) != binding["sha256"]:
        raise PipelineError(f"stale migration witness: {binding['path']}")
    return body


def _bound_claim(root: Path, binding: dict) -> str:
    body = _bound_bytes(root, binding)
    lines = read_input_lines(resolve_repo_path(root, binding["path"]), body=body)
    start, end = binding["line_start"], binding["line_end"]
    if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines):
        raise PipelineError(f"invalid migration witness extent: {binding['path']}")
    return "\n".join(lines[start-1:end])


def load_migration(root: Path, identifier: str, cache: dict[str, Any]) -> tuple[dict, dict, dict]:
    if identifier not in cache:
        document = load_json(resolve_repo_path(root, migration_path(identifier)))
        validate_record("lead-migration", document, context=identifier)
        if document["migration_id"] != identifier:
            raise PipelineError(f"contradictory migration ID: {identifier}")
        home = migration_path(identifier).rsplit("/", 1)[0]
        if document["queue_before"]["path"] != f"{home}/queue-before.jsonl" or document["claims_before"]["path"] != f"{home}/claims-before.txt":
            raise PipelineError(f"migration witnesses are outside their immutable scope: {identifier}")
        prior = _queue(_bound_bytes(root, document["queue_before"]))
        before = {record["lead_id"]: record for record in prior}
        entries = {entry["lead_id"]: entry for entry in document["entries"]}
        if len(entries) != len(document["entries"]) or set(before) - set(entries):
            raise PipelineError(f"migration drops or duplicates historical identities: {identifier}")
        _bound_bytes(root, document["claims_before"])
        current = resolve_repo_path(root, document["manifest_current"]["path"])
        if sha256_bytes(read_input_bytes(current)) != document["manifest_current"]["sha256"]:
            raise PipelineError(f"stale current manifest in migration: {identifier}")
        cache[identifier] = document, before, entries
    return cache[identifier]


def validate_migrated_lead(record: dict, *, root: Path, expected: dict, cache: dict[str, Any]) -> str | None:
    identifier = record["lead_id"]
    document, prior, entries = load_migration(root, record["migration_id"], cache)
    entry = entries.get(identifier)
    if entry is None:
        raise PipelineError(f"unevidenced migrated lead: {identifier}")
    observation_id = entry["current_observation_id"]
    current = expected.get(observation_id)
    if observation_id is not None and current is None:
        raise PipelineError(f"migration current observation is missing: {identifier}")
    if current and (entry["current_evidence"] != current["evidence"] or entry["current_claim_sha256"] != sha256_bytes(current["observed_claim"].encode("utf-8"))):
        raise PipelineError(f"migration current observation differs: {identifier}")
    if identifier in prior:
        previous = prior[identifier]
        if entry["status"] == "added" or entry["previous_evidence"] != previous["evidence"]:
            raise PipelineError(f"migration changes previous binding: {identifier}")
        if record["observed_claim"] != previous["observed_claim"]:
            raise PipelineError(f"migration changes the conserved claim: {identifier}")
        if record.get("acquisition_intent") != previous.get("acquisition_intent"):
            raise PipelineError(f"migration changes acquisition intent: {identifier}")
        if record["schema_version"] != "2.2" and any(record.get(field) != previous.get(field) for field in EDITORIAL_FIELDS):
            raise PipelineError(f"migration changes editorial decisions: {identifier}")
        if entry["history_evidence"] is None or any(entry["history_evidence"][field] != document["claims_before"][field] for field in ("path", "sha256")):
            raise PipelineError(f"migration claim witness is outside its immutable scope: {identifier}")
        if entry["old_claim_sha256"] != sha256_bytes(previous["observed_claim"].encode("utf-8")) or _bound_claim(root, entry["history_evidence"]) != previous["observed_claim"]:
            raise PipelineError(f"migration loses exact previous claim: {identifier}")
        if entry["status"] in {"changed_claim_hold", "ambiguous_claim_hold", "unresolved_claim_hold"}:
            if record["observed_claim"] != previous["observed_claim"] or record["evidence"] != entry["history_evidence"]:
                raise PipelineError(f"held claim was silently revised: {identifier}")
            return observation_id
    elif entry["status"] != "added" or not identifier.startswith("TFR-20261001-"):
        raise PipelineError(f"migration creates an unassigned identity: {identifier}")
    elif any(entry[field] is not None for field in ("old_claim_sha256", "history_evidence", "previous_evidence")):
        raise PipelineError(f"added identity has invented previous evidence: {identifier}")
    if current is None or any(record.get(field) != current.get(field) for field in OBSERVATION_FIELDS):
        raise PipelineError(f"migrated source observation differs: {identifier}")
    return observation_id


def _line_binding(root: Path, reference: str, start: int, end: int) -> tuple[dict, str]:
    try:
        path = resolve_repo_path(root, reference)
    except (StorageTopologyError, TypeError) as exc:
        raise PipelineError(f"invalid lead evidence path: {reference}") from exc
    body = read_input_bytes(path)
    lines = read_input_lines(path, body=body)
    if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines):
        raise PipelineError(f"invalid lead evidence extent: {reference}")
    return ({"path": reference, "sha256": sha256_bytes(body), "line_start": start, "line_end": end},
            "\n".join(lines[start - 1:end]))


def plan_lead_upkeep(
    root: Path, *, lead_id: str, evidence_path: str, line_start: int, line_end: int,
    disposition: str | None = None, work_id: str | None = None,
    acquisition_intent: str | None = None, context: list[str] | None = None,
) -> dict:
    """Plan one current lead addition or disposition change without remigration."""
    root = Path(root).resolve()
    safe_identifier(lead_id, field="lead_id")
    binding, claim = _line_binding(root, evidence_path, line_start, line_end)
    queue_path = resolve_repo_path(root, "library/acquisition-leads.jsonl")
    before = read_input_bytes(queue_path)
    records = _queue(before)
    matches = [record for record in records if record["lead_id"] == lead_id]
    if len(matches) > 1:
        raise PipelineError(f"ambiguous lead identity: {lead_id}")
    if matches:
        if disposition not in {"promoted", "closed"} or acquisition_intent is not None or context is not None:
            raise PipelineError("existing lead upkeep requires promoted or closed disposition only")
        record = matches[0]
        if record["disposition"] != "unresolved":
            raise PipelineError(f"lead already has a current disposition: {lead_id}")
        if record.get("migration_id"):
            _, _, entries = load_migration(root, record["migration_id"], {})
            if entries[lead_id]["status"].endswith("_hold"):
                raise PipelineError(f"held lead claim requires separate identity review: {lead_id}")
        record["schema_version"] = "2.2"
        record["disposition"] = disposition
        record["resolution"] = claim
        record["decision_evidence"] = binding
        if disposition == "promoted":
            if work_id is None:
                raise PipelineError("promoted lead requires work_id")
            record["work_id"] = safe_identifier(work_id, field="work_id")
        elif work_id is not None:
            raise PipelineError("closed lead cannot carry work_id")
        else:
            record.pop("work_id", None)
        action = "update"
    else:
        if disposition is not None or work_id is not None:
            raise PipelineError("new lead starts unresolved")
        if not acquisition_intent or not context or not all(isinstance(value, str) and value.strip() for value in context):
            raise PipelineError("new lead requires acquisition intent and context")
        if any(record["observed_claim"] == claim or record["evidence"] == binding for record in records):
            raise PipelineError("new lead evidence is ambiguous with an existing lead")
        records.append({"schema_version": "2.2", "lead_id": lead_id, "observed_claim": claim,
                        "evidence": binding, "acquisition_intent": acquisition_intent,
                        "disposition": "unresolved", "context": context})
        action = "add"
    records.sort(key=lambda item: item["lead_id"])
    after = b"".join(canonical_bytes(record) for record in records)
    return {"action": action, "lead_id": lead_id, "queue_before_sha256": sha256_bytes(before),
            "queue_after": after, "queue_after_sha256": sha256_bytes(after)}


def apply_lead_upkeep(root: Path, plan: dict) -> dict:
    """Atomically apply one preflighted current lead operation."""
    root = Path(root).resolve()
    queue_path = resolve_repo_path(root, "library/acquisition-leads.jsonl")
    with acquire_jsonl_lock(queue_path):
        if sha256_file(queue_path) != plan["queue_before_sha256"]:
            raise PipelineError("lead queue changed before upkeep")
        pending = queue_path.with_name(f"acquisition-leads.pending-upkeep-{plan['lead_id']}.jsonl")
        io_path(pending).write_bytes(plan["queue_after"])
        try:
            load_acquisition_leads(pending, root=root)
            if sha256_file(queue_path) != plan["queue_before_sha256"]:
                raise PipelineError("lead queue changed during upkeep; queue unchanged")
            _replace_with_retry(pending, queue_path)
        finally:
            if io_path(pending).exists():
                io_path(pending).unlink()
    return {key: plan[key] for key in ("action", "lead_id", "queue_before_sha256", "queue_after_sha256")}


def plan_lead_repair(root: Path) -> dict:
    """Build one bounded repair; exact comparison and holds replace guessed rebinding."""
    root = Path(root)
    queue_path = root / "library/acquisition-leads.jsonl"
    queue_raw = io_path(queue_path).read_bytes()
    previous = _queue(queue_raw)
    previous_by_id = {record["lead_id"]: record for record in previous}
    imported = manifest_research(root / "research/MANIFEST.md", root=root)
    manifest_raw = io_path(root / "research/MANIFEST.md").read_bytes()
    migration_id = "lead-repair-" + sha256_bytes(canonical_bytes({"queue": sha256_bytes(queue_raw), "manifest": sha256_bytes(manifest_raw)}))[:16]
    home = f"research/lead-history/{migration_id}"
    claim_lines: list[str] = []
    extents = {}
    for record in previous:
        start = len(claim_lines) + 1
        claim_lines.extend(record["observed_claim"].split("\n"))
        extents[record["lead_id"]] = (start, len(claim_lines))
    claims_raw = ("\n".join(claim_lines) + "\n").encode("utf-8")
    candidates: dict[str, list[dict]] = defaultdict(list)
    for observation in imported["leads"]:
        candidates[observation["observed_claim"]].append(observation)
    records, entries, used = [], [], set()
    old_maps: dict[str, dict] = {}
    for previous_record in previous:
        identifier = previous_record["lead_id"]
        matching = candidates.get(previous_record["observed_claim"], [])
        observation = matching[0] if len(matching) == 1 else None
        if observation is not None and observation["lead_id"] in used:
            observation = None
        history = {"path": f"{home}/claims-before.txt", "sha256": sha256_bytes(claims_raw),
                   "line_start": extents[identifier][0], "line_end": extents[identifier][1]}
        record = deepcopy(previous_record)
        record.update(schema_version="2.1", migration_id=migration_id)
        if observation:
            for field in OBSERVATION_FIELDS:
                if field in observation:
                    record[field] = deepcopy(observation[field])
                else:
                    record.pop(field, None)
            status = "unchanged" if previous_record["evidence"]["line_start"] == observation["evidence"]["line_start"] else "moved"
        else:
            locator = previous_record["evidence"]
            if "migration_id" in previous_record:
                old_id = previous_record["migration_id"]
                if old_id not in old_maps:
                    old_maps[old_id] = load_json(root / migration_path(old_id))
                prior_entry = next(entry for entry in old_maps[old_id]["entries"] if entry["lead_id"] == identifier)
                locator = prior_entry["current_evidence"] or locator
            possible = [item for item in imported["leads"] if item["evidence"]["line_start"] == locator["line_start"] and item["context"] == previous_record["context"] and item["lead_id"] not in used]
            observation = possible[0] if len(possible) == 1 else None
            record["evidence"] = history
            status = ("ambiguous_claim_hold" if len(matching) > 1 else "changed_claim_hold") if observation else "unresolved_claim_hold"
        if observation:
            used.add(observation["lead_id"])
        records.append(record)
        entries.append({"lead_id": identifier, "status": status, "old_claim_sha256": sha256_bytes(previous_record["observed_claim"].encode("utf-8")),
                        "history_evidence": history, "previous_evidence": previous_record["evidence"],
                        "current_observation_id": observation["lead_id"] if observation else None,
                        "current_evidence": observation["evidence"] if observation else None,
                        "current_claim_sha256": sha256_bytes(observation["observed_claim"].encode("utf-8")) if observation else None})
    unassigned = []
    for observation in imported["leads"]:
        if observation["lead_id"] in used:
            continue
        if not observation["lead_id"].startswith("TFR-20261001-"):
            unassigned.append(observation["lead_id"])
            continue
        record = deepcopy(observation)
        record.update(schema_version="2.1", migration_id=migration_id)
        records.append(record)
        entries.append({"lead_id": record["lead_id"], "status": "added", "old_claim_sha256": None,
                        "history_evidence": None, "previous_evidence": None,
                        "current_observation_id": record["lead_id"], "current_evidence": record["evidence"],
                        "current_claim_sha256": sha256_bytes(record["observed_claim"].encode("utf-8"))})
        used.add(record["lead_id"])
    if unassigned:
        raise PipelineError(f"unassigned manifest observations require explicit stable identity or hold review: {unassigned}")
    records.sort(key=lambda record: record["lead_id"])
    queue_after = b"".join(canonical_bytes(record) for record in records)
    document = {"contract": "ocd-lead-migration-v1", "migration_id": migration_id,
                "queue_before": {"path": f"{home}/queue-before.jsonl", "sha256": sha256_bytes(queue_raw)},
                "claims_before": {"path": f"{home}/claims-before.txt", "sha256": sha256_bytes(claims_raw)},
                "manifest_current": imported["manifest"], "entries": sorted(entries, key=lambda entry: entry["lead_id"]),
                "historical_basis": "Exact previous queue bytes and literal observed claims retained. Previous full-manifest bindings are historical declarations, not a claim that the old full document was recovered or reverified. Changed-row locators are candidates on hold, not identity judgments."}
    validate_record("lead-migration", document)
    conservation = {"contract": "ocd-lead-conservation-v1", "migration_id": migration_id,
                    "old_leads": len(previous), "new_leads": len(records),
                    "statuses": dict(sorted(Counter(entry["status"] for entry in entries).items())),
                    "before_dispositions": dict(sorted(Counter(record["disposition"] for record in previous).items())),
                    "after_dispositions": dict(sorted(Counter(record["disposition"] for record in records).items())),
                    "conserved_ids": sorted(record["lead_id"] for record in previous),
                    "added_ids": sorted(set(record["lead_id"] for record in records) - set(record["lead_id"] for record in previous)),
                    "editorial_fields_conserved": all(all(record.get(field) == previous_by_id[record["lead_id"]].get(field) for field in EDITORIAL_FIELDS) for record in records if record["lead_id"] in extents),
                    "queue_before_sha256": sha256_bytes(queue_raw), "queue_after_sha256": sha256_bytes(queue_after),
                    "manifest_sha256": imported["manifest"]["sha256"], "historical_basis": document["historical_basis"]}
    return {"records": records, "migration": document, "conservation": conservation,
            "history": {f"{home}/queue-before.jsonl": queue_raw, f"{home}/claims-before.txt": claims_raw,
                        f"{home}/manifest-at-repair.md": manifest_raw}, "queue_after": queue_after}


def apply_lead_repair(root: Path, plan: dict) -> dict:
    """Install immutable witnesses first; atomically replace the queue last."""
    root = Path(root)
    queue_path = resolve_repo_path(root, "library/acquisition-leads.jsonl")
    conservation = plan["conservation"]
    with acquire_jsonl_lock(queue_path):
        if sha256_file(queue_path) != conservation["queue_before_sha256"] or sha256_file(root / "research/MANIFEST.md") != conservation["manifest_sha256"]:
            raise PipelineError("lead repair inputs changed before installation")
        for reference, body in plan["history"].items():
            destination = resolve_repo_path(root, reference)
            io_path(destination.parent).mkdir(parents=True, exist_ok=True)
            if io_path(destination).exists() and io_path(destination).read_bytes() != body:
                raise PipelineError(f"immutable lead witness differs: {reference}")
            io_path(destination).write_bytes(body)
        map_path = resolve_repo_path(root, migration_path(plan["migration"]["migration_id"]))
        if io_path(map_path).exists() and load_json(map_path) != plan["migration"]:
            raise PipelineError("immutable migration map differs")
        write_json_atomic(map_path, plan["migration"], _schema("lead-migration"))
        pending = queue_path.with_name(f"acquisition-leads.pending-{plan['migration']['migration_id']}.jsonl")
        io_path(pending).write_bytes(plan["queue_after"])
        load_acquisition_leads(pending, root=root)
        if sha256_file(queue_path) != conservation["queue_before_sha256"] or sha256_file(root / "research/MANIFEST.md") != conservation["manifest_sha256"]:
            raise PipelineError("lead repair inputs changed during staged validation; queue unchanged")
        _replace_with_retry(pending, queue_path)
    load_acquisition_leads(queue_path, root=root)
    report = map_path.with_name("conservation.json")
    io_path(report).write_bytes(canonical_bytes(conservation))
    return conservation
