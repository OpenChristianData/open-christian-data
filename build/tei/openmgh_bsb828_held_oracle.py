"""Independent exact-source oracle for the eight held bsb00000828 candidates.

The boundary table is deliberately separate from the producer's profile. It
checks source XML labels, child ranges, conserved nodes, exclusions, and TEI XSD.
"""

from __future__ import annotations

import ast
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import platform
import sys

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.install_accepted import _io_path


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML}}}id"
ORACLE_ID = "ocd-openmgh-bsb828-held-source-oracle"
ORACLE_VERSION = "1"
SOURCE = "raw/openmgh/bsb00000828/tei/bsb00000828.xml"
SOURCE_SHA = "698ce3c035506c19292c4af5121f133cd5bf033c11eda238d2ed2338f3c872bd"
# work ID: source division, selection, inclusive child range, source label.
EXPECTED = {
    "de-ordinando-pontifice-gallic-author": (2, "whole-div", 1, 1, "De ordinando pontifice"),
    "peter-damian-liber-gratissimus": (3, "ab-child-range", 17, 3634, "Petri Dam. Liber gratissimus"),
    "peter-damian-disceptatio-synodalis": (4, "whole-div", 1, 1, "Petri Dam. Disceptatio synodalis"),
    "manegold-against-wolfelm-of-cologne": (9, "part-range", 1, 2, "Manegoldi ad Geb. liber"),
    "manegold-to-gebhard": (9, "part-range", 3, 3, "Manegoldi ad Geb. liber"),
    "hugo-verses-against-manegold": (9, "part-range", 4, 4, "Manegoldi ad Geb. liber"),
    "dicta-cuiusdam-on-discord-between-pope-and-king": (11, "whole-div", 1, 1, "Dicta cuiusdam de discordia papae et regis"),
    "osnabruck-t-letter-presenting-wido-excerpts": (12, "ab-child-range", 1, 39, "Exc. ex Widonis Osnabrug."),
}


def _tag(name: str) -> str:
    return f"{{{TEI}}}{name}"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _same(a: etree._Element, b: etree._Element, *, top: bool = False) -> bool:
    if a.tag != b.tag or dict(a.attrib) != dict(b.attrib) or a.text != b.text:
        return False
    if not top and a.tail != b.tail:
        return False
    return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))


def _expected_body(work: etree._Element, mode: str, start: int, stop: int) -> etree._Element:
    if mode == "whole-div":
        if len(work) != 1:
            raise ValueError("whole work division child count changed")
        return work
    body = etree.Element(_tag("div"), type="work", n=work.get("n"))
    if mode == "part-range":
        if len(work) != 4 or any(x.tag != _tag("div") or x.get("type") != "part" for x in work):
            raise ValueError("four-part Manegold source envelope changed")
        for child in list(work)[start - 1:stop]:
            body.append(deepcopy(child))
    else:
        if len(work) != 1 or work[0].tag != _tag("ab"):
            raise ValueError("flat source ab envelope changed")
        source_ab = work[0]
        if (start, stop) == (17, 3634) and len(source_ab) != 3634:
            raise ValueError("Liber gratissimus source child count changed")
        if (start, stop) == (1, 39) and len(source_ab) != 668:
            raise ValueError("Osnabruck letter source child count changed")
        ab = etree.SubElement(body, _tag("ab"), attrib=source_ab.attrib)
        ab.text = source_ab.text
        for child in list(source_ab)[start - 1:stop]:
            ab.append(deepcopy(child))
    return body


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    manifest.verify()
    candidate.verify_integrity()
    profile_path = manifest.authority_path("reconstruction-profile")
    policy_path = manifest.authority_path("validation-policy")
    profile = json.loads(profile_path.read_bytes())
    policy = json.loads(policy_path.read_bytes())
    work_id = profile.get("work_id")
    if (profile.get("contract") != "ocd-openmgh-bsb828-held-profile-v1"
            or policy.get("contract") != "ocd-openmgh-bsb828-held-policy-v1"
            or work_id not in EXPECTED):
        raise ValueError("held source profile or policy invalid")
    ordinal, mode, start, stop, label = EXPECTED[work_id]
    if (profile.get("work_div_ordinal"), profile.get("selection_mode"),
            profile.get("child_start"), profile.get("child_stop"), profile.get("work_div_n")) != EXPECTED[work_id]:
        raise ValueError("held source boundary differs from independent oracle")
    source = manifest.authority_path("extracted-xml").read_bytes()
    if profile.get("source_path") != SOURCE or _sha(source) != SOURCE_SHA:
        raise ValueError("primary extracted XML identity changed")
    root = etree.fromstring(source, parser=etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    if root.tag != _tag("TEI") or root.getroottree().docinfo.doctype:
        raise ValueError("invalid source XML")
    volume = root.find(f"{_tag('text')}/{_tag('body')}/{_tag('div')}")
    if volume is None or volume.get("type") != "volume" or len(volume) != 17:
        raise ValueError("17-work volume envelope changed")
    if any(x.tag != _tag("div") or x.get("type") != "work" for x in volume):
        raise ValueError("volume contains material outside work divisions")
    work = volume[ordinal - 1]
    if work.get("n") != label:
        raise ValueError("source work division label changed")
    expected_body = _expected_body(work, mode, start, stop)
    actual = etree.fromstring(candidate.member_bytes("content.tei.xml"), parser=etree.XMLParser(resolve_entities=False, no_network=True))
    if actual.tag != _tag("TEI") or actual.get(XML_ID) != f"ocd-{work_id}-electronic-v1":
        raise ValueError("candidate TEI identity changed")
    actual_body = actual.find(f"{_tag('text')}/{_tag('body')}")
    if actual_body is None or len(actual_body) != 1 or not _same(expected_body, actual_body[0], top=True):
        raise ValueError("candidate readable body differs from selected source nodes")
    source_header = root.find(_tag("teiHeader"))
    if source_header is None:
        raise ValueError("source header absent")
    title = actual.find(f"{_tag('teiHeader')}/{_tag('fileDesc')}/{_tag('titleStmt')}/{_tag('title')}")
    if title is None or title.text != profile.get("work_title"):
        raise ValueError("candidate title differs from work identity")
    for xpath in (f"{_tag('fileDesc')}/{_tag('publicationStmt')}",
                  f"{_tag('fileDesc')}/{_tag('sourceDesc')}/{_tag('biblFull')}"):
        original = source_header.find(xpath)
        observed = actual.find(f"{_tag('teiHeader')}/{xpath}")
        if original is None or observed is None or not _same(original, observed, top=True):
            raise ValueError("source publication or bibliography omitted")
    etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd")))).assertValid(actual)
    work_record = json.loads(manifest.authority_path("work-sidecar").read_bytes())
    acquisition = json.loads(_io_path(manifest.repository_root / profile["acquisition_path"]).read_bytes())
    editions = [e for f in work_record.get("textual_forms", []) for e in f.get("editions", [])]
    if (work_record.get("work_id") != work_id or len([e for e in editions if e.get("edition_id") == profile["edition_id"]
            and profile["acquisition_id"] in e.get("acquisition_ids", [])]) != 1
            or acquisition.get("source_path") != SOURCE or acquisition.get("source_sha256") != SOURCE_SHA
            or acquisition.get("acquisition_id") != profile["acquisition_id"]):
        raise ValueError("work, edition, or acquisition identity changed")
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    counts = dict(sorted(Counter(etree.QName(n).localname for n in expected_body.iter() if isinstance(n.tag, str)).items()))
    required = {"contract": "ocd-openmgh-bsb828-held-accounting-v1", "work_id": work_id,
                "edition_id": profile["edition_id"], "acquisition_id": profile["acquisition_id"],
                "source_path": SOURCE, "source_sha256": SOURCE_SHA,
                "work_div_ordinal": ordinal, "work_div_n": label,
                "selection_mode": mode, "child_start": start, "child_stop": stop,
                "scope_note": profile["scope_note"], "element_counts": counts,
                "selected_c14n_sha256": _sha(etree.tostring(actual_body[0], method="c14n", with_comments=True))}
    if any(accounting.get(key) != value for key, value in required.items()):
        raise ValueError("candidate source accounting differs from independently selected XML")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if provenance.get("status") != "nonaccepted" or provenance.get("work_id") != work_id or provenance.get("canonical_ir_written") is not False:
        raise ValueError("candidate provenance or acceptance status changed")
    if not candidate.member_bytes("unresolved.jsonl").strip() or b"Monumenta" not in candidate.member_bytes("README.source.md"):
        raise ValueError("rights and unresolved handoff absent")
    oracle_source = Path(__file__).resolve()
    forbidden = policy.get("forbidden_oracle_imports", [])
    if any(isinstance(n, ast.ImportFrom) and n.module in forbidden
           for n in ast.walk(ast.parse(oracle_source.read_text(encoding="utf-8")))):
        raise ValueError("oracle imports the producer")
    closure = _sha(_json([{"path": rel, "sha256": _sha((manifest.repository_root / rel).read_bytes())}
                         for rel in policy["closure_inputs"]]))
    result = {
        "status": "pass", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(oracle_source.read_bytes()), "import_closure_sha256": closure,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": manifest.sha256, "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_path.read_bytes()),
        "package_schema_sha256": _sha(manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": SOURCE_SHA, "xsd_sha256": _sha(manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_path.read_bytes()), "findings": [],
    }
    result["result_sha256"] = _sha(_json(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
