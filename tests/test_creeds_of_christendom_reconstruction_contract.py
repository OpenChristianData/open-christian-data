from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.lib029_oracle import _oracle
from build.tei.lib029_reconstruction import _convert
from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    prepare_review,
    reconstruct,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/puritan-creeds-of-christendom-vol-1.source-manifest.json'
RETAINED_RAW_ROOT = Path(
    os.environ.get("OCD_RETAINED_RAW_ROOT", r"D:\Library\Open Christian Data\raw")
)
EXPECTED_MEMBERS = {
    "manifest.json",
    "content.tei.xml",
    "source-accountability.json",
    "provenance.json",
    "unresolved.jsonl",
    "README.source.md",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(record: object) -> bytes:
    return (
        json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _reseal_member(path: Path, name: str, content: bytes) -> CandidatePackage:
    (path / name).write_bytes(content)
    manifest = json.loads((path / "manifest.json").read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == name)
    member.update(bytes=len(content), sha256=_sha(content))
    (path / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


@pytest.fixture(scope="module")
def lib029_evidence(tmp_path_factory: pytest.TempPathFactory):
    if not RETAINED_RAW_ROOT.is_dir():
        pytest.skip(f"durable retained raw root is unavailable: {RETAINED_RAW_ROOT}")
    previous = os.environ.get("OCD_RETAINED_RAW_ROOT")
    os.environ["OCD_RETAINED_RAW_ROOT"] = str(RETAINED_RAW_ROOT)
    try:
        source = SourceManifest.load(SOURCE_MANIFEST, repository_root=ROOT)
        candidate = reconstruct(
            source, tmp_path_factory.mktemp("lib029-contract") / "candidate", _convert
        )
        report = validate(source, candidate, _oracle)
        yield source, candidate, report
    finally:
        if previous is None:
            os.environ.pop("OCD_RETAINED_RAW_ROOT", None)
        else:
            os.environ["OCD_RETAINED_RAW_ROOT"] = previous


def test_lib029_candidate_is_complete_accounted_and_reviewable(lib029_evidence) -> None:
    source, candidate, report = lib029_evidence
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    unresolved = [
        json.loads(line)
        for line in candidate.member_bytes("unresolved.jsonl").splitlines()
    ]
    assert set(candidate.member_names) == EXPECTED_MEMBERS
    assert candidate.manifest["status"] == "nonaccepted"
    assert accountability["work_count"] == 1
    assert accountability["feature_count"] == 24_893
    assert accountability["attribute_count"] == 39_983
    assert len(accountability["crosswalk"]) == accountability["feature_count"]
    assert (
        accountability["omitted_feature_count"]
        == accountability["duplicate_feature_count"]
        == accountability["unresolved_feature_count"]
        == 0
    )
    assert [item["work_id"] for item in accountability["source_members"]] == [
        "creeds-of-christendom-vol-1"
    ]
    assert accountability["document_accounting"][0]["scope_div1_ids"] == [
        "iii",
        "iv",
        "v",
        "vi",
        "vii",
        "viii",
        "ix",
        "x",
    ]
    assert [item["work_id"] for item in provenance["works"]] == [
        "creeds-of-christendom-vol-1"
    ]
    assert (
        provenance["canonical_data_written"] is False
        and provenance["canonical_ir_written"] is False
    )
    assert all(item["status"] == "unresolved" for item in unresolved)
    assert b"CCEL.org" in candidate.member_bytes("README.source.md")
    assert report.status == "pass"
    # A one-member source binds the source bytes, not its census JSON file.
    assert _oracle(source, candidate)["source_sha256"] == _sha(
        source.authority_path("creeds-of-christendom-vol-1-source").read_bytes()
    )
    review = prepare_review(source, candidate, report)
    assert review.candidate_sha256 == candidate.sha256
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    assert len(tei.xpath('//*[local-name()="div" and @type="work"]')) == 1
    assert (
        len(
            tei.xpath(
                '//*[@xml:id][starts-with(@xml:id,"lib029-f-")]',
                namespaces={"xml": "http://www.w3.org/XML/1998/namespace"},
            )
        )
        == 24_893
    )
    assert (
        len(tei.xpath('//*[local-name()="div" and @type="work"]/*[local-name()="div"]'))
        == 8
    )
    chapter_ids = {
        row["source_xml_id"]
        for row in accountability["crosswalk"]
        if row["source_tag"] == "div1"
    }
    assert chapter_ids == {"iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}
    assert {
        row["source_xml_id"]
        for row in accountability["crosswalk"]
        if row["source_tag"] == "div1"
    } == chapter_ids


def test_lib029_attribute_dispositions_describe_actual_projection(
    lib029_evidence,
) -> None:
    _, candidate, _ = lib029_evidence
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    rows = accountability["crosswalk"]
    falsely_projected = {
        ("p", "class"),
        ("pb", "href"),
        ("span", "class"),
        ("div", "class"),
        ("hr", "class"),
    }
    affected = [
        disposition
        for row in rows
        for disposition in row["attribute_dispositions"]
        if (row["source_tag"], disposition["source_attribute"]) in falsely_projected
    ]
    assert len(affected) == 5_831
    assert {item["destination"] for item in affected} == {"source-accountability"}
    source_id_dispositions = [
        disposition
        for row in rows
        for disposition in row["attribute_dispositions"]
        if disposition["source_attribute"] == "id"
    ]
    assert source_id_dispositions
    assert {item["destination"] for item in source_id_dispositions} == {
        "source-accountability"
    }
    assert all(
        row["tei_attributes"]["xml:id"] == row["tei_xml_id"] == f"lib029-f-{index:07d}"
        for index, row in enumerate(rows, start=1)
    )

    titled_divisions = [
        row
        for row in rows
        if row["source_tag"].startswith("div") and "title" in row["attributes"]
    ]
    assert len(titled_divisions) == 133
    assert sum(row["source_title_head"] is not None for row in titled_divisions) == 118
    for row in titled_divisions:
        title_disposition = next(
            item
            for item in row["attribute_dispositions"]
            if item["source_attribute"] == "title"
        )
        expected = (
            "child::head[1]"
            if row["source_title_head"] is not None
            else "source-accountability"
        )
        assert title_disposition["destination"] == expected


def test_lib029_reconstruction_is_deterministic_across_process_and_cwd(
    tmp_path: Path,
) -> None:
    if not RETAINED_RAW_ROOT.is_dir():
        pytest.skip(f"durable retained raw root is unavailable: {RETAINED_RAW_ROOT}")
    other_cwd = tmp_path / "different-cwd"
    other_cwd.mkdir()
    first, second = tmp_path / "first", tmp_path / "second"
    script = (
        "from pathlib import Path; import hashlib, sys; "
        "from ocd_kernel.reconstruction import SourceManifest,reconstruct; "
        "from build.tei.lib029_reconstruction import _convert; "
        f"root=Path({str(ROOT)!r}); "
        f"manifest=SourceManifest.load(root/{str(SOURCE_MANIFEST.relative_to(ROOT))!r}, repository_root=root); "
        "candidate=reconstruct(manifest, Path(sys.argv[1]), _convert); "
        "print('|'.join(name+':'+hashlib.sha256(candidate.member_bytes(name)).hexdigest() for name in candidate.member_names))"
    )
    environment = os.environ.copy()
    environment["OCD_RETAINED_RAW_ROOT"] = str(RETAINED_RAW_ROOT)
    environment["PYTHONPATH"] = str(ROOT)
    first_run = subprocess.run(
        [sys.executable, "-B", "-c", script, str(first)],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    second_run = subprocess.run(
        [sys.executable, "-B", "-c", script, str(second)],
        cwd=other_cwd,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert first_run.stdout == second_run.stdout
    assert {
        item.name: item.read_bytes() for item in first.iterdir() if item.is_file()
    } == {item.name: item.read_bytes() for item in second.iterdir() if item.is_file()}


def test_lib029_oracle_rejects_resealed_projection_mutation(
    lib029_evidence, tmp_path: Path
) -> None:
    source, candidate, _ = lib029_evidence
    mutated = tmp_path / "resealed-mutation"
    shutil.copytree(candidate.path, mutated)
    tree = etree.fromstring((mutated / "content.tei.xml").read_bytes())
    paragraph = tree.xpath(
        '//*[local-name()="div" and @type="work"]//*[local-name()="p"]'
    )[0]
    paragraph.text = (paragraph.text or "") + " MUTATION"
    content = etree.tostring(
        tree, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )
    resealed = _reseal_member(mutated, "content.tei.xml", content)
    with pytest.raises(ValueError):
        _oracle(source, resealed)


@pytest.mark.parametrize(
    "field",
    (
        "feature_id",
        "source_selector",
        "attributes",
        "direct_text",
        "tail_text",
        "tei_parent_id",
        "tei_child_ordinal",
        "tei_attributes.xml:id",
        "attribute_dispositions",
        "tei_selector",
        "parent_feature_id",
        "source_title_head",
    ),
)
def test_lib029_oracle_rejects_resealed_crosswalk_full_row_mutation(
    lib029_evidence, tmp_path: Path, field: str
) -> None:
    source, candidate, _ = lib029_evidence
    mutated = tmp_path / f"resealed-crosswalk-{field.replace(':', '-')}"
    shutil.copytree(candidate.path, mutated)
    accountability = json.loads((mutated / "source-accountability.json").read_bytes())
    rows = accountability["crosswalk"]
    row = rows[0]
    if field == "feature_id":
        row[field] = "lib029-feature-9999999"
    elif field == "source_selector":
        row[field] += "/p[9999999]"
    elif field == "attributes":
        row[field]["adversarial"] = "mutation"
    elif field in {"direct_text", "tail_text", "tei_parent_id"}:
        row[field] += " MUTATION"
    elif field == "tei_child_ordinal":
        row[field] += 1
    elif field == "tei_attributes.xml:id":
        row["tei_attributes"]["xml:id"] = "lib029-f-9999999"
    elif field == "attribute_dispositions":
        row = next(item for item in rows if item["attribute_dispositions"])
        row[field][0]["destination"] += "-mutation"
    elif field == "tei_selector":
        row[field] = "#lib029-f-9999999"
    elif field == "parent_feature_id":
        row[field] = "lib029-feature-9999999"
    elif field == "source_title_head":
        row[field] = "MUTATED TITLE"
    else:
        raise AssertionError(f"unhandled crosswalk field: {field}")
    resealed = _reseal_member(
        mutated, "source-accountability.json", _canonical(accountability)
    )
    with pytest.raises(ValueError, match="crosswalk drifted"):
        _oracle(source, resealed)
