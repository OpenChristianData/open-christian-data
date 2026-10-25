"""Read-only, bounded candidate-binding inventory for selected ThML works."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from lxml import etree

from ._common import PipelineError
from .source_selection import verify_complete_source_accounting, verify_source_selection


def report_selection_affectedness(
    *,
    root: Path,
    children: Sequence[Mapping[str, Any]],
    carrier_accounting: Sequence[Mapping[str, Any]],
    outputs: Mapping[str, Sequence[Path]],
) -> dict[str, Any]:
    """Compare explicit candidate paths to current verified acquisition bindings.

    Children contain acquisition and work declarations for one retained member.
    This inventories only supplied outputs, never establishes fidelity, human
    observation applicability, acceptance, or a complete downstream census.
    Missing/ambiguous candidate bindings remain unknown and require checks.
    """
    if not children:
        raise PipelineError("affectedness: empty child inventory")
    verified = []
    identities = set()
    member_binding = None
    dependencies: dict[str, dict[str, Any]] = {}
    for child in children:
        acquisition, work = child["acquisition"], child["work"]
        work_id = work["work_id"]
        if work_id in identities:
            raise PipelineError("affectedness: duplicate child work")
        identities.add(work_id)
        selection = verify_source_selection(acquisition, work, root=root)
        if selection is None:
            raise PipelineError("affectedness: missing source selection")
        binding = (acquisition["source_selection"]["member_path"], selection["member_sha256"])
        if member_binding is not None and binding != member_binding:
            raise PipelineError("affectedness: children must bind the same retained member")
        member_binding = binding
        verified.append(dict(selection, work_id=work_id))
        for dependency in selection["dependencies"]:
            native_id = dependency["native_id"]
            row = dependencies.setdefault(native_id, {
                "native_id": native_id,
                "text_sha256": dependency["text_sha256"],
                "dependents": [],
            })
            row["dependents"].append({"work_id": work_id, "purpose": dependency["purpose"]})
    if set(outputs) - identities:
        raise PipelineError("affectedness: output work outside bounded child inventory")
    coverage = verify_complete_source_accounting(
        children[0]["acquisition"], verified, carrier_accounting, root=root
    )
    results = []
    seen_paths = set()
    for child, selection in zip(children, verified):
        work_id = selection["work_id"]
        paths = outputs.get(work_id, ())
        if not paths:
            results.append({"work_id": work_id, "path": None, "status": "unknown",
                            "reasons": ["no supplied output"], "requires_check": True})
        for path in paths:
            path = Path(path).resolve()
            if path in seen_paths:
                raise PipelineError("affectedness: duplicate output path")
            seen_paths.add(path)
            row = {"work_id": work_id, "path": str(path), "status": "unknown",
                   "reasons": [], "requires_check": True}
            results.append(row)
            try:
                raw = path.read_bytes()
            except FileNotFoundError:
                row["reasons"] = ["output missing"]
                continue
            row["sha256"] = hashlib.sha256(raw).hexdigest()
            try:
                tree = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))
            except etree.XMLSyntaxError:
                row["reasons"] = ["invalid candidate XML"]
                continue
            expected = {"work_id": work_id,
                        "acquisition_id": child["acquisition"]["acquisition_id"],
                        "source_sha256": selection["member_sha256"],
                        "source_selection_sha256": selection["selection_sha256"]}
            observed = {}
            for key in expected:
                nodes = tree.xpath(
                    '/t:TEI/t:teiHeader//t:bibl/t:idno[@type=$key]',
                    namespaces={"t": "http://www.tei-c.org/ns/1.0"}, key=key,
                )
                if len(nodes) != 1 or len(nodes[0]) or not nodes[0].text:
                    row["reasons"].append(f"missing or ambiguous {key}")
                else:
                    observed[key] = nodes[0].text
            if row["reasons"]:
                continue
            row["reasons"] = [f"{key} differs" for key in expected if observed[key] != expected[key]]
            row["status"] = "stale" if row["reasons"] else "binding-current"
    return {"scope": "supplied candidate bindings only", "member_path": member_binding[0],
            "member_sha256": member_binding[1], "coverage": coverage,
            "shared_dependencies": list(dependencies.values()), "outputs": results}
