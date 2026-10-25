"""Reading layouts for explicit Metadata/Data book records; bytes stay untouched."""

from __future__ import annotations

import json
import re
from typing import Any
from xml.etree import ElementTree as ET

from cvw_app.renderer_nodes import (
    _StructureLocations, _finalize_structure, _heading_contexts, _node,
    project_visible_text, bounded_visible_text, MAX_STRUCTURE_LABEL_SCALARS,
)
from cvw_app.tei_inline import inline_node


def _label(key: str) -> str:
    return {
        "OriginStory": "Background", "SourceUrl": "Source URL",
        "SourceAttribution": "Attribution reported by the source",
        "AnswerWithProofs": "Answer with reference numbers",
        "QuestionWithProofs": "Question with reference numbers",
        "ContentWithProofs": "Text with reference numbers",
        "Proofs": "Scripture references", "ProofsWithScripture": "Quoted Scripture",
    }.get(key, re.sub(r"(?<=[a-z])(?=[A-Z])", " ", key).replace("_", " "))


def _fields(value: Any) -> list[dict[str, Any]]:
    """Keep every ancillary value accessible, including unfamiliar fields."""
    if isinstance(value, dict):
        nodes = []
        for key, child in value.items():
            nodes.append(_node("paragraph", _label(key), inline=[
                {"text": project_visible_text(_label(key)), "marks": ["bold"]},
            ]))
            nodes.extend(_fields(child))
        return nodes
    if isinstance(value, list):
        return [node for child in value for node in _fields(child)]
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return [_node("paragraph", project_visible_text(part))
            for part in re.split(r"\n\s*\n", text) if part.strip()]


def render_json_book(value: Any, *, kind: str = "json-tree",
                     native_ids: dict[str, str] | None = None) -> dict[str, Any] | None:
    if not (isinstance(value, dict) and isinstance(value.get("Metadata"), dict)
            and isinstance(value.get("Data"), (list, dict)) and value["Data"]):
        return None
    nodes: list[dict[str, Any]] = []
    outline: list[dict[str, Any]] = []
    locations = _StructureLocations()

    def heading(text: str, path: str, level: int, ancestors: tuple[str, ...], label: str | None = None) -> str:
        text = project_visible_text(text)
        location = locations.allocate((native_ids or {}).get(path, path), len(outline) + 1)
        nodes.append(_node("heading", text, level=min(level, 6), location=location))
        label = project_visible_text(label) if label is not None else text
        outline.append({"location": location, "label": bounded_visible_text(
            " › ".join((*ancestors, label)), MAX_STRUCTURE_LABEL_SCALARS, "Passage heading"), "level": min(level, 6)})
        return label

    def rows(records: list[Any], path: str, level: int, ancestors: tuple[str, ...] = ()) -> bool:
        for index, row in enumerate(records):
            row_path = f"{path}/{index}"
            if isinstance(row, str):
                nodes.extend(_fields(row))
                continue
            if not isinstance(row, dict):
                return False
            used: set[str] = set()
            if isinstance(row.get("Question"), str) and isinstance(row.get("Answer"), str):
                number = row.get("Number", "")
                title = heading(f"{number}. {row['Question']}" if number != "" else row["Question"],
                                f"{row_path}/Question", level, ancestors)
                nodes.extend(_fields(row["Answer"]))
                used.update({"Number", "Question", "Answer"})
            elif isinstance(row.get("Title"), str) and (
                isinstance(row.get("Content"), str) or isinstance(row.get("Sections"), list)
            ):
                label = f"Chapter {row['Chapter']}. {row['Title']}" if "Chapter" in row else row["Title"]
                title = heading(row["Title"], f"{row_path}/Title", level, ancestors, label)
                if "Content" in row:
                    nodes.extend(_fields(row["Content"]))
                used.update({"Title", "Content", "Article", "Chapter"})
            elif isinstance(row.get("Content"), str):
                number = row.get("Section", row.get("Number", index + 1))
                title = heading(str(number), f"{row_path}/Content", level, ancestors)
                nodes.extend(_fields(row["Content"]))
                used.update({"Section", "Number", "Content"})
            else:
                return False
            for collection in ("Sections", "SubQuestions"):
                if collection in row:
                    if not isinstance(row[collection], list) or not rows(row[collection], f"{row_path}/{collection}", level + 1, (*ancestors, title)):
                        return False
                    used.add(collection)
            extras = {key: child for key, child in row.items() if key not in used}
            if extras:
                nodes.append(_node("details", "References and source notes", children=_fields(extras)))
        return True

    if isinstance(value["Data"], dict):
        if not isinstance(value["Data"].get("Content"), str):
            return None
        nodes.extend(_fields(value["Data"]["Content"]))
        extras = {key: child for key, child in value["Data"].items() if key != "Content"}
        if extras:
            nodes.append(_node("details", "References and source notes", children=_fields(extras)))
    elif not rows(value["Data"], "/Data", 2):
        return None
    metadata = _fields(value["Metadata"])
    metadata.extend(_fields({key: child for key, child in value.items() if key not in {"Data", "Metadata"}}))
    # Keep the book text first; descriptions and all unrecognized top-level fields
    # remain available behind one disclosure rather than in the reading sequence.
    nodes.insert(0, _node("details", "About this book", children=metadata))
    return _finalize_structure(kind, nodes, outline, _heading_contexts(nodes, outline))


def semantic_json_book(root: ET.Element) -> dict[str, Any] | None:
    """Read the TEI semantic tree itself, never substitute its source-byte carrier."""
    trees = [item for item in root.iter() if item.get("type") == "json-semantic-tree"]
    if len(trees) != 1 or len(trees[0]) != 1:
        return None
    native_ids: dict[str, str] = {}

    def decode(element: ET.Element, path: str) -> Any:
        native = element.get("{http://www.w3.org/XML/1998/namespace}id")
        if native:
            native_ids[path] = native
        kind = element.get("type")
        if kind == "json-object":
            result = {}
            for member in element:
                if member.get("type") != "json-member" or len(member) != 2 or member[0].get("type") != "json-key":
                    raise ValueError("Unrecognized JSON semantic member")
                key = "".join(member[0].itertext())
                if key in result:
                    raise ValueError("Duplicate JSON semantic member")
                escaped = key.replace("~", "~0").replace("/", "~1")
                result[key] = decode(member[1], f"{path}/{escaped}")
            return result
        if kind == "json-array":
            if any(item.get("type") != "json-item" or len(item) != 1 for item in element):
                raise ValueError("Unrecognized JSON semantic array")
            return [decode(item[0], f"{path}/{index}") for index, item in enumerate(element)]
        if kind in {"json-string", "json-number", "json-boolean", "json-null"}:
            if len(element) != 1 or element[0].get("type") != "json-scalar":
                raise ValueError("Unrecognized JSON semantic scalar")
            text = "".join(element[0].itertext())
            if kind == "json-null":
                if text.strip() not in {"", "null"}:
                    raise ValueError("Invalid JSON semantic null")
                return None
            return text if kind == "json-string" else json.loads(text)
        raise ValueError("Unrecognized JSON semantic node")

    try:
        value = decode(trees[0][0], "")
    except (ValueError, json.JSONDecodeError):
        return None
    return render_json_book(value, kind="tei-reader", native_ids=native_ids)


def catechism_layout(root: ET.Element, rendered: dict[str, Any]) -> dict[str, Any] | None:
    """Group explicit TEI question units without repeating their annotated answers."""
    bodies = [item for item in root.iter() if item.tag.rsplit("}", 1)[-1] == "body"]
    if len(bodies) != 1 or len(bodies[0]) != 1 or bodies[0][0].get("type") != "catechism":
        return None
    units = list(bodies[0][0])
    if not units or any(unit.get("type") != "question-unit" for unit in units):
        return None
    original = rendered["nodes"]
    indices = {node.get("location"): index for index, node in enumerate(original) if node.get("location")}
    starts = []
    for unit in units:
        questions = [child for child in unit if child.get("ana") == "#question"]
        if len(questions) != 1:
            return None
        location = questions[0].get("{http://www.w3.org/XML/1998/namespace}id")
        index = indices.get(location, 0)
        if not index or original[index - 1]["text"] != unit.get("n"):
            return None
        starts.append(index)
    if starts[0] != 1 or starts != sorted(set(starts)):
        return None
    nodes = []
    outline = []
    for ordinal, (unit, start) in enumerate(zip(units, starts)):
        end = starts[ordinal + 1] - 1 if ordinal + 1 < len(starts) else len(original)
        question = original[start]
        title = f"{unit.get('n')}. {question['text']}"
        nodes.append(_node("heading", title, location=question["location"], level=2))
        outline.append({"location": question["location"], "label": bounded_visible_text(
            title, MAX_STRUCTURE_LABEL_SCALARS, "Question"), "level": 2})
        answers = {child.get("{http://www.w3.org/XML/1998/namespace}id")
                   for child in unit if child.get("ana") == "#answer"}
        annotated = {child.get("{http://www.w3.org/XML/1998/namespace}id")
                     for child in unit if child.get("ana") in {"#answer-with-proofs", "#question-with-proofs"}}
        lists = [child for child in unit if child.tag.rsplit("}", 1)[-1] == "list"]
        rendered_lists = [node for node in original[start + 1:end] if node["type"] == "list"]
        if len(lists) != len(rendered_lists):
            return None
        list_sources = {id(node): source for node, source in zip(rendered_lists, lists)}
        notes = []
        for node in original[start + 1:end]:
            if node.get("location"):
                label = "Answer" if node["location"] in answers else "References"
                outline.append({"location": node["location"], "label": f"{unit.get('n')}. {label}", "level": 3})
            source_list = list_sources.get(id(node))
            if source_list is not None and source_list.get("type") == "subquestions":
                if len(source_list) != len(node["children"]):
                    return None
                for source_item, item in zip(source_list, node["children"]):
                    fields = list(source_item)
                    blocks = item.get("children", [])
                    if (len(fields) != 3 or len(blocks) != 3
                            or fields[0].get("type") != "subquestion-number"
                            or fields[1].get("ana") != "#subquestion-question"
                            or fields[2].get("ana") != "#subquestion-answer"
                            or any(inline_node("paragraph", field)["text"] != block["text"]
                                   for field, block in zip(fields, blocks))):
                        return None
                    location = fields[1].get("{http://www.w3.org/XML/1998/namespace}id")
                    if not location:
                        return None
                    child_title = f"{blocks[0]['text']}. {blocks[1]['text']}"
                    child_node = inline_node("heading", fields[1], level=3, location=location)
                    child_node["text"] = child_title
                    if child_node.get("inline"):
                        child_node["inline"] = [{"text": f"{blocks[0]['text']}. ", "marks": []}, *child_node["inline"]]
                    nodes.extend([child_node, inline_node("paragraph", fields[2])])
                    outline.append({"location": location, "label": bounded_visible_text(
                        f"{title} › {child_title}", MAX_STRUCTURE_LABEL_SCALARS, "Question"), "level": 3})
            elif node.get("location") in annotated or (source_list is not None and source_list.get("type") == "proofs"):
                notes.append(node)
            else:
                nodes.append(node)
        if notes:
            nodes.append(_node("details", "References and source notes", children=notes))
    flat_locations = {node.get("location") for node in nodes}
    contexts = _heading_contexts(nodes, [item for item in outline if item["location"] in flat_locations])
    for item in outline:
        if item["location"] not in contexts:
            contexts[item["location"]] = {**rendered["contexts"][item["location"]], "label": item["label"]}
    return _finalize_structure("tei-reader", nodes, outline, contexts)
