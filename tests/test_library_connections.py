from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import pytest
from tests.test_library_records import root as canonical_root, write

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import load_acquisition_leads, manifest_research
from ocd_kernel.library.research_leads import apply_lead_repair, plan_lead_repair
from ocd_kernel.library.records import lookup_library_record, lookup_exit_code, render_library_record

def fixture(tmp_path):
    root = tmp_path / "r"
    manifest = root / "research/MANIFEST.md"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("# Research\n## Acquisition queue\n### Works\n| Work | Status |\n|---|---|\n| Same | NEXT |\n| Changed | NEXT |\n", encoding="utf-8")
    records = manifest_research(manifest, root=root)["leads"]
    (root / "library").mkdir(exist_ok=True)
    queue = root / "library/acquisition-leads.jsonl"
    queue.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return root, records

def change_manifest(root):
    path = root / "research/MANIFEST.md"
    text = path.read_text(encoding="utf-8").replace("| Changed | NEXT |", "| Changed | QUALITY HOLD |")
    path.write_text(text + "\n## 2026-10-01 TFR follow-up acquisition leads\n| Lead ID | Work |\n|---|---|\n| TFR-20261001-09 | English Deposited Book |\n", encoding="utf-8")

def test_repair_conserves_identity_decisions_and_changed_claim(tmp_path):
    root, previous = fixture(tmp_path)
    previous[0].update(disposition="closed", resolution="Explicitly deferred")
    (root / "library/acquisition-leads.jsonl").write_text("".join(json.dumps(record) + "\n" for record in previous), encoding="utf-8")
    before = (root / "library/acquisition-leads.jsonl").read_bytes()
    change_manifest(root)
    plan = plan_lead_repair(root)
    assert (root / "library/acquisition-leads.jsonl").read_bytes() == before
    report = apply_lead_repair(root, plan)
    assert report["old_leads"] == 2 and report["new_leads"] == 3
    assert report["statuses"] == {"added": 1, "changed_claim_hold": 1, "unchanged": 1}
    result = load_acquisition_leads(root / "library/acquisition-leads.jsonl", root=root)
    by_id = {record["lead_id"]: record for record in result}
    for old in previous:
        assert by_id[old["lead_id"]]["observed_claim"] == old["observed_claim"]
        assert by_id[old["lead_id"]]["disposition"] == old["disposition"]
    assert report["editorial_fields_conserved"]

@pytest.mark.parametrize("mutation", ["claim", "previous_evidence", "status", "witness"])
def test_migration_rejects_silent_revisions(tmp_path, mutation):
    root, previous = fixture(tmp_path)
    change_manifest(root)
    plan = plan_lead_repair(root)
    apply_lead_repair(root, plan)
    queue = root / "library/acquisition-leads.jsonl"
    records = [json.loads(line) for line in queue.read_text(encoding="utf-8").splitlines()]
    migration = root / f"research/lead-history/{plan['migration']['migration_id']}/migration.json"
    document = json.loads(migration.read_text(encoding="utf-8"))
    held = next(entry for entry in document["entries"] if entry["status"] == "changed_claim_hold")
    if mutation == "claim":
        record = next(record for record in records if record["lead_id"] == held["lead_id"])
        current = next(item for item in manifest_research(root / "research/MANIFEST.md", root=root)["leads"] if item["lead_id"] == held["current_observation_id"])
        record.update(observed_claim=current["observed_claim"], evidence=current["evidence"])
        held["status"] = "unchanged"
        queue.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    elif mutation == "previous_evidence":
        held["previous_evidence"]["sha256"] = "0" * 64
    elif mutation == "status":
        held["status"] = "added"
    else:
        (root / document["claims_before"]["path"]).write_text("corrupted", encoding="utf-8")
    migration.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(PipelineError):
        load_acquisition_leads(queue, root=root)

def test_failure_before_cutover_preserves_old_queue(tmp_path, monkeypatch):
    root, _ = fixture(tmp_path)
    change_manifest(root)
    plan = plan_lead_repair(root)
    path = root / "library/acquisition-leads.jsonl"
    before = path.read_bytes()
    import ocd_kernel.library.research_leads as module
    def reject(*args, **kwargs):
        raise PipelineError("staged validation failed")
    monkeypatch.setattr(module, "load_acquisition_leads", reject)
    with pytest.raises(PipelineError, match="staged"):
        apply_lead_repair(root, plan)
    assert path.read_bytes() == before

def test_changed_inputs_before_apply_do_not_write_queue(tmp_path):
    root, _ = fixture(tmp_path)
    change_manifest(root)
    plan = plan_lead_repair(root)
    path = root / "library/acquisition-leads.jsonl"
    before = path.read_bytes()
    (root / "research/MANIFEST.md").write_text("changed after planning", encoding="utf-8")
    with pytest.raises(PipelineError, match="inputs changed"):
        apply_lead_repair(root, plan)
    assert path.read_bytes() == before

def minimal_connections(root):
    path = root / "research/library-record-links.json"
    path.write_text(json.dumps({"contract": "ocd-library-record-links-v1", "relationships": [], "associations": []}), encoding="utf-8")
    catalog = root / "research/the-faith-received/source/the-faith-received-complete-works-20260930.md"
    catalog.parent.mkdir(parents=True)
    catalog.write_text("### English Editions (1 entries)\n#### Author not supplied\n- [Example](https://mereorthodoxy.com/the-faith-received/read/?w=example)\n", encoding="utf-8")

def test_exact_lead_lookup_is_read_only_and_reports_hold(tmp_path):
    root, previous = fixture(tmp_path)
    change_manifest(root)
    apply_lead_repair(root, plan_lead_repair(root))
    minimal_connections(root)
    files = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    result = lookup_library_record(root, {"kind": "research_lead", "namespace": "research", "id": previous[1]["lead_id"]})
    assert result["resolution"] == "found"
    assert result["sections"]["research"]["data"]["leads"][0]["observed_claim"] == previous[1]["observed_claim"]
    assert result["sections"]["research"]["data"]["claim_holds"][0]["status"] == "changed_claim_hold"
    assert files == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert result["fingerprint"] in render_library_record(result)
    assert result["sections"]["coordination"]["data"]["availability_to_start"] == "not_assessed"

def test_duplicate_catalog_identifier_is_ambiguous(tmp_path):
    root, _ = fixture(tmp_path)
    minimal_connections(root)
    path = root / "research/the-faith-received/source/the-faith-received-complete-works-20260930.md"
    path.write_text(path.read_text(encoding="utf-8").replace("(1 entries)", "(2 entries)") + "- [Second](https://mereorthodoxy.com/the-faith-received/read/?w=example)\n", encoding="utf-8")
    result = lookup_library_record(root, {"kind": "source_catalog_entry", "namespace": "tfr", "id": "example"})
    assert result["resolution"] == "ambiguous"
    assert lookup_exit_code(result) == 5
    assert len(result["sections"]["research"]["data"]["catalog_entries"]) == 2

def test_default_lookup_rejects_body_evidence_before_existing_validator(tmp_path, monkeypatch):
    root, _ = fixture(tmp_path)
    minimal_connections(root)
    path = root / "library/acquisition-leads.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    records[0]["evidence"]["path"] = "raw/huge.xml"
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    original = Path.open
    def guarded(path, *args, **kwargs):
        assert "raw" not in path.parts
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", guarded)
    result = lookup_library_record(root, {"kind": "research_lead", "namespace": "research", "id": records[0]["lead_id"]})
    assert result["resolution"] is None
    assert result["collection"] == "partial"

def test_removed_historical_hold_cannot_disappear_from_migrated_queue(tmp_path):
    root, _ = fixture(tmp_path)
    manifest = root / "research/MANIFEST.md"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace("| Changed | NEXT |\n", ""), encoding="utf-8")
    apply_lead_repair(root, plan_lead_repair(root))
    path = root / "library/acquisition-leads.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    records = [record for record in records if "Changed" not in record["observed_claim"]]
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    with pytest.raises(PipelineError, match="drops"):
        load_acquisition_leads(path, root=root)

@pytest.mark.parametrize("mutation", ["strength", "reviewer", "direction", "missing_extent", "duplicate", "correction"])
def test_relationship_claims_fail_closed(canonical_root, mutation):
    root = canonical_root
    from ocd_kernel.library.record_connections import _relationships
    from ocd_kernel.library.record_read import RecordRead
    evidence = {"path": "research/evidence.md", "sha256": hashlib.sha256((root / "research/evidence.md").read_bytes()).hexdigest()}
    link = {"relationship_id": "comparison", "source": {"kind": "source_catalog_entry", "namespace": "tfr", "id": "example"},
        "target": {"kind": "work", "namespace": "ocd", "id": "alpha"}, "relation": "same_work", "decision_status": "reviewed",
        "reviewer": "named-reviewer", "decided_at": "2026-10-03", "judgment": "Explicit work-level judgment only", "evidence": [evidence],
        "extent": None, "current_applicability": "supported", "legacy_relation": "candidate", "legacy_note": "Preserved", "unresolved_questions": []}
    if mutation == "strength":
        link["relation"] = "same_edition"
    elif mutation == "reviewer":
        link["reviewer"] = None
    elif mutation in {"direction", "missing_extent"}:
        link["relation"] = "partial_component"
        if mutation == "direction":
            link["extent"] = {"direction": "target_contains_source", "containing_identity": {"kind": "work", "namespace": "ocd", "id": "other"}, "boundary": "Chapters I-II", "evidence": [evidence]}
    elif mutation == "correction":
        old = root / "library/works/alpha/work.json"
        record = json.loads(old.read_text(encoding="utf-8"))
        record.update(work_id="bcp-1928-collects", textual_forms=[])
        write(root / "library/works/bcp-1928-collects/work.json", record)
        link["source"]["id"] = "1928-bcp"
        link["target"]["id"] = "bcp-1928-collects"
    links = [link, copy.deepcopy(link)] if mutation == "duplicate" else [link]
    write(root / "research/library-record-links.json", {"contract": "ocd-library-record-links-v1", "relationships": links, "associations": []})
    with pytest.raises(PipelineError):
        _relationships(RecordRead(root), [], [{"tfr_entry_id": link["source"]["id"]}])

def test_owner_conflicts_and_historical_owner_are_distinct(canonical_root):
    from ocd_kernel.library.record_connections import _coordination
    from ocd_kernel.library.record_read import RecordRead
    root = canonical_root
    (root / "PROJECT_STATE.md").write_text("| Current work | Owner | Next verification |\n|---|---|---|\n| [A](library/works/alpha/work.json) | Agent One | Working |\n| [A](library/works/alpha/state.json) | Agent Two | Reviewing |\n\n## Historical\n", encoding="utf-8")
    write(root / "plans/2026-08-31-library-pipeline-redesign/tickets/example.md", {})
    ticket = root / "plans/2026-08-31-sample-first-library-verification/issues/37c-001-alpha.md"
    ticket.parent.mkdir(parents=True)
    (ticket.parent.parent / "RETIREMENT.md").write_text("# Retired campaign\n", encoding="utf-8")
    ticket.write_text("**Work ID:** `alpha`\n**Owner:** Prior owner\n**Status:** Active historically\n**Blocked by:** 37c-999\n", encoding="utf-8")
    sections = {"selection": {"health": "not_assessed", "data": {}}, "coordination": {"health": "not_assessed", "data": {}}}
    _coordination(RecordRead(root), {"kind": "work", "namespace": "ocd", "id": "alpha"}, sections, "alpha", [])
    assert sections["coordination"]["data"]["ownership"] == "conflicted"
    current = next(task for task in sections["coordination"]["data"]["tasks"] if task["owner"] == "Agent One")
    assert current["status"] == "unknown"
    assert "next_verification" not in current
    historical = next(task for task in sections["coordination"]["data"]["tasks"] if task["owner"] == "Prior owner")
    assert historical["applicability"] == "historical"
    assert historical["dependencies"] == [{"reference": "37c-999", "health": "unavailable"}]

def test_metadata_and_release_connections_never_read_master(canonical_root, monkeypatch):
    from ocd_kernel.library.record_connections import _metadata, _release
    from ocd_kernel.library.record_read import RecordRead
    root = canonical_root
    original = Path.open
    def guarded(path, *args, **kwargs):
        assert not str(path).endswith(".xml")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", guarded)
    selection = {"schema_version": "2.0", "release_id": "test", "items": [{"item_id": "alpha", "category": "prose", "acceptance_path": "library/works/alpha/forms/en/editions/first/acceptance.json"}]}
    write(root / "library/works/alpha/publication/selection.json", selection)
    sections = {"selection": {"data": {}}, "metadata": {"data": {"source_observations": []}}}
    _release(RecordRead(root), sections, "alpha")
    assert sections["selection"]["data"]["release_record"]["current_readiness"] == "not_assessed"
    write(root / "metadata/source-evidence/index.json", {"subjects": []})
    with pytest.raises(PipelineError):
        _metadata(RecordRead(root), sections, "alpha", [])

def test_repaired_lead_ids_remain_metadata_accounting_authority(tmp_path):
    from build.tools.report_library_metadata import _expected_lead_ids
    root, previous = fixture(tmp_path)
    change_manifest(root)
    apply_lead_repair(root, plan_lead_repair(root))
    expected, error = _expected_lead_ids(root, {})
    assert error is None
    assert set(expected) == {record["lead_id"] for record in previous} | {"TFR-20261001-09"}

def test_catalog_still_resolves_when_lead_queue_is_stale(tmp_path):
    root, _ = fixture(tmp_path)
    minimal_connections(root)
    (root / "research/MANIFEST.md").write_text("changed", encoding="utf-8")
    result = lookup_library_record(root, {"kind": "source_catalog_entry", "namespace": "tfr", "id": "example"})
    assert result["resolution"] == "found" and result["collection"] == "partial"
    assert result["sections"]["research"]["data"]["lead_population"] is None
    assert len(result["sections"]["research"]["data"]["catalog_entries"]) == 1

def test_invalid_catalog_does_not_become_a_negative_result(tmp_path):
    root, _ = fixture(tmp_path)
    minimal_connections(root)
    path = root / "research/the-faith-received/source/the-faith-received-complete-works-20260930.md"
    path.write_text("- [Broken](https://mereorthodoxy.com/the-faith-received/read/?w=example)\n", encoding="utf-8")
    result = lookup_library_record(root, {"kind": "source_catalog_entry", "namespace": "tfr", "id": "example"})
    assert result["resolution"] is None and result["collection"] == "partial"
    assert result["sections"]["research"]["data"]["catalog_population"] is None

def test_tfr_duplicate_catalog_entries_require_explicit_opt_in(tmp_path):
    from runpy import run_path
    parser_path = Path(__file__).resolve().parents[1] / "research/the-faith-received/reconcile_catalog.py"
    parse_catalog = run_path(str(parser_path))["parse_catalog"]
    url = "https://mereorthodoxy.com/the-faith-received/read/?w=duplicate"
    source = tmp_path / "catalog.md"
    source.write_text(
        f"### Example (2 entries)\n- [First]({url})\n- [Second]({url})\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="identifiers are not unique"):
        parse_catalog(source)
    records, counts, declared_total = parse_catalog(source, allow_duplicate_ids=True)
    assert [record["tfr_entry_id"] for record in records] == ["duplicate", "duplicate"]
    assert counts == {"Example": 2}
    assert declared_total is None

def tracker_fixture(tmp_path):
    root, _ = fixture(tmp_path)
    minimal_connections(root)
    (root / "PROJECT_STATE.md").write_text(
        "# State\n\n## Current work\n| Current work | Owner | Next verification |\n|---|---|---|\n",
        encoding="utf-8",
    )
    worklist = root / "plans/2026-09-23-acquisition-manifest-source-to-tei/WORKLIST.md"
    worklist.parent.mkdir(parents=True)
    worklist.write_text("## Current dispositions\n", encoding="utf-8")
    for reference in (
        "plans/2026-08-31-library-pipeline-redesign/04-ticket-ledger.md",
        "plans/2026-08-31-library-pipeline-redesign/18-unified-ocd-completion-plan.md",
    ):
        write(root / reference, "# Tracker\n")
    ticket = root / "plans/2026-08-31-library-pipeline-redesign/tickets/WU-13-legacy.md"
    ticket.parent.mkdir(parents=True, exist_ok=True)
    return root, ticket


def test_legacy_ticket_encoding_is_warning_not_corrupt_coordination(tmp_path):
    root, ticket = tracker_fixture(tmp_path)
    ticket.write_bytes(b"# Historical punctuation: \x97\n")

    result = lookup_library_record(root, {"kind": "source_catalog_entry", "namespace": "tfr", "id": "example"})

    assert result["sections"]["coordination"]["health"] == "valid"
    assert result["sections"]["coordination"]["data"]["coverage"] == "incomplete"
    assert result["collection"] == "partial"
    assert lookup_exit_code(result) == 3
    assert any(item["code"] == "legacy-encoding" and item["severity"] == "warning" for item in result["diagnostics"])


@pytest.mark.parametrize('missing_anchor', [False, True])
def test_explicit_tracker_scope_is_distinct_from_global_availability(tmp_path, missing_anchor):
    root, ticket = tracker_fixture(tmp_path)
    ticket.write_text('# WU-13: Punctuation — UTF-8\n', encoding='utf-8')
    anchor = root / 'PROJECT_STATE.md'
    anchor.write_text(anchor.read_text(encoding='utf-8')+'\nExample is assigned to an owner in unstructured prose.\n',encoding='utf-8')
    if missing_anchor:
        anchor.unlink()
    record = lookup_library_record(root, {'kind':'source_catalog_entry','namespace':'tfr','id':'example'})
    coordination = record['sections']['coordination']['data']
    assert coordination['availability_to_start'] == 'not_assessed'
    assert coordination['ownership'] == 'unknown' and not coordination['tasks']
    if missing_anchor:
        assert coordination['coverage'] == 'incomplete'
        assert lookup_exit_code(record) == 3
        assert any(item['code']=='unavailable' for item in record['diagnostics'])
    else:
        assert coordination['coverage'] == 'complete_explicit_scope'
        assert any(item['support']=='partial' and item['coverage']=='incomplete' for item in coordination['populations'])
        assert not record['diagnostics']
        assert lookup_exit_code(record) == 0
        assert 'free-form project prose' in render_library_record(record)

def test_discovery_connection_returns_lead_without_inventing_a_work(tmp_path):
    root, _ = fixture(tmp_path)
    change_manifest(root)
    apply_lead_repair(root, plan_lead_repair(root))
    minimal_connections(root)
    new = next(lead for lead in manifest_research(root / "research/MANIFEST.md", root=root)["leads"] if lead["lead_id"] == "TFR-20261001-09")
    write(root / "research/library-record-links.json", {"contract": "ocd-library-record-links-v1", "relationships": [], "associations": [],
        "source_leads": [{"entry_id": "example", "lead_id": new["lead_id"], "basis": "Discovery only, not edition equivalence", "evidence": new["evidence"]}]})
    result = lookup_library_record(root, {"kind": "source_catalog_entry", "namespace": "tfr", "id": "example"})
    assert result["resolution"] == "found"
    assert result["sections"]["research"]["data"]["leads"][0]["lead_id"] == "TFR-20261001-09"
    assert result["sections"]["identity"]["data"] == {}
    assert result["sections"]["holdings"]["health"] == "not_assessed"

def test_cli_json_and_readable_output_share_normalized_result(canonical_root, capsys):
    from build.tools.lookup_library_record import main
    args = ["--root", str(canonical_root), "--kind", "work", "--namespace", "ocd", "--id", "alpha", "--records-only"]
    assert main(args + ["--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert main(args) == 0
    readable = capsys.readouterr().out
    assert result["fingerprint"] in readable
    assert "current text-byte integrity is not assessed" in readable

def test_deep_views_bind_immutable_migration_inputs_and_stable_ids(tmp_path):
    from ocd_kernel.library.views import build_library_views, check_library_views
    from ocd_kernel.library.acquisitions import acquisition_research_report
    root, previous = fixture(tmp_path)
    change_manifest(root)
    plan = plan_lead_repair(root)
    apply_lead_repair(root, plan)
    write(root / "library/works/known/work.json", {"schema_version": "2.0", "work_id": "known", "title": "Identity-only test",
        "evidence": ["research/MANIFEST.md"], "textual_forms": []})
    output = tmp_path / "views"
    result = build_library_views(root, output)
    assert {lead["lead_id"] for lead in result["manifest"]["research_leads"]} == {lead["lead_id"] for lead in previous} | {"TFR-20261001-09"}
    assert check_library_views(root, output)["fresh"] is True
    report = acquisition_research_report(root)
    assert report["schema_version"] == "2.1"
    assert all(group["lead_id"] in {lead["lead_id"] for lead in report["leads"]} for group in report["line_dispositions"] if "lead_id" in group)
    migration = root / f"research/lead-history/{plan['migration']['migration_id']}/migration.json"
    document = json.loads(migration.read_text(encoding="utf-8"))
    document["historical_basis"] += " Additional bound note."
    migration.write_text(json.dumps(document), encoding="utf-8")
    assert check_library_views(root, output)["fresh"] is False



def relationship_fixture(root, source, target):
    evidence = {"path": "research/evidence.md", "sha256": hashlib.sha256((root / "research/evidence.md").read_bytes()).hexdigest()}
    link = {"relationship_id": "endpoint-check", "source": source, "target": target,
            "relation": "unresolved_candidate", "decision_status": "proposed", "reviewer": None,
            "decided_at": None, "judgment": None, "evidence": [evidence], "extent": None,
            "current_applicability": "unassessed", "legacy_relation": "candidate", "legacy_note": "Preserved", "unresolved_questions": []}
    write(root / "research/library-record-links.json", {"contract": "ocd-library-record-links-v1", "relationships": [link], "associations": []})


@pytest.mark.parametrize("side", ["source", "target"])
@pytest.mark.parametrize("endpoint", [
    {"kind": "work", "namespace": "ocd", "id": "missing"},
    {"kind": "textual_form", "namespace": "ocd", "id": "missing", "work_id": "alpha"},
    {"kind": "edition", "namespace": "ocd", "id": "second", "work_id": "alpha", "textual_form_id": "en"},
    {"kind": "research_lead", "namespace": "research", "id": "missing"},
    {"kind": "source_catalog_entry", "namespace": "tfr", "id": "missing"},
])
def test_relationship_checks_both_endpoint_populations(canonical_root, side, endpoint):
    from ocd_kernel.library.record_connections import _relationships
    from ocd_kernel.library.record_read import RecordRead
    endpoints = {"source": {"kind": "work", "namespace": "ocd", "id": "alpha"},
                 "target": {"kind": "work", "namespace": "ocd", "id": "alpha"}}
    endpoints[side] = endpoint
    relationship_fixture(canonical_root, **endpoints)
    error = "target" if side == "target" and endpoint["kind"] in {"research_lead", "source_catalog_entry"} else "endpoint"
    with pytest.raises(PipelineError, match=error):
        _relationships(RecordRead(canonical_root), [], [])


@pytest.mark.parametrize("side", ["source", "target"])
@pytest.mark.parametrize("damage", ["missing", "invalid", "identity", "parent", "none"])
def test_relationship_loads_exact_acquisition_record(canonical_root, monkeypatch, side, damage):
    from ocd_kernel.library.record_connections import _relationships
    from ocd_kernel.library.record_read import RecordRead
    root = canonical_root
    path = root / "library/works/alpha/forms/en/editions/first/acquisitions/copy.json"
    if damage == "missing":
        path.unlink()
    elif damage == "invalid":
        path.write_text("{}", encoding="utf-8")
    elif damage in {"identity", "parent"}:
        record = json.loads(path.read_text(encoding="utf-8"))
        record["acquisition_id" if damage == "identity" else "edition_id"] = "other"
        write(path, record)
    endpoints = {"source": {"kind": "work", "namespace": "ocd", "id": "alpha"},
                 "target": {"kind": "work", "namespace": "ocd", "id": "alpha"}}
    endpoints[side] = {"kind": "acquisition", "namespace": "ocd", "id": "copy", "work_id": "alpha", "textual_form_id": "en", "edition_id": "first"}
    relationship_fixture(root, **endpoints)
    original = Path.open
    def guarded(path, *args, **kwargs):
        assert "raw" not in path.parts and not str(path).endswith(".xml")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", guarded)
    read = RecordRead(root)
    if damage == "none":
        assert _relationships(read, [], [])["relationships"]
        assert str(path.relative_to(root)).replace("\\", "/") in read.inputs
    else:
        with pytest.raises(PipelineError, match="acquisition"):
            _relationships(read, [], [])


@pytest.mark.parametrize("kind,label,namespace", [("research_lead", "Lead ID", "research"), ("source_catalog_entry", "TFR entry ID", "tfr")])
def test_unpromoted_task_retains_exact_subject(tmp_path, kind, label, namespace):
    root, leads = fixture(tmp_path)
    minimal_connections(root)
    identifier = leads[0]["lead_id"] if kind == "research_lead" else "example"
    ticket = root / "plans/2026-08-31-library-pipeline-redesign/tickets/LIBRARY-999-01-check.md"
    ticket.parent.mkdir(parents=True)
    ticket.write_text(f"ticket: LIBRARY-999-01\n**{label}:** `{identifier}`\n**Owner:** Researcher\n**Status:** Researching\n", encoding="utf-8")
    selector = {"kind": kind, "namespace": namespace, "id": identifier}
    result = lookup_library_record(root, selector)
    assert result["resolution"] == "found"
    tasks = result["sections"]["coordination"]["data"]["tasks"]
    assert len(tasks) == 1 and tasks[0]["subject"] == selector
    assert tasks[0]["owner"] == "Researcher"
    other = {**selector, "id": "unrelated"}
    assert not lookup_library_record(root, other)["sections"]["coordination"]["data"]["tasks"]


@pytest.mark.parametrize("kind,identifier,parents,path", [
    ("work", "alpha", {}, "library/works/alpha/work.json"),
    ("textual_form", "en", {"work_id": "alpha"}, "library/works/alpha/forms/en/"),
    ("edition", "first", {"work_id": "alpha", "textual_form_id": "en"}, "library/works/alpha/forms/en/editions/first/master.tei.xml"),
    ("acquisition", "copy", {"work_id": "alpha", "textual_form_id": "en", "edition_id": "first"}, "library/works/alpha/forms/en/editions/first/acquisitions/copy.json"),
])
def test_task_hierarchy_paths_preserve_scope(canonical_root, kind, identifier, parents, path):
    from ocd_kernel.library.record_connections import _ticket_tasks
    from ocd_kernel.library.record_read import RecordRead
    ticket = canonical_root / "plans/2026-08-31-library-pipeline-redesign/tickets/LIBRARY-999-01-scope.md"
    ticket.parent.mkdir(parents=True)
    ticket.write_text(f"ticket: LIBRARY-999-01\nScope: `{path}`\n**Owner:** Scoped owner\n", encoding="utf-8")
    selector = {"kind": kind, "namespace": "ocd", "id": identifier, **parents}
    tasks = _ticket_tasks(RecordRead(canonical_root), selector, [])
    assert len(tasks) == 1 and tasks[0]["subject"] == selector
    sibling = {"kind": "edition", "namespace": "ocd", "id": "second", "work_id": "alpha", "textual_form_id": "fr"}
    assert not _ticket_tasks(RecordRead(canonical_root), sibling, [])
    if kind != "work":
        assert not _ticket_tasks(RecordRead(canonical_root), {"kind": "work", "namespace": "ocd", "id": "alpha"}, [])


def test_typed_edition_task_does_not_become_a_work_or_sibling_task(canonical_root):
    from ocd_kernel.library.record_connections import _ticket_tasks
    from ocd_kernel.library.record_read import RecordRead
    ticket = canonical_root / "plans/2026-08-31-library-pipeline-redesign/tickets/LIBRARY-999-01-scope.md"
    ticket.parent.mkdir(parents=True)
    ticket.write_text("**Work ID:** `alpha`\n**Textual form ID:** `en`\n**Edition ID:** `first`\n", encoding="utf-8")
    selector = {"kind": "edition", "namespace": "ocd", "id": "first", "work_id": "alpha", "textual_form_id": "en"}
    assert _ticket_tasks(RecordRead(canonical_root), selector, [])[0]["subject"] == selector
    assert not _ticket_tasks(RecordRead(canonical_root), {"kind": "work", "namespace": "ocd", "id": "alpha"}, [])
    assert not _ticket_tasks(RecordRead(canonical_root), {**selector, "id": "second", "textual_form_id": "fr"}, [])


def test_work_tracker_associations_do_not_relabel_child_lookup(canonical_root):
    from ocd_kernel.library.record_connections import WORKLIST, _coordination
    from ocd_kernel.library.record_read import RecordRead
    root = canonical_root
    (root / "PROJECT_STATE.md").write_text("| Current work | Owner | Next verification |\n|---|---|---|\n| [A](library/works/alpha/work.json) | Work owner | Check |\n", encoding="utf-8")
    path = root / WORKLIST
    path.parent.mkdir(parents=True)
    row = "| LIBRARY-999 | HOLD | Work-level decision |"
    path.write_text("## Current dispositions\n" + row + "\n", encoding="utf-8")
    association = {"work_id": "alpha", "tracker": WORKLIST, "task": "LIBRARY-999", "row_sha256": hashlib.sha256(row.encode()).hexdigest()}
    selector = {"kind": "edition", "namespace": "ocd", "id": "first", "work_id": "alpha", "textual_form_id": "en"}
    sections = {"selection": {"data": {}}, "coordination": {"data": {}}}
    _coordination(RecordRead(root), selector, sections, "alpha", [association])
    assert sections["coordination"]["data"]["tasks"] == []
    assert sections["selection"]["data"]["current_decisions"] == []


@pytest.mark.parametrize("text", ["**Edition ID:** `first`", "**Work ID:** `alpha`\n**Acquisition ID:** `copy`"])
def test_incomplete_typed_task_scope_fails_closed(text):
    from ocd_kernel.library.record_connections import _task_subjects
    with pytest.raises(PipelineError, match="unique parent IDs"):
        _task_subjects(text)


@pytest.mark.parametrize("endpoint", [
    {"kind": "research_lead", "namespace": "research", "id": "existing-lead"},
    {"kind": "source_catalog_entry", "namespace": "tfr", "id": "existing-entry"},
])
def test_research_endpoints_allowed_only_as_relationship_sources(canonical_root, endpoint):
    from ocd_kernel.library.record_connections import _relationships
    from ocd_kernel.library.record_read import RecordRead
    canonical = {"kind": "work", "namespace": "ocd", "id": "alpha"}
    leads, catalog = [{"lead_id": "existing-lead"}], [{"tfr_entry_id": "existing-entry"}]
    relationship_fixture(canonical_root, endpoint, canonical)
    assert _relationships(RecordRead(canonical_root), leads, catalog)["relationships"][0]["source"] == endpoint
    relationship_fixture(canonical_root, canonical, endpoint)
    with pytest.raises(PipelineError, match="target"):
        _relationships(RecordRead(canonical_root), leads, catalog)


@pytest.mark.parametrize("form_id,valid", [("missing", False), ("en", True)])
def test_partial_containment_resolves_declared_form(canonical_root, form_id, valid):
    from ocd_kernel.library.record_connections import _relationships
    from ocd_kernel.library.record_read import RecordRead
    relationship_fixture(canonical_root, {"kind": "source_catalog_entry", "namespace": "tfr", "id": "example"},
                         {"kind": "work", "namespace": "ocd", "id": "alpha"})
    path = canonical_root / "research/library-record-links.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    link = document["relationships"][0]
    link["relation"] = "partial_component"
    link["extent"] = {"direction": "target_contains_source", "containing_identity": {
        "kind": "textual_form", "namespace": "ocd", "id": form_id, "work_id": "alpha"},
        "boundary": "Chapters I-II", "evidence": link["evidence"]}
    write(path, document)
    read = RecordRead(canonical_root)
    if valid:
        assert _relationships(read, [], [{"tfr_entry_id": "example"}])["relationships"][0]["extent"] == link["extent"]
        assert "library/works/alpha/work.json" in read.inputs
    else:
        with pytest.raises(PipelineError, match="form is undeclared"):
            _relationships(read, [], [{"tfr_entry_id": "example"}])


def test_partial_containment_rejects_existing_sibling_form(canonical_root):
    from ocd_kernel.library.record_connections import _relationships
    from ocd_kernel.library.record_read import RecordRead
    relationship_fixture(canonical_root, {"kind": "source_catalog_entry", "namespace": "tfr", "id": "example"},
                         {"kind": "edition", "namespace": "ocd", "id": "first", "work_id": "alpha", "textual_form_id": "en"})
    path = canonical_root / "research/library-record-links.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    link = document["relationships"][0]
    link["relation"] = "partial_component"
    link["extent"] = {"direction": "target_contains_source", "containing_identity": {
        "kind": "textual_form", "namespace": "ocd", "id": "fr", "work_id": "alpha"},
        "boundary": "Chapters I-II", "evidence": link["evidence"]}
    write(path, document)
    with pytest.raises(PipelineError, match="containment form disagrees"):
        _relationships(RecordRead(canonical_root), [], [{"tfr_entry_id": "example"}])


@pytest.mark.parametrize("text,expected", [
    ("Research catalog entry `example`", []),
    ("catalog entry `alpha`", []),
    ("**Source catalog entry:** `example`", [{"kind": "source_catalog_entry", "namespace": "tfr", "id": "example"}]),
    ("**TFR entry ID:** `example`", [{"kind": "source_catalog_entry", "namespace": "tfr", "id": "example"}]),
    ("**Work ID:** `alpha`", [{"kind": "work", "namespace": "ocd", "id": "alpha"}]),
])
def test_catalog_task_scope_requires_explicit_type(text, expected):
    from ocd_kernel.library.record_connections import _task_subjects
    assert _task_subjects(text) == expected


def test_ambiguous_catalog_task_does_not_attach_to_work(canonical_root):
    from ocd_kernel.library.record_connections import _ticket_tasks
    from ocd_kernel.library.record_read import RecordRead
    ticket = canonical_root / "plans/2026-08-31-library-pipeline-redesign/tickets/LIBRARY-999-01-ambiguous.md"
    ticket.parent.mkdir(parents=True)
    ticket.write_text("Research catalog entry `alpha`\n**Owner:** Researcher\n", encoding="utf-8")
    for selector in ({"kind": "work", "namespace": "ocd", "id": "alpha"},
                     {"kind": "source_catalog_entry", "namespace": "tfr", "id": "alpha"}):
        assert _ticket_tasks(RecordRead(canonical_root), selector, []) == []


@pytest.mark.parametrize("name", ["library-record-links", "library-record", "lead-migration"])
def test_connected_record_schemas_declare_local_draft_and_identity(name):
    from jsonschema import Draft202012Validator
    from ocd_kernel.library.identities import _schema_path
    schema = json.loads(_schema_path(name).read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == f"ocd://schemas/v2/{name}.schema.json"
    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("field", ["target", "containing_identity"])
@pytest.mark.parametrize("endpoint,target_valid,containing_valid", [
    ({"kind": "work", "namespace": "ocd", "id": "alpha"}, True, True),
    ({"kind": "textual_form", "namespace": "ocd", "id": "en", "work_id": "alpha"}, True, True),
    ({"kind": "edition", "namespace": "ocd", "id": "first", "work_id": "alpha", "textual_form_id": "en"}, True, False),
    ({"kind": "acquisition", "namespace": "ocd", "id": "copy", "work_id": "alpha", "textual_form_id": "en", "edition_id": "first"}, True, False),
    ({"kind": "research_lead", "namespace": "research", "id": "existing-lead"}, False, False),
    ({"kind": "source_catalog_entry", "namespace": "tfr", "id": "example"}, False, False),
])
def test_output_relationship_endpoint_contract(canonical_root, field, endpoint, target_valid, containing_valid):
    from ocd_kernel.library.identities import validate_record
    relationship_fixture(canonical_root, {"kind": "source_catalog_entry", "namespace": "tfr", "id": "example"},
                         {"kind": "work", "namespace": "ocd", "id": "alpha"})
    link = json.loads((canonical_root / "research/library-record-links.json").read_text(encoding="utf-8"))["relationships"][0]
    if field == "target":
        link["target"] = endpoint
        valid = target_valid
    else:
        link["relation"] = "partial_component"
        link["extent"] = {"direction": "target_contains_source", "containing_identity": endpoint,
                          "boundary": "Chapters I-II", "evidence": link["evidence"]}
        valid = containing_valid
    result = lookup_library_record(canonical_root, {"kind": "work", "namespace": "ocd", "id": "alpha"}, connections=False)
    result["sections"]["research"]["health"] = "valid"
    result["sections"]["research"]["data"]["relationships"] = [link]
    if valid:
        validate_record("library-record", result)
    else:
        with pytest.raises(PipelineError, match="relationships"):
            validate_record("library-record", result)


@pytest.mark.parametrize("invalid", [False, True])
def test_output_relationship_schema_matches_validated_link_boundaries(canonical_root, invalid):
    from ocd_kernel.library.identities import validate_record
    result = lookup_library_record(canonical_root, {"kind": "work", "namespace": "ocd", "id": "alpha"}, connections=False)
    link = {"relationship_id": "example", "source": {"kind": "work", "namespace": "ocd", "id": "alpha"},
            "target": {"kind": "work", "namespace": "ocd", "id": "alpha"}, "relation": "same_work",
            "decision_status": "reviewed", "reviewer": "fixture", "decided_at": "2026-10-14", "judgment": "Fixture judgment",
            "evidence": [{"path": "research/evidence.md", "sha256": "0" * 64}], "extent": None,
            "current_applicability": "supported", "legacy_relation": "candidate", "legacy_note": "Retained", "unresolved_questions": []}
    if invalid:
        link["target"]["kind"] = "unsupported"
    result["sections"]["research"]["health"] = "valid"
    result["sections"]["research"]["data"] = {"relationships": [link]}
    document = {"contract": "ocd-library-record-links-v1", "relationships": [link], "associations": []}
    for name, record in (("library-record-links", document), ("library-record", result)):
        if invalid:
            with pytest.raises(PipelineError):
                validate_record(name, record)
        else:
            validate_record(name, record)


def test_explicit_task_assignment_and_superseded_successor_are_currently_bound(canonical_root):
    from ocd_kernel.library.record_connections import _ticket_tasks
    from ocd_kernel.library.record_read import RecordRead
    home = canonical_root / "plans/2026-08-31-library-pipeline-redesign/tickets/simplification"
    home.mkdir(parents=True)
    active = home / "08-active.md"
    active.write_text("**Ticket ID:** SIMP-008\n**Work ID:** `alpha`\n**Status:** running\n"
                      "**Task applicability:** current\n**Owner:** Fixture curator\n"
                      "**Next action:** Review exact source evidence\n**Blocked by:** SIMP-007\n", encoding="utf-8")
    (home / "07-metadata.md").write_text("**Ticket ID:** SIMP-007\n**Status:** ready-for-agent\n", encoding="utf-8")
    old = canonical_root / "plans/2026-08-31-library-pipeline-redesign/tickets/LIBRARY-998-old.md"
    old.write_text("ticket: LIBRARY-998\n**Work ID:** `alpha`\n**Owner:** Historical owner\n"
                   "**Status:** superseded\n**Successor:** SIMP-008\n", encoding="utf-8")
    selector = {"kind": "work", "namespace": "ocd", "id": "alpha"}
    tasks = _ticket_tasks(RecordRead(canonical_root), selector, [])
    current = next(task for task in tasks if task["task"] == "SIMP-008")
    historical = next(task for task in tasks if task["task"] == "LIBRARY-998")
    assert current["applicability"] == "current" and current["owner"] == "Fixture curator"
    assert current["next_action"] == "Review exact source evidence"
    assert current["dependencies"][0]["tracker"].endswith("07-metadata.md")
    assert historical["applicability"] == "historical"
    assert historical["successors"][0]["tracker"].endswith("08-active.md")
    active.write_text(active.read_text().replace("Review exact source evidence", "Check selected output"), encoding="utf-8")
    assert next(task for task in _ticket_tasks(RecordRead(canonical_root), selector, []) if task["task"] == "SIMP-008")["next_action"] == "Check selected output"
