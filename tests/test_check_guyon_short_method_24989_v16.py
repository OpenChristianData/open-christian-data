"""Exercise exact frozen challenge functions without rerunning the dated full matrix."""

import ast
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree
import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def challenge():
    path = ROOT / "build/tools/check_guyon_short_method_24989_v16.py"
    receipt = json.loads((ROOT / "plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/GUYON_PG24989_V16_REPLAY_AND_SEMANTIC_CHALLENGES_20261003.json").read_bytes())
    raw = path.read_bytes()
    assert receipt["status"] == "pass"
    assert receipt["challenge_tool_path"] == path.relative_to(ROOT).as_posix()
    assert sha256(raw).hexdigest() == receipt["challenge_tool_sha256"]
    tree = ast.parse(raw)
    declarations = [node for node in tree.body if
        (isinstance(node, ast.FunctionDef) and node.name in {"one", "body_text", "footnote_attachment"}) or
        (isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "NS" for target in node.targets))]
    scope = {}
    exec(compile(ast.Module(body=declarations, type_ignores=[]), str(path), "exec"), scope)
    return scope


def test_frozen_challenges_change_selected_text_and_note_attachment(challenge):
    tree = etree.fromstring(b'''<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>
        <p>Retained words</p><ref xml:id="fna.1" target="#fn.1">1</ref>
        <note xml:id="fn.1">First note</note><note xml:id="fn.2">Second note</note>
    </body></text></TEI>''')
    challenge["body_text"](tree, {}, {})
    assert tree.find(".//{*}p").text == "Retained words MUTATED"
    challenge["footnote_attachment"](tree, {}, {})
    assert tree.find(".//{*}ref").get("target") == "#fn.2"
    assert [node.text for node in tree.findall(".//{*}note")] == ["First note", "Second note"]


def test_frozen_note_challenge_rejects_unexpected_source_preimage(challenge):
    tree = etree.fromstring(b'''<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>
        <ref xml:id="fna.1" target="#unexpected">1</ref><note xml:id="fn.2">Retained</note>
    </body></text></TEI>''')
    with pytest.raises(AssertionError):
        challenge["footnote_attachment"](tree, {}, {})
    assert tree.find(".//{*}ref").get("target") == "#unexpected"
