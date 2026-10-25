"""Located BSB scaffolding diagnostics through the actual supported Bible API."""
from copy import deepcopy
from hashlib import sha256
import json
from lxml import etree
from build.tools.prepare_bsb_current import *
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.projection.categories.bible import project_bible_document, verify_bible_document
from ocd_kernel.library._common import PipelineError


def main():
    ns = "{http://www.tei-c.org/ns/1.0}"
    space = "{http://www.w3.org/XML/1998/namespace}space"
    xmlid = "{http://www.w3.org/XML/1998/namespace}id"
    baseline = io_path(ROOT / BASELINE / "content.tei.xml").read_bytes()
    original = etree.fromstring(baseline)
    profile = json.loads((ROOT / BASE / "profile.json").read_bytes())
    acquired = json.loads(io_path(ROOT / ACQUISITION).read_bytes())
    member = acquired["retained_files"][0]
    source = dict(source_path=member["path"], source_sha256=member["sha256"], source_bytes=member["bytes"], source_scope=member["scope"])
    identity = dict(work_id=WORK_ID, textual_form_id=FORM_ID, edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID)
    revision = "bsb-scaffold-diagnostic-v1"
    kwargs = dict(identity={k: v for k, v in identity.items() if k != "acquisition_id"}, language="en", representation_revision=revision, edition_title=TITLE, versification="source-native-bsb", source_url=acquired["url"], source_sha256=SOURCE_SHA, retained_sha256=SOURCE_SHA)
    body = original.find(ns + "text/" + ns + "body")
    selected = []
    for b_number, c_number, v_number in [(1, 1, 1), (40, 17, 21)]:
        book = deepcopy(body[b_number - 1])
        chapter = deepcopy(book[c_number])
        verse = deepcopy(chapter[v_number])
        for child in list(book)[1:]:
            book.remove(child)
        for child in list(chapter)[1:]:
            chapter.remove(child)
        chapter.append(verse)
        book.append(chapter)
        selected.append(book)
    for child in list(body):
        body.remove(child)
    body.extend(selected)
    observations = []
    for phase in ("historical-header", "renewed-header", "removed-generated-text-type", "explicit-source-whitespace", "literal-source-book-labels"):
        if phase == "renewed-header":
            old_tail = original[0].tail
            header = etree.fromstring(profile["header_xml"].encode())
            header.tail = old_tail
            original.replace(original[0], header)
        elif phase == "removed-generated-text-type":
            del original[1].attrib["type"]
        elif phase == "explicit-source-whitespace":
            for node in original.findall(".//" + ns + "ab"):
                node.set(space, "preserve")
        elif phase == "literal-source-book-labels":
            for book, name in zip(body, ["Genesis", "Matthew"], strict=True):
                book.set("n", name)
        raw = etree.tostring(original, encoding="utf-8", xml_declaration=True)
        path = ROOT / LOG / (phase + ".tei.xml")
        bound = raw
        try:
            bound = bind_reviewed_header(raw, expected_sha256=sha256(raw).hexdigest(), identity=identity, source=source, source_url=acquired["url"], declared_scope="Diagnostic only: exact retained Genesis1:1 and empty Matthew17:21, not a full candidate or acceptance.", revision=dict(id=revision, date="2026-10-02", note="Actual supported source-scaffold diagnostic only."))
            io_path(path).write_bytes(bound)
            projected = project_bible_document(io_path(path), **kwargs)
        except PipelineError as error:
            if phase in ("explicit-source-whitespace", "literal-source-book-labels"):
                raise
            observations.append(dict(phase=phase, status="located-rejection", error=str(error), tei_sha256=sha256(bound).hexdigest()))
            io_path(path).write_bytes(bound)
        else:
            errors = verify_bible_document(io_path(path), projected["rows"], projected["receipt"], **kwargs)
            rows = projected["rows"]
            if errors or len(rows) != 2 or rows[1]["text"] != "" or rows[0]["text"] != " In the beginning God created the heavens and the earth. ":
                raise ValueError("Actual source whitespace/empty diagnostic differs")
            observations.append(dict(phase=phase, status="pass", tei_sha256=sha256(bound).hexdigest(), independent_errors=errors, observed=[dict(locator=r["locator"], text=r["text"]) for r in rows]))
    if [r["locator"]["book"] for r in rows] != ["Genesis", "Matthew"]:
        raise ValueError("Literal source book routing differs")
    proof = dict(status="pass", source_sha256=SOURCE_SHA, historical_baseline_sha256=sha256(baseline).hexdigest(), diagnostic_scope="Exactly two retained source leaves; source-empty and literal whitespace/label semantics only, not complete collection fidelity.", observations=observations, shared_bible_sha256=sha256((ROOT / "ocd_kernel/projection/categories/bible.py").read_bytes()).hexdigest(), shared_edits_required=False)
    put(LOG / "book-label-route-probe.json", canonical(proof))
    print(json.dumps(dict(status="pass", phases=[dict(phase=o["phase"], status=o["status"], error=o.get("error")) for o in observations])))


if __name__ == "__main__":
    main()
