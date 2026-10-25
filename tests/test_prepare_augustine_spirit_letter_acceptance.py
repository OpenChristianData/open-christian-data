"""Public acceptance regression for Augustine's pinned Spirit and Letter route."""

import json
import shutil
from pathlib import Path

from lxml import etree
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.acceptance import make_file_binding, validate_acceptance, write_acceptance


ROOT = Path(__file__).resolve().parents[1]
WORK = Path("library/works/augustine-spirit-and-letter")
EDITION = WORK / "forms/augustine-spirit-and-letter-english/editions/augustine-spirit-and-letter-ccel"
ACCEPTANCE = EDITION / "acceptance.json"
SOURCE = Path("raw/ccel/npnf1/npnf105.xml")
IDENTITY = {
    "work_id": "augustine-spirit-and-letter",
    "textual_form_id": "augustine-spirit-and-letter-english",
    "edition_id": "augustine-spirit-and-letter-ccel",
    "acquisition_id": "augustine-spirit-and-letter-retained",
}
SOURCE_SHA256 = "224f0e6a188ddfe691c1433c8db9a883755a9f030b71fede644d4af6c18ee63f"
NAMESPACES = {
    "tei": "http://www.tei-c.org/ns/1.0",
    "xml": "http://www.w3.org/XML/1998/namespace",
}


def _record_paths(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"path", "state_path"} and isinstance(child, str):
                yield child
            yield from _record_paths(child)
    elif isinstance(value, list):
        for child in value:
            yield from _record_paths(child)


def _copy_validation_root(tmp_path):
    stage = tmp_path / "r"
    stage.mkdir()
    try:
        stage.resolve().relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise AssertionError("acceptance mutation fixture must be outside the repository")

    record = json.loads((ROOT / ACCEPTANCE).read_text(encoding="utf-8"))
    relative_paths = {
        ACCEPTANCE,
        WORK / "work.json",
        WORK / "state.json",
        SOURCE,
        Path(record["source"]["source_path"]),
    }
    state_record = json.loads((ROOT / WORK / "state.json").read_text(encoding="utf-8"))
    for target in state_record.get("targets", []):
        for evidence in target.get("evidence", []):
            relative = Path(evidence)
            if relative.is_absolute() or ".." in relative.parts:
                raise AssertionError(f"state evidence path is not repository-relative: {evidence}")
            relative_paths.add(relative)

    for value in _record_paths(record):
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            raise AssertionError(f"acceptance evidence path is not repository-relative: {value}")
        relative_paths.add(relative)

    for relative in sorted(relative_paths, key=lambda item: item.as_posix()):
        source = ROOT / relative
        if not source.is_file():
            raise AssertionError(f"pinned acceptance evidence is missing: {relative}")
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    return stage, stage / ACCEPTANCE


@pytest.fixture
def pinned_acceptance(tmp_path):
    stage, acceptance_path = _copy_validation_root(tmp_path)
    try:
        record = validate_acceptance(acceptance_path, root=stage)
        assert record["identity"] == IDENTITY
        assert record["source"]["source_sha256"] == SOURCE_SHA256
        assert record["promotion"]["status"] == "promoted"
        assert record["decision"]["agent_assessment"]["status"] == "accepted"
        assert record["decision"]["human_decision"]["status"] == "not-recorded"
        yield stage, acceptance_path, record
    finally:
        if stage.exists():
            resolved = stage.resolve()
            if resolved.parent != tmp_path.resolve() or stage.is_symlink():
                raise AssertionError("refusing cleanup outside the exact test fixture root")
            shutil.rmtree(stage)


def _mapped_attribute(stage, record, mapping):
    acquisition_path = stage / Path(record["source"]["source_manifest"]["path"])
    acquisition = json.loads(acquisition_path.read_text(encoding="utf-8"))
    source_path = stage / Path(record["source"]["source_path"])
    source_root = etree.parse(str(source_path)).getroot()

    selected = []
    for unit in acquisition["source_selection"]["units"]:
        matches = source_root.xpath(
            "/ThML/ThML.body/div1[@id=$native_id]",
            native_id=unit["native_id"],
        )
        assert len(matches) == 1
        selected.extend(matches)

    source_elements = [
        node for unit in selected for node in unit.iter()
        if isinstance(node.tag, str)
    ]
    if mapping == "n":
        source_node = next(node for node in source_elements if node.get("n"))
        source_attribute = target_attribute = "n"
    else:
        source_node = next(
            node for node in source_elements
            if node.tag == "scripRef" and node.get("passage") and node.get("osisRef")
        )
        source_attribute = {"cRef": "passage", "target": "osisRef"}[mapping]
        target_attribute = mapping

    position = next(
        index for index, node in enumerate(source_elements, 1)
        if node.get("id") == source_node.get("id")
    )
    candidate_path = stage / Path(record["technical"]["candidate"]["path"])
    candidate_tree = etree.parse(str(candidate_path))
    matches = candidate_tree.xpath(
        "//*[@xml:id=$identifier]",
        namespaces=NAMESPACES,
        identifier=f"src-{position}",
    )
    assert len(matches) == 1
    target_node = matches[0]
    assert etree.QName(target_node).localname == ("div" if mapping == "n" else "ref")
    return source_node.get(source_attribute), target_node, target_attribute, candidate_path


def test_valid(pinned_acceptance):
    stage, _acceptance_path, record = pinned_acceptance
    for mapping in ("n", "cRef", "target"):
        source_value, target_node, target_attribute, _candidate_path = _mapped_attribute(
            stage, record, mapping
        )
        assert source_value
        assert target_node.get(target_attribute) == source_value


@pytest.mark.parametrize("mapping", ["n", "cRef", "target"])
def test_mutation(pinned_acceptance, mapping):
    stage, acceptance_path, record = pinned_acceptance
    source_value, target_node, target_attribute, candidate_path = _mapped_attribute(
        stage, record, mapping
    )
    assert source_value and target_node.get(target_attribute) == source_value

    target_node.set(target_attribute, source_value + "-mutated")
    candidate_path.write_bytes(
        etree.tostring(
            target_node.getroottree(),
            encoding="utf-8",
            xml_declaration=True,
        )
    )

    resealed = json.loads(acceptance_path.read_text(encoding="utf-8"))
    candidate_binding = make_file_binding(stage, candidate_path)
    resealed["technical"]["candidate"] = candidate_binding
    resealed["promotion"]["master"]["bytes"] = candidate_binding["bytes"]
    resealed["promotion"]["master"]["sha256"] = candidate_binding["sha256"]
    write_acceptance(acceptance_path, resealed)

    with pytest.raises(PipelineError, match="selected ThML attribute mapping differs"):
        validate_acceptance(acceptance_path, root=stage)