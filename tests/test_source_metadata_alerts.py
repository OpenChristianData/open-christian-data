"""Semantic warnings must surface risks without changing authored claims."""

import copy

from build.lib.source_metadata_alerts import semantic_alerts


def claim(predicate, excerpt, *, classification="supported", entity="work"):
    return {"scope": {"entity": entity, "predicate": predicate,
            "member": "whole", "event_role": "unspecified"},
            "evidence": {"classification": classification, "bindings": [
                {"role": "primary", "locator": {"expected": excerpt}}]}}


def test_editor_as_translator_is_advisory_and_preserves_input():
    value = claim("translator", "Edited by A. Coxe")
    before = copy.deepcopy(value)
    assert any(s.startswith("contributor_role:") for s in semantic_alerts(value))
    assert value == before


def test_first_publication_needs_distinct_event_review():
    assert any(s.startswith("publication_event:") for s in semantic_alerts(
        claim("first_publication_year", "London 1875")))


def test_legacy_date_is_flagged_for_missing_event_semantics():
    assert any(s.startswith("publication_event_unspecified:") for s in semantic_alerts(
        claim("publication_year", "1875")))


def test_volume_evidence_for_work_requires_scope_review():
    value = claim("license", "This collection is licensed for distribution")
    assert any(s.startswith("evidence_scope:") for s in semantic_alerts(value))
    value["scope"]["entity"] = "collection"
    assert not semantic_alerts(value)


def test_unresolved_or_nonprimary_editor_cues_are_not_role_claims():
    assert not semantic_alerts(claim("translator", "Edited by Coxe", classification="unresolved"))
    value = claim("translator", "Edited by Coxe")
    value["evidence"]["bindings"][0]["role"] = "prior_review"
    assert not semantic_alerts(value)


def test_real_preflight_exposes_advisory_and_requires_engine_identity(tmp_path):
    import pytest
    from build.lib import source_metadata as sm, source_metadata_review as review
    from tests.test_source_metadata_review import _comparison_fixture

    root, work, decisions, selection, _, _, _ = _comparison_fixture(tmp_path)
    evidence_path = root / "evidence.json"
    credit = "Edited by A. Coxe"
    evidence_path.write_bytes(sm.canonical_bytes({"title": credit}))
    identity = review.file_identity(evidence_path)
    worklist = sm.load_json(work)
    item = worklist["subjects"][0]["dimensions"]["work"]["items"][0]
    item.update(field="translator", input_value=credit, input_sha256=identity["sha256"])
    work.write_bytes(sm.canonical_bytes(worklist))
    document = sm.load_json(decisions)
    value = document["decisions"][0]["dimensions"]["work"]["fields"][0]
    value["scope"]["predicate"] = "translator"
    value["evidence"]["value"] = credit
    binding = value["evidence"]["bindings"][0]
    binding.update(sha256=identity["sha256"], bytes=identity["bytes"])
    binding["locator"]["expected"] = credit
    decisions.write_bytes(sm.canonical_bytes(document))
    selected = sm.load_json(selection)
    selected["worklist_sha256"] = review.file_identity(work)["sha256"]
    selection.write_bytes(sm.canonical_bytes(selected))
    sm.validate_decision_documents([document], worklist=worklist)
    receipt, view, _ = review.preflight(root, worklist_path=work, decisions_path=decisions, selection_path=selection)
    assert receipt["mechanical_status"] == "pass"
    assert any(row["reason"].startswith("contributor_role:") for row in receipt["alerts"])
    assert receipt["alerts"] == view["alerts"]
    assert not review.verify_receipt(receipt)
    del receipt["artifacts"]["semantic_alert_engine"]
    with pytest.raises(sm.MetadataError, match="missing a required"):
        review.verify_receipt(receipt)


def test_typed_publication_events_do_not_retrigger_date_or_contributor_alerts():
    for event in ("first_publication", "translation_publication"):
        value = claim("publication_date", "London ed. 1875")
        value["scope"]["event_role"] = event
        value["semantics"] = {"kind": "publication_event", "predicate": "publication_date",
                              "event": event, "scope": "work" if event == "first_publication" else "edition"}
        value["scope"]["entity"] = value["semantics"]["scope"]
        assert not semantic_alerts(value)


def test_publication_places_and_publishers_are_not_date_claims():
    for predicate in ("publisher", "publication_place", "publisher_place_name", "edition_statement"):
        value = claim(predicate, "London")
        value["scope"]["event_role"] = "publication"
        assert not semantic_alerts(value)
