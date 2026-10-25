"""Exact retained-source bindings for the three missing 37c NPNF2 routes.

This module selects source roots for producers. It is not an independent
fidelity oracle and must not be imported by a checker establishing selection
independence. Existing LIB-046/047 sibling routes retain their original scope.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
from pathlib import Path

from lxml import etree


@dataclass(frozen=True)
class WorkRoot:
    work_id: str
    source_path: str
    source_bytes: int
    source_sha256: str
    root_path: tuple[str, ...]
    root_title: str


WORK_ROOTS = {
    "cyril-of-jerusalem-catechetical-lectures": WorkRoot(
        "cyril-of-jerusalem-catechetical-lectures",
        "raw/ccel/npnf2/npnf207.xml",
        4_247_548,
        "3ac73f4179c0b7d6e66e6fea04ae572e64c0e4a80e8fa38980b40366c8a13928",
        ("ii",),
        "The Catechetical Lectures of S. Cyril.",
    ),
    "gregory-of-nazianzus-select-orations": WorkRoot(
        "gregory-of-nazianzus-select-orations",
        "raw/ccel/npnf2/npnf207.xml",
        4_247_548,
        "3ac73f4179c0b7d6e66e6fea04ae572e64c0e4a80e8fa38980b40366c8a13928",
        ("iii",),
        "Select Orations of Saint Gregory Nazianzen.",
    ),
    "gregory-of-nyssa-against-eunomius": WorkRoot(
        "gregory-of-nyssa-against-eunomius",
        "raw/ccel/npnf2/npnf205.xml",
        4_225_695,
        "43e87ed232457fd2d5862f72dd2d5d84fe1e8b69f4c3eec839bad04579327bf3",
        ("viii", "viii.i"),
        "Against Eunomius.",
    ),
}


def select_work_root(tree: etree._ElementTree, binding: WorkRoot) -> etree._Element:
    """Require the work's exact source-native ancestry, identity, and title."""
    if WORK_ROOTS.get(binding.work_id) != binding:
        raise ValueError(f"unregistered work/root binding: {binding.work_id}")
    document = tree.getroot()
    bodies = document.findall("ThML.body")
    if document.tag != "ThML" or len(bodies) != 1:
        raise ValueError("expected exactly one ThML.body")
    parent = bodies[0]
    for depth, source_id in enumerate(binding.root_path, start=1):
        matches = [node for node in parent if node.get("id") == source_id]
        all_matches = [node for node in document.iter() if node.get("id") == source_id]
        if len(matches) != 1 or len(all_matches) != 1:
            raise ValueError(f"missing, displaced, or duplicate work ancestor: {source_id}")
        parent = matches[0]
        if parent.tag != f"div{depth}":
            raise ValueError(f"wrong division level at {source_id}: {parent.tag}")
    if parent.get("title") != binding.root_title:
        raise ValueError(f"retained work title mismatch: {binding.work_id}")
    return parent


def load_work_root(repository_root: Path, work_id: str) -> tuple[etree._ElementTree, etree._Element]:
    """Read once, verify the exact member, and select within that same parse tree."""
    try:
        binding = WORK_ROOTS[work_id]
    except KeyError as exc:
        raise ValueError(f"unsupported NPNF2 work: {work_id}") from exc
    content = (repository_root / binding.source_path).read_bytes()
    if len(content) != binding.source_bytes or hashlib.sha256(content).hexdigest() != binding.source_sha256:
        raise ValueError(f"retained source identity mismatch: {binding.source_path}")
    tree = etree.parse(
        io.BytesIO(content),
        etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False,
                        remove_pis=False, huge_tree=True),
    )
    return tree, select_work_root(tree, binding)
