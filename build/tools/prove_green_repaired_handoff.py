"""Challenge and reproduce the Green handoff without source conversion."""

import copy
import json
from pathlib import Path
import subprocess
import sys

from lxml import etree

from build.tools.prepare_green_current import ROOT, LOG, BASE, WORK_ID, FORM_ID, EDITION_ID, REVISION, digest, save, json_bytes
from build.tei.green_header_archive import T, decode, serialize_decoded
from ocd_kernel.library._common import io_path
from ocd_kernel.projection.categories.native_documents import verify_document


def inverse(raw):
    current = etree.fromstring(raw)
    old = etree.fromstring((LOG / "historical-package/content.tei.xml").read_bytes())
    text = copy.deepcopy(current.find(T + "text"))
    changes = json.loads((LOG / "body-adapter-inverse-v2.json").read_bytes())["changes"]
    nodes = list(text.iter())
    for change in changes:
        node = nodes[change["ordinal"] - 1]
        if node.tag != T + change["current_tag"] or list(node.attrib.items()) != [tuple(a) for a in change["current_attributes"]]:
            raise ValueError("Exact alias QName/attributes changed")
        node.tag = T + change["source_tag"]
        node.attrib.clear()
        for name, value in change["source_attributes"]:
            node.set(name, value)
    if etree.tostring(text) != etree.tostring(old.find(T + "text")):
        raise ValueError("Whole historical text inverse changed")
    archive = current.find(T + "teiHeader/" + T + "fileDesc/" + T + "sourceDesc/" + T + "bibl[@type='retained-historical-header-evidence']/" + T + "note[@type='source-header-archive']/" + T + "seg")
    if serialize_decoded(decode(etree.tostring(archive))) != etree.tostring(old.find(T + "teiHeader")):
        raise ValueError("Whole historical header inverse changed")


def replay():
    import build.tools.prepare_green_current as composer
    output = LOG / "replay"
    original_save = composer.save
    def retained_save(path, raw):
        if path.is_relative_to(BASE):
            original_save(output / path.relative_to(BASE), raw)
        else:
            if io_path(path).read_bytes() != raw:
                raise ValueError("Composition would change a frozen original artifact")
    composer.save = retained_save
    # Only header/body composition is replayed. Already verified public output
    # is reused, not falsely claimed as a second projection execution.
    composer.project_prose_document = lambda *a, **k: json.loads((LOG / "current-projection-v3.json").read_bytes())
    composer.main()
    raw = (output / "candidate.tei.xml").read_bytes()
    if raw != (BASE / "candidate.tei.xml").read_bytes():
        raise ValueError("Fresh-process exact header/body composition replay differs")
    original_save(output / "replay.json", json_bytes({"status": "pass", "candidate_sha256": digest(raw), "byte_exact": True, "source_conversion_executed": False, "public_projection_reexecuted": False, "claim": "Fresh-process constrained active-header plus conserved-body composition"}))


def main():
    if "--replay-child" in sys.argv:
        replay()
        return
    candidate = BASE / "candidate.tei.xml"
    raw = candidate.read_bytes()
    inverse(raw)
    result = subprocess.run([sys.executable, "-m", "build.tools.prove_green_repaired_handoff", "--replay-child"], cwd=ROOT, check=True, capture_output=True, text=True)
    tree = etree.fromstring(raw)
    mutations = []
    def challenge(name, alter):
        variant = copy.deepcopy(tree)
        alter(variant)
        altered = etree.tostring(variant, xml_declaration=True, encoding="UTF-8")
        if altered == raw:
            raise ValueError("Mutation did not change candidate: " + name)
        try:
            inverse(altered)
        except (ValueError, etree.XMLSyntaxError, IndexError) as exc:
            mutations.append({"name": name, "rejected": True, "reason": str(exc), "candidate_sha256": digest(altered)})
        else:
            raise ValueError("Inverse accepted mutation: " + name)
    challenge("printed-title-source-role", lambda x: x.find(".//" + T + "ab[@subtype='titlePart']").set("subtype", "docTitle"))
    challenge("note-back-reference", lambda x: x.find(".//" + T + "text//" + T + "note").set("corresp", "#ref999"))
    challenge("standalone-empty-correction-fabricated-space", lambda x: setattr(x.find(".//" + T + "seg[@type='source-editorial-correction']"), "text", " "))
    challenge("wording", lambda x: setattr(x.find(".//" + T + "body//" + T + "p"), "text", "INVENTED"))
    challenge("page-omission", lambda x: x.find(".//" + T + "pb").getparent().remove(x.find(".//" + T + "pb")))
    def duplicate(x):
        p = x.find(".//" + T + "body//" + T + "p")
        clone = copy.deepcopy(p)
        for node in clone.iter():
            node.attrib.pop("{http://www.w3.org/XML/1998/namespace}id", None)
        p.addnext(clone)
    challenge("paragraph-duplication", duplicate)
    def attachment(x):
        note = x.find(".//" + T + "text//" + T + "note")
        parent = note.getparent()
        parent.remove(note)
        x.find(".//" + T + "body//" + T + "p").append(note)
    challenge("note-attachment", attachment)
    challenge("choice-alternative", lambda x: setattr(x.find(".//" + T + "choice/" + T + "corr"), "text", "changed correction"))
    challenge("archival-header-text", lambda x: setattr(x.find(".//" + T + "seg[@type='source-header-element'][@n='4']"), "text", "changed header"))
    projection = json.loads((LOG / "current-projection-v3.json").read_bytes())
    work = json.loads(io_path(ROOT / "library/works" / WORK_ID / "work.json").read_bytes())
    import ocd_kernel.projection.native_content as producer
    original = producer.project_content
    producer.project_content = lambda *a, **k: (_ for _ in ()).throw(AssertionError("Producer disabled"))
    try:
        for name in ("output-wording", "output-omission", "output-duplication", "output-order"):
            rows = copy.deepcopy(projection["rows"])
            if name == "output-wording":
                rows[0]["text"] += "changed"
            elif name == "output-omission":
                rows.pop()
            elif name == "output-duplication":
                rows.append(copy.deepcopy(rows[-1]))
            else:
                rows[0], rows[1] = rows[1], rows[0]
            errors = verify_document(candidate, rows, projection["receipt"], identity={"work_id": WORK_ID, "textual_form_id": FORM_ID, "edition_id": EDITION_ID}, language="en", representation_revision=REVISION, edition_title=work["textual_forms"][0]["editions"][0]["title"], _allow_acceptance_metadata=True, category="prose")
            if not errors:
                raise ValueError("Saved producer-disabled verification accepted " + name)
            mutations.append({"name": name, "rejected": True, "reason": errors})
    finally:
        producer.project_content = original
    proof = LOG / "current-candidate-proof-v3.json"
    paths = [proof, LOG / "body-adapter-inverse-v2.json", LOG / "current-projection-v3.json", Path(__file__).resolve(), ROOT / "build/tools/check_green_current_candidate.py", LOG / "replay/replay.json", ROOT / "build/tei/green_header_archive.py", BASE / "candidate.tei.xml", BASE / "profile.json"]
    report = {"status": "pass", "candidate_sha256": digest(raw), "mutations": mutations, "mutations_rejected": len(mutations), "replay": {"exit_code": result.returncode, "stdout": result.stdout.strip(), "byte_exact": True}, "source_body_proof_reused": "V6B exact source/native proof and three original-body replays remain bound through exact whole-text inverse; no source converter was run.", "binding_supplement": "The current proof completed successfully before its final input-list cleanup was loaded. This supplement binds the correct current v2 inverse/v3 projection and current checker-tool bytes without repeating P5 or projection gates.", "bindings": {p.relative_to(ROOT).as_posix(): digest(io_path(p).read_bytes()) for p in paths}}
    save(LOG / "repaired-handoff-proof.json", json_bytes(report))
    print(json.dumps({"status": "pass", "mutations": len(mutations), "fresh_composition_replay_exit": result.returncode, "candidate_sha256": digest(raw)}))


if __name__ == "__main__":
    main()
