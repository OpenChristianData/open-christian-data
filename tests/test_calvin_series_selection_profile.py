from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from lxml import etree

from build.tei.calvin_series_selection import validate_title_selection_profile
from build.tei.calvin_joshua_oracle import _verify_container_members, _verify_prior_wrapper


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "sources/commentaries/calvin/calvin-commentaries-title-selection-profile.json"


def _profile() -> dict:
    return json.loads(PROFILE.read_text(encoding="utf-8"))


def _retained_candidate() -> etree._Element:
    path = ROOT / "plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/CALVIN_JOSHUA_TITLE_GROUP_CANDIDATE_V2.tei.xml"
    return etree.parse(str(path)).getroot()


def test_calvin_title_profile_binds_19_groups_to_all_45_component_rows() -> None:
    result = validate_title_selection_profile(_profile())
    assert len(result["groups"]) == 19
    assert len(result["component_rows"]) == 45
    assert len({member for group in result["groups"] for member in group["members"]}) == 45
    assert next(group for group in result["groups"] if group["title"] == "Commentary on Joshua")["members"] == [
        "calcom07.xml"
    ]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("digest", "crosswalk digest"),
        ("duplicate-row", "duplicate members"),
        ("overlap", "overlap or duplicate members"),
        ("omission", "do not partition"),
        ("selection", "selected membership differs"),
    ],
)
def test_calvin_title_profile_rejects_partition_and_selection_mutations(
    mutation: str, reason: str
) -> None:
    changed = copy.deepcopy(_profile())
    crosswalk = changed["title_hierarchy_crosswalk"]
    if mutation == "digest":
        changed["crosswalk_sha256"] = "0" * 64
    elif mutation == "duplicate-row":
        crosswalk["component_rows"][1]["member"] = crosswalk["component_rows"][0]["member"]
    elif mutation == "overlap":
        crosswalk["title_hierarchy_disposition"]["component_groups"][1]["members"].append(
            crosswalk["title_hierarchy_disposition"]["component_groups"][0]["members"][0]
        )
    elif mutation == "omission":
        crosswalk["title_hierarchy_disposition"]["component_groups"][0]["members"].pop()
        changed["groups"][0]["members"].pop()
    elif mutation == "selection":
        changed["selected_unit"]["members"] = ["calcom08.xml"]
    if mutation in {"duplicate-row", "overlap", "omission"}:
        changed["crosswalk_sha256"] = hashlib.sha256(
            json.dumps(
                crosswalk, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
    with pytest.raises(ValueError, match=reason):
        validate_title_selection_profile(changed)


def test_calvin_joshua_rejects_source_attribute_change() -> None:
    tei = _retained_candidate()
    wrapper = tei.xpath("//tei:div[@type='source-member'][@n='calcom07.xml']", namespaces={"tei":"http://www.tei-c.org/ns/1.0"})[0]
    changed = copy.deepcopy(wrapper)
    mapped = next(
        node for node in list(changed.iter())[1:]
        if isinstance(node.tag, str) and etree.QName(node).localname == "hi" and node.get("rend") == "italic"
    )
    mapped.set("rend", "bold")
    with pytest.raises(ValueError, match="source wrapper bytes differ"):
        _verify_prior_wrapper(changed, _profile(), "calcom07.xml")


def test_calvin_joshua_rejects_catalogue_link_change() -> None:
    tei = _retained_candidate()
    wrapper = tei.xpath("//tei:div[@type='source-member'][@n='commentaries.xml']", namespaces={"tei":"http://www.tei-c.org/ns/1.0"})[0]
    changed = copy.deepcopy(wrapper)
    link = next(node for node in changed.iter() if isinstance(node.tag, str) and node.get("target"))
    link.set("target", "/ccel/calvin/invented.html")
    with pytest.raises(ValueError, match="source wrapper bytes differ"):
        _verify_prior_wrapper(changed, _profile(), "commentaries.xml")


def test_calvin_joshua_rejects_omitted_misassigned_and_invented_siblings() -> None:
    tei = _retained_candidate()
    ns = {"tei":"http://www.tei-c.org/ns/1.0"}
    body = tei.xpath("/tei:TEI/tei:text/tei:body", namespaces=ns)[0]
    wrong = copy.deepcopy(body)
    wrong[0].set("n", "calcom08.xml")
    with pytest.raises(ValueError, match="omitted, misassigned, or invented"):
        _verify_container_members(wrong, ["calcom07.xml"], "Joshua title body")
    empty = etree.Element(body.tag)
    with pytest.raises(ValueError, match="omitted, misassigned, or invented"):
        _verify_container_members(empty, ["calcom07.xml"], "Joshua title body")
    front = tei.xpath("/tei:TEI/tei:text/tei:front", namespaces=ns)[0]
    invented = copy.deepcopy(front)
    etree.SubElement(invented, "{http://www.tei-c.org/ns/1.0}p").text = "Invented sibling prose"
    with pytest.raises(ValueError, match="omitted, misassigned, or invented"):
        _verify_container_members(invented, ["commentaries.xml"], "Joshua shared catalogue front")
