"""Use source-attested A75019 glyph literals without rewriting its TEI.

This process-local context supports exactly the pinned complete electronic
witness. Both the maintained producer and its independent observer use the
same source-bound policy; their original schema paths are restored on exit.
Run one selected work in this context, with no concurrent projection threads.
"""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import patch

from lxml import etree

from ocd_kernel.lib.path_io import io_path
from ocd_kernel.projection import native_content, native_content_check


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "raw/tcp/high-range/A75019/A75019.xml"
SOURCE_SHA256 = "800bae82b44a6c45ef3d49af85e1e0dd046ace2741055a078acc9be808d69aec"
MASTER_SHA256 = "281fa46fc262fa1a88aee15e35c23f70e1c97f6ad60ef93367034c674f807f38"
BASE = ROOT / "schemas/v2/native-content.schema.json"
BASE_SHA256 = "685abd36b52f8de31c3d702eedfc93b7c660aaaad2cce2bcaad6a3c6fd825042"
POLICY = ROOT / "sources/tcp-private-devotions-a75019/native-content-a75019-literal-glyph.schema.json"
POLICY_SHA256 = "17d72a31839676dac379b9212ad5165f3d0937a3d739cae244f61be677db5908"
NS = "{http://www.tei-c.org/ns/1.0}"


def _pinned(path: Path, expected: str) -> bytes:
    raw = io_path(path).read_bytes()
    if sha256(raw).hexdigest() != expected:
        raise ValueError(f"A75019 consumer binding differs: {path}")
    return raw


@contextmanager
def a75019_literal_glyph_policy(master: Path):
    """Bind unchanged complete text and add char:V's source-observed U+01B2 literal."""
    source = _pinned(SOURCE, SOURCE_SHA256)
    bound = _pinned(master, MASTER_SHA256)
    base_raw = _pinned(BASE, BASE_SHA256)
    policy_raw = _pinned(POLICY, POLICY_SHA256)
    expected = deepcopy(json.loads(base_raw))
    declared = expected["x-ocd-native-content"]["source_declared_glyphs"]
    if "char:V" in declared:
        raise ValueError("A75019 base policy already defines char:V")
    declared["char:V"] = "\u01b2"
    if json.loads(policy_raw) != expected:
        raise ValueError("A75019 policy has an undeclared semantic change")
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    original = etree.fromstring(source, parser)
    current = etree.fromstring(bound, parser)
    original_text, current_text = original.find(NS + "text"), current.find(NS + "text")
    if (original_text is None or current_text is None
            or etree.tostring(original_text, method="c14n")
            != etree.tostring(current_text, method="c14n")):
        raise ValueError("A75019 complete source text differs from bound master")
    glyphs = [node for node in original_text.iter(NS + "g")
              if node.get("ref") == "char:V"]
    if (len(glyphs) != 7 or any(dict(node.attrib) != {"ref": "char:V"}
                              or node.text != "\u01b2" or len(node) for node in glyphs)):
        raise ValueError("A75019 seven source-observed glyphs differ")
    if native_content.SCHEMA != BASE or native_content_check.SCHEMA != BASE:
        raise ValueError("A75019 consumer context requires unmodified base consumers")
    try:
        with patch.object(native_content, "SCHEMA", POLICY), patch.object(native_content_check, "SCHEMA", POLICY):
            yield {
                "contract": "ocd-a75019-source-literal-consumer-context-v1",
                "source_sha256": SOURCE_SHA256,
                "master_sha256": MASTER_SHA256,
                "base_schema_sha256": BASE_SHA256,
                "consumer_schema_sha256": POLICY_SHA256,
                "literal_glyphs": 7,
                "complete_source_text_unchanged": True,
                "shared_schema_unchanged": True,
            }
    finally:
        if native_content.SCHEMA != BASE or native_content_check.SCHEMA != BASE:
            raise ValueError("A75019 consumer context did not restore base consumers")
        for path, digest in ((SOURCE, SOURCE_SHA256), (master, MASTER_SHA256),
                             (BASE, BASE_SHA256), (POLICY, POLICY_SHA256)):
            _pinned(path, digest)
