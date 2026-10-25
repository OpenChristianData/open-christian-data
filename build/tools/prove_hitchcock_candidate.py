"""Prove actual whole candidate under the unapplied lexical successor."""

import copy
import importlib.util
import json
from pathlib import Path

from lxml import etree

from build.tools.prepare_hitchcock_current import BASE, ROOT, LOG, SOURCE, SOURCE_SHA, WORK_ID, FORM_ID, EDITION_ID, REVISION, HISTORICAL, verify_body, save, json_bytes, digest
from ocd_kernel.projection.categories import reference_entries as current


def main() -> None:
    proposed = LOG / "native-support-proposal/reference_entries.after.py"
    spec = importlib.util.spec_from_file_location("hitchcock_proposed_reference", proposed)
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    adapter.ROOT, adapter.SCHEMA, adapter.COMMON = current.ROOT, current.SCHEMA, current.COMMON
    candidate = BASE / "candidate.tei.xml"
    raw = candidate.read_bytes()
    tree = etree.fromstring(raw)
    xsd = etree.XMLSchema(etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")))
    xsd.assertValid(tree)
    accounting = json.loads((BASE / "source-accounting.json").read_text())
    context = {"identity": {"work_id": WORK_ID, "textual_form_id": FORM_ID, "edition_id": EDITION_ID}, "language": "en", "representation_revision": REVISION, "edition_title": "JWBickel/BibleDictionaries retained electronic witness", "source_url": "https://huggingface.co/datasets/JWBickel/BibleDictionaries", "source_sha256": SOURCE_SHA, "retained_sha256": SOURCE_SHA, "source_path": SOURCE, **accounting["projection_context"]}
    projection = adapter.project_reference_entries(candidate, **context)
    receipt = adapter.build_reference_entries_receipt(projection, identity=context["identity"])
    if len(projection["rows"]) != 2622 or sum(len(row["definition_blocks"]) for row in projection["rows"]) != 2622:
        raise ValueError("Hitchcock actual projection count mismatch")
    def disabled(*args, **kwargs):
        raise AssertionError("Producer called during independent check")
    adapter.project_reference_entries = disabled
    adapter._easton_lexical = disabled
    adapter._render = disabled
    errors = adapter.verify_reference_entries(candidate, projection["rows"], receipt, **context)
    if errors:
        raise ValueError(errors)
    mutations = []
    source = SOURCE.read_bytes()
    original = (HISTORICAL / "content.tei.xml").read_bytes()
    for label in ("omitted-entry", "duplicated-entry", "reordered-entry", "term-wording", "definition-whitespace", "field-order", "definition-attachment"):
        node = etree.fromstring(original)
        body = node.find("{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body")
        changed_source = source
        if label == "omitted-entry": body.remove(body[-1])
        elif label == "duplicated-entry":
            duplicate = copy.deepcopy(body[-1])
            for child in duplicate.iter():
                if child.get("{http://www.w3.org/XML/1998/namespace}id"):
                    child.set("{http://www.w3.org/XML/1998/namespace}id", child.get("{http://www.w3.org/XML/1998/namespace}id") + "-duplicate")
            body.append(duplicate)
        elif label == "reordered-entry": body.insert(0, body[-1])
        elif label == "term-wording": body[0][0][0].text += " invented"
        elif label == "definition-whitespace": body[0][1][0].text += " "
        elif label == "field-order":
            records = source.splitlines(keepends=True)
            first = json.loads(records[0])
            records[0] = (json.dumps({"definitions": first["definitions"], "term": first["term"]}) + "\n").encode()
            changed_source = b"".join(records)
        elif label == "definition-attachment":
            body[0][1][0].text, body[1][1][0].text = body[1][1][0].text, body[0][1][0].text
        changed = etree.tostring(node)
        if changed_source == source and changed == etree.tostring(etree.fromstring(original)):
            raise ValueError("No-op mutation: " + label)
        try:
            verify_body(changed_source, changed)
        except ValueError as exc:
            mutations.append({"case": label, "status": "rejected", "reason": str(exc)})
        else:
            raise ValueError("Source mutation accepted: " + label)
    save(BASE / "proposed-projection.json", json_bytes(projection))
    save(BASE / "proposed-projection-receipt.json", json_bytes(receipt))
    proof = {"status": "pass", "candidate_sha256": digest(raw), "adapter_before_sha256": digest(Path(current.__file__).read_bytes()), "adapter_proposed_sha256": digest(proposed.read_bytes()), "source_sha256": SOURCE_SHA, "p5": "pass", "rows": 2622, "characters": sum(len(row["text"]) for row in projection["rows"]), "whole_projection_independent_check": "pass with producer/ET lexical renderer disabled", "meaningful_source_mutations": mutations, "source_body_proof": {"path": (BASE / "source-proof.json").relative_to(ROOT).as_posix(), "sha256": digest((BASE / "source-proof.json").read_bytes())}, "runtime_written": False}
    save(LOG / "native-support-proposal/actual-candidate-proof.json", json_bytes(proof))
    print(json.dumps(proof))


if __name__ == "__main__":
    main()
