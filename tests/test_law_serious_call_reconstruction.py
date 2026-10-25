from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.law_serious_call_mutation_check import run_mutation_challenge
from build.tools.reconstruct_candidate import run as reconstruct_candidate


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST = 'tests/fixtures/reconstruction-runtime/law-serious-call.source-manifest.json'
SOURCE_SHA256 = "edc2bf6021f36bb7e42e1feb819c37492f920595e05ed31e22d52e7caa12c2bd"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"


@pytest.fixture(scope="module")
def law_candidate(tmp_path_factory: pytest.TempPathFactory) -> Path:
    destination = tmp_path_factory.mktemp("law-serious-call") / "handoff"
    result = reconstruct_candidate(
        manifest=SOURCE_MANIFEST,
        destination=str(destination),
        repository_root=str(ROOT),
    )
    assert result["status"] == "pass"
    return destination / "package"


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_candidate_records_exact_absent_navigation_edges_and_preserves_resolved_links(
    law_candidate: Path,
) -> None:
    profile = json.loads(
        (ROOT / "sources/structured-text/law-serious-call/source-profile.json").read_text(
            encoding="utf-8"
        )
    )
    policy = json.loads(
        (ROOT / "sources/structured-text/law-serious-call/independent-validation-policy.json").read_text(
            encoding="utf-8"
        )
    )
    assert profile["source_navigation"]["edge_count"] == 62
    assert profile["source_navigation"]["resolved_edge_count"] == 60
    assert [row["id"] for row in profile["source_navigation"]["unresolved_edges"]] == [
        "navigation-prev-toc-title-page",
        "navigation-next-toc-acknowledgements",
    ]
    assert policy["source_navigation"]["permitted_unresolved_edge_ids"] == [
        "navigation-prev-toc-title-page",
        "navigation-next-toc-acknowledgements",
    ]

    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    root = etree.parse(str(law_candidate / "content.tei.xml"), parser).getroot()
    ids = {
        node.get(f"{{{XML_NS}}}id")
        for node in root.iter()
        if node.get(f"{{{XML_NS}}}id")
    }
    assert "toc" not in ids
    assert len(root.findall(f".//{{{TEI_NS}}}head[@type='ThML-h3']")) == 3
    source_heading_blocks = root.findall(
        f".//{{{TEI_NS}}}ab[@type='source-heading'][@subtype='h3']"
    )
    assert len(source_heading_blocks) == 24
    assert not root.findall(f".//{{{TEI_NS}}}ab[@type='ThML-h3']")
    source = etree.parse(str(ROOT / "raw/ccel/law/serious_call.xml"), parser)
    source_heading_ids = [
        element.get("id") for element in source.findall(".//ThML.body//h3")
    ]
    candidate_heading_ids = [
        element.get(f"{{{XML_NS}}}id")
        for element in root.iter()
        if element.tag in {f"{{{TEI_NS}}}head", f"{{{TEI_NS}}}ab"}
        and element.get("type") in {"ThML-h3", "source-heading"}
        and (element.get("type") != "source-heading" or element.get("subtype") == "h3")
    ]
    assert [value for value in candidate_heading_ids if value] == source_heading_ids
    assert len(root.findall(f"./{{{TEI_NS}}}text//{{{TEI_NS}}}note")) == 46

    notes = root.find(f"{{{TEI_NS}}}teiHeader/{{{TEI_NS}}}fileDesc/{{{TEI_NS}}}notesStmt")
    assert notes is not None
    exceptions = notes.findall(f"{{{TEI_NS}}}note[@type='unresolved-source-navigation-edge']")
    assert len(exceptions) == 2
    expected = (
        (
            "navigation-prev-toc-title-page",
            "/ThML[1]/ThML.body[1]/div1[1]",
            "prev",
            "i",
        ),
        (
            "navigation-next-toc-acknowledgements",
            "/ThML[1]/ThML.body[1]/div1[30]",
            "next",
            "xxx",
        ),
    )
    for note, (record_id, selector, direction, carrier_id) in zip(exceptions, expected, strict=True):
        assert note.get(f"{{{XML_NS}}}id") == f"law-serious-call-{record_id}"
        assert note.get("corresp") == f"#{carrier_id}"
        assert note.findtext(f".//{{{TEI_NS}}}seg[@type='source-sha256']") == SOURCE_SHA256
        assert note.findtext(f".//{{{TEI_NS}}}seg[@type='source-selector']") == selector
        assert note.findtext(f".//{{{TEI_NS}}}seg[@type='source-direction']") == direction
        assert note.findtext(f".//{{{TEI_NS}}}seg[@type='source-raw-target']") == "toc"
        assert note.findtext(f".//{{{TEI_NS}}}seg[@type='source-carrier-id']") == carrier_id
        assert note.findtext(f".//{{{TEI_NS}}}seg[@type='source-disposition']") == "source-target-absent"

    unresolved = _jsonl(law_candidate / "unresolved.jsonl")
    unresolved_navigation = [
        item for item in unresolved
        if item.get("category") == "source-navigation-edge"
    ]
    assert [item["id"] for item in unresolved_navigation] == [row[0] for row in expected]
    assert all(item["source_sha256"] == SOURCE_SHA256 for item in unresolved_navigation)
    assert all(item["disposition"] == "source-target-absent" for item in unresolved_navigation)
    assert all(item["owner"] == "source-evidence-maintainer" for item in unresolved_navigation)
    assert all(item.get("reopening_condition") for item in unresolved_navigation)

    accountability = json.loads(
        (law_candidate / "source-accountability.json").read_text(encoding="utf-8")
    )
    assert accountability["source_navigation"] == {
        "edge_count": 62,
        "resolved_edge_count": 60,
        "unresolved_edges": [
            {
                "id": row[0],
                "source_sha256": SOURCE_SHA256,
                "selector": row[1],
                "direction": row[2],
                "raw_target": "toc",
                "carrier_id": row[3],
                "disposition": "source-target-absent",
                "owner": "source-evidence-maintainer",
                "reopening_condition": unresolved_navigation[index]["reopening_condition"],
            }
            for index, row in enumerate(expected)
        ],
    }

    resolved_edges = [
        (node, direction, node.get(direction))
        for node in root.iter()
        for direction in ("prev", "next")
        if node.get(direction) is not None
    ]
    assert len(resolved_edges) == 60
    assert all(target.startswith("#") and target[1:] in ids for _, _, target in resolved_edges)
    local_refs = [
        node for node in root.iter(f"{{{TEI_NS}}}ref")
        if (node.get("target") or "").startswith("#")
    ]
    assert len(local_refs) == 137
    assert all(node.get("target")[1:] in ids for node in local_refs)


def test_resealed_candidate_mutations_reject_navigation_exception_changes(
    law_candidate: Path,
) -> None:
    result = run_mutation_challenge(
        repository_root=ROOT,
        source_manifest_path=ROOT / SOURCE_MANIFEST,
        candidate_path=law_candidate,
    )
    assert result["status"] == "pass"
    outcomes = {
        item["case"]: item
        for item in result["mutations"]
    }
    required_cases = {
        "delete-source-navigation-note",
        "change-source-navigation-note-direction",
        "change-source-navigation-note-value",
        "change-source-navigation-note-carrier",
        "false-resolve-to-generated-navigation-title",
        "invent-source-navigation-target",
        "alter-navigation-accountability",
        "delete-source-navigation-unresolved-record",
        "change-source-navigation-unresolved-direction",
        "change-source-navigation-unresolved-value",
        "change-source-navigation-unresolved-carrier",
        "falsely-resolve-source-navigation-unresolved-record",
    }
    assert required_cases <= outcomes.keys()
    assert all(outcomes[name]["result"] == "rejected" for name in required_cases)


def test_candidate_reproduces_in_a_fresh_process(
    law_candidate: Path,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "fresh-process-handoff"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "build.tools.reconstruct_candidate",
            "--manifest",
            SOURCE_MANIFEST,
            "--destination",
            str(destination),
            "--repository-root",
            str(ROOT),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["status"] == "pass"
    reproduced = destination / "package"
    expected_files = {path.name for path in law_candidate.iterdir()}
    assert {path.name for path in reproduced.iterdir()} == expected_files
    assert {
        name: (law_candidate / name).read_bytes()
        for name in expected_files
    } == {
        name: (reproduced / name).read_bytes()
        for name in expected_files
    }
