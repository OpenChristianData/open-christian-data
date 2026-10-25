"""Verified release statistics use accepted fixture authority only."""
import copy
import hashlib
import json

import pytest

from build.tools.report_release_stats import release_statistics
from ocd_kernel.library._common import PipelineError
from tests.test_release_assembly_v2 import _build_single


@pytest.fixture
def release(tmp_path_factory):
    # Simulated acceptance is confined to temporary fixtures.
    return _build_single(tmp_path_factory.mktemp("ls"))


def test_statistics_ignore_legacy_data_and_count_verified_text(release):
    root, output, selection, _ = release
    for relative in ("data/legacy.json", "reports/publish/work_catalog.json"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("invalid JSON", encoding="utf-8")
    result = release_statistics(root, output, selection)
    rows_path = output / "public/data/quotations/train.jsonl"
    rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines()]
    assert result["total"] == {
        "records": len(rows),
        "text_characters": sum(len(row["text"]) for row in rows),
        "uncompressed_bytes": len(rows_path.read_bytes()),
    }


def test_statistics_reject_changed_public_bytes(release):
    root, output, selection, _ = release
    path = output / "public/data/quotations/train.jsonl"
    path.write_bytes(path.read_bytes() + b"{}\n")
    with pytest.raises(PipelineError, match="verification failed"):
        release_statistics(root, output, selection)


def test_statistics_require_original_selection(release):
    root, output, selection, _ = release
    wrong = copy.deepcopy(selection)
    wrong["release_id"] = "another-release"
    with pytest.raises(PipelineError, match="verification failed"):
        release_statistics(root, output, wrong)


def test_existing_statistics_cli_uses_verified_release(release, tmp_path, monkeypatch, capsys):
    from build.tools import export_stats
    root, output, selection, _ = release
    def reject_legacy(*args, **kwargs):
        raise AssertionError('legacy statistics must not run')
    monkeypatch.setattr(export_stats, 'collect_stats', reject_legacy)
    selected = tmp_path / 'selection.json'
    selected.write_text(json.dumps(selection), encoding='utf-8')
    assert export_stats.main(['--root', str(root), '--release', str(output), '--selection', str(selected)]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'pass'


def test_record_counter_normal_cli_does_not_rebuild_workcatalog(release, tmp_path, monkeypatch, capsys):
    from build.tools import count_dataset_records
    root, output, selection, _ = release
    def reject_catalog(*args, **kwargs):
        raise AssertionError('normal record counting must not build WorkCatalog')
    monkeypatch.setattr(count_dataset_records, 'collect_work_catalog', reject_catalog)
    selected = tmp_path/'selection.json'
    selected.write_text(json.dumps(selection), encoding='utf-8')
    assert count_dataset_records.main(['--root', str(root), '--release', str(output), '--selection', str(selected)]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'pass'


def test_optional_tokenizer_counts_only_verified_public_text(release, monkeypatch):
    import sys
    from types import SimpleNamespace
    root, output, selection, _ = release
    texts = []
    class Encoding:
        def encode_ordinary(self, value):
            texts.append(value)
            return value.split()
    monkeypatch.setitem(sys.modules, 'tiktoken', SimpleNamespace(get_encoding=lambda name: Encoding()))
    result = release_statistics(root, output, selection, encoding_name='test-only')
    rows = [json.loads(line) for line in (output / 'public/data/quotations/train.jsonl').read_text(encoding='utf-8').splitlines()]
    assert texts == [row['text'] for row in rows]
    assert result['total']['tokens'] == sum(len(text.split()) for text in texts)


def test_existing_export_cli_builds_verified_v2_without_legacy(release, tmp_path, monkeypatch, capsys):
    from build.scripts import export_huggingface
    root, _, selection, _ = release
    def reject_legacy(*args, **kwargs):
        raise AssertionError('legacy exporter must not run')
    monkeypatch.setattr(export_huggingface, 'run_export', reject_legacy)
    selected = tmp_path / 'selection.json'
    selected.write_text(json.dumps(selection), encoding='utf-8')
    output = tmp_path / 'new-release'
    args = ['--root', str(root), '--selection', str(selected), '--output', str(output)]
    assert export_huggingface.main(args) == 0
    assert json.loads(capsys.readouterr().out)['verification'] == 'pass'
    before = (output / 'internal/release-report.json').read_bytes()
    with pytest.raises(SystemExit):
        export_huggingface.main(args)
    assert (output / 'internal/release-report.json').read_bytes() == before


def test_token_cli_verifies_selection_without_legacy_writes(release, tmp_path, monkeypatch, capsys):
    import sys
    from types import SimpleNamespace
    from build.scripts import add_token_counts

    root, output, selection, _ = release
    requested_encodings = []

    def encoding(name):
        requested_encodings.append(name)
        return SimpleNamespace(encode_ordinary=lambda text: text.split())

    def reject_legacy(*args, **kwargs):
        raise AssertionError("default token reporting must not run the legacy writer")

    monkeypatch.setitem(sys.modules, "tiktoken", SimpleNamespace(get_encoding=encoding))
    monkeypatch.setattr(add_token_counts, "legacy_main", reject_legacy)
    selected = tmp_path / "selected.json"
    selected.write_text(json.dumps(selection), encoding="utf-8")
    args = ["--root", str(root), "--release", str(output), "--selection", str(selected)]
    assert add_token_counts.main(args) == 0
    assert json.loads(capsys.readouterr().out)["total"]["tokens"] > 0
    assert requested_encodings == ["cl100k_base"]
    assert add_token_counts.main([*args, "--encoding=test-explicit"]) == 0
    capsys.readouterr()
    assert requested_encodings[-1] == "test-explicit"
    selected.write_text(json.dumps({**selection, "release_id": "wrong-release"}), encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        add_token_counts.main(args)
    assert error.value.code == 2


def test_short_entry_cli_refuses_release_without_commentary(release):
    from build.scripts.short_entries_report import short_release_entries

    root, output, selection, _ = release
    with pytest.raises(PipelineError, match="no commentary configuration"):
        short_release_entries(root, output, selection, 20)


@pytest.mark.requires_local_artifacts
def test_short_entries_use_verified_commentary_and_reject_changed_rows(tmp_path_factory):
    from build.scripts.short_entries_report import short_release_entries
    from tests.test_projection_commentary import _accepted_commentary_fixture
    from tests.test_release_assembly_v2 import _item, _selection
    from ocd_kernel.tei.acceptance import promote_accepted_master
    from ocd_kernel.release.assemble import assemble_release_v2

    temporary = tmp_path_factory.mktemp("sc")
    source_root, acceptance, _, _ = _accepted_commentary_fixture(tmp_path_factory)
    promoted = promote_accepted_master(source_root, acceptance_path=acceptance, destination=temporary / "p")
    root = promoted.destination_root
    selection = _selection(_item(root, "commentary", "commentary", promoted.acceptance_path))
    output = temporary / "r"
    report = assemble_release_v2(root, output, selection=selection)
    rows_path = output / report["configurations"][0]["path"]
    rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines()]
    threshold = len(rows[0]["text"].split()) + 1
    result = short_release_entries(root, output, selection, threshold)
    assert result["total_records"] == len(rows)
    assert [item["record_id"] for item in result["short_records"]] == [
        row["record_id"] for row in rows if len(row["text"].split()) < threshold
    ]
    with pytest.raises(PipelineError, match="no commentary rows for work"):
        short_release_entries(root, output, selection, threshold, "missing-work")
    rows_path.write_bytes(rows_path.read_bytes() + b"{}\n")
    with pytest.raises(PipelineError, match="verification failed"):
        short_release_entries(root, output, selection, threshold)


def test_short_entry_explicit_historical_mode(tmp_path, monkeypatch, capsys):
    from build.scripts import short_entries_report

    folder = tmp_path / "historical"
    folder.mkdir()
    (folder / "entries.json").write_text(json.dumps({"data": [
        {"entry_id": "old-one", "word_count": 2, "commentary_text": "Two words"}
    ]}), encoding="utf-8")
    monkeypatch.setattr(short_entries_report, "DATA_DIR", tmp_path)
    assert short_entries_report.main(["--legacy-data", "--commentary", "historical", "--threshold", "3"]) == 0
    assert "old-one" in capsys.readouterr().out


@pytest.mark.parametrize("tool_name", ["check_witness_inventory", "scaffold_witness_inventory"])
@pytest.mark.parametrize("missing", ["--legacy-data", "--repo-root", "--schema"])
def test_witness_cli_requires_explicit_historical_contract(tool_name, missing, tmp_path, monkeypatch):
    from importlib import import_module
    tool = import_module("build.tools." + tool_name)
    def reject_discovery(*args, **kwargs):
        raise AssertionError("must reject before discovering historical data")
    monkeypatch.setattr(tool, "_enumerate_resources", reject_discovery)
    options = {"--legacy-data": [], "--repo-root": [str(tmp_path)],
               "--schema": [str(tmp_path / "absent.json")]}
    argv = [part for option, values in options.items() if option != missing
            for part in [option, *values]]
    entry = tool.main if tool_name == "check_witness_inventory" else tool._cli
    with pytest.raises(SystemExit) as exc:
        entry(argv)
    assert exc.value.code == 2
    assert list(tmp_path.iterdir()) == []


def test_historical_witness_tools_use_explicit_schema_and_preserve_existing(tmp_path):
    from build.tools import check_witness_inventory as checker
    from build.tools import scaffold_witness_inventory as creator
    # Deliberately synthetic historical fixture, not a restored production schema.
    schema = tmp_path / "historical-schema.json"
    schema.write_text(json.dumps({"type": "object", "required": ["related_resource_id", "witnesses"],
                                "properties": {"witnesses": {"type": "array"}}}), encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    (data / "old.json").write_text(json.dumps({"meta": {"id": "old-work"}}), encoding="utf-8")
    args = ["--legacy-data", "--repo-root", str(tmp_path), "--schema", str(schema)]
    target = tmp_path / "sources/old-work/witnesses.json"
    assert checker.main(args) == 1
    assert creator._cli([*args, "--dry-run"]) == 0
    assert not target.exists()
    assert creator._cli(args) == 0
    original = target.read_bytes()
    assert checker.main(args) == 0
    assert creator._cli(args) == 0
    assert target.read_bytes() == original
    payload = json.loads(original)
    payload["related_resource_id"] = "wrong-work"
    target.write_text(json.dumps(payload), encoding="utf-8")
    assert checker.main(args) == 1


@pytest.mark.parametrize("reason", ["index unavailable", "known omission - not in critical text",
                                    "versification offset - SWORD/MT differs from KJV/BSB"])
def test_reference_audit_does_not_promote_permissive_validation(tmp_path, reason):
    from build.tools.audit_ref_coverage import audit_data
    folder = tmp_path / "commentaries"
    folder.mkdir()
    (folder / "sample.json").write_text(json.dumps({"data": [
        {"entry_id": "one", "cross_references": ["Gen.1.1"]}
    ]}), encoding="utf-8")
    report = audit_data(tmp_path, None, lambda ref: (True, reason))
    assert report["counts"]["valid_bsb"] == 0
    assert report["counts"]["valid_kjv_only"] == 0
    assert report["counts"]["unverified"] == 1
    assert report["unverified_refs"] == [{"file": "commentaries/sample.json".replace("/", __import__("os").sep),
                                           "entry_id": "one", "ref": "Gen.1.1", "reason": reason}]


@pytest.mark.parametrize("endpoint_result,expected", [
    ((True, "index unavailable"), "unverified"),
    ((True, "in KJV/TR - not in BSB critical text"), "valid-kjv-only"),
    ((False, "missing"), "failed"),
])
def test_reference_range_preserves_endpoint_outcomes(endpoint_result, expected):
    from build.tools.audit_ref_coverage import _validate_ref_verbose
    def validate(ref):
        return endpoint_result if ref == "Matt.17.21" else (True, "")
    bucket, reason = _validate_ref_verbose("Matt.17.20-Matt.17.21", validate)
    assert bucket == expected
    assert endpoint_result[1] in reason



def test_reference_release_accounts_for_unsupported_rows(release):
    from build.tools.audit_ref_coverage import audit_release
    root, output, selection, _ = release
    def reject_inference(ref):
        raise AssertionError("quotation text must not be inferred as OSIS")
    report = audit_release(root, output, selection, reject_inference)
    assert report["status"] == "incomplete"
    assert report["rows_scanned"] > 0
    assert len(report["unsupported_rows"]) == report["rows_scanned"]
    assert report["references"] == []
    wrong = copy.deepcopy(selection)
    wrong["release_id"] = "wrong-selection"
    with pytest.raises(PipelineError, match="verification failed"):
        audit_release(root, output, wrong, reject_inference)


def test_reference_cli_default_requires_release_inputs(monkeypatch):
    from build.tools import audit_ref_coverage as audit
    def reject_legacy(*args):
        raise AssertionError("implicit legacy discovery")
    monkeypatch.setattr(audit, "legacy_main", reject_legacy)
    with pytest.raises(SystemExit) as exc:
        audit.main([])
    assert exc.value.code == 2


@pytest.mark.parametrize("category", ["catechisms", "doctrinal_documents"])
@pytest.mark.requires_local_artifacts
def test_reference_audit_extracts_source_bound_proofs(tmp_path, monkeypatch, category):
    from lxml import etree
    from collections import Counter
    from tests import test_release_accepted_structured as structured
    from tests.test_release_assembly_v2 import _item, _selection
    from ocd_kernel.tei.acceptance import promote_accepted_master
    from ocd_kernel.release.assemble import assemble_release_v2
    from build.tools.audit_ref_coverage import audit_release
    if category == "doctrinal_documents":
        monkeypatch.setitem(structured._CASES, category,
                            ("doctrinal-documents", "fixture-westminster-confession", "doctrinal-documents"))
    _, case, directory = structured._fixture_case(category)
    tree = etree.parse(str(directory / case["tei_file"]))
    expected = Counter(target for target in tree.xpath(
        "//t:ref[@type='scripture']/@target", namespaces={"t": structured.TEI_NS}))
    assert expected
    source, acceptance = structured.accepted_fixture(tmp_path / "f", category)
    promoted = promote_accepted_master(source, acceptance_path=acceptance, destination=tmp_path / "p")
    root = promoted.destination_root
    selection = _selection(_item(root, category, category, promoted.acceptance_path))
    output = tmp_path / "out"
    assemble_release_v2(root, output, selection=selection)
    if category == "doctrinal_documents":
        public = output / "public/data/doctrinal_documents/train.jsonl"
        rows = [json.loads(line) for line in public.read_text(encoding="utf-8").splitlines()]
        assert rows and all(row["revision_history"] == [] for row in rows)
        assert all("Bound structured category fixture." not in row["text"] for row in rows)
    # Deterministic classification isolates extraction from host verse-index availability.
    report = audit_release(root, output, selection, lambda ref: (True, ""))
    assert report["status"] == "pass"
    assert report["unsupported_rows"] == []
    assert Counter(item["reference"] for item in report["references"]) == expected
    unknown = audit_release(root, output, selection, lambda ref: (True, "index unavailable"))
    assert unknown["status"] == "incomplete"
    assert all(item["outcome"] == "unverified" for item in unknown["references"])



def test_reference_cli_reports_incomplete_release(release, tmp_path, capsys):
    from build.tools.audit_ref_coverage import main
    root, output, selection, _ = release
    selected = tmp_path / "selection.json"
    selected.write_text(json.dumps(selection), encoding="utf-8")
    assert main(["--root", str(root), "--release", str(output), "--selection", str(selected)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "incomplete"
    assert report["unsupported_rows"]


@pytest.mark.parametrize("reference,result,exit_code,bucket", [
    ("Gen.1.1", (True, ""), 0, "valid_bsb"),
    ("Gen.1.999", (False, "missing verse"), 1, "failed"),
    ("Gen.1.1", (True, "index unavailable"), 1, "unverified"),
    ("Tob.1.1", (True, ""), 1, "deuterocanon"),
])
def test_historical_reference_cli_retains_outcomes(tmp_path, monkeypatch, reference, result, exit_code, bucket):
    import logging
    from build.tools import audit_ref_coverage as audit
    from build.scripts import validate_osis
    data = tmp_path / "data/commentaries"
    data.mkdir(parents=True)
    source = data / "sample.json"
    source.write_text(json.dumps({"data": [{"entry_id": "old-entry", "cross_references": [reference]}]}), encoding="utf-8")
    original = source.read_bytes()
    output = tmp_path / "report.json"
    monkeypatch.setattr(audit, "DATA_ROOT", tmp_path / "data")
    monkeypatch.setattr(audit, "OUTPUT_FILE", output)
    monkeypatch.setattr(logging, "FileHandler", lambda *args, **kwargs: logging.NullHandler())
    monkeypatch.setattr(logging, "basicConfig", lambda *args, **kwargs: None)
    monkeypatch.setattr(validate_osis, "validate_osis_ref", lambda ref: result)
    assert audit.main(["--legacy-data", "--category", "commentaries"]) == exit_code
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["counts"][bucket] == 1
    if bucket in ("failed", "unverified", "deuterocanon"):
        assert report[bucket + "_refs"][0]["ref"] == reference
        assert report[bucket + "_refs"][0]["entry_id"] == "old-entry"
    assert source.read_bytes() == original



def test_accuracy_cli_separates_integrity_from_unexecuted_checks(release, tmp_path, monkeypatch, capsys):
    from build.tools import audit_data_accuracy as audit
    root, output, selection, _ = release
    def reject_legacy(*args, **kwargs):
        raise AssertionError("current accuracy report must not read historical data")
    monkeypatch.setattr(audit, "load_all_files", reject_legacy)
    selected = tmp_path / "selection.json"
    selected.write_text(json.dumps(selection), encoding="utf-8")
    assert audit.main(["--root", str(root), "--release", str(output), "--selection", str(selected)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "incomplete"
    assert result["release_integrity"]["status"] == "pass"
    assert len(result["unsupported_checks"]) == 1
    assert len(result["historical_only_checks"]) == 4
    rows = [json.loads(line) for line in (output / "public/data/quotations/train.jsonl").read_text(encoding="utf-8").splitlines()]
    counts = [len(row["text"].split()) for row in rows]
    assert result["word_count_distributions"][0]["minimum"] == min(counts)
    assert result["word_count_distributions"][0]["maximum"] == max(counts)
    assert result["public_text_checks"]["rows_scanned"] == result["release_integrity"]["total"]["records"]
    assert result["release_integrity"]["total"]["records"] > 0
    wrong = copy.deepcopy(selection)
    wrong["release_id"] = "wrong"
    with pytest.raises(PipelineError, match="verification failed"):
        audit.release_accuracy(root, output, wrong)
    with pytest.raises(SystemExit) as exc:
        audit.main([])
    assert exc.value.code == 2



def test_accuracy_public_text_observations_preserve_source():
    from build.tools.audit_data_accuracy import public_text_findings
    row = {"work_id": "work", "record_id": "record", "category": "prose", "text": "Cafe\u0301"}
    original = copy.deepcopy(row)
    findings = public_text_findings(row)
    assert any(item["check"] == "non_nfc" for item in findings)
    assert all(item["record_id"] == "record" for item in findings)
    assert row == original



def test_accuracy_historical_cli_retains_report_and_data(tmp_path, monkeypatch):
    import logging
    from build.tools import audit_data_accuracy as audit
    data = tmp_path / "data/commentaries"
    data.mkdir(parents=True)
    source = data / "sample.json"
    source.write_text(json.dumps({"meta": {"schema_type": "commentary", "id": "old-work"},
                                 "data": [{"entry_id": "duplicate", "commentary_text": "Example text."},
                                          {"entry_id": "duplicate", "commentary_text": "Other text."}]}), encoding="utf-8")
    original = source.read_bytes()
    output = tmp_path / "reports"
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"books": {}}), encoding="utf-8")
    for name, value in {"REPO_ROOT": tmp_path, "DATA_DIR": tmp_path / "data", "OUTPUT_DIR": output,
                        "REPORT_MD_PATH": output / "report.md", "REPORT_JSON_PATH": output / "report.json",
                        "VERSE_INDEX_PATH": index, "DISPUTED_VERSES_PATH": index}.items():
        monkeypatch.setattr(audit, name, value)
    monkeypatch.setattr(logging, "FileHandler", lambda *args, **kwargs: logging.NullHandler())
    monkeypatch.setattr(logging, "basicConfig", lambda *args, **kwargs: None)
    # No stored token counts in this fixture; avoid optional tokenizer loading.
    monkeypatch.setattr(audit, "run_task_10_token_counts", lambda files: [])
    assert audit.main(["--legacy-data", "--category", "commentaries"]) == 0
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert "duplicate" in json.dumps(report)
    assert (output / "report.md").is_file()
    assert source.read_bytes() == original



@pytest.mark.requires_local_artifacts
def test_doctrinal_hierarchy_paths_preserve_source_chapter_and_section():
    from tests.test_projection_doctrinal_documents import _project, _source_units, CASES
    for name in ("fixture-westminster-confession", "fixture-canons-of-dort"):
        case = CASES[name]
        source = {item["id"]: item for item in _source_units(case)}
        projection, _ = _project(name)
        assert len(projection["rows"]) == len(case["selected_source_units"])
        for row, selected in zip(projection["rows"], case["selected_source_units"], strict=True):
            assert selected in source
            chapter, section = selected.split(".", 1)
            assert row["parent_path"] == ["chapter:" + chapter]
            assert row["locator"]["unit_path"] == ["chapter:" + chapter, "section:" + section]
            assert row["number"] == section



@pytest.mark.parametrize("placement", ["paragraph", "direct", "tail"])
@pytest.mark.requires_local_artifacts
def test_doctrinal_parent_paragraph_cannot_disappear(tmp_path, placement):
    from lxml import etree as E
    from tests.test_projection_doctrinal_documents import CASES, FIXTURES, _context, _project
    from ocd_kernel.projection.categories.doctrinal_documents import project_doctrinal_document, verify_doctrinal_document
    case = CASES["fixture-westminster-confession"]
    tree = E.parse(str(FIXTURES / case["tei_file"]))
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    parent = tree.xpath("//t:div[@type='chapter']", namespaces=ns)[0]
    paragraph = E.Element("{" + ns["t"] + "}p")
    paragraph.text = "Parent content must not disappear."
    if placement == "paragraph":
        parent.insert(1, paragraph)
    elif placement == "direct":
        parent.text = paragraph.text
    else:
        parent[-1].tail = paragraph.text
    path = tmp_path / "parent.xml"
    path.write_bytes(E.tostring(tree, encoding="utf-8"))
    with pytest.raises(PipelineError, match="hierarchy requires source_tei_unit_bindings"):
        project_doctrinal_document(path, **_context(case))
    original, receipt = _project("fixture-westminster-confession")
    errors = verify_doctrinal_document(path, original["rows"], receipt, **_context(case))
    assert any("hierarchy requires source_tei_unit_bindings" in error for error in errors)

    # With explicit leaf accounting, parent content is supported and must survive.
    # This synthetic extension is a mapping test, not retained-source evidence.
    from ocd_kernel.projection.categories.doctrinal_documents import build_doctrinal_receipt
    context = _context(case)
    context["source_tei_unit_bindings"] = [
        {"tei_xml_id": "fixture-wcf-1647-unit-1-1", "source_unit_ids": ["1.1"]},
        {"tei_xml_id": "fixture-wcf-1647-unit-1-2", "source_unit_ids": ["1.2"]},
    ]
    projected = project_doctrinal_document(path, **context)
    receipt = build_doctrinal_receipt(projected, identity=case["identity"])
    assert verify_doctrinal_document(path, projected["rows"], receipt, **context) == []
    assert sum(row["text"].count(paragraph.text) for row in projected["rows"]) == 1
    changed = copy.deepcopy(projected["rows"])
    for row in changed:
        row["text"] = row["text"].replace(paragraph.text, "")
    receipt["output_sha256"] = hashlib.sha256(json.dumps(
        changed, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()).hexdigest()
    assert verify_doctrinal_document(path, changed, receipt, **context)



@pytest.mark.requires_local_artifacts
def test_doctrinal_processing_revision_is_not_source_history(tmp_path):
    from tests.test_release_accepted_structured import accepted_fixture
    from ocd_kernel.projection.categories.doctrinal_documents import _revision_history, _checker_revision_history
    from xml.etree import ElementTree as ET
    from lxml import etree as E
    root, _ = accepted_fixture(tmp_path, "doctrinal_documents")
    path = next(root.rglob("candidate.xml"))
    raw = path.read_bytes()
    assert _revision_history(ET.fromstring(raw)) == []
    assert _checker_revision_history(E.fromstring(raw)) == []
    tree = E.fromstring(raw)
    change = tree.find(".//{http://www.tei-c.org/ns/1.0}change")
    change.set("{http://www.w3.org/XML/1998/namespace}id", "unclassified")
    with pytest.raises(PipelineError, match="revision"):
        _revision_history(ET.fromstring(E.tostring(tree)))
    with pytest.raises(PipelineError, match="revision"):
        _checker_revision_history(tree)


@pytest.mark.requires_local_artifacts
def test_doctrinal_kind_preserved_and_forged_row_rejected():
    import copy
    from tests.test_projection_doctrinal_documents import CASES, FIXTURES, _context, _project
    from ocd_kernel.projection.categories.doctrinal_documents import verify_doctrinal_document

    for name, case in CASES.items():
        projection, receipt = _project(name)
        assert projection["rows"]
        assert all(row["document_kind"] == case["document_kind"] for row in projection["rows"])
        assert verify_doctrinal_document(
            FIXTURES / case["tei_file"], projection["rows"], receipt, **_context(case)
        ) == []
        forged = copy.deepcopy(projection["rows"])
        forged[0]["document_kind"] = "creed" if case["document_kind"] != "creed" else "confession"
        assert verify_doctrinal_document(
            FIXTURES / case["tei_file"], forged, receipt, **_context(case)
        )


@pytest.mark.parametrize("declared", ["la", "", "invalid language"])
def test_hymn_occurrence_language_overrides_collection(tmp_path, declared):
    from lxml import etree as E
    from tests.test_projection_hymns import PATH, CONTEXT, project, verify
    tree = E.parse(str(PATH))
    unit = tree.xpath('//t:div[@type="hymn"]', namespaces={"t": "http://www.tei-c.org/ns/1.0"})[0]
    unit.set("{http://www.w3.org/XML/1998/namespace}lang", declared)
    path = tmp_path / "language.xml"
    path.write_bytes(E.tostring(tree))
    if declared != "la":
        with pytest.raises(PipelineError, match="language"):
            project(path, **CONTEXT)
        baseline = project(PATH, **CONTEXT)
        assert verify(path, baseline["rows"], baseline["receipt"], **CONTEXT)
        return
    result = project(path, **CONTEXT)
    assert result["rows"][0]["language"] == "la"
    assert result["rows"][1]["language"] == "en"
    assert verify(path, result["rows"], result["receipt"], **CONTEXT) == []
    result["rows"][0]["language"] = "en"
    assert verify(path, result["rows"], result["receipt"], **CONTEXT)


@pytest.mark.parametrize("element", ["TEI", "text", "body", "div"])
def test_hymn_language_uses_nearest_ancestor_declaration(tmp_path, element):
    from lxml import etree as E
    from tests.test_projection_hymns import PATH, CONTEXT, project, verify
    tree = E.parse(str(PATH))
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    language = "{http://www.w3.org/XML/1998/namespace}lang"
    tree.xpath("//t:" + element, namespaces=ns)[0].set(language, "de")
    first = tree.xpath('//t:div[@type="hymn"]', namespaces=ns)[0]
    first.set(language, "la")
    path = tmp_path / "ancestor-language.xml"
    path.write_bytes(E.tostring(tree))
    result = project(path, **CONTEXT)
    assert [row["language"] for row in result["rows"]] == ["la", "de", "de"]
    assert verify(path, result["rows"], result["receipt"], **CONTEXT) == []


def test_native_prose_preserves_parent_content_and_nested_sections(tmp_path):
    import copy
    from ocd_kernel.projection.categories.native_documents import project_document, verify_document
    path = tmp_path / "hierarchy.xml"
    path.write_text('<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc><titleStmt><title>Hierarchy</title></titleStmt><publicationStmt><p>Private</p></publicationStmt><sourceDesc><p>Fixture</p></sourceDesc></fileDesc></teiHeader><text><body><div type="book" n="I"><head>Book title</head><p>Parent text</p><div type="chapter" n="1"><head>Chapter title</head><p>First paragraph</p><p>Second paragraph</p></div><p>After chapter</p></div></body></text></TEI>', encoding="utf-8")
    context = dict(identity={"work_id":"work", "textual_form_id":"form", "edition_id":"edition"}, language="en", representation_revision="revision", edition_title="Hierarchy", category="prose")
    result = project_document(path, **context)
    assert len(result["rows"]) == 1
    root = result["rows"][0]["structure"][0]
    assert root["kind"] == "division"
    assert root["attributes"]["type"] == "book"
    assert root["attributes"]["number"] == "I"
    assert [node["kind"] for node in root["content"]] == ["heading", "paragraph", "division", "paragraph"]
    chapter = root["content"][2]
    assert chapter["attributes"]["type"] == "chapter"
    assert chapter["attributes"]["number"] == "1"
    assert [node["kind"] for node in chapter["content"]] == ["heading", "paragraph", "paragraph"]
    assert verify_document(path, result["rows"], result["receipt"], **context) == []
    for mutation in ("parent", "children", "type", "title"):
        rows = copy.deepcopy(result["rows"])
        node = rows[0]["structure"][0]
        if mutation == "parent": node["content"].pop(1)
        elif mutation == "children": node["content"][2]["content"].reverse()
        elif mutation == "type": node["attributes"]["type"] = "chapter"
        else: node["content"][0]["content"][0]["text"] = "Invented title"
        assert verify_document(path, rows, result["receipt"], **context)


@pytest.mark.parametrize("target, expected", [
    ("https://example.org/commentary-part-one", "other"),
    ("https://example.org/John.1.1", "other"),
    ("John.1.1.extra", "other"),
    ("Bible:GEN.1.1", "verse"),
    ("osis:John.1", "chapter"),
    ("Bible:John.1.1-John.1.3", "range"),
    ("John.1.1-3", "range"),
    ("ZEP", "book"),
])
def test_commentary_scope_does_not_treat_urls_as_bible_ranges(target, expected):
    from ocd_kernel.projection.categories.commentary import _scope
    result = _scope(target)
    assert result["raw"] == target
    assert result["type"] == expected
    if target.startswith("https:"):
        assert result["normalized"] == target


def test_untitled_prayer_preserves_opening_without_inventing_title(tmp_path):
    from lxml import etree as E
    from tests.test_projection_prayers import F, CASES, project, verify
    case = next(c for c in CASES if c["name"] == "collects")
    original = project(F / case["tei_file"], **case["context"])
    tree = E.parse(str(F / case["tei_file"]))
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    unit = tree.xpath("//t:body/t:div", namespaces=ns)[0]
    unit.remove(unit.find("t:head", ns))
    path = tmp_path / "untitled-prayer.xml"
    path.write_bytes(E.tostring(tree))
    result = project(path, **case["context"])
    row = result["rows"][0]
    assert row["locator"]["title"] is None
    assert row["occasion"] is None
    assert row["divisions"] == original["rows"][0]["divisions"]
    assert row["text"] == original["rows"][0]["text"]
    assert row["record_id"] == original["rows"][0]["record_id"]
    assert verify(path, result["rows"], result["receipt"], **case["context"]) == []
    row["locator"]["title"] = row["text"][:30]
    assert verify(path, result["rows"], result["receipt"], **case["context"])


@pytest.mark.parametrize("category, old_version", [
    ("hymns", "ocd-hymns-mapping-provisional-v3"),
    ("commentary", "ocd-commentary-mapping-provisional-v2"),
    pytest.param("doctrinal_documents", "ocd-doctrinal-documents-mapping-v2", marks=pytest.mark.requires_local_artifacts),
])
def test_repaired_projection_rejects_previous_mapping_receipt(category, old_version):
    from pathlib import Path
    import copy
    if category == "hymns":
        from tests.test_projection_hymns import PATH, CONTEXT, project, verify
        result = project(PATH, **CONTEXT)
        check = lambda receipt: verify(PATH, result["rows"], receipt, **CONTEXT)
    elif category == "commentary":
        from tests.test_projection_commentary import CASES, FIXTURE, _result, _context, verify
        case = CASES[0]
        result = _result(case)
        path = FIXTURE / Path(case["tei_path"]).name
        check = lambda receipt: verify(path, result["rows"], receipt, **_context(case))
    else:
        from tests.test_projection_doctrinal_documents import CASES, FIXTURES, _project, _context
        from ocd_kernel.projection.categories.doctrinal_documents import verify_doctrinal_document
        name = next(iter(CASES)); case = CASES[name]
        projection, receipt = _project(name)
        result = {"rows": projection["rows"], "receipt": receipt}
        check = lambda receipt: verify_doctrinal_document(FIXTURES / case["tei_file"], result["rows"], receipt, **_context(case))
    assert result["receipt"]["mapping_version"] != old_version
    assert check(result["receipt"]) == []
    stale = copy.deepcopy(result["receipt"])
    stale["mapping_version"] = old_version
    assert check(stale)
