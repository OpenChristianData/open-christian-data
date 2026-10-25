"""Regression for the promoted WEB Classic administrative-header successor."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.validate import validate_file


ROOT = Path(os.environ.get("OCD_WEB_HEADER_TEST_ROOT", Path.cwd()))
WORK = Path("library/works/world-english-bible-classic")
EDITION = WORK / "forms/world-english-bible-classic-retained-en/editions/world-english-bible-classic-electronic"
EVIDENCE = WORK / "integration/ebible-eng-web-v3/acceptance"
PREDECESSOR_SHA = "90ca58e9c8d359a4ad62e60172c3fdd7a2e2b35100817110a7e9713e62cbd418"
SUCCESSOR_SHA = "65dfe3dea411239014e2bde8b7ee8dd7a60aa53b3c17e1cdbc5700c04bcb87ff"
ORIGINAL_DECISION_SHA = "97b6bf20c9e904e891881a610ca4ade70ca3ae53a4e76656426fe172660a2a97"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_promoted_web_classic_header_preserves_exact_text_and_decision() -> None:
    old = (ROOT / EVIDENCE / "candidate.tei.xml").read_bytes()
    master = ROOT / EDITION / "master.tei.xml"
    new = master.read_bytes()
    assert _sha(old) == PREDECESSOR_SHA
    assert _sha(new) == SUCCESSOR_SHA
    old_header, old_text = old.split(b"</teiHeader>", 1)
    new_header, new_text = new.split(b"</teiHeader>", 1)
    assert old_text == new_text
    assert b'ana="#nonaccepted-candidate"' in old_header
    assert b'ana="#nonaccepted-candidate"' not in new_header
    assert b"Nonaccepted source-to-TEI candidate" not in new_header
    assert b"world-english-bible-classic-eng-web-electronic-v2" in new_header
    change = (
        b'<change xmlns="http://www.tei-c.org/ns/1.0" '
        b'xml:id="world-english-bible-classic-eng-web-electronic-v2" when="2026-10-12">'
        b'Reconcile accepted administrative header status; retain the complete 83-member electronic text unchanged.'
        b'</change>'
    )
    restored = new.replace(change + b"</revisionDesc>", b"</revisionDesc>", 1)
    restored = restored.replace(
        b'<idno type="representation_revision">world-english-bible-classic-eng-web-electronic-v2</idno>',
        b'<idno type="representation_revision">world-english-bible-classic-eng-web-electronic-v1</idno>', 1,
    )
    restored = restored.replace(
        b'Source reconstruction accepted for the retained electronic edition; human verification, rights review, release selection, and publication remain separate.',
        b'Nonaccepted source-to-TEI candidate; human acceptance, rights review, and publication remain open.', 1,
    )
    restored = restored.replace(b' xml:lang="en">', b' xml:lang="en" ana="#nonaccepted-candidate">', 1)
    assert restored == old

    acceptance = ROOT / EDITION / "acceptance.json"
    record = json.loads(acceptance.read_text(encoding="utf-8"))
    decision = json.dumps(record["decision"], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert _sha(decision) == ORIGINAL_DECISION_SHA
    assert not validate_file(master)
    assert validate_acceptance(acceptance, root=ROOT)["promotion"]["status"] == "promoted"
