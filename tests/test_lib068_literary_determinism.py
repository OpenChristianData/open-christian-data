"""Regression for deterministic LIB-068 literary block application."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

from lxml import etree


ROOT = Path(__file__).resolve().parents[1]
NS = {"t": "http://www.tei-c.org/ns/1.0"}
WORKS = (
    "newman-apologia-pro-vita-sua",
    "donne-devotions-upon-emergent-occasions",
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _render(producer, blocks, work_id: str) -> bytes:
    spec = producer._SPECS[work_id]
    profile = json.loads(
        (ROOT / "sources/structured-text" / work_id / "LIB-068.reconstruction-profile.json").read_bytes()
    )
    lines = producer._source_lines((ROOT / spec.path).read_bytes(), spec)
    root = etree.fromstring(producer._tei(work_id, spec, profile, lines))
    scope = root.xpath(
        './t:text/t:body/t:div[@type="retained-source"]', namespaces=NS
    )[0]
    assert scope.xpath('.//t:quote[@type="source-verse"]', namespaces=NS)
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def test_literary_blocks_are_byte_deterministic_across_work_orders() -> None:
    producer = _load(
        ROOT / "build/tei/lib068_source_local.py",
        "_lib068_determinism_producer",
    )
    blocks = _load(
        ROOT / "build/tei/lib068_literary_blocks.py",
        "_lib068_determinism_blocks",
    )

    orders = (WORKS, tuple(reversed(WORKS)))
    outputs: dict[str, list[bytes]] = {work_id: [] for work_id in WORKS}
    for order in orders:
        for _ in range(2):
            for work_id in order:
                outputs[work_id].append(_render(producer, blocks, work_id))

    for work_id, samples in outputs.items():
        assert samples
        assert all(sample == samples[0] for sample in samples), work_id
