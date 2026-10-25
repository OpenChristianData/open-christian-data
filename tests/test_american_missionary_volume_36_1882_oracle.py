from __future__ import annotations

import copy
from pathlib import Path
import shutil

import pytest
from lxml import etree

from build.tei.american_missionary_volume_36_1882_oracle import ORACLE_ID, check_candidate
from build.tei.american_missionary_volume_36_1882_to_tei import convert


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "sources" / "structured-text" / "american-missionary-volume-36-1882" / "config.json"
RAW = Path(r"D:\Library\Open Christian Data\raw\clean-ready-acquisition-to-tei\master-5\35\american-missionary-volume-36-1882")
VOLUME_37_CANDIDATE = Path(r"D:\Library\Open Christian Data\reports\clean-ready-acquisition-to-tei\master-5\35\american-missionary-volume-37-1883\candidate\american-missionary-volume-37-1883.tei.xml")
ORACLE = ROOT / "build" / "tei" / "american_missionary_volume_36_1882_oracle.py"
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
NS = {"tei": TEI, "xml": XML}


@pytest.fixture(scope="module")
def candidate(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("amv36-oracle")
    report = root / "report"
    path = report / "candidate.xml"
    convert(CONFIG, RAW, path, report)
    return path


def _write_mutation(source: Path, destination: Path, mutate) -> Path:
    tree = etree.parse(str(source))
    mutate(tree.getroot())
    tree.write(str(destination), encoding="UTF-8", xml_declaration=True, pretty_print=True)
    return destination


def _carrier(root: etree._Element, identity: str) -> etree._Element:
    nodes = root.xpath("//*[@xml:id=$identity]", namespaces=NS, identity=identity)
    assert len(nodes) == 1
    return nodes[0]


def test_checker_has_no_producer_import_or_binding() -> None:
    source = ORACLE.read_text(encoding="utf-8")
    assert "american_missionary_volume_36_1882_to_tei" not in source
    assert "BuildState" not in source


@pytest.mark.requires_local_artifacts
def test_independent_checker_accepts_corrected_candidate(candidate: Path) -> None:
    report = check_candidate(CONFIG, RAW, candidate)
    assert report["status"] == "pass"
    assert report["oracle_id"] == ORACLE_ID
    assert report["source_carrier_count"] == report["candidate_carrier_count"] == 18_242
    assert report["source_carrier_stream_sha256"] == report["candidate_carrier_stream_sha256"] == "2b1f2ae0371e03eb46ebe0f3f4db7af5acb2218a1117a768c68df2a8b418ca66"
    assert report["source_fragment_kind_counts"] == {"element-text": 22_614, "child-tail": 2_289}
    assert report["source_feature_disposition_counts"]["represented-as-page-break-when-inline"] == 393
    assert report["source_feature_disposition_counts"]["represented-as-table"] == 472
    assert report["source_feature_disposition_counts"]["represented-as-cell"] == 14_163
    assert report["candidate_tag_counts"]["table"] == 472
    assert report["candidate_tag_counts"]["row"] == 7_420
    assert report["candidate_tag_counts"]["cell"] == 14_163
    assert report["candidate_tag_counts"]["graphic"] == 136
    assert report["candidate_tag_counts"]["milestone"] == 814
    assert report["candidate_carrier_inventory"][1143]["text"].startswith("There will be many important events")
    assert report["candidate_carrier_inventory"][1144]["text"] == "Witness"


@pytest.mark.requires_local_artifacts
def test_independent_checker_rejects_carrier_deletion(candidate: Path, tmp_path: Path) -> None:
    def delete(root: etree._Element) -> None:
        node = _carrier(root, "amv36-src-B01144")
        parent = node.getparent()
        assert parent is not None
        parent.remove(node)

    mutated = _write_mutation(candidate, tmp_path / "deleted.xml", delete)
    with pytest.raises(ValueError, match="carrier omission or duplication"):
        check_candidate(CONFIG, RAW, mutated)


@pytest.mark.requires_local_artifacts
def test_independent_checker_rejects_carrier_duplication(candidate: Path, tmp_path: Path) -> None:
    def duplicate(root: etree._Element) -> None:
        node = _carrier(root, "amv36-src-B01144")
        parent = node.getparent()
        assert parent is not None
        duplicate_node = copy.deepcopy(node)
        duplicate_node.set(f"{{{XML}}}id", "amv36-src-B18243")
        duplicate_node.set("n", "18243")
        parent.insert(parent.index(node) + 1, duplicate_node)

    mutated = _write_mutation(candidate, tmp_path / "duplicated.xml", duplicate)
    with pytest.raises(ValueError, match="carrier omission or duplication"):
        check_candidate(CONFIG, RAW, mutated)


@pytest.mark.requires_local_artifacts
def test_independent_checker_rejects_carrier_reordering(candidate: Path, tmp_path: Path) -> None:
    def reorder(root: etree._Element) -> None:
        first = _carrier(root, "amv36-src-B01144")
        second = _carrier(root, "amv36-src-B01145")
        first_wrapper = first.getparent()
        second_wrapper = second.getparent()
        assert first_wrapper is not None and second_wrapper is not None
        parent = first_wrapper.getparent()
        assert parent is second_wrapper.getparent() and parent is not None
        index = parent.index(first_wrapper)
        parent.remove(first_wrapper)
        parent.remove(second_wrapper)
        parent.insert(index, second_wrapper)
        parent.insert(index + 1, first_wrapper)

    mutated = _write_mutation(candidate, tmp_path / "reordered.xml", reorder)
    with pytest.raises(ValueError, match="carrier stream drift"):
        check_candidate(CONFIG, RAW, mutated)


@pytest.mark.requires_local_artifacts
def test_independent_checker_rejects_carrier_misattachment(candidate: Path, tmp_path: Path) -> None:
    def misattach(root: etree._Element) -> None:
        node = _carrier(root, "amv36-src-B01144")
        wrapper = node.getparent()
        assert wrapper is not None
        issue_two = root.xpath("//tei:div[@type='issue'][@n='2']", namespaces=NS)[0]
        wrapper.getparent().remove(wrapper)
        issue_two.insert(1, wrapper)

    mutated = _write_mutation(candidate, tmp_path / "misattached.xml", misattach)
    with pytest.raises(ValueError, match="carrier stream drift"):
        check_candidate(CONFIG, RAW, mutated)


@pytest.mark.requires_local_artifacts
def test_independent_checker_rejects_wrong_source_candidate(candidate: Path, tmp_path: Path) -> None:
    wrong_source = tmp_path / "volume-37.xml"
    shutil.copyfile(VOLUME_37_CANDIDATE, wrong_source)
    with pytest.raises(ValueError, match="header identity drift"):
        check_candidate(CONFIG, RAW, wrong_source)


@pytest.mark.requires_local_artifacts
def test_independent_checker_rejects_unsupported_candidate_feature(candidate: Path, tmp_path: Path) -> None:
    def unsupported(root: etree._Element) -> None:
        issue = root.xpath("//tei:div[@type='issue'][@n='1']", namespaces=NS)[0]
        issue.append(etree.Element(f"{{{TEI}}}foreign"))

    mutated = _write_mutation(candidate, tmp_path / "unsupported.xml", unsupported)
    with pytest.raises(ValueError, match="schema failure|unsupported"):
        check_candidate(CONFIG, RAW, mutated)


@pytest.mark.requires_local_artifacts
def test_independent_checker_rejects_prior_circular_candidate(candidate: Path) -> None:
    prior = Path(r"D:\Library\Open Christian Data\reports\clean-ready-acquisition-to-tei\master-5\35\american-missionary-volume-36-1882\candidate\american-missionary-volume-36-1882.tei.xml")
    with pytest.raises(ValueError, match="carrier omission or duplication"):
        check_candidate(CONFIG, RAW, prior)
