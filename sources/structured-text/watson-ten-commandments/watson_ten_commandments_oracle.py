"""Independent Watson check for source headings versus ThML navigation labels.

The generic selected-ThML checker verifies the source conversion in full. This
work-local adapter supplies its legacy synthetic-title expectation only in a
temporary validation view; the actual candidate must omit those title heads
where a direct source heading already exists.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile

from lxml import etree

from build.tei.selected_thml_oracle import (
    CLOSURE as SELECTED_THML_CLOSURE,
    _read_json,
    _validate_expected_accounting,
)
from ocd_kernel.library.acquisitions import load_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.reconstruction.contract import (
    _canonical,
    _validation_authority_bindings,
)
from ocd_kernel.reconstruction.verifier import (
    MechanicalFacts,
    verify_mechanical_facts,
)
from ocd_kernel.tei.selected_thml_check import check_selected_thml
from ocd_kernel.tei.validate import compiled_schema


WORK_ID = "watson-ten-commandments"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
PROFILE_RULE = {
    "source_attribute": "div@title",
    "disposition": "Retain as source navigation metadata in the complete source-feature ledger.",
    "when_direct_heading_exists": (
        "Map the direct source h1, h2, or h3 headings only; do not synthesize a TEI head from div@title."
    ),
    "when_no_direct_heading_exists": "Preserve div@title as a synthetic TEI head.",
    "source_derived_synthetic_heads_suppressed": 7,
}
_HEADING_TAGS = frozenset({"h1", "h2", "h3"})
IMPORT_CLOSURE = (
    "build/tei/selected_thml_oracle.py",
    *SELECTED_THML_CLOSURE,
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _closure_digest(root: Path) -> str:
    rows = [
        {
            "path": path,
            "sha256": _sha((root / path).read_bytes()),
        }
        for path in IMPORT_CLOSURE
    ]
    return _sha(_canonical(rows))


def _profile_rule(manifest) -> dict:
    profile = _read_json(manifest.authority_path("profile").read_bytes(), "selected-ThML profile")
    rule = profile.get("heading_policy", {}).get("division_title_rule")
    if rule != PROFILE_RULE:
        raise ValueError("Watson division-title rule differs from the bound profile")
    return profile


def _source_title_mismatches(source_root, selected_feature_paths: set[str]):
    """Recompute only source divisions for which the generic route adds a title head."""

    source_tree = source_root.getroottree()
    mismatches = []
    for division in source_root.iter():
        if (
            not isinstance(division.tag, str)
            or not division.tag.startswith("div")
            or not division.get("title")
        ):
            continue
        source_path = source_tree.getpath(division)
        if source_path not in selected_feature_paths:
            continue
        headings = [
            child for child in division
            if isinstance(child.tag, str) and child.tag in _HEADING_TAGS
        ]
        if not headings:
            continue
        title_text = " ".join(division.get("title").split()).casefold()
        exact_heading = any(
            " ".join("".join(heading.itertext()).split()).casefold() == title_text
            for heading in headings
        )
        if not exact_heading:
            mismatches.append((source_path, division.get("title")))
    return mismatches


def _oracle(manifest, candidate):
    """Validate the exact candidate while adapting the shared checker in memory."""

    if manifest.record.get("work_id") != WORK_ID:
        raise ValueError("Watson Ten Commandments oracle received another work")
    manifest.verify()
    acquisition = load_acquisition(manifest.authority_path("acquisition"))
    work = load_work(manifest.authority_path("work"))
    profile = _profile_rule(manifest)

    tei_bytes = candidate.member_bytes("content.tei.xml")
    tei_tree = etree.fromstring(
        tei_bytes,
        etree.XMLParser(resolve_entities=False, no_network=True, recover=False),
    )
    schema = compiled_schema()
    if not schema.validate(tei_tree):
        raise ValueError(f"selected ThML TEI schema failed: {schema.error_log}")

    accountability = _read_json(
        candidate.member_bytes("source-accountability.json"),
        "candidate source-accountability member",
    )
    features = accountability.get("features")
    if not isinstance(features, list):
        raise ValueError("candidate source-accountability features are invalid")
    feature_by_path = {}
    for feature in features:
        if not isinstance(feature, dict) or not isinstance(feature.get("source_path"), str):
            raise ValueError("candidate source-accountability feature identity is invalid")
        if feature["source_path"] in feature_by_path:
            raise ValueError("candidate source-accountability feature paths are not unique")
        feature_by_path[feature["source_path"]] = feature

    source_root = etree.fromstring(
        manifest.authority_path("retained-source").read_bytes(),
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            recover=False,
            remove_comments=False,
            remove_pis=False,
        ),
    )
    mismatches = _source_title_mismatches(source_root, set(feature_by_path))
    expected_suppressed = profile["heading_policy"]["division_title_rule"][
        "source_derived_synthetic_heads_suppressed"
    ]
    if len(mismatches) != expected_suppressed:
        raise ValueError(
            "Watson source-derived navigation-title mismatch count differs: "
            f"{len(mismatches)} != {expected_suppressed}"
        )

    validation_view = deepcopy(tei_tree)
    for source_path, title in mismatches:
        feature = feature_by_path.get(source_path)
        if feature is None or not isinstance(feature.get("tei_id"), str):
            raise ValueError(f"Watson division lacks a bound TEI identity: {source_path}")
        actual_targets = tei_tree.xpath(
            "//*[@xml:id=$value]",
            namespaces={"xml": XML_NS},
            value=feature["tei_id"],
        )
        view_targets = validation_view.xpath(
            "//*[@xml:id=$value]",
            namespaces={"xml": XML_NS},
            value=feature["tei_id"],
        )
        if len(actual_targets) != 1 or len(view_targets) != 1:
            raise ValueError(f"Watson division target is missing or ambiguous: {source_path}")
        title_head = f"{{{TEI_NS}}}head"
        if any(
            child.tag == title_head
            and child.get(f"{{{XML_NS}}}id") is None
            and child.get("type") is None
            and child.text == title
            for child in actual_targets[0]
        ):
            raise ValueError(f"candidate retains a navigation title as a body head: {source_path}")
        synthetic = etree.Element(title_head)
        synthetic.text = title
        view_targets[0].insert(0, synthetic)

    with tempfile.TemporaryDirectory(prefix="ocd-watson-ten-commandments-check-") as scratch:
        adapted_path = Path(scratch) / "validation-view.tei.xml"
        adapted_path.write_bytes(
            etree.tostring(validation_view, encoding="utf-8", xml_declaration=True)
        )
        result = check_selected_thml(
            manifest.repository_root,
            acquisition,
            work,
            adapted_path,
        )

    expected_accounting_fields = {
        "selection_sha256": result["selection_sha256"],
        "units": acquisition["source_selection"]["units"],
        "features": result["features"],
        "source_envelope": result["source_envelope"],
        "body_node_sequence": result["body_node_sequence"],
        "document_shell": result["document_shell"],
    }
    for key, expected in expected_accounting_fields.items():
        if accountability.get(key) != expected:
            raise ValueError(f"selected ThML candidate accounting differs: {key}")
    _validate_expected_accounting(manifest, result)

    expected_questions = profile.get("candidate_questions", [])
    unresolved_lines = candidate.member_bytes("unresolved.jsonl").splitlines()
    unresolved = [
        _read_json(line, "candidate unresolved item")
        for line in unresolved_lines
    ]
    if unresolved != expected_questions:
        raise ValueError("selected ThML unresolved questions differ from bound profile")

    readme = candidate.member_bytes("README.source.md").decode("utf-8")
    for child in result["document_shell"]["head_children"]:
        if child["disposition"] == "reproduced-in-source-readme" and child["text"]:
            section = f"### ThML.head/{child['tag']}\n\n{child['text']}"
            if section not in readme:
                raise ValueError("selected ThML source metadata deliverable differs")
    source_tree = etree.parse(
        str(manifest.authority_path("retained-source")),
        etree.XMLParser(resolve_entities=False, no_network=True),
    )
    for dependency in acquisition["source_selection"]["dependencies"]:
        dependency_nodes = source_tree.xpath(
            "//*[@id=$value]", value=dependency["native_id"]
        )
        if (
            len(dependency_nodes) != 1
            or "".join(dependency_nodes[0].itertext()) not in readme
        ):
            raise ValueError("selected ThML human-visible source-credit deliverable differs")

    bindings = _validation_authority_bindings(manifest)
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=_closure_digest(manifest.repository_root),
        source_sha256=result["source_sha256"],
        profile_sha256=bindings["profile_sha256"],
        package_schema_sha256=bindings["package_schema_sha256"],
        xsd_sha256=bindings["xsd_sha256"],
        policy_sha256=bindings["policy_sha256"],
        findings=(),
    )
    return verify_mechanical_facts(manifest, candidate, facts).as_record()


_oracle.oracle_id = "ocd-watson-ten-commandments-selected-thml-independent-check"
_oracle.oracle_version = "1"
