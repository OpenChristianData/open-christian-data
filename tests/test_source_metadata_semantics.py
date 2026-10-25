"""Focused tests for optional typed source-metadata claim semantics."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from build.lib import source_metadata


DIMENSIONS = source_metadata.dimension_names()


def _fixture(
    tmp_path: Path,
    *,
    descriptor: dict[str, str] | None = None,
    packet_value: str = "Synthetic metadata value",
) -> tuple[dict, dict, dict, Path, Path]:
    """Create one valid metadata decision and its frozen input packet."""

    packet = {"value": packet_value}
    packet_path = tmp_path / "evidence.json"
    packet_bytes = source_metadata.canonical_bytes(packet)
    packet_path.write_bytes(packet_bytes)
    packet_sha256 = hashlib.sha256(packet_bytes).hexdigest()

    predicate = descriptor["predicate"] if descriptor is not None else "title"
    entity = descriptor["scope"] if descriptor is not None else "work"
    event_role = (
        descriptor.get("event", descriptor.get("role", "none"))
        if descriptor is not None
        else "none"
    )
    item_id = f"work:{predicate}"
    item = {
        "item_id": item_id,
        "field": predicate,
        "source_packet": "evidence.json",
        "input_pointer": "/value",
        "input_value": packet["value"],
        "input_sha256": packet_sha256,
        "requirement": "useful_optional",
        "repair_required": False,
    }
    dimensions = {
        dimension: {"items": [copy.deepcopy(item)] if dimension == "work" else []}
        for dimension in DIMENSIONS
    }
    worklist = {
        "schema_version": "source-metadata-worklist-v1",
        "writer": source_metadata.WRITER_ID,
        "batch_id": "semantic-test-batch",
        "subjects": [
            {
                "subject": {"kind": "catalog", "id": "synthetic-work"},
                "dimensions": dimensions,
            }
        ],
    }
    binding = {
        "path": "evidence.json",
        "sha256": packet_sha256,
        "bytes": len(packet_bytes),
        "role": "primary",
        "locator": {
            "kind": "json_pointer",
            "value": "/value",
            "expected": packet["value"],
        },
    }
    claim = {
        "worklist_item_id": item_id,
        "claim_id": f"synthetic-{predicate}",
        "scope": {
            "member": "evidence.json",
            "entity": entity,
            "predicate": predicate,
            "event_role": event_role,
        },
        "evidence": {
            "classification": "supported",
            "value": packet["value"],
            "bindings": [binding],
        },
        "requirement": {
            "classification": "useful_optional",
            "reason": "semantic contract test",
        },
        "adoption": {
            "classification": "adopted",
            "destination": "source_evidence_only",
        },
        "inspection": {
            "classification": "inspected",
            "owner": "test",
            "evidence": "evidence.json#/value",
        },
    }
    if descriptor is not None:
        claim["semantics"] = copy.deepcopy(descriptor)
    decision = {
        "schema_version": "source-metadata-decisions-v1",
        "writer": source_metadata.WRITER_ID,
        "batch_id": "semantic-test-batch",
        "decisions": [
            {
                "subject": {"kind": "catalog", "id": "synthetic-work"},
                "dimensions": {
                    "work": {
                        "status": "inspected",
                        "owner": "test",
                        "fields": [claim],
                    }
                },
            }
        ],
    }
    worklist_path = tmp_path / "worklist.json"
    decisions_path = tmp_path / "decisions.json"
    worklist_path.write_bytes(source_metadata.canonical_bytes(worklist))
    decisions_path.write_bytes(source_metadata.canonical_bytes(decision))
    return worklist, decision, claim, worklist_path, decisions_path


PUBLICATION_CASES = (
    ("first_publication", "work"),
    ("edition_publication", "edition"),
    ("collection_publication", "collection"),
    ("translation_publication", "edition"),
    ("transcription", "edition"),
    ("revision", "edition"),
)


@pytest.mark.parametrize(("event", "scope"), PUBLICATION_CASES)
def test_publication_event_semantics_accept_event_scope_pair(
    tmp_path: Path, event: str, scope: str
) -> None:
    descriptor = {
        "kind": "publication_event",
        "predicate": "publication_date",
        "event": event,
        "scope": scope,
    }
    worklist, decision, _claim, _worklist_path, _decisions_path = _fixture(
        tmp_path, descriptor=descriptor
    )

    entries = source_metadata.validate_decision_documents([decision], worklist=worklist)

    assert entries[0]["dimensions"]["work"]["fields"][0]["semantics"] == descriptor


@pytest.mark.parametrize("role", ("author", "editor", "translator", "compiler", "illustrator", "commentator"))
@pytest.mark.parametrize("scope", ("work", "edition", "collection"))
def test_contributor_role_semantics_accept_role_and_scope(
    tmp_path: Path, role: str, scope: str
) -> None:
    descriptor = {
        "kind": "contributor_role",
        "predicate": "contributor",
        "role": role,
        "scope": scope,
    }
    worklist, decision, _claim, _worklist_path, _decisions_path = _fixture(
        tmp_path, descriptor=descriptor
    )

    source_metadata.validate_decision_documents([decision], worklist=worklist)


def test_legacy_claim_without_semantics_remains_valid(tmp_path: Path) -> None:
    worklist, decision, claim, _worklist_path, _decisions_path = _fixture(tmp_path)

    source_metadata.validate_decision_documents([decision], worklist=worklist)

    assert "semantics" not in claim


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("event_scope", "schema violation"),
        ("unknown_key", "schema violation"),
        ("unknown_role", "schema violation"),
        ("wrong_kind", "schema violation"),
    ],
)
def test_invalid_semantic_descriptor_combinations_fail_closed(
    tmp_path: Path, mutation: str, message: str
) -> None:
    descriptor = {
        "kind": "publication_event",
        "predicate": "publication_date",
        "event": "first_publication",
        "scope": "work",
    }
    worklist, decision, claim, _worklist_path, _decisions_path = _fixture(
        tmp_path, descriptor=descriptor
    )
    semantics = claim["semantics"]
    if mutation == "event_scope":
        semantics["scope"] = "edition"
    elif mutation == "unknown_key":
        semantics["unexpected"] = True
    elif mutation == "unknown_role":
        semantics["kind"] = "contributor_role"
        semantics["predicate"] = "contributor"
        semantics.pop("event")
        semantics["role"] = "not-a-role"
    elif mutation == "wrong_kind":
        semantics["kind"] = "contributor_role"

    with pytest.raises(source_metadata.MetadataError, match=message):
        source_metadata.validate_decision_documents([decision], worklist=worklist)


@pytest.mark.parametrize("scope_field", ("entity", "predicate", "event_role"))
def test_semantics_must_match_existing_claim_scope(
    tmp_path: Path, scope_field: str
) -> None:
    descriptor = {
        "kind": "publication_event",
        "predicate": "publication_date",
        "event": "first_publication",
        "scope": "work",
    }
    worklist, decision, claim, _worklist_path, _decisions_path = _fixture(
        tmp_path, descriptor=descriptor
    )
    claim["scope"][scope_field] = {
        "entity": "edition",
        "predicate": "contributor",
        "event_role": "translator",
    }[scope_field]

    with pytest.raises(source_metadata.MetadataError, match=r"semantics\.(scope|predicate)|semantics event/role"):
        source_metadata.validate_decision_documents([decision], worklist=worklist)


def test_semantics_descriptor_survives_sidecar_persistence_roundtrip(tmp_path: Path) -> None:
    descriptor = {
        "kind": "contributor_role",
        "predicate": "contributor",
        "role": "translator",
        "scope": "edition",
    }
    _worklist, _decision, _claim, worklist_path, decisions_path = _fixture(
        tmp_path, descriptor=descriptor
    )

    source_metadata.write_outputs(
        tmp_path,
        worklist_path=worklist_path,
        decisions_path=decisions_path,
    )
    sidecar = source_metadata.lookup_sidecar(tmp_path, "catalog", "synthetic-work")
    persisted = sidecar["dimensions"]["work"]["fields"][0]["semantics"]

    assert persisted == descriptor


def test_rehashed_sidecar_with_scope_mismatch_is_rejected_on_lookup(tmp_path: Path) -> None:
    descriptor = {
        "kind": "contributor_role",
        "predicate": "contributor",
        "role": "translator",
        "scope": "edition",
    }
    _worklist, _decision, _claim, worklist_path, decisions_path = _fixture(
        tmp_path, descriptor=descriptor
    )
    source_metadata.write_outputs(
        tmp_path,
        worklist_path=worklist_path,
        decisions_path=decisions_path,
    )

    sidecar_path = tmp_path / source_metadata.sidecar_relative_path(
        {"kind": "catalog", "id": "synthetic-work"}
    )
    sidecar = source_metadata.load_json(sidecar_path)
    sidecar["dimensions"]["work"]["fields"][0]["scope"]["entity"] = "work"
    sidecar_bytes = source_metadata.canonical_bytes(sidecar)
    sidecar_path.write_bytes(sidecar_bytes)
    index_path = tmp_path / "metadata/source-evidence/index.json"
    index = source_metadata.load_json(index_path)
    index["subjects"][0]["sha256"] = hashlib.sha256(sidecar_bytes).hexdigest()
    index_path.write_bytes(source_metadata.canonical_bytes(index))

    with pytest.raises(source_metadata.MetadataError, match=r"semantics\.scope"):
        source_metadata.lookup_sidecar(tmp_path, "catalog", "synthetic-work")

@pytest.mark.parametrize('value', ['la', 'grc', 'en-US'])
def test_original_language_claim_has_work_scope_and_language_value(tmp_path, value):
    descriptor = {'kind':'original_language', 'predicate':'original_language', 'role':'original_composition', 'scope':'work'}
    worklist, decision, claim, _, _ = _fixture(tmp_path, descriptor=descriptor)
    claim['evidence']['value'] = value
    entries = source_metadata.validate_decision_documents([decision], worklist=worklist)
    assert entries[0]['dimensions']['work']['fields'][0]['evidence']['value'] == value


@pytest.mark.parametrize('change', ['edition-scope', 'invalid-value', 'missing-value', 'no-evidence'])
def test_original_language_claim_rejects_invalid_scope_or_support(tmp_path, change):
    descriptor = {'kind':'original_language', 'predicate':'original_language', 'role':'original_composition', 'scope':'work'}
    worklist, decision, claim, _, _ = _fixture(tmp_path, descriptor=descriptor)
    claim['evidence']['value'] = 'la'
    if change == 'edition-scope':
        claim['semantics']['scope'] = claim['scope']['entity'] = 'edition'
    elif change == 'invalid-value':
        claim['evidence']['value'] = 'Latin language'
    elif change == 'missing-value':
        del claim['evidence']['value']
    else:
        claim['evidence']['bindings'] = []
    with pytest.raises(source_metadata.MetadataError):
        source_metadata.validate_decision_documents([decision], worklist=worklist)


def test_original_language_sidecar_preserves_scope_and_checks_evidence(tmp_path):
    descriptor = {'kind':'original_language', 'predicate':'original_language', 'role':'original_composition', 'scope':'work'}
    _, _, _, worklist_path, decisions_path = _fixture(tmp_path, descriptor=descriptor, packet_value='la')
    source_metadata.write_outputs(tmp_path, worklist_path=worklist_path, decisions_path=decisions_path)
    sidecar = source_metadata.lookup_sidecar(tmp_path, 'catalog', 'synthetic-work')
    claim = sidecar['dimensions']['work']['fields'][0]
    assert claim['semantics'] == descriptor
    assert claim['evidence']['value'] == 'la'
    assert claim['adoption']['destination'] == 'source_evidence_only'
    (tmp_path / 'evidence.json').write_bytes(source_metadata.canonical_bytes({'value':'en'}))
    with pytest.raises(source_metadata.MetadataError):
        source_metadata.write_outputs(tmp_path, worklist_path=worklist_path, decisions_path=decisions_path)


def test_adopted_original_language_requires_live_evidence_and_exact_target(tmp_path):
    descriptor = {'kind':'original_language', 'predicate':'original_language', 'role':'original_composition', 'scope':'work'}
    _, decision, claim, worklist_path, decisions_path = _fixture(tmp_path, descriptor=descriptor, packet_value='la')
    source_metadata.write_outputs(tmp_path, worklist_path=worklist_path, decisions_path=decisions_path)
    def lookup():
        return source_metadata.lookup_adopted_original_language(
            tmp_path, 'catalog', 'synthetic-work', target_path='work.json', selector='/original_language',
        )
    assert lookup() is None
    target = source_metadata.canonical_bytes({'original_language':'la'})
    (tmp_path / 'work.json').write_bytes(target)
    claim['adoption'] = {'classification':'adopted', 'destination':'v2', 'target':{'path':'work.json', 'selector':'/original_language', 'current_raw_sha256':hashlib.sha256(target).hexdigest(), 'expected_value':'la', 'value_check':True}}
    decisions_path.write_bytes(source_metadata.canonical_bytes(decision))
    source_metadata.write_outputs(tmp_path, worklist_path=worklist_path, decisions_path=decisions_path)
    assert lookup()['evidence']['value'] == 'la'
    assert source_metadata.lookup_adopted_original_language(tmp_path, 'catalog', 'synthetic-work', target_path='other.json', selector='/original_language') is None
    (tmp_path / 'evidence.json').write_bytes(source_metadata.canonical_bytes({'value':'en'}))
    with pytest.raises(source_metadata.EvidenceError):
        lookup()


def test_work_original_language_uses_explicit_subject_binding(tmp_path):
    descriptor = {'kind':'original_language', 'predicate':'original_language', 'role':'original_composition', 'scope':'work'}
    _, decision, claim, worklist_path, decisions_path = _fixture(tmp_path, descriptor=descriptor, packet_value='la')
    work = {'schema_version':'2.0', 'work_id':'different-library-id', 'title':'Test', 'evidence':['evidence.json'], 'textual_forms':[]}
    work_path = tmp_path / 'work.json'
    work_path.write_bytes(source_metadata.canonical_bytes(work))
    assert source_metadata.lookup_work_original_language(tmp_path, work_path) is None
    work['original_language'] = {'value':'la', 'source_metadata_subject':{'kind':'catalog','id':'synthetic-work'}}
    content = source_metadata.canonical_bytes(work)
    work_path.write_bytes(content)
    claim['adoption'] = {'classification':'adopted','destination':'v2','target':{'path':'work.json','selector':'/original_language/value','expected_value':'la','value_check':True,'current_raw_sha256':hashlib.sha256(content).hexdigest()}}
    decisions_path.write_bytes(source_metadata.canonical_bytes(decision))
    source_metadata.write_outputs(tmp_path, worklist_path=worklist_path, decisions_path=decisions_path)
    assert source_metadata.lookup_work_original_language(tmp_path, work_path)['evidence']['value'] == 'la'
    work['original_language']['value'] = 'en'
    work_path.write_bytes(source_metadata.canonical_bytes(work))
    with pytest.raises(source_metadata.EvidenceError):
        source_metadata.lookup_work_original_language(tmp_path, work_path)


@pytest.mark.parametrize("category", [
    "prose", pytest.param("bible", marks=pytest.mark.requires_local_artifacts),
    pytest.param("catechisms", marks=pytest.mark.requires_local_artifacts),
    "devotionals", "prayers", "sermons",
])
def test_original_language_adoption_survives_accepted_promotion(tmp_path_factory, category, monkeypatch):
    tmp_path = tmp_path_factory.mktemp("lang")
    from tests.test_tei_acceptance import _fixture_root, _write_valid_acceptance
    from ocd_kernel.tei.acceptance import promote_accepted_master
    import json
    acceptance = None
    if category == 'prose':
        root = _fixture_root(tmp_path)
    elif category == 'bible':
        from tests.test_projection_bible import _accepted_bible_fixture
        root, acceptance, _, _ = _accepted_bible_fixture(tmp_path_factory)
    else:
        if category in ('sermons', 'prayers'):
            from tests.test_release_accepted_sermons_prayers import accepted_fixture
        elif category == 'devotionals':
            from tests.test_projection_quotations import accepted_fixture
        else:
            from tests.test_release_accepted_structured import accepted_fixture
        root, acceptance = accepted_fixture(tmp_path / 'f', category)
    descriptor = {'kind':'original_language', 'predicate':'original_language', 'role':'original_composition', 'scope':'work'}
    _, decision, claim, worklist_path, decisions_path = _fixture(root, descriptor=descriptor, packet_value='grc')
    work_path = next((root / 'library/works').glob('*/work.json'))
    work = json.loads(work_path.read_text(encoding='utf-8'))
    work['original_language'] = {'value':'grc','source_metadata_subject':{'kind':'catalog','id':'synthetic-work'}}
    content = source_metadata.canonical_bytes(work)
    work_path.write_bytes(content)
    relative = work_path.relative_to(root).as_posix()
    claim['adoption'] = {'classification':'adopted','destination':'v2','target':{'path':relative,'selector':'/original_language/value','expected_value':'grc','value_check':True,'current_raw_sha256':hashlib.sha256(content).hexdigest()}}
    decisions_path.write_bytes(source_metadata.canonical_bytes(decision))
    source_metadata.write_outputs(root, worklist_path=worklist_path, decisions_path=decisions_path)
    if acceptance is None:
        acceptance, _ = _write_valid_acceptance(root)
    promoted = promote_accepted_master(root, acceptance_path=acceptance, destination=tmp_path / 'promoted')
    result = source_metadata.lookup_work_original_language(promoted.destination_root, promoted.destination_root / relative)
    assert result['evidence']['value'] == 'grc'
    from tests.test_release_assembly_v2 import _selection, _item, _assert_configuration
    from ocd_kernel.release.assemble import assemble_release_v2
    from ocd_kernel.release.verify import verify_release_v2
    selection = _selection(_item(promoted.destination_root, category, category, promoted.acceptance_path))
    release = tmp_path / 'out'
    report = assemble_release_v2(promoted.destination_root, release, selection=selection)
    assert report['status'] == 'pass', report
    rows = _assert_configuration(release, report['configurations'][0])
    assert all(row['provenance']['original_language'] == 'grc' for row in rows)
    assert all(row['language'] == 'en' for row in rows)
    from ocd_kernel.release import work_metadata
    monkeypatch.setattr(work_metadata, 'compose_work_metadata', lambda *args: pytest.fail('metadata producer called'))
    if category == 'prose':
        receipt = json.loads((release / report['items'][0]['receipt_path']).read_text(encoding='utf-8'))
        forged_rows = copy.deepcopy(rows)
        forged_rows[0]['provenance']['original_language'] = 'en'
        forged_receipt = copy.deepcopy(receipt)
        forged_receipt['work_metadata']['output_sha256'] = hashlib.sha256(json.dumps(forged_rows, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        from ocd_kernel.library._common import PipelineError
        with pytest.raises(PipelineError, match='public original language differs'):
            work_metadata.check_work_metadata(promoted.destination_root, forged_rows, forged_receipt)
        del receipt['work_metadata']
        with pytest.raises(PipelineError, match='receipt differs'):
            work_metadata.check_work_metadata(promoted.destination_root, rows, receipt)
    assert verify_release_v2(promoted.destination_root, release, selection=selection)['status'] == 'pass'
    (promoted.destination_root / 'evidence.json').write_bytes(b'{}')
    assert verify_release_v2(promoted.destination_root, release, selection=selection)['status'] == 'fail'
    with pytest.raises(source_metadata.EvidenceError):
        source_metadata.lookup_work_original_language(promoted.destination_root, promoted.destination_root / relative)


def test_work_kind_uses_explicit_adoption(tmp_path):
    descriptor = {'kind':'work_kind', 'predicate':'work_kind', 'role':'work_classification', 'scope':'work'}
    _, decision, claim, worklist_path, decisions_path = _fixture(tmp_path, descriptor=descriptor, packet_value='treatise')
    work = {'schema_version':'2.0', 'work_id':'different-library-id', 'title':'Test', 'evidence':['evidence.json'], 'textual_forms':[]}
    work_path = tmp_path / 'work.json'
    work_path.write_bytes(source_metadata.canonical_bytes(work))
    assert source_metadata.lookup_work_kind(tmp_path, work_path) is None
    work['work_kind'] = {'value':'treatise', 'source_metadata_subject':{'kind':'catalog','id':'synthetic-work'}}
    content = source_metadata.canonical_bytes(work)
    work_path.write_bytes(content)
    claim['adoption'] = {'classification':'adopted','destination':'v2','target':{'path':'work.json','selector':'/work_kind/value','expected_value':'treatise','value_check':True,'current_raw_sha256':hashlib.sha256(content).hexdigest()}}
    decisions_path.write_bytes(source_metadata.canonical_bytes(decision))
    source_metadata.write_outputs(tmp_path, worklist_path=worklist_path, decisions_path=decisions_path)
    assert source_metadata.lookup_work_kind(tmp_path, work_path)['evidence']['value'] == 'treatise'
    work['work_kind']['value'] = 'church-history'
    work_path.write_bytes(source_metadata.canonical_bytes(work))
    with pytest.raises(source_metadata.EvidenceError):
        source_metadata.lookup_work_kind(tmp_path, work_path)




def test_work_kind_survives_accepted_release(tmp_path_factory, monkeypatch):
    category = "prose"
    tmp_path = tmp_path_factory.mktemp("lang")
    from tests.test_tei_acceptance import _fixture_root, _write_valid_acceptance
    from ocd_kernel.tei.acceptance import promote_accepted_master
    import json
    acceptance = None
    if category == 'prose':
        root = _fixture_root(tmp_path)
    elif category == 'bible':
        from tests.test_projection_bible import _accepted_bible_fixture
        root, acceptance, _, _ = _accepted_bible_fixture(tmp_path_factory)
    else:
        if category in ('sermons', 'prayers'):
            from tests.test_release_accepted_sermons_prayers import accepted_fixture
        elif category == 'devotionals':
            from tests.test_projection_quotations import accepted_fixture
        else:
            from tests.test_release_accepted_structured import accepted_fixture
        root, acceptance = accepted_fixture(tmp_path / 'f', category)
    descriptor = {'kind':'work_kind', 'predicate':'work_kind', 'role':'work_classification', 'scope':'work'}
    _, decision, claim, worklist_path, decisions_path = _fixture(root, descriptor=descriptor, packet_value='treatise')
    work_path = next((root / 'library/works').glob('*/work.json'))
    work = json.loads(work_path.read_text(encoding='utf-8'))
    work['work_kind'] = {'value':'treatise','source_metadata_subject':{'kind':'catalog','id':'synthetic-work'}}
    content = source_metadata.canonical_bytes(work)
    work_path.write_bytes(content)
    relative = work_path.relative_to(root).as_posix()
    claim['adoption'] = {'classification':'adopted','destination':'v2','target':{'path':relative,'selector':'/work_kind/value','expected_value':'treatise','value_check':True,'current_raw_sha256':hashlib.sha256(content).hexdigest()}}
    decisions_path.write_bytes(source_metadata.canonical_bytes(decision))
    source_metadata.write_outputs(root, worklist_path=worklist_path, decisions_path=decisions_path)
    if acceptance is None:
        acceptance, _ = _write_valid_acceptance(root)
    promoted = promote_accepted_master(root, acceptance_path=acceptance, destination=tmp_path / 'promoted')
    result = source_metadata.lookup_work_kind(promoted.destination_root, promoted.destination_root / relative)
    assert result['evidence']['value'] == 'treatise'
    from tests.test_release_assembly_v2 import _selection, _item, _assert_configuration
    from ocd_kernel.release.assemble import assemble_release_v2
    from ocd_kernel.release.verify import verify_release_v2
    selection = _selection(_item(promoted.destination_root, category, category, promoted.acceptance_path))
    release = tmp_path / 'out'
    report = assemble_release_v2(promoted.destination_root, release, selection=selection)
    assert report['status'] == 'pass', report
    rows = _assert_configuration(release, report['configurations'][0])
    assert all(row['provenance']['work_kind'] == 'treatise' for row in rows)
    assert all(row['language'] == 'en' for row in rows)
    from ocd_kernel.release import work_metadata
    monkeypatch.setattr(work_metadata, 'compose_work_metadata', lambda *args: pytest.fail('metadata producer called'))
    if category == 'prose':
        receipt = json.loads((release / report['items'][0]['receipt_path']).read_text(encoding='utf-8'))
        forged_rows = copy.deepcopy(rows)
        forged_rows[0]['provenance']['work_kind'] = 'en'
        forged_receipt = copy.deepcopy(receipt)
        forged_receipt['work_metadata']['output_sha256'] = hashlib.sha256(json.dumps(forged_rows, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        from ocd_kernel.library._common import PipelineError
        with pytest.raises(PipelineError, match='public work kind differs'):
            work_metadata.check_work_metadata(promoted.destination_root, forged_rows, forged_receipt)
        del receipt['work_metadata']
        with pytest.raises(PipelineError, match='receipt differs'):
            work_metadata.check_work_metadata(promoted.destination_root, rows, receipt)
    assert verify_release_v2(promoted.destination_root, release, selection=selection)['status'] == 'pass'
    (promoted.destination_root / 'evidence.json').write_bytes(b'{}')
    assert verify_release_v2(promoted.destination_root, release, selection=selection)['status'] == 'fail'
    with pytest.raises(source_metadata.EvidenceError):
        source_metadata.lookup_work_kind(promoted.destination_root, promoted.destination_root / relative)


@pytest.mark.parametrize("kind,value,role", [
    ("original_language", "la", "original_composition"),
    ("work_kind", "treatise", "work_classification"),
])
@pytest.mark.parametrize("case", [
    "valid", "already_correct", "stale_evidence", "stale_target",
    "wrong_path", "wrong_selector", "duplicate", "unsupported_evidence",
    "no_primary", "value_mismatch", "decision_evidence", "unapplied",
])
def test_adopted_lookup_shared_policy(tmp_path, monkeypatch, kind, value, role, case):
    descriptor = {"kind": kind, "predicate": kind, "role": role, "scope": "work"}
    _, _, claim, _, _ = _fixture(tmp_path, descriptor=descriptor, packet_value=value)
    content = source_metadata.canonical_bytes({kind: value})
    target = tmp_path / "work.json"
    target.write_bytes(content)
    claim["adoption"] = {
        "classification": "adopted", "destination": "v2",
        "target": {"path": "work.json", "selector": f"/{kind}",
                   "expected_value": value, "value_check": True,
                   "current_raw_sha256": hashlib.sha256(content).hexdigest()},
    }
    fields = [claim]
    # Substitute only the already validated sidecar, keeping evidence and target
    # reads real so both public lookup interfaces exercise the adoption policy.
    monkeypatch.setattr(source_metadata, "lookup_sidecar", lambda *args: {
        "dimensions": {"work": {"fields": fields}},
    })
    error = None
    if case == "already_correct":
        claim["adoption"]["classification"] = "already_correct"
    elif case == "stale_evidence":
        (tmp_path / "evidence.json").write_bytes(b'{}')
        error = source_metadata.EvidenceError
    elif case == "stale_target":
        target.write_bytes(b'{}')
        error = source_metadata.EvidenceError
    elif case == "wrong_path":
        claim["adoption"]["target"]["path"] = "other.json"
    elif case == "wrong_selector":
        claim["adoption"]["target"]["selector"] = "/other"
    elif case == "duplicate":
        fields.append(copy.deepcopy(claim))
        error = source_metadata.MetadataError
    elif case == "unsupported_evidence":
        claim["evidence"]["classification"] = "unsupported"
        error = source_metadata.EvidenceError
    elif case == "no_primary":
        claim["evidence"]["bindings"][0]["role"] = "supporting"
        error = source_metadata.EvidenceError
    elif case == "value_mismatch":
        claim["adoption"]["target"]["expected_value"] = "other"
        error = source_metadata.EvidenceError
    elif case == "decision_evidence":
        claim["evidence"]["bindings"][0]["path"] = "decisions/evidence.json"
        error = source_metadata.EvidenceError
    elif case == "unapplied":
        claim["adoption"]["classification"] = "not_adopted"
    lookup = getattr(source_metadata, f"lookup_adopted_{kind}")
    def run():
        return lookup(tmp_path, "catalog", "synthetic-work",
                      target_path="work.json", selector=f"/{kind}")
    if error:
        with pytest.raises(error):
            run()
    elif case in {"wrong_path", "wrong_selector", "unapplied"}:
        assert run() is None
    else:
        result = run()
        assert result == claim
        result["evidence"]["value"] = "changed by caller"
        assert claim["evidence"]["value"] == value
