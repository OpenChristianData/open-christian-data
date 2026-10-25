from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.wesley_plain_account_oracle import _content_text as _oracle_content_text
from build.tei.wesley_plain_account_oracle import _oracle
from build.tei.wesley_plain_account_reconstruction import (
    _content_text as _producer_content_text,
)
from build.tei.wesley_plain_account_reconstruction import _convert
from build.tools.count_dataset_records import (
    _manifest_config_ids,
    _manifest_primary_hashes,
    collect_work_catalog,
)
from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    prepare_review,
    reconstruct,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/puritan-wesley-plain-account.source-manifest.json'
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
EXPECTED_WORKS = [
    "wesley-plain-account",
]
EXPECTED_FEATURE_COUNTS = {
    "#comment": 6,
    "a": 56,
    "div": 1,
    "div1": 3,
    "div2": 7,
    "h1": 3,
    "h2": 1,
    "h3": 1,
    "h4": 2,
    "hr": 2,
    "i": 22,
    "insertIndex": 1,
    "l": 230,
    "p": 547,
    "scripRef": 56,
    "verse": 9,
}
EXPECTED_SOURCE_HASHES = [
    "2c6d835621077e8002c86a4a3cfd0613c604d56626110d3d77d5e43c50dfab9b",
]


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(record: object) -> bytes:
    return (
        json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _reseal_member(
    candidate: CandidatePackage,
    destination: Path,
    name: str,
    content: bytes,
) -> CandidatePackage:
    shutil.copytree(candidate.path, destination)
    (destination / name).write_bytes(content)
    manifest = json.loads((destination / "manifest.json").read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == name)
    member.update(bytes=len(content), sha256=_sha(content))
    (destination / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(destination)


def _reseal_manifest(
    candidate: CandidatePackage,
    destination: Path,
    mutate,
) -> CandidatePackage:
    shutil.copytree(candidate.path, destination)
    manifest = json.loads((destination / "manifest.json").read_bytes())
    mutate(manifest)
    (destination / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(destination)


@pytest.fixture(scope="module")
def lib032_evidence(tmp_path_factory: pytest.TempPathFactory):
    if not RETAINED_RAW_ROOT.is_dir():
        pytest.skip(f"durable retained raw root is unavailable: {RETAINED_RAW_ROOT}")
    previous = os.environ.get("OCD_RETAINED_RAW_ROOT")
    os.environ["OCD_RETAINED_RAW_ROOT"] = str(RETAINED_RAW_ROOT)
    try:
        source = SourceManifest.load(SOURCE_MANIFEST, repository_root=ROOT)
        candidate = reconstruct(
            source,
            tmp_path_factory.mktemp("lib032-contract") / "candidate",
            _convert,
        )
        report = validate(source, candidate, _oracle)
        yield source, candidate, report
    finally:
        if previous is None:
            os.environ.pop("OCD_RETAINED_RAW_ROOT", None)
        else:
            os.environ["OCD_RETAINED_RAW_ROOT"] = previous


def test_lib032_candidate_is_complete_accounted_and_reviewable(lib032_evidence) -> None:
    source, candidate, report = lib032_evidence
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    unresolved = [
        json.loads(line)
        for line in candidate.member_bytes("unresolved.jsonl").splitlines()
    ]

    assert set(candidate.member_names) == EXPECTED_MEMBERS
    assert candidate.manifest["status"] == "nonaccepted"
    assert accountability["work_count"] == 1
    assert accountability["feature_count"] == 947
    assert accountability["attribute_count"] == 1_409
    assert accountability["feature_counts"] == EXPECTED_FEATURE_COUNTS
    assert (
        sum(
            1
            for row in accountability["crosswalk"]
            if row["direct_text"] and not row["direct_text"].strip()
        )
        == 41
    )
    assert (
        sum(
            1
            for row in accountability["crosswalk"]
            if row["tail_text"] and not row["tail_text"].strip()
        )
        == 864
    )
    assert len(accountability["crosswalk"]) == 947
    assert accountability["omitted_feature_count"] == 0
    assert accountability["duplicate_feature_count"] == 0
    assert accountability["unresolved_feature_count"] == 0
    assert [
        item["work_id"] for item in accountability["source_members"]
    ] == EXPECTED_WORKS
    assert [item["work_id"] for item in provenance["works"]] == EXPECTED_WORKS
    assert all(item["accepted_ir"] == "not_accepted" for item in provenance["works"])
    assert all(item["human_review"] == "required" for item in provenance["works"])
    assert all(item["publication"] == "not_ready" for item in provenance["works"])
    assert provenance["canonical_data_written"] is False
    assert provenance["canonical_ir_written"] is False
    assert [item["id"] for item in unresolved] == [
        "lib032-print-edition-collation",
        "lib032-human-acceptance-and-publication",
    ]
    assert b"CCEL.org" in candidate.member_bytes("README.source.md")
    assert report.status == "pass"

    review = prepare_review(source, candidate, report)
    assert review.candidate_sha256 == candidate.sha256
    assert review.member_names == tuple(sorted(EXPECTED_MEMBERS))
    assert source.authority_path("retained-source-set").is_file()

    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    assert len(tei.xpath('//*[local-name()="div" and @type="work"]')) == 1
    assert (
        len(
            tei.xpath(
                '//*[@xml:id][starts-with(@xml:id,"lib032-f-")]',
                namespaces={"xml": "http://www.w3.org/XML/1998/namespace"},
            )
        )
        == 947
    )


def test_lib032_public_seam_resolves_configured_raw_topology_without_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not (ROOT / ".ocd-storage.json").is_file():
        pytest.skip("repository storage topology is not configured")
    monkeypatch.delenv("OCD_RETAINED_RAW_ROOT", raising=False)

    source = SourceManifest.load(SOURCE_MANIFEST, repository_root=ROOT)
    candidate = reconstruct(source, tmp_path / "candidate", _convert)
    report = validate(source, candidate, _oracle)
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))

    assert report.status == "pass"
    assert accountability["source_members"] == [
        {
            "work_id": "wesley-plain-account",
            "path": "ccel/wesley/perfection.xml",
            "bytes": 228_042,
            "sha256": EXPECTED_SOURCE_HASHES[0],
        }
    ]


def test_lib032_reconstruction_is_deterministic_across_process_and_cwd(
    tmp_path: Path,
) -> None:
    if not RETAINED_RAW_ROOT.is_dir():
        pytest.skip(f"durable retained raw root is unavailable: {RETAINED_RAW_ROOT}")
    other_cwd = tmp_path / "different-cwd"
    other_cwd.mkdir()
    first = tmp_path / "first"
    second = tmp_path / "second"
    script = (
        "from pathlib import Path; import hashlib, sys; "
        "from ocd_kernel.reconstruction import SourceManifest, reconstruct; "
        "from build.tei.wesley_plain_account_reconstruction import _convert; "
        f"root=Path({str(ROOT)!r}); "
        f"manifest=SourceManifest.load(root/{str(SOURCE_MANIFEST.relative_to(ROOT))!r}, repository_root=root); "
        "candidate=reconstruct(manifest, Path(sys.argv[1]), _convert); "
        "print('|'.join(name+':'+hashlib.sha256(candidate.member_bytes(name)).hexdigest() for name in candidate.member_names))"
    )
    environment = os.environ.copy()
    environment["OCD_RETAINED_RAW_ROOT"] = str(RETAINED_RAW_ROOT)
    environment["PYTHONPATH"] = str(ROOT)
    environment["PYTHONHASHSEED"] = "1"

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
        env={**environment, "PYTHONHASHSEED": "8675309"},
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert first_run.stdout == second_run.stdout
    assert {
        item.name: item.read_bytes() for item in first.iterdir() if item.is_file()
    } == {item.name: item.read_bytes() for item in second.iterdir() if item.is_file()}
    assert all(
        f"{name}:{_sha((first / name).read_bytes())}" in first_run.stdout
        for name in EXPECTED_MEMBERS
    )


def test_lib032_source_census_maps_and_exact_identity_route(
    lib032_evidence,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, candidate, validation = lib032_evidence
    from tests.test_runtime_manifest_binding_boundaries import allow_runtime_manifest_selection

    allow_runtime_manifest_selection(monkeypatch, SOURCE_MANIFEST)
    selection = {
        "source_manifest_allowlist": [SOURCE_MANIFEST.relative_to(ROOT).as_posix()],
        "data_resource_allowlist": [f"data/structured-text/{work_id}.json" for work_id in EXPECTED_WORKS],
    }
    source_set = json.loads(source.authority_path("retained-source-set").read_bytes())
    assert source_set["census"] == {
        "included": 1,
        "excluded": 0,
        "basis": "the sole ticket-assigned CCEL ThML witness is present, byte-pinned, and suitable for complete ThML.body reconstruction",
    }
    assert all(
        item["disposition"] == "include"
        and item["reason"] == "ticket-assigned complete retained CCEL ThML witness"
        for item in source_set["members"]
    )
    assert _manifest_config_ids(source.record, ROOT) == set(EXPECTED_WORKS)
    assert _manifest_primary_hashes(source.record) == set(EXPECTED_SOURCE_HASHES)
    work_map = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/02-work-ticket-map.md"
    ).read_text(encoding="utf-8")
    source_map = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/05-source-ticket-map.md"
    ).read_text(encoding="utf-8")
    for work_id, digest in zip(EXPECTED_WORKS, EXPECTED_SOURCE_HASHES, strict=True):
        assert (
            sum(line.startswith(f"| `{work_id}` |") for line in work_map.splitlines())
            == 1
        )
        assert (
            f"| `{work_id}` | `sha256:{digest}` | LIB-032 | current-claim |"
            in source_map
        )
    report = {
        "contract": "ocd-validation-report-v1",
        "status": validation.status,
        "candidate_sha256": validation.candidate_sha256,
        "source_manifest_sha256": validation.source_manifest_sha256,
        "attestation": dict(validation.attestation),
        "findings": list(validation.findings),
        "report_sha256": validation.sha256,
    }
    validation_path = tmp_path / "validation.json"
    validation_path.write_bytes(_canonical(report))
    evidence = {
        (source.record["source_id"], work_id): (candidate.path, validation_path)
        for work_id in EXPECTED_WORKS
    }
    catalog = collect_work_catalog(ROOT / "data", reconstruction_evidence=evidence, **selection)
    assert catalog.summary["work_units"] == len(EXPECTED_WORKS)
    by_id = {work["work_id"]: work for work in catalog.works}
    for work_id in EXPECTED_WORKS:
        routes = [
            route
            for route in by_id[work_id]["reconstruction_state"]["routes"]
            if route["source_id"] == source.record["source_id"]
        ]
        assert len(routes) == 1
        assert routes[0]["association"] == "source_hash+exact_id"
        assert routes[0]["candidate_verification"] == "verified"
        assert routes[0]["validation_verification"] == "verified"


def test_lib032_element_only_text_guard_and_whitespace_preservation() -> None:
    for function in (_producer_content_text, _oracle_content_text):
        assert function("div", "\n  ") == "\n  "
        assert function("p", "substantive") == "substantive"
        with pytest.raises(ValueError):
            function("div", "substantive")


def test_lib032_oracle_rejects_resealed_tei_projection_mutation(
    lib032_evidence,
    tmp_path: Path,
) -> None:
    source, candidate, _ = lib032_evidence
    mutated = tmp_path / "resealed-mutation"
    shutil.copytree(candidate.path, mutated)
    tree = etree.fromstring((mutated / "content.tei.xml").read_bytes())
    paragraph = tree.xpath(
        '//*[local-name()="div" and @type="work"]//*[local-name()="p"]'
    )[0]
    paragraph.text = (paragraph.text or "") + " MUTATION"
    content = etree.tostring(
        tree,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )
    (mutated / "content.tei.xml").write_bytes(content)
    manifest = json.loads((mutated / "manifest.json").read_bytes())
    member = next(
        item for item in manifest["members"] if item["name"] == "content.tei.xml"
    )
    member.update(bytes=len(content), sha256=_sha(content))
    (mutated / "manifest.json").write_bytes(_canonical(manifest))
    resealed = CandidatePackage.load(mutated)

    with pytest.raises(ValueError):
        _oracle(source, resealed)


@pytest.mark.parametrize(
    "case",
    [
        "reordered-attributes",
        "prefixed-default-namespace",
        "trailing-newline",
        "formatted-attribute-whitespace",
    ],
)
def test_lib032_oracle_rejects_resealed_tei_serialization_drift(
    lib032_evidence,
    tmp_path: Path,
    case: str,
) -> None:
    """Equivalent XML infosets must not bypass the exact byte projection."""
    source, candidate, _ = lib032_evidence
    content = candidate.member_bytes("content.tei.xml")
    if case == "reordered-attributes":
        match = re.search(
            rb'(<[^/> ]+ )xml:id=("[^"]+") ([A-Za-z][A-Za-z0-9_-]*)=("[^"]+")',
            content,
        )
        assert match is not None
        content = (
            content[: match.start()]
            + match.group(1)
            + match.group(3)
            + b"="
            + match.group(4)
            + b" xml:id="
            + match.group(2)
            + content[match.end() :]
        )
    elif case == "prefixed-default-namespace":
        content = content.replace(
            b'<TEI xmlns="http://www.tei-c.org/ns/1.0"',
            b'<tei:TEI xmlns:tei="http://www.tei-c.org/ns/1.0"',
            1,
        )
        content = re.sub(
            rb"<(/?)([A-Za-z][A-Za-z0-9_.-]*)(?=[\x20\t\r\n/>])",
            rb"<\1tei:\2",
            content,
        )
        content = content.replace(b"</TEI>", b"</tei:TEI>", 1)
    elif case == "trailing-newline":
        content += b"\n"
    else:
        match = re.search(
            rb'(<[^/> ]+ xml:id="[^"]+") ([A-Za-z][A-Za-z0-9_-]*="[^"]+")',
            content,
        )
        assert match is not None
        content = (
            content[: match.start()]
            + match.group(1)
            + b"\n  "
            + match.group(2)
            + content[match.end() :]
        )
    assert etree.tostring(etree.fromstring(content))
    resealed = _reseal_member(candidate, tmp_path / case, "content.tei.xml", content)
    with pytest.raises(ValueError):
        _oracle(source, resealed)


@pytest.mark.parametrize(
    "case",
    ["extra", "wrong-source-id", "float-bytes", "member-order", "status"],
)
def test_lib032_oracle_rejects_resealed_manifest_drift(
    lib032_evidence,
    tmp_path: Path,
    case: str,
) -> None:
    source, candidate, _ = lib032_evidence

    def mutate(manifest: dict[str, object]) -> None:
        if case == "extra":
            manifest["unexpected"] = "valid-looking"
        elif case == "wrong-source-id":
            manifest["source_id"] = "another-source"
        elif case == "float-bytes":
            manifest["members"][0]["bytes"] = float(manifest["members"][0]["bytes"])
        elif case == "member-order":
            manifest["members"].reverse()
        elif case == "status":
            manifest["status"] = "accepted"

    resealed = _reseal_manifest(candidate, tmp_path / case, mutate)
    with pytest.raises(ValueError):
        _oracle(source, resealed)


@pytest.mark.parametrize(
    "case",
    [
        "title",
        "author",
        "source-url",
        "source-hash",
        "print-source",
        "rights",
        "extra-node",
        "extra-attribute",
        "wrong-qname",
        "whitespace-direct-text",
        "whitespace-tail",
    ],
)
def test_lib032_oracle_rejects_resealed_full_tei_drift(
    lib032_evidence,
    tmp_path: Path,
    case: str,
) -> None:
    source, candidate, _ = lib032_evidence
    tree = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    ns = {
        "tei": "http://www.tei-c.org/ns/1.0",
        "xml": "http://www.w3.org/XML/1998/namespace",
    }
    if case == "title":
        tree.xpath("/tei:TEI/tei:teiHeader//tei:title", namespaces=ns)[
            0
        ].text += " drift"
    elif case == "author":
        tree.xpath("/tei:TEI/tei:teiHeader//tei:author", namespaces=ns)[
            0
        ].text = "Wrong author"
    elif case == "source-url":
        tree.xpath("/tei:TEI/tei:teiHeader//tei:ptr", namespaces=ns)[0].set(
            "target", "https://example.invalid/"
        )
    elif case == "source-hash":
        tree.xpath("/tei:TEI/tei:teiHeader//tei:idno[@type='sha256']", namespaces=ns)[
            0
        ].text = "0" * 64
    elif case == "print-source":
        tree.xpath(
            "/tei:TEI/tei:teiHeader//tei:note[@type='print-source']", namespaces=ns
        )[0].text = "invented edition"
    elif case == "rights":
        tree.xpath("/tei:TEI/tei:teiHeader//tei:availability/tei:p", namespaces=ns)[
            0
        ].text = "cleared"
    elif case == "extra-node":
        tree.xpath("/tei:TEI/tei:text/tei:body", namespaces=ns)[0].append(
            etree.Element("{http://www.tei-c.org/ns/1.0}div")
        )
    elif case == "extra-attribute":
        tree.xpath("/tei:TEI/tei:text/tei:body", namespaces=ns)[0].set("n", "extra")
    elif case == "wrong-qname":
        node = tree.xpath("//*[@xml:id]", namespaces=ns)[0]
        value = node.attrib.pop("{http://www.w3.org/XML/1998/namespace}id")
        node.set("id", value)
    else:
        accountability = json.loads(
            candidate.member_bytes("source-accountability.json")
        )
        field = "direct_text" if case == "whitespace-direct-text" else "tail_text"
        row = next(
            item
            for item in accountability["crosswalk"]
            if item[field] and not item[field].strip()
        )
        node = tree.xpath(f"//*[@xml:id='{row['tei_xml_id']}']", namespaces=ns)[0]
        if field == "direct_text":
            if row["source_title_head"] is None:
                node.text = ""
            else:
                node[0].tail = ""
        else:
            node.tail = ""
    content = etree.tostring(
        tree, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )
    resealed = _reseal_member(candidate, tmp_path / case, "content.tei.xml", content)
    with pytest.raises(ValueError):
        _oracle(source, resealed)


@pytest.mark.parametrize(
    "case",
    [
        "accountability-source-hash",
        "accountability-document-count",
        "crosswalk-parent",
        "crosswalk-ordinal",
        "crosswalk-attributes",
        "crosswalk-disposition",
        "crosswalk-text",
        "crosswalk-provenance-hash",
        "accountability-extra",
        "accountability-bool",
        "accountability-float",
        "provenance-source-id",
        "provenance-rights",
        "provenance-status",
        "provenance-extra",
        "provenance-bool",
        "unresolved-evidence",
        "unresolved-status",
        "unresolved-extra",
    ],
)
def test_lib032_oracle_rejects_resealed_evidence_drift(
    lib032_evidence,
    tmp_path: Path,
    case: str,
) -> None:
    source, candidate, _ = lib032_evidence
    if case.startswith("accountability") or case.startswith("crosswalk"):
        name = "source-accountability.json"
        record = json.loads(candidate.member_bytes(name))
        row = record["crosswalk"][100]
        if case == "accountability-source-hash":
            record["source_members"][0]["sha256"] = "0" * 64
        elif case == "accountability-document-count":
            record["document_accounting"][0]["document_accounting"][
                "body_element_count"
            ] += 1
        elif case == "crosswalk-parent":
            row["tei_parent_id"] = "wrong-parent"
        elif case == "crosswalk-ordinal":
            row["tei_child_ordinal"] += 1
        elif case == "crosswalk-attributes":
            row["attributes"]["invented"] = "value"
        elif case == "crosswalk-disposition":
            row["attribute_dispositions"].append(
                {
                    "source_attribute": "invented",
                    "source_value": "value",
                    "destination": "source-accountability",
                }
            )
        elif case == "crosswalk-text":
            row["direct_text"] += " drift"
        elif case == "crosswalk-provenance-hash":
            row["tail_text_sha256"] = "0" * 64
        elif case == "accountability-extra":
            record["extra"] = None
        elif case == "accountability-bool":
            record["feature_count"] = True
        elif case == "accountability-float":
            record["attribute_count"] = float(record["attribute_count"])
        content = _canonical(record)
    elif case.startswith("provenance"):
        name = "provenance.json"
        record = json.loads(candidate.member_bytes(name))
        if case == "provenance-source-id":
            record["source_id"] = "wrong"
        elif case == "provenance-rights":
            record["rights"]["worldwide_rights_decision"] = "resolved"
        elif case == "provenance-status":
            record["status"] = "accepted"
        elif case == "provenance-extra":
            record["extra"] = None
        elif case == "provenance-bool":
            record["works"][0]["publication"] = True
        content = _canonical(record)
    else:
        name = "unresolved.jsonl"
        records = [
            json.loads(line) for line in candidate.member_bytes(name).splitlines()
        ]
        if case == "unresolved-evidence":
            records[0]["evidence"] = "stale"
        elif case == "unresolved-status":
            records[0]["status"] = "resolved"
        elif case == "unresolved-extra":
            records[0]["extra"] = None
        content = b"".join(_canonical(item) for item in records)
    resealed = _reseal_member(candidate, tmp_path / case, name, content)
    with pytest.raises(ValueError):
        _oracle(source, resealed)
