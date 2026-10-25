"""Independent source-led BSB verification with exact scaffold inversion."""
from hashlib import sha256
import json
from pathlib import Path
import platform
import re
import sys
from xml.sax.saxutils import escape
from lxml import etree
from build.tei.bsb_oracle import _read_native_source, _enumerate_source, _verify_candidate_tei, _expected_accountability

ORACLE_ID = "ocd-bsb-independent-complete-retained-current-v1"
ORACLE_VERSION = "1"
NS = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def closure_sha(root):
    paths = ["build/tei/bsb_current_oracle.py", "build/tei/bsb_oracle.py", "ocd_kernel/reconstruction/contract.py", "ocd_kernel/reconstruction/verifier.py", "ocd_kernel/reconstruction/__init__.py"]
    return sha256(canonical([dict(path=p, sha256=sha256((root / p).read_bytes()).hexdigest()) for p in sorted(paths)])).hexdigest()


def fingerprint(node):
    return node.tag, tuple(node.attrib.items()), node.text, node.tail, tuple(fingerprint(c) for c in node)


class NativeMember:
    def __init__(self, raw):
        self.raw = raw

    def member_bytes(self, name):
        if name != "content.tei.xml":
            raise ValueError(name)
        return self.raw


def check(manifest, raw):
    manifest.verify()
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    source_raw, source, config, old_profile, policy = _read_native_source(manifest)
    marker, source_books, chapters, verses, empties = _enumerate_source(source, old_profile, policy)
    original = manifest.authority_path("historical-native-baseline").read_bytes()
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
    doc = etree.fromstring(raw, parser)
    baseline = etree.fromstring(original, parser)
    if doc.getroottree().docinfo.doctype or doc.tag != NS + "TEI" or dict(doc.attrib) != {XML + "id": "bsb-candidate"} or [n.tag for n in doc] != [NS + "teiHeader", NS + "text"]:
        raise ValueError("Complete BSB namespace/envelope differs")
    expected_header = etree.fromstring(profile["header_xml"].encode(), parser)
    expected_header.tail = baseline[0].tail
    if fingerprint(doc[0]) != fingerprint(expected_header):
        raise ValueError("Exact source-qualified current header differs")
    if dict(doc[1].attrib) != {XML + "id": "bsb-text"}:
        raise ValueError("Generated text role disposition differs")
    books = doc.findall(NS + "text/" + NS + "body/" + NS + "div")
    if len(books) != 66 or len(profile["book_label_revisions"]) != 66:
        raise ValueError("Complete source book cardinality differs")
    restored = raw
    expected_openings = set()
    for b_index, (book, expected_book) in enumerate(zip(books, source_books, strict=True), 1):
        name = expected_book["name"]
        identity = f"bsb-book-{b_index:02d}"
        revision = dict(source_pointer=f"/books/{b_index - 1}/name", old_n=str(b_index), source_name=name, id=identity)
        if profile["book_label_revisions"][b_index - 1] != revision or dict(book.attrib) != {"type": "book", "n": name, XML + "id": identity}:
            raise ValueError("Exact source-backed book label/identity differs")
        new = f'<div type="book" n="{escape(name, {chr(34): "&quot;"})}" xml:id="{identity}">'.encode()
        old = f'<div type="book" n="{b_index}" xml:id="{identity}">'.encode()
        if restored.count(new) != 1:
            raise ValueError("Book label serialized preimage differs")
        restored = restored.replace(new, old)
        chapter_nodes = list(book)[1:]
        if len(chapter_nodes) != len(expected_book["chapters"]):
            raise ValueError("Complete source chapter cardinality differs")
        for c_index, (chapter, expected_chapter) in enumerate(zip(chapter_nodes, expected_book["chapters"], strict=True), 1):
            nodes = list(chapter)[1:]
            if len(nodes) != len(expected_chapter["verses"]):
                raise ValueError("Complete source verse cardinality differs")
            for v_index, (node, expected_verse) in enumerate(zip(nodes, expected_chapter["verses"], strict=True), 1):
                identity = f"bsb-book-{b_index:02d}-chapter-{c_index:03d}-verse-{v_index:03d}"
                if node.tag != NS + "ab" or dict(node.attrib) != {"type": "verse", "n": str(expected_verse["verse"]), XML + "id": identity, XML + "space": "preserve"} or len(node) or (node.text or "") != expected_verse["text"]:
                    raise ValueError("Exact source verse text/whitespace/empty identity differs: " + identity)
                expected_openings.add(f'<ab type="verse" n="{expected_verse["verse"]}" xml:id="{identity}" xml:space="preserve"'.encode())
    seen = set()
    def unmark(match):
        prefix = match.group()
        if prefix not in expected_openings or prefix in seen:
            raise ValueError("Source whitespace marker preimage differs")
        seen.add(prefix)
        return prefix[:-len(b' xml:space="preserve"')]
    restored = re.sub(rb'<ab type="verse" n="[^"]+" xml:id="[^"]+" xml:space="preserve"(?=[/>])', unmark, restored)
    if seen != expected_openings or len(seen) != 31102:
        raise ValueError("Complete source whitespace marker coverage differs")
    text_opening = b'<text xml:id="bsb-text">'
    if restored.count(text_opening) != 1:
        raise ValueError("Generated text scaffolding preimage differs")
    restored = restored.replace(text_opening, b'<text xml:id="bsb-text" type="bible">')
    start, end = restored.index(b"<teiHeader"), restored.index(b"</teiHeader>") + len(b"</teiHeader>")
    old_start, old_end = original.index(b"<teiHeader>"), original.index(b"</teiHeader>") + len(b"</teiHeader>")
    restored = restored[:start] + original[old_start:old_end] + restored[end:]
    if restored != original:
        raise ValueError("Only declared scaffolds/header inversion fails exact historical native bytes")
    _verify_candidate_tei(manifest, NativeMember(restored), config, marker, source_books, source_raw)
    ledger = _expected_accountability(marker, source_books, manifest, source_raw)
    if canonical(ledger) != manifest.authority_path("historical-accountability").read_bytes():
        raise ValueError("Full independent source field ledger differs")
    etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd")))).assertValid(doc)
    return dict(status="pass", books=66, chapters=chapters, verses=verses, empty_text=len(empties), empty_locations=empties,
                literal_book_labels=66, exact_baseline_byte_restoration=True, whitespace_preserve_markers=31102, p5="pass",
                source_counts=ledger["source_envelope"], independent_source_mapping="Unchanged independent complete BSB JSON enumerator and full native/ledger checker plus direct source leaf/empty/whitespace checks and byte-exact scaffold inverse. No producer import.")


def _oracle(manifest, candidate):
    candidate.verify_integrity()
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    if candidate.manifest["source_manifest"]["sha256"] != manifest.sha256 or manifest.record["validator"]["import_closure_sha256"] != closure_sha(manifest.repository_root):
        raise ValueError("Current source manifest/import closure differs")
    check(manifest, candidate.member_bytes("content.tei.xml"))
    if candidate.member_bytes("source-accountability.json") != manifest.authority_path("historical-accountability").read_bytes():
        raise ValueError("Complete source accounting differs")
    if candidate.member_bytes("README.source.md") != manifest.authority_path("source-readme").read_bytes() or [json.loads(x) for x in candidate.member_bytes("unresolved.jsonl").splitlines()] != profile["questions"]:
        raise ValueError("Visible credits/unresolved ledger differs")
    expected = dict(work_id="bsb", scope=profile["scope"], source_manifest_sha256=manifest.sha256,
                    historical_native_sha256=sha256(manifest.authority_path("historical-native-baseline").read_bytes()).hexdigest(),
                    book_label_revisions=profile["book_label_revisions"], whitespace_markers=31102, generated_text_type_removed="bible", status="nonaccepted")
    if json.loads(candidate.member_bytes("provenance.json")) != expected:
        raise ValueError("Provenance differs")
    result = dict(status="pass", oracle_id=ORACLE_ID, oracle_version=ORACLE_VERSION, implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                  import_closure_sha256=closure_sha(manifest.repository_root), runtime=f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
                  # The unchanged source profile/policy retain their protocol
                  # roles because the independent historical source oracle uses
                  # those exact authorities. The additional current scaffold
                  # profile/policy are also bound by the complete manifest hash.
                  source_manifest_sha256=manifest.sha256, candidate_sha256=candidate.sha256, profile_sha256=sha256(manifest.authority_path("reconstruction-profile").read_bytes()).hexdigest(),
                  package_schema_sha256=manifest.record["package_schema"]["sha256"], source_sha256=profile["source_sha256"],
                  xsd_sha256=sha256(manifest.authority_path("tei-p5-xsd").read_bytes()).hexdigest(), policy_sha256=sha256(manifest.authority_path("validation-policy").read_bytes()).hexdigest(), findings=[])
    result["result_sha256"] = sha256(canonical(result)).hexdigest()
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
