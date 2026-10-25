"""Align only the prepared Easton header scope with acquisition authority."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lxml import etree


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "library/works/eastons-bible-dictionary/integration/easton-current-v1"
ACQUISITION = ROOT / "library/works/eastons-bible-dictionary/forms/eastons-bible-dictionary-retained-electronic/editions/eastons-bible-dictionary-retained-electronic-witness/acquisitions/eastons-bible-dictionary-retained-source.json"
OLD_SHA = "d3095b72265507523bbb1d83bd8d3aecb82efb2f68ec352bfd9b3bc3128c6bba"
SOURCE_PROOF_SHA = "2fc3aa9d847c83aea71d9f2b84c2eb699a5810303fd383720c50ffe94e719bc6"
TEI = "{http://www.tei-c.org/ns/1.0}"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def save(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(raw)


def canonical(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def main() -> None:
    old = (BASE / "candidate.tei.xml").read_bytes()
    if digest(old) != OLD_SHA or digest((BASE / "source-proof.json").read_bytes()) != SOURCE_PROOF_SHA:
        raise ValueError("Easton prepared candidate or complete source proof drifted")
    acquisition = json.loads(ACQUISITION.read_text(encoding="utf-8"))
    former = json.loads((BASE / "header-renewal.json").read_text(encoding="utf-8"))["scope"]
    declared = acquisition["source_scope"]
    if declared != acquisition["retained_files"][0]["scope"] or former == declared:
        raise ValueError("Easton acquisition scope relationship differs")
    old_scope_bytes = former.encode("utf-8")
    if old.count(old_scope_bytes) != 1:
        raise ValueError("Easton prepared header scope is not unique")
    close = b"</teiHeader>"
    if old.count(close) != 1 or old.find(old_scope_bytes) > old.find(close):
        raise ValueError("Easton scope text is not confined to the TEI header")
    fresh = old.replace(old_scope_bytes, declared.encode("utf-8"), 1)
    if fresh.split(close, 1)[1] != old.split(close, 1)[1]:
        raise ValueError("Easton native body changed")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    old_tree = etree.fromstring(old, parser)
    new_tree = etree.fromstring(fresh, parser)
    if etree.tostring(old_tree.find(TEI + "text")) != etree.tostring(new_tree.find(TEI + "text")):
        raise ValueError("Easton parsed text tree changed")
    scope_nodes = new_tree.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl[@type='ocd-acceptance-binding']/tei:note[@type='source-scope']", namespaces={"tei": TEI[1:-1]})
    if len(scope_nodes) != 1 or scope_nodes[0].text != declared:
        raise ValueError("Easton acquisition scope was not precisely installed")
    new_sha = digest(fresh)
    save(BASE / "candidate-v2.tei.xml", fresh)
    accounting = json.loads((BASE / "source-accounting.json").read_text(encoding="utf-8"))
    if accounting["candidate_master_sha256"] != OLD_SHA:
        raise ValueError("Easton current source accounting refers to a different candidate")
    accounting["candidate_master_sha256"] = new_sha
    accounting["header_scope_reconciliation"] = {"former_candidate_sha256": OLD_SHA, "proof_path": "library/works/eastons-bible-dictionary/integration/easton-current-v1/source-proof.json", "source_proof_sha256": SOURCE_PROOF_SHA, "native_body_bytes_identical": True}
    save(BASE / "source-accounting-v2.json", canonical(accounting))
    proof = {"contract": "ocd-easton-acceptance-scope-header-proof-v1", "status": "pass", "former_candidate_sha256": OLD_SHA, "candidate_sha256": new_sha, "source_proof_sha256": SOURCE_PROOF_SHA, "native_body_bytes_identical": True, "parsed_text_tree_identical": True, "source_scope": declared, "source_scope_authority": ACQUISITION.relative_to(ROOT).as_posix(), "technical_limit": "Header-only correction; source comparison is inherited through byte-identical native body and the earlier complete source proof. No rights or print identity claim."}
    save(BASE / "header-scope-v2.json", canonical(proof))
    print(json.dumps({"candidate_v2_sha256": new_sha, "accounting_v2_sha256": digest((BASE / "source-accounting-v2.json").read_bytes()), "header_scope_proof_sha256": digest((BASE / "header-scope-v2.json").read_bytes())}, sort_keys=True))


if __name__ == "__main__":
    main()
