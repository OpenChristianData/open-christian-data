"""Verify acquisition-owned ThML work boundaries against retained evidence.

This module does not import a converter or a reconstruction profile. Identity
comes from the work declaration and the source's native ID and title together.
The initial contract supports one retained ThML member, ordered complete
division subtrees, and source-credit dependencies. Selected body divisions may
be followed by selected back divisions; other selection shapes fail closed.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from lxml import etree

from ocd_kernel.lib.path_io import io_path
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ._common import PipelineError, canonical_bytes


def selection_digest(selection: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(dict(selection))).hexdigest()


def verify_source_selection(
    acquisition: Mapping[str, Any], work: Mapping[str, Any], *, root: Path
) -> dict[str, Any] | None:
    """Check already schema-validated declarations against independently read XML."""
    selection = acquisition.get("source_selection")
    if selection is None:
        return None
    label = f"source selection for {work['work_id']}"
    if selection["work_id"] != work["work_id"]:
        raise PipelineError(f"{label}: work identity differs")
    members = [m for m in acquisition["retained_files"] if m["path"] == selection["member_path"]]
    if len(members) != 1 or len(acquisition["retained_files"]) != 1:
        raise PipelineError(f"{label}: requires exactly one declared retained member")
    member = members[0]
    if "source_path" in acquisition and any(acquisition[key] != member[field] for key,field in
            [('source_path','path'),('source_bytes','bytes'),('source_sha256','sha256')]):
        raise PipelineError(f"{label}: original source binding differs from selected member")
    raw = io_path(resolve_repo_path(root, member["path"])).read_bytes()
    if len(raw) != member["bytes"] or hashlib.sha256(raw).hexdigest() != member["sha256"]:
        raise PipelineError(f"{label}: retained member binding differs")
    try:
        tree = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as exc:
        raise PipelineError(f"{label}: invalid retained XML: {exc}") from exc
    if tree.tag != "ThML" or any(isinstance(n, etree._Entity) for n in tree.iter()):
        raise PipelineError(f"{label}: requires ThML without unresolved entities")
    bodies = tree.findall("ThML.body")
    if len(bodies) != 1:
        raise PipelineError(f"{label}: requires one ThML body")
    body = bodies[0]
    edition_has_containing_source = False
    for form in work['textual_forms']:
        for edition in form['editions']:
            context = edition.get('containing_source')
            if edition['edition_id'] == acquisition['edition_id']:
                edition_has_containing_source = context is not None
                if context is not None:
                    titles = tree.xpath('/ThML/ThML.head//DC.Title[not(@sub)]/text()')
                    if titles != [context['title']] or context['locator'] != member['path']:
                        raise PipelineError(f"{label}: containing source title or locator differs")
    indexed: dict[str, list[etree._Element]] = {}
    for node in tree.iter():
        if node.get("id"):
            indexed.setdefault(node.get("id"), []).append(node)

    def exact(native_id: str) -> etree._Element:
        matches = indexed.get(native_id, [])
        if len(matches) != 1:
            raise PipelineError(f"{label}: native ID {native_id!r} missing or ambiguous")
        return matches[0]

    ids = [u["native_id"] for u in selection["units"]]
    if len(set(ids)) != len(ids):
        raise PipelineError(f"{label}: duplicate selected unit")
    selected = [exact(value) for value in ids]
    if any(n.getparent() is not body or n.tag != "div1" for n in selected):
        raise PipelineError(f"{label}: units must be complete top-level div1 subtrees")
    if selected != sorted(selected, key=lambda n: body.index(n)):
        raise PipelineError(f"{label}: selected unit order differs from source")
    selected_ids = [n.get('id') for unit in selected for n in unit.iter() if n.get('id')]
    if len(selected_ids) != len(set(selected_ids)):
        raise PipelineError(f"{label}: duplicate native ID inside selected work")
    roles = [unit["role"] for unit in selection["units"]]
    if not roles or roles[0] != "body" or any(
        role not in {"body", "back"} for role in roles
    ):
        raise PipelineError(f"{label}: requires one or more leading body units")
    if "back" in roles and any(role == "body" for role in roles[roles.index("back") :]):
        raise PipelineError(f"{label}: body units cannot follow back units")
    for unit, node in zip(selection["units"], selected):
        if node.get("title") != unit["title"]:
            raise PipelineError(f"{label}: source heading differs for {unit['native_id']}")
        reference = f"{member['path']}#{unit['native_id']}"
        if reference not in work["evidence"]:
            raise PipelineError(f"{label}: native unit lacks independent work evidence: {reference}")
    source_titles = tree.xpath('/ThML/ThML.head//DC.Title[not(@sub)]/text()')
    if not edition_has_containing_source and source_titles:
        if source_titles != [work["title"]]:
            raise PipelineError(f"{label}: source work title differs from work declaration")
    elif not edition_has_containing_source and selection["units"][0]["title"] != work["title"]:
        raise PipelineError(f"{label}: source work title differs from work declaration")
    dependency_ids = [d["native_id"] for d in selection["dependencies"]]
    if len(dependency_ids) != len(set(dependency_ids)):
        raise PipelineError(f"{label}: duplicate dependency")
    prefix = member["path"] + "#"
    declared_ids = {ref[len(prefix):] for ref in work["evidence"] if ref.startswith(prefix)}
    if declared_ids != set(ids) | set(dependency_ids):
        raise PipelineError(f"{label}: selected units and dependencies differ from work evidence")
    dependencies = []
    for dependency in selection["dependencies"]:
        node = exact(dependency["native_id"])
        if any(node is unit or unit in node.iterancestors() for unit in selected):
            raise PipelineError(f"{label}: dependency duplicates selected content")
        text = "".join(node.itertext())
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != dependency["text_sha256"]:
            raise PipelineError(f"{label}: dependency text differs: {dependency['native_id']}")
        dependencies.append(dict(dependency, text=text))
    return {"selection_sha256": selection_digest(selection), "member_sha256": member["sha256"],
            "selected_native_ids": ids, "dependencies": dependencies, "bytes_parsed": len(raw)}


def verify_selection_union(
    expected: Mapping[str, str], children: Sequence[Mapping[str, Any]]
) -> None:
    """Compare an independently declared envelope with child ownership receipts.

    Keys are native unit IDs; values are work IDs. Shared credit dependencies
    are deliberately outside this ownership partition.
    """
    if not expected:
        raise PipelineError("selection union: expected envelope is empty")
    observed: Counter[str] = Counter()
    for child in children:
        for native_id in child["selected_native_ids"]:
            if native_id not in expected or expected[native_id] != child["work_id"]:
                raise PipelineError(f"selection union: misassigned or unexpected unit {native_id}")
            observed[native_id] += 1
    if observed != Counter({native_id: 1 for native_id in expected}):
        raise PipelineError("selection union: omitted or duplicated unit")


def derive_source_carrier_inventory(
    acquisition: Mapping[str, Any], *, root: Path
) -> list[dict[str, Any]]:
    """Derive the ordered top-level carrier inventory from retained ThML."""
    label = f"source envelope for {acquisition['acquisition_id']}"
    source_path = acquisition.get("source_path")
    if source_path is None:
        selection = acquisition.get("source_selection") or {}
        source_path = selection.get("member_path")
    members = [m for m in acquisition["retained_files"] if m["path"] == source_path]
    if len(members) != 1:
        raise PipelineError(f"{label}: requires exactly one source member")
    member = members[0]
    raw = io_path(resolve_repo_path(root, member["path"])).read_bytes()
    if len(raw) != member["bytes"] or hashlib.sha256(raw).hexdigest() != member["sha256"]:
        raise PipelineError(f"{label}: retained member binding differs")
    try:
        tree = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as exc:
        raise PipelineError(f"{label}: invalid retained XML: {exc}") from exc
    body = tree.find("ThML.body")
    if tree.tag != "ThML" or body is None or len(tree.findall("ThML.body")) != 1:
        raise PipelineError(f"{label}: requires one ThML body")
    carriers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position, node in enumerate(body):
        if not isinstance(node.tag, str):
            continue
        native_id = node.get("id")
        if not native_id or native_id in seen:
            raise PipelineError(f"{label}: top-level carriers require unique IDs")
        seen.add(native_id)
        carriers.append(dict(native_id=native_id, position=position,
                             title=node.get("title"), tag=node.tag))
    if not carriers:
        raise PipelineError(f"{label}: source envelope is empty")
    return carriers


def verify_complete_source_accounting(
    acquisition: Mapping[str, Any],
    children: Sequence[Mapping[str, Any]],
    carrier_accounting: Sequence[Mapping[str, Any]],
    *,
    root: Path,
) -> list[dict[str, Any]]:
    """Verify child ownership and explicit dispositions against source truth.

    The retained XML supplies the expected carrier order.  Caller-provided
    accounting is only evidence to check against that source-derived envelope.
    """
    inventory = derive_source_carrier_inventory(acquisition, root=root)
    source_ids = [carrier["native_id"] for carrier in inventory]
    accounting_ids = [row.get("native_id") for row in carrier_accounting]
    if accounting_ids != source_ids:
        raise PipelineError("source accounting: omitted, duplicated, or reordered carrier")

    selected: list[tuple[str, str]] = []
    for child in children:
        work_id = child.get("work_id")
        if not isinstance(work_id, str) or not work_id:
            raise PipelineError("source accounting: child work identity is missing")
        for native_id in child.get("selected_native_ids", []):
            selected.append((native_id, work_id))
    selected_ids = [native_id for native_id, _ in selected]
    if selected_ids != [row["native_id"] for row in carrier_accounting
                        if row.get("disposition") == "selected"]:
        raise PipelineError("source accounting: selected carriers are reordered or incomplete")
    if len(selected_ids) != len(set(selected_ids)):
        raise PipelineError("source accounting: duplicate selected carrier")

    by_id = {native_id: work_id for native_id, work_id in selected}
    result: list[dict[str, Any]] = []
    for row in carrier_accounting:
        native_id = row["native_id"]
        disposition = row.get("disposition")
        if not isinstance(disposition, str) or not disposition:
            raise PipelineError(f"source accounting: disposition missing for {native_id}")
        if disposition == "selected":
            if row.get("work_id") != by_id.get(native_id):
                raise PipelineError(f"source accounting: misassigned carrier {native_id}")
        elif native_id in by_id:
            raise PipelineError(f"source accounting: selected carrier {native_id} has non-selected disposition")
        result.append(dict(row, position=inventory[source_ids.index(native_id)]["position"]))
    return result
