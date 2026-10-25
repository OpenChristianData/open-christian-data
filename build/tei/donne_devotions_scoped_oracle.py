"""Source-derived scoped checks plus the independent retained literary oracle.

The producer is never imported. Reassembly is checker-only: independently
selected actual sections replace their counterparts in the bound full-volume
tree before the existing full-source relationship checker observes them.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
import platform
import sys
import xml.etree.ElementTree as ET
from lxml import etree

from build.tei import lib068_source_local_oracle as legacy

ORACLE_ID = "ocd-donne-devotions-scoped-independent-oracle-v1"
ORACLE_VERSION = "2"
NS = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"


def closure_sha(root):
    paths = ["build/tei/donne_devotions_scoped_oracle.py", "build/tei/lib068_source_local_oracle.py",
             "build/tei/lib068_source_letters_oracle.py", "build/tei/lib068_literary_blocks_oracle.py",
             "ocd_kernel/reconstruction/contract.py", "ocd_kernel/reconstruction/__init__.py"]
    records = [{"path": p, "sha256": sha256((root / p).read_bytes()).hexdigest()} for p in sorted(paths)]
    return sha256((json.dumps(records, sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest()


class _ObservedContent:
    def __init__(self, raw):
        self.raw = raw

    def member_bytes(self, name):
        if name != "content.tei.xml":
            raise ValueError("literary tree checker requested an unexpected member")
        return self.raw


def _fingerprint(node):
    return (node.tag, sorted(node.attrib.items()), node.text, node.tail,
            tuple(_fingerprint(child) for child in node))


def check(manifest, raw):
    manifest.verify()
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    source = manifest.authority_path("retained-text").read_bytes()
    if sha256(source).hexdigest() != profile["source_sha256"]:
        raise ValueError("source bytes differ")
    if not source.endswith(b"\r\n") or b"\n" in source.replace(b"\r\n", b""):
        raise ValueError("retained CRLF contract differs")
    lines = source.decode("utf8").split("\r\n")
    positions = lambda literal: [i for i, line in enumerate(lines, 1) if line == literal]
    life, start, end, footer = (positions(x) for x in
        ("_THE LIFE OF DR. JOHN DONNE_", "    DEVOTIONS", "_DEATH'S DUEL,_",
         "*** END OF THE PROJECT GUTENBERG EBOOK DEVOTIONS UPON EMERGENT OCCASIONS; TOGETHER WITH DEATH'S DUEL ***"))
    if [life, start, end, footer] != [[93], [1481], [6491], [7296]] or len(lines) != 7647:
        raise ValueError("independently discovered work boundaries differ")
    if (lines[1475] != "I.W." or lines[6485] != "[346] 1 Tim. i. 19."
            or lines[94] != "(_Taken from the life by Izaak Walton_)."
            or lines[83] != "THE LIFE OF DR. JOHN DONNE     v"
            or lines[85] != "DEVOTIONS                      1"
            or lines[87] != "DEATH'S DUEL                 161"):
        raise ValueError("neighboring closing or final Devotions note differs")
    movements = [(i, match.group(1), match.group(2).lower())
                 for i, line in enumerate(lines, 1)
                 if start[0] <= i < end[0] and (match := re.fullmatch(r"([IVX]+)\. (MEDITATION|EXPOSTULATION|PRAYER)\.", line))]
    groups = [movements[i:i + 3] for i in range(0, len(movements), 3)]
    if len(groups) != 23 or any([r[2] for r in group] != ["meditation", "expostulation", "prayer"]
                               or len({r[1] for r in group}) != 1 for group in groups):
        raise ValueError("complete source station group census differs")
    notes = [int(m.group(1)) for line in lines[start[0] - 1:end[0] - 1]
             if (m := re.match(r"^\[(\d+)\] ", line))]
    if notes != list(range(1, 347)):
        raise ValueError("complete Devotions footnote census differs")
    original_raw = manifest.authority_path("historical-literary-tei").read_bytes()
    old_profile = json.loads(manifest.authority_path("historical-profile").read_bytes())
    legacy._verify_tei(_ObservedContent(original_raw), profile["work_id"], legacy._SPECS[profile["work_id"]],
                       old_profile["identity"], lines, old_profile)
    document = etree.fromstring(raw)
    std_document = ET.fromstring(raw)
    if _fingerprint(std_document) != _fingerprint(ET.fromstring(etree.tostring(document))):
        raise ValueError("independent stdlib/lxml parse correspondence differs")
    original = etree.fromstring(original_raw)
    if document.tag != NS + "TEI" or dict(document.attrib) != dict(original.attrib) or [n.tag for n in document] != [NS + "teiHeader", NS + "text"]:
        raise ValueError("scoped document envelope differs")
    expected_header = deepcopy(original.find(NS + "teiHeader"))
    expected_header.find(NS + "encodingDesc/" + NS + "p").text = profile["encoding_statement"]
    etree.SubElement(expected_header.find(NS + "fileDesc/" + NS + "sourceDesc/" + NS + "bibl"), NS + "note", type="work-scope").text = profile["scope"]
    if etree.tostring(document[0]) != etree.tostring(expected_header):
        raise ValueError("scoped header/qualification differs")
    text = document[1]
    if text.attrib or text.text or text.tail or [n.tag for n in text] != [NS + "front", NS + "body", NS + "back"]:
        raise ValueError("front/body/back ownership differs")
    selected = []
    expected_starts = [[1, 48, 81, 93], [1481, 1508, 1539, 1608], [7296]]
    kinds = ["volume-context", "work", "shared-license"]
    suffixes = ["shared-volume-front", "complete-devotions", "shared-volume-license"]
    for part, starts, kind, suffix in zip(text, expected_starts, kinds, suffixes, strict=True):
        if part.attrib or part.text or part.tail or len(part) != 1:
            raise ValueError("scoped part envelope differs")
        wrapper = part[0]
        attrs = {"type": kind, XML + "id": profile["work_id"] + "-" + suffix}
        if kind == "work":
            attrs["n"] = "Devotions Upon Emergent Occasions"
        if wrapper.tag != NS + "div" or dict(wrapper.attrib) != attrs or wrapper.text or wrapper.tail:
            raise ValueError("scoped ownership wrapper differs")
        if [node.get("n") for node in wrapper] != list(map(str, starts)):
            raise ValueError("source section ownership/omission/order differs")
        selected.extend(wrapper)
    actual_lines = [node for node in text.iter(NS + "seg") if node.get("type") == "source-line"]
    expected_numbers = list(range(1, 6491)) + list(range(7296, 7648))
    if [int(node.get("n", "-1")) for node in actual_lines] != expected_numbers or any(
        "".join(node.itertext()) != lines[number - 1] for node, number in zip(actual_lines, expected_numbers, strict=True)):
        raise ValueError("source-derived exact scoped line conservation differs")
    # Replace only independently selected scoped sections, not excluded siblings.
    old_scope = original.find(NS + "text/" + NS + "body/" + NS + "div")
    for actual in selected:
        expected = next(n for n in old_scope if n.get("n") == actual.get("n"))
        old_scope.replace(expected, deepcopy(actual))
    legacy._verify_tei(_ObservedContent(etree.tostring(original)), profile["work_id"], legacy._SPECS[profile["work_id"]],
                       old_profile["identity"], lines, old_profile)
    ids = [n.get(XML + "id") for n in document.iter() if n.get(XML + "id")]
    if len(ids) != len(set(ids)):
        raise ValueError("scoped duplicate IDs")
    for node in text.iter(NS + "ref"):
        target = node.get("target", "")
        if not target.startswith("#") or target[1:] not in ids:
            raise ValueError("scoped local note link closure differs")
    schema = etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd"))))
    schema.assertValid(document)
    if json.loads(manifest.authority_path("profile").read_bytes())["accounting"]["represented_line_count"] != len(expected_numbers):
        raise ValueError("scoped accounting differs")
    return dict(status="pass", oracle_id=ORACLE_ID, source_lines=len(lines), represented_lines=len(expected_numbers),
        devotions_lines=end[0] - start[0], stations=23, movements=69, footnotes=346,
        exclusions=[[6491, 7295]], shared_biographical_front=[93, 1480],
        front_attribution="Izaak Walton excerpt; heading attribution and I.W. closing conserved",
        classification="Volume Contents places excerpt at roman page v, Devotions at page 1, separate sermon at page 161; front excerpt is context, not a complete independent Walton Life.",
        full_source_literary_relationship_check="pass",
        stdlib_parse_correspondence="pass", local_note_closure="pass", p5="pass",
        prior_exposure="Historical producer/independent checker and complete source inspected; no blind claim.",
        shared_assumptions="Declarative legacy profile and XML parsing; critical headings/line ranges/station groups/notes independently derived from retained text; stdlib corroborates XML parse.")


def _oracle(manifest, candidate):
    candidate.verify_integrity()
    if (candidate.manifest["source_manifest"]["sha256"] != manifest.sha256
            or manifest.record["validator"]["import_closure_sha256"] != closure_sha(manifest.repository_root)):
        raise ValueError("current manifest/independent closure differs")
    report = check(manifest, candidate.member_bytes("content.tei.xml"))
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    if json.loads(candidate.member_bytes("source-accountability.json")) != profile["accounting"]:
        raise ValueError("candidate accountability differs")
    if candidate.member_bytes("README.source.md") != manifest.authority_path("source-readme").read_bytes():
        raise ValueError("candidate source notice differs")
    if [json.loads(x) for x in candidate.member_bytes("unresolved.jsonl").splitlines()] != profile["questions"]:
        raise ValueError("unresolved scope statements differ")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if provenance.get("source_manifest_sha256") != manifest.sha256 or provenance.get("scope") != profile["scope"]:
        raise ValueError("provenance scope differs")
    result = dict(status="pass", oracle_id=ORACLE_ID, oracle_version=ORACLE_VERSION,
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        import_closure_sha256=closure_sha(manifest.repository_root),
        runtime=f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        source_manifest_sha256=manifest.sha256, candidate_sha256=candidate.sha256,
        profile_sha256=sha256(manifest.authority_path("profile").read_bytes()).hexdigest(),
        package_schema_sha256=manifest.record["package_schema"]["sha256"],
        source_sha256=profile["source_sha256"],
        xsd_sha256=sha256(manifest.authority_path("tei-p5-xsd").read_bytes()).hexdigest(),
        policy_sha256=sha256(manifest.authority_path("validation-policy").read_bytes()).hexdigest(), findings=[])
    result["result_sha256"] = sha256((json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest()
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
