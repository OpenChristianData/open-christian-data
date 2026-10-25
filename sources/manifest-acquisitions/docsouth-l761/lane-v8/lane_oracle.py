from __future__ import annotations
import hashlib, json, re
import importlib.util
from pathlib import Path
from typing import Mapping
from lxml import etree
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
_BASE_PATH = Path(__file__).with_name("docsouth_l761_l762_oracle.py")
_spec = importlib.util.spec_from_file_location("lane_v8_base_oracle", _BASE_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError("Lane v8 base oracle cannot be loaded")
_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base)
_base_oracle = _base._oracle
ORACLE_ID = "ocd-docsouth-l761-lane-v8-row-title-cardinality-oracle"
ORACLE_VERSION = "1"
def _sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def _canonical(value: object) -> bytes: return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
def _norm(node: etree._Element) -> str: return re.sub(r"\s+", " ", "".join(node.itertext())).strip()
def _one(nodes: list[etree._Element], label: str) -> etree._Element:
    if len(nodes) != 1: raise ValueError("Lane v8 expected exactly one " + label)
    return nodes[0]
def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    result = dict(_base_oracle(manifest, candidate)); findings = list(result["findings"])
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    source_bytes = manifest.authority_path("official-source-member").read_bytes()
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True)
    source = etree.fromstring(source_bytes, parser)
    tei_bytes = candidate.member_bytes("content.tei.xml")
    target = etree.fromstring(tei_bytes, parser)
    if source.tag != "TEI.2" or target.tag != "{http://www.tei-c.org/ns/1.0}TEI":
        findings.append("candidate must contain exactly one TEI root for the Lane work")
    source_titles = source.findall("teiHeader/fileDesc/titleStmt/title")
    target_titles = target.findall("{http://www.tei-c.org/ns/1.0}teiHeader/{http://www.tei-c.org/ns/1.0}fileDesc/{http://www.tei-c.org/ns/1.0}titleStmt/{http://www.tei-c.org/ns/1.0}title")
    if len(source_titles) != 1 or len(target_titles) != 1 or _norm(source_titles[0]) != _norm(target_titles[0]):
        findings.append("candidate title statement differs from the retained source title statement")
    source_print_titles = source.findall("teiHeader/fileDesc/sourceDesc/bibl/title")
    target_print_titles = target.findall("{http://www.tei-c.org/ns/1.0}teiHeader/{http://www.tei-c.org/ns/1.0}fileDesc/{http://www.tei-c.org/ns/1.0}sourceDesc/{http://www.tei-c.org/ns/1.0}bibl/{http://www.tei-c.org/ns/1.0}title")
    if len(source_print_titles) != 1 or len(target_print_titles) != 1 or _norm(source_print_titles[0]) != _norm(target_print_titles[0]):
        findings.append("candidate print bibliography title differs from the retained source title")
    if profile.get("candidate_cardinality_rule") is None or profile.get("candidate_tei_root_count") != 1:
        findings.append("Lane profile does not declare one source-attested work and one TEI")
    manifest_data = manifest.authority_path("current-manifest").read_bytes()
    worklist_data = manifest.authority_path("current-worklist").read_bytes()
    manifest_row = profile.get("manifest_row_text", "").encode("utf-8")
    worklist_row = profile.get("worklist_row_text", "").encode("utf-8")
    if (_sha(manifest_data) != profile.get("manifest_sha256") or manifest_row not in manifest_data.splitlines()
            or _sha(manifest_row) != profile.get("manifest_row_text_sha256")):
        findings.append("candidate source profile does not bind the current Manifest row")
    if (_sha(worklist_data) != profile.get("worklist_sha256") or worklist_row not in worklist_data.splitlines()
            or _sha(worklist_row) != profile.get("worklist_row_text_sha256")):
        findings.append("candidate source profile does not bind the frozen Worklist row")
    work = json.loads(manifest.authority_path("canonical-work-record").read_bytes())
    acquisition = json.loads(manifest.authority_path("canonical-acquisition-sidecar").read_bytes())
    if work.get("work_id") != "isaac-lane-autobiography" or manifest.record.get("work_id") != work.get("work_id"):
        findings.append("Lane canonical work identity does not match the candidate profile")
    if (acquisition.get("edition_id") != profile.get("edition_id") or acquisition.get("acquisition_id") != profile.get("acquisition_id")
            or acquisition.get("source_sha256") != profile.get("source_sha256")):
        findings.append("Lane source acquisition identity differs from the canonical sidecar")
    skill = manifest.authority_path("current-source-to-tei-skill").read_bytes()
    if b"One top-level titled work, one TEI" not in skill:
        findings.append("current source-to-TEI skill lacks the one-work one-TEI rule")
    result["status"] = "pass" if not findings else "fail"; result["findings"] = findings
    result["oracle_id"] = ORACLE_ID; result["oracle_version"] = ORACLE_VERSION
    result["implementation_sha256"] = _sha(Path(__file__).read_bytes())
    result["import_closure_sha256"] = _sha(Path(__file__).read_bytes() + _BASE_PATH.read_bytes())
    result.pop("result_sha256", None); result["result_sha256"] = _sha(_canonical(result))
    return result
_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
