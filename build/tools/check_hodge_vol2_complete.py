"""Run the bounded full-volume replay and source-feature mutation checks."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from lxml import etree

from build.tei import hodge_vol2_complete_oracle as checker
from build.tools.prepare_hodge_vol2_complete import ROOT, SOURCE, MANIFEST, HISTORICAL, canonical
from ocd_kernel.reconstruction.contract import SourceManifest, CandidatePackage


def check(candidate, replay, output):
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    package, repeated = (CandidatePackage.load(p / "package") for p in (candidate, replay))
    assert package.sha256 == repeated.sha256
    assert package.member_names == repeated.member_names
    assert all(package.member_bytes(n) == repeated.member_bytes(n) for n in package.member_names)
    assert (candidate / "validation.json").read_bytes() == (replay / "validation.json").read_bytes()
    validation = json.loads((candidate / "validation.json").read_bytes())
    assert validation["status"] == "pass" and not validation["findings"]
    raw = package.member_bytes("content.tei.xml")
    account = package.member_bytes("source-accountability.json")
    source = (ROOT / SOURCE).read_bytes()
    historical = (ROOT / HISTORICAL / "content.tei.xml").read_bytes()
    baseline = checker.check(manifest, raw, account)
    assert checker._oracle(manifest, package)["status"] == "pass"
    # A second XML implementation corroborates the source traversal assumption.
    native = ET.fromstring(source)
    second = checker.parse(source).getroot()
    signature = lambda root: [(n.tag, dict(n.attrib), n.text, n.tail) for n in root.iter()]
    assert signature(native) == signature(second)
    cases = []

    def reject(name, tree, reason):
        changed = etree.tostring(tree, encoding="utf-8")
        assert changed != raw, name
        try:
            checker.inspect(source, changed, account, historical)
        except ValueError as exc:
            assert reason in str(exc), (name, str(exc))
            cases.append(dict(id=name, status="rejected", reason=str(exc), changed_sha256=sha256(changed).hexdigest()))
        else:
            raise AssertionError("Mutation survived: " + name)

    ns = {"t": checker.NS[1:-1]}
    changes = [
        ("title-wording", "//t:body/t:div[1]//t:ab[1]", None, "invented title", "text/tail differs"),
        ("table-rowspan", "//t:cell[@rows][1]", "rows", "999", "tag/attributes differs"),
        ("table-colspan", "//t:cell[@cols][1]", "cols", "999", "tag/attributes differs"),
        ("table-header-role", "//t:cell[@role='label'][1]", "role", "data", "tag/attributes differs"),
        ("column-layout", "//t:seg[@type='source-column'][1]", "rend", "wrong-width", "tag/attributes differs"),
        ("index-wrong-target", "//t:ref[@type='source-link'][1]", "target", "#hodge-systematic-theology-vol-2-feature-000001", "tag/attributes differs"),
        ("index-literal-query", "//t:ref[@type='source-link'][1]", "ana", "urn:wrong-source-href", "tag/attributes differs"),
        ("index-marker-type", "//t:anchor[1]", "subtype", "wrong-index", "tag/attributes differs"),
        ("inline-language", "//t:foreign[1]", checker.XML + "lang", "en", "tag/attributes differs"),
        ("note-number", "//t:note[@n][1]", "n", "999", "tag/attributes differs"),
        ("page-marker", "//t:body//t:pb[1]", "n", "999", "tag/attributes differs"),
        ("qualified-header-date", "//t:note[@type='electronic-creation-date']", None, "unverified date", "header field missing"),
    ]
    for name, xpath, attribute, value, reason in changes:
        tree = checker.parse(raw)
        node = tree.xpath(xpath, namespaces=ns)[0]
        if attribute is None:
            node.text = value
        else:
            node.set(attribute, value)
        reject(name, tree, reason)
    tree = checker.parse(raw)
    body = tree.find(checker.NS + "text/" + checker.NS + "body")
    body.remove(body[1])
    reject("contents-root-omission", tree, "five-root scope differs")
    tree = checker.parse(raw)
    link = tree.xpath("//t:ref[@type='source-link'][1]", namespaces=ns)[0]
    link.getparent().remove(link)
    reject("index-link-omission", tree, "carrier count or unique IDs differs")
    tree = checker.parse(raw)
    note = tree.xpath("//t:body//t:note[1]", namespaces=ns)[0]
    parent = note.getparent()
    parent.remove(note)
    parent.getparent().append(note)
    reject("note-wrong-attachment", tree, "child attachment/order differs")
    result = dict(status="pass", candidate_sha256=package.sha256, replay_sha256=repeated.sha256,
                  baseline=baseline, cases=cases, validation=validation,
                  source_parser_corroboration="stdlib ElementTree and lxml agree on every source tag, attribute, direct text and tail")
    if output.exists():
        raise FileExistsError(output)
    output.write_bytes(canonical(result))
    print(json.dumps(dict(status="pass", mutation_cases=len(cases), candidate_sha256=package.sha256)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "replay", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    check(args.candidate, args.replay, args.output)
