"""Real retained-member contract tests for the first LIB-057 tranche."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

from lxml import etree
import pytest

from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)

ROOT = Path(__file__).resolve().parents[1]
LOCAL = Path("sources/commentaries/robertson-word-pictures-vol1")
MANIFEST_RELATIVE = Path("tests/fixtures/reconstruction-runtime/robertson-word-pictures-vol1.source-manifest.json")


@pytest.fixture(scope="module")
def route(tmp_path_factory):
    root = tmp_path_factory.mktemp("robertson-authorities")
    manifest_path = ROOT / MANIFEST_RELATIVE
    record = json.loads(manifest_path.read_bytes())
    paths = {a["path"] for a in record["authorities"]}
    paths.update(record[k]["implementation_path"] for k in ("converter", "validator"))
    paths.add(MANIFEST_RELATIVE.as_posix())
    canonical = ROOT.parents[1] if ROOT.parent.name == ".worktrees" else ROOT
    for name in paths:
        source = (canonical if name.startswith("raw/") else ROOT) / name
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    # XSD's local imports are part of the bound schema closure.
    for source in (ROOT / "ocd_kernel/tei/vendor/xsd").glob("*.xsd"):
        shutil.copyfile(source, root / "ocd_kernel/tei/vendor/xsd" / source.name)
    modules = []
    for key in ("converter", "validator"):
        spec = importlib.util.spec_from_file_location(
            "robertson_test_" + key, root / record[key]["implementation_path"]
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    manifest = SourceManifest.load(
        root / MANIFEST_RELATIVE, repository_root=root
    )
    return manifest, modules[0], modules[1]


def test_load_and_complete_member_boundary(route):
    manifest, producer, oracle = route
    assert manifest.record["work_id"] == "robertson-word-pictures-vol1"
    assert manifest.record["scope"]["member_order"] == ("matthew", "mark")
    inventory = producer.inventory(manifest)
    assert [m["element_count"] for m in inventory] == [7469, 5741]
    assert [len(m["body_divisions"]) for m in inventory] == [31, 18]
    assert [len(m["chapters"]) for m in inventory] == [28, 16]
    assert inventory[0]["body_divisions"][1]["title"] == "Introduction"
    assert all(m["body_divisions"][-1]["title"] == "Indexes" for m in inventory)
    assert all(
        m["shell"]["doctype"] and len(m["shell"]["comments"]) == 2 for m in inventory
    )


def test_reconstruct_and_independent_validation(route, tmp_path):
    manifest, producer, oracle = route
    candidate = reconstruct(manifest, tmp_path / "candidate", producer.convert)
    assert validate(manifest, candidate, oracle.validate).status == "pass"
    repeat = reconstruct(manifest, tmp_path / "repeat", producer.convert)
    assert {n: candidate.member_bytes(n) for n in candidate.member_names} == {
        n: repeat.member_bytes(n) for n in repeat.member_names
    }
    script = """
import importlib.util
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[3])
from ocd_kernel.reconstruction.contract import SourceManifest, reconstruct
root = Path(sys.argv[1])
manifest = SourceManifest.load(root / 'tests/fixtures/reconstruction-runtime/robertson-word-pictures-vol1.source-manifest.json', repository_root=root)
spec = importlib.util.spec_from_file_location('fresh_robertson', root / manifest.record['converter']['implementation_path'])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
reconstruct(manifest, sys.argv[2], module.convert)
"""
    subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            script,
            str(manifest.repository_root),
            str(tmp_path / "fresh"),
            str(ROOT),
        ],
        check=True,
    )
    fresh = CandidatePackage.load(tmp_path / "fresh")
    assert {n: candidate.member_bytes(n) for n in candidate.member_names} == {
        n: fresh.member_bytes(n) for n in fresh.member_names
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "drop-member",
        "swap-members",
        "drop-introduction",
        "drop-index",
        "inline",
        "target",
        "header",
        "shell",
        "ledger",
        "language",
        "version",
        "heading-attachment",
        "extra-text",
    ],
)
def test_oracle_rejects_mutations(route, mutation):
    manifest, producer, oracle = route
    members = dict(producer.convert(manifest))
    tree = etree.fromstring(members["content.tei.xml"])
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    body = tree.find("t:text/t:body", ns)
    if mutation == "drop-member":
        body.remove(body[1])
    elif mutation == "swap-members":
        body.insert(0, body[1])
    elif mutation in ("drop-introduction", "drop-index"):
        member = body[0]
        member.remove(member[1] if mutation == "drop-introduction" else member[-1])
    elif mutation == "inline":
        tree.find(".//t:hi", ns).text = "invented wording"
    elif mutation == "target":
        tree.find(".//t:ref[@target]", ns).set("target", "wrong-target")
    elif mutation == "header":
        tree.find(".//t:title", ns).text = "unsupported edition"
    elif mutation == "language":
        tree.find(".//t:hi[@{http://www.w3.org/XML/1998/namespace}lang]", ns).set(
            "{http://www.w3.org/XML/1998/namespace}lang", "en"
        )
    elif mutation == "version":
        tree.find(".//t:ref[@subtype]", ns).set("subtype", "invented")
    elif mutation == "heading-attachment":
        section = tree.find('.//t:div[@type="source-heading-section"]', ns)
        section.getparent().append(section[-1])
    elif mutation == "extra-text":
        body.text = "invented content"
    else:
        ledger = json.loads(members["source-accountability.json"])
        if mutation == "shell":
            ledger["members"][0]["raw_base64"] = ""
        else:
            ledger["members"][0]["nodes"].pop()
        members["source-accountability.json"] = json.dumps(ledger).encode()
    members["content.tei.xml"] = etree.tostring(tree)
    expected = {
        "drop-member": "member omission/order",
        "swap-members": "member omission/order",
        "drop-introduction": "source child omission/duplication",
        "drop-index": "source child omission/duplication",
        "inline": "mixed text order/content drift",
        "target": "readable attribute/attachment drift",
        "header": "header drift",
        "shell": "complete raw envelope drift",
        "ledger": "node inventory omission",
        "language": "readable attribute/attachment drift",
        "version": "readable attribute/attachment drift",
        "heading-attachment": "heading ownership drift",
        "extra-text": "TEI wrapper drift",
    }
    with pytest.raises(ValueError, match=expected[mutation]):
        oracle.check(manifest, members)


def test_source_drift_rejected(route):
    manifest, _, _ = route
    path = manifest.authority_path("mark")
    original = path.read_bytes()
    try:
        path.write_bytes(original + b" ")
        with pytest.raises(ValueError, match="mark authority bytes drifted"):
            manifest.verify()
    finally:
        path.write_bytes(original)


def test_real_query_links_resolve_with_original_context(route):
    manifest, producer, _ = route
    tei = etree.fromstring(producer.convert(manifest)["content.tei.xml"])
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    counts = {}
    for member in ("matthew", "mark"):
        source = etree.parse(
            str(manifest.authority_path(member)),
            etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False),
        )
        source_ids = {n.get("id"): n for n in source.xpath("//*[@id]")}
        member_tei = tei.find(f'.//t:div[@n="{member}"]', ns)
        target_ids = {
            n.get("{http://www.w3.org/XML/1998/namespace}id"): n
            for n in member_tei.iter()
            if n.get("{http://www.w3.org/XML/1998/namespace}id")
        }
        links = source.xpath("//a[@href]")
        refs = member_tei.findall('.//t:ref[@type="source-link"]', ns)
        counts[member] = 0
        for link, ref in zip(links, refs, strict=True):
            original = urlsplit(link.get("href"))
            actual = urlsplit(ref.get("target"))
            assert original.fragment in source_ids
            assert (
                ref.get("target").partition("#")[0]
                == link.get("href").partition("#")[0]
            )
            assert actual.fragment == member + "-" + original.fragment
            assert actual.fragment in target_ids
            assert "".join(target_ids[actual.fragment].itertext()) == "".join(
                source_ids[original.fragment].itertext()
            )
            counts[member] += bool(original.query)
    assert counts == {"matthew": 1446, "mark": 1179}


@pytest.mark.parametrize(
    "mutation",
    ["original-fragment", "wrong-existing-destination", "wrong-member", "query-drift"],
)
def test_oracle_rejects_query_link_relationship_drift(route, mutation):
    manifest, producer, oracle = route
    members = dict(producer.convert(manifest))
    tree = etree.fromstring(members["content.tei.xml"])
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    refs = tree.xpath(
        '//t:div[@n="matthew"]//t:ref[starts-with(@target,"?scrBook=")]', namespaces=ns
    )
    ref = refs[0]
    context, _, fragment = ref.get("target").partition("#")
    if mutation == "original-fragment":
        # Recreate the review's real defect even before the producer is fixed.
        fragment = fragment.removeprefix("matthew-")
    elif mutation == "wrong-existing-destination":
        fragment = "matthew-i"
    elif mutation == "wrong-member":
        fragment = "mark-i"
    else:
        context = "?scrBook=Invented&scrCh=99&scrV=1"
    ref.set("target", context + "#" + fragment)
    members["content.tei.xml"] = etree.tostring(tree)
    with pytest.raises(ValueError, match="source-link (destination|context)"):
        oracle.check(manifest, members)


@pytest.mark.parametrize(
    "href",
    [
        "https://example.org/other?x=1#v-p9.1",
        "//example.org/other?x=1#v-p9.1",
        "other.html?x=1#v-p9.1",
    ],
)
def test_other_document_links_are_not_retargeted(route, href):
    _, producer, _ = route
    source = etree.Element("a", href=href)
    source.text = "External destination"
    assert producer.mapped(source, "matthew").get("target") == href
