from copy import deepcopy
import json
from pathlib import Path

import pytest

from build.tools.build_public_acquisition_list import current_snapshot, project, render, write_or_check
from ocd_kernel.library._common import PipelineError


def snapshot():
    work = {"work_id": "one", "title": "One", "editions": [{}]}
    item = {"work_id": "one", "edition_id": "copy", "edition_title": "Copy", "master_status": "absent", "state_stage": "planned", "source_url": "https://example.org/source"}
    lead = {"lead_id": "lead-1", "columns": ["Work", "Status"], "observed_claim": "| One | ACQUIRE NOW |", "disposition": "unresolved"}
    return {"manifest": {"works": [work, {"work_id": "two", "title": "Two", "editions": []}]}, "queue": {"items": [item], "research_leads": [lead], "issues": [], "freshness": {"input_sha256": "a" * 64}}}


def test_research_claim_does_not_become_an_open_job_or_rights_grant():
    value = project(snapshot(), "2026-10-24T00:00:00+00:00")
    assert value["research_leads"][0]["disposition"] == "unresolved"
    assert "ACQUIRE NOW" not in json.dumps(value)
    assert value["editions_without_accepted_master"][0]["edition_id"] == "copy"
    assert value["catalog_only_works"][0]["work_id"] == "two"
    assert "approved new jobs" in render(value)


def test_accepted_warnings_do_not_request_duplicate_reconstruction():
    data = snapshot()
    data["queue"]["items"][0]["master_status"] = "accepted"
    assert project(data, "now")["editions_without_accepted_master"] == []


def test_missing_title_is_accounted_for_and_private_fields_are_not_exported():
    data = snapshot()
    lead = data["queue"]["research_leads"][0]
    lead.update(columns=[], observed_claim="A research note", evidence={"path": "private/receipt"}, context=["private context"])
    result = project(data, "now")
    assert result["research_leads"][0]['title'] is None
    assert "private" not in json.dumps(result)


def test_markdown_output_escapes_markup_and_uses_public_links_only():
    data = snapshot()
    data["manifest"]["works"][0]["title"] = "<script>alert(1)</script>|next\nrow"
    data["queue"]["items"][0]["source_url"] = "javascript:alert(1) https://user:password@example.org/private"
    text = render(project(data, "now"))
    assert "<script>" not in text and "&#124;" in text
    assert "javascript:" not in text and "password" not in text


def test_public_links_preserve_parentheses_in_titles_and_remove_markdown_wrapper():
    from build.tools.build_public_acquisition_list import _links
    url = 'https://en.wikisource.org/wiki/New_Hampshire_Baptist_Confession_of_Faith_(1833)'
    assert _links(f'[Confession]({url}); | {url}') == [url.replace('(', '%28').replace(')', '%29')]


def test_duplicate_leads_fail_instead_of_disappearing():
    data = snapshot()
    data["queue"]["research_leads"] *= 2
    with pytest.raises(PipelineError, match="duplicate.*lead-1"):
        project(data, "now")


def test_freshness_check_rejects_authority_change_and_output_edits(tmp_path):
    data = snapshot()
    write_or_check(data, tmp_path)
    assert write_or_check(data, tmp_path, check=True)["checked"]
    changed = deepcopy(data)
    changed["queue"]["freshness"]["input_sha256"] = "b" * 64
    with pytest.raises(PipelineError, match="stale"):
        write_or_check(changed, tmp_path, check=True)
    (tmp_path / "ACQUISITIONS.md").write_text("changed", encoding="utf-8")
    with pytest.raises(PipelineError, match="edited"):
        write_or_check(data, tmp_path, check=True)


def test_cataloging_template_can_enter_library_queue_and_public_projection(tmp_path):
    from ocd_kernel.library.acquisitions import load_acquisition_leads
    from ocd_kernel.library.research_leads import apply_lead_upkeep, plan_lead_upkeep
    from tests.test_acquisition_leads import research_root
    root = research_root(tmp_path)
    guide = (Path(__file__).resolve().parents[1] / 'docs/examples/information-templates.md').read_text(encoding='utf-8')
    note = guide.split('```text\n', 1)[1].split('```', 1)[0].replace('Title:\n', 'Title: Proposed text\n', 1)
    evidence = root / 'library/acquisition-research/proposed-text.md'
    evidence.parent.mkdir()
    evidence.write_text(note, encoding='utf-8')
    plan = plan_lead_upkeep(root, lead_id='proposed-text', evidence_path=evidence.relative_to(root).as_posix(),
                            line_start=1, line_end=len(note.splitlines()),
                            acquisition_intent='Assess the proposed edition', context=['Contributor cataloging'])
    apply_lead_upkeep(root, plan)
    leads = load_acquisition_leads(root / 'library/acquisition-leads.jsonl', root=root)
    assert not (root / 'research/acquisition-leads.jsonl').exists()
    data = snapshot()
    data['queue']['research_leads'] = leads
    row = next(row for row in project(data, 'now')['research_leads'] if row['lead_id'] == 'proposed-text')
    assert row['title'] == 'Proposed text' and row['disposition'] == 'unresolved'
    data['queue']['research_leads'] = [{'lead_id': 'blank-title', 'observed_claim': 'Title:\nAuthor: Unknown', 'disposition': 'unresolved'}]
    assert project(data, 'now')['research_leads'][0]['title'] is None


def test_public_list_uses_recorded_library_acceptance_and_rejects_invalid_records(tmp_path):
    import shutil
    root = tmp_path / 'library-workspace'
    shutil.copytree(Path(__file__).resolve().parents[1] / 'tests/fixtures/library-pipeline', root)
    state_path = next((root / 'library/works').glob('*/state.json'))
    state = json.loads(state_path.read_text(encoding='utf-8'))
    state['targets'][0]['stage'] = 'acquired'
    state_path.write_text(json.dumps(state), encoding='utf-8')
    data = current_snapshot(root)
    assert len(data['manifest']['works']) == 1
    assert data['queue']['items'][0]['master_status'] == 'not-recorded-accepted'
    work = next((root / 'library/works').glob('*/work.json'))
    work.write_text('{}', encoding='utf-8')
    with pytest.raises(PipelineError, match='issues'):
        current_snapshot(root)
