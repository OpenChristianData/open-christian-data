"""Work-local mappings for the retained Watson Beatitudes ThML envelope."""

from __future__ import annotations

from collections import Counter
from types import FunctionType
import json
from typing import Mapping

from lxml import etree

from build.tei import selected_thml as _selected_thml


WORK_ID = "watson-beatitudes"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
_CUSTOM_TAGS = {"scripCom": "milestone", "ol": "list"}


def _read_json(path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not readable UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _isolated_selected_thml_converter():
    """Use the shared converter with a private tag map, never mutating its module."""

    namespace = vars(_selected_thml).copy()
    namespace["TAGS"] = {**_selected_thml.TAGS, **_CUSTOM_TAGS}
    return FunctionType(
        _selected_thml._convert.__code__,
        namespace,
        name="_convert",
        argdefs=_selected_thml._convert.__defaults__,
        closure=_selected_thml._convert.__closure__,
    )


def _convert(source_manifest) -> Mapping[str, bytes]:
    """Produce the five in-memory members for this source-bound route."""

    if source_manifest.record.get("work_id") != WORK_ID:
        raise ValueError("Watson Beatitudes converter received another work")
    source_manifest.verify()
    profile = _read_json(source_manifest.authority_path("profile"), "route profile")
    custom_rules = profile.get("custom_element_rules")
    if not isinstance(custom_rules, dict) or set(custom_rules) != set(_CUSTOM_TAGS):
        raise ValueError("Watson Beatitudes custom element rules differ from the route")

    # The generic converter remains untouched. A copied globals dictionary gives
    # this work a narrow local extension for its two observed source-native tags.
    produced = dict(_isolated_selected_thml_converter()(source_manifest))
    account = json.loads(produced["source-accountability.json"].decode("utf-8"))
    features = account.get("features")
    if not isinstance(features, list):
        raise ValueError("selected-ThML producer returned invalid source features")
    counts = Counter(row.get("source_tag") for row in features if isinstance(row, dict))
    tei_root = etree.fromstring(
        produced["content.tei.xml"],
        etree.XMLParser(resolve_entities=False, no_network=True, recover=False),
    )
    for source_tag, rule in custom_rules.items():
        if not isinstance(rule, dict) or counts[source_tag] != rule.get("expected_occurrences"):
            raise ValueError(f"Watson Beatitudes {source_tag} occurrence count differs")
        for feature in features:
            if feature.get("source_tag") != source_tag:
                continue
            targets = tei_root.xpath(
                "//*[@xml:id=$value]",
                namespaces={"xml": XML_NS},
                value=feature["tei_id"],
            )
            if len(targets) != 1:
                raise ValueError(f"Watson Beatitudes {source_tag} TEI target is missing or ambiguous")
            target = targets[0]
            if target.tag != f"{{{TEI_NS}}}{rule['tei_element']}":
                raise ValueError(f"Watson Beatitudes {source_tag} TEI element differs")
            source_attributes = feature["attributes"]
            if source_tag == "scripCom":
                if len(target) or target.text is not None:
                    raise ValueError("Watson Beatitudes scripCom marker must be empty")
                target.set("unit", rule["tei_unit"])
                target.set("type", source_attributes[rule["tei_type_from_source_attribute"]])
                target.set("n", source_attributes[rule["passage_from_source_attribute"]])
                target.set("corresp", source_attributes[rule["osis_reference_from_source_attribute"]])
            elif source_tag == "ol":
                target.set("type", rule["tei_type"])
            else:  # pragma: no cover - guarded by the exact rule-key check
                raise ValueError(f"No Watson Beatitudes mapping for {source_tag}")

    produced["content.tei.xml"] = etree.tostring(
        tei_root, encoding="utf-8", xml_declaration=True
    )
    return produced


_convert.converter_id = "ocd-watson-beatitudes-selected-thml-route"
_convert.converter_version = "1"
