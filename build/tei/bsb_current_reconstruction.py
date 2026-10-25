"""Reuse complete BSB native text with reversible publication scaffolding."""
from hashlib import sha256
import json
import re
from pathlib import Path
from xml.sax.saxutils import escape
from build.tei.bsb_reconstruction import _convert as historical_convert

CONVERTER_ID = "ocd-bsb-complete-retained-current-v1"
CONVERTER_VERSION = "1"


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def _convert(manifest):
    manifest.verify()
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    baseline = manifest.authority_path("historical-native-baseline").read_bytes()
    ledger = manifest.authority_path("historical-accountability").read_bytes()
    reproduced = historical_convert(manifest)
    if reproduced["content.tei.xml"] != baseline or reproduced["source-accountability.json"] != ledger:
        raise ValueError("Complete unchanged historical BSB source replay differs")
    current = baseline
    for row in profile["book_label_revisions"]:
        old = f'<div type="book" n="{row["old_n"]}" xml:id="{row["id"]}">'.encode()
        new = f'<div type="book" n="{escape(row["source_name"], {chr(34): "&quot;"})}" xml:id="{row["id"]}">'.encode()
        if current.count(old) != 1:
            raise ValueError("Exact book-label preimage differs")
        current = current.replace(old, new)
    old_text = b'<text xml:id="bsb-text" type="bible">'
    if current.count(old_text) != 1:
        raise ValueError("Generated text role preimage differs")
    current = current.replace(old_text, b'<text xml:id="bsb-text">')
    source = json.loads(manifest.authority_path("retained-bsb-json").read_bytes())
    expected = set()
    for b, book in enumerate(source["books"], 1):
        for c, chapter in enumerate(book["chapters"], 1):
            for v, verse in enumerate(chapter["verses"], 1):
                prefix = f'<ab type="verse" n="{verse["verse"]}" xml:id="bsb-book-{b:02d}-chapter-{c:03d}-verse-{v:03d}"'.encode()
                expected.add(prefix)
    seen = set()
    def mark(match):
        prefix = match.group()
        if prefix not in expected or prefix in seen:
            raise ValueError("Exact source verse preimage differs")
        seen.add(prefix)
        return prefix + b' xml:space="preserve"'
    current = re.sub(rb'<ab type="verse" n="[^"]+" xml:id="[^"]+"(?=[/>])', mark, current)
    if seen != expected or len(seen) != 31102:
        raise ValueError("Complete source verse marker coverage differs")
    start = current.index(b"<teiHeader>")
    end = current.index(b"</teiHeader>") + len(b"</teiHeader>")
    current = current[:start] + profile["header_xml"].encode() + current[end:]
    return {
        "content.tei.xml": current,
        "source-accountability.json": ledger,
        "README.source.md": manifest.authority_path("source-readme").read_bytes(),
        "provenance.json": canonical(dict(work_id="bsb", scope=profile["scope"], source_manifest_sha256=manifest.sha256,
                                         historical_native_sha256=sha256(baseline).hexdigest(), book_label_revisions=profile["book_label_revisions"],
                                         whitespace_markers=31102, generated_text_type_removed="bible", status="nonaccepted")),
        "unresolved.jsonl": b"".join(canonical(q) for q in profile["questions"]),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
