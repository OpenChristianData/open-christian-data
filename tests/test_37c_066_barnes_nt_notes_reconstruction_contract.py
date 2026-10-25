from __future__ import annotations

import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path
import shutil
import sys
import tempfile

from lxml import etree
import pytest

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/barnes-nt-notes.source-manifest.json"
TEI = {"t": "http://www.tei-c.org/ns/1.0"}


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def source() -> SourceManifest:
    return SourceManifest.load(MANIFEST, repository_root=ROOT)


@pytest.fixture(scope="module")
def producer():
    return _load(ROOT / "build/tei/barnes_nt_notes_reconstruction.py", "_barnes_producer_test")


@pytest.fixture(scope="module")
def oracle():
    return _load(ROOT / "build/tei/barnes_nt_notes_oracle.py", "_barnes_oracle_test")


@pytest.fixture(scope="module")
def candidate(source, producer):
    with tempfile.TemporaryDirectory(prefix="ocd-37c-066-barnes-") as temp_root:
        yield reconstruct(source, Path(temp_root) / "candidate", producer._convert)


@pytest.fixture(scope="module")
def baseline_report(source, candidate, oracle):
    return validate(source, candidate, oracle._oracle)


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _reseal(root: Path, name: str, data: bytes) -> CandidatePackage:
    (root / name).write_bytes(data)
    record = json.loads((root / "manifest.json").read_bytes())
    row = next(item for item in record["members"] if item["name"] == name)
    row.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    (root / "manifest.json").write_bytes(_canonical(record))
    return CandidatePackage.load(root)


def test_exact_retained_member_set_and_all_slots_are_bound(source, candidate, baseline_report) -> None:
    source.verify()
    assert baseline_report.status == "pass"
    account = json.loads(candidate.member_bytes("source-accountability.json"))
    assert account["slot_count"] == 8246
    assert account["empty_slots"] == 783
    assert len(account["invalid_utf8_slots"]) == 60
    assert len(account["xml_incompatible_slots"]) == 76
    assert account["unrepresentable_byte_counts"] == {"invalid_utf8": 68, "xml_1_0_forbidden": 98}
    assert account["unrepresentable_byte_count"] == 166
    assert account["carrier_stream_sha256"] == "4d6272933786b27ba42c9d3c027ece7248a33f1bbb7ccf7e3560e6c991451725"


def test_installed_acquisition_binds_exact_primary_member_set(source, producer, oracle) -> None:
    produced, produced_set = producer._acquisition_binding(source)
    checked, checked_set = oracle._acquisition_binding(source)
    assert produced["source_sha256"] == checked["source_sha256"] == "4a62f1ef906ae95d216517bd7f2fc1b654828d64f9972dff5b13e8d10ca8856f"
    assert produced_set == checked_set == "723432d9d293dcf78f093be09520678d7a9e0b6275b0d0220b3e22be0be85a75"
    assert [Path(item["path"]).name for item in produced["retained_files"]] == ["nt.czs", "nt.czv", "nt.czz"]
    assert all(not item["path"].endswith(".zip") for item in produced["retained_files"])


def test_candidate_header_binds_member_set_and_labels_zip_package(source, candidate, baseline_report) -> None:
    assert baseline_report.status == "pass"
    assert candidate.sha256 == "0c8babd55c5bab8b58ada7e0807fefa61fc75fa4aa0dcd8626073a093f05865c"
    tree = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    source_ids = tree.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl/t:idno", namespaces=TEI)
    assert [(item.get("type"), item.text) for item in source_ids] == [
        ("sha256", "4a62f1ef906ae95d216517bd7f2fc1b654828d64f9972dff5b13e8d10ca8856f"),
        ("source-member-set-sha256", "723432d9d293dcf78f093be09520678d7a9e0b6275b0d0220b3e22be0be85a75"),
        ("acquisition-package-sha256", "9e8edc0333875c214124371b3862df118ad3a76ade7753cb2faeed3484615baf"),
    ]
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    assert provenance["acquisition_id"] == "barnes-sword-v1.1"
    assert provenance["edition_id"] == "crosswire-sword-v1.1"
    assert provenance["source_member_set_sha256"] == source_ids[1].text


def test_oracle_rejects_resealed_zip_as_textual_source(tmp_path, source, candidate, oracle) -> None:
    target = tmp_path / "zip-as-source"
    shutil.copytree(candidate.path, target)
    tree = etree.fromstring((target / "content.tei.xml").read_bytes())
    source_id = tree.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl/t:idno[@type='sha256']", namespaces=TEI)[0]
    source_id.text = "9e8edc0333875c214124371b3862df118ad3a76ade7753cb2faeed3484615baf"
    altered = _reseal(target, "content.tei.xml", etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False))
    with pytest.raises(ValueError, match="does not distinguish extracted members from package"):
        validate(source, altered, oracle._oracle)


def test_every_slot_has_a_stable_source_derived_bible_position(source, candidate, baseline_report) -> None:
    assert baseline_report.status == "pass"
    account = json.loads(candidate.member_bytes("source-accountability.json"))
    positions = [slot["bible_position"] for slot in account["slots"]]
    assert account["bible_position_mapping"] == {
        "scheme": "ocd-barnes-sword-kjv-position-v1",
        "versification": "KJV",
        "counts": {"book-heading": 27, "chapter-heading": 260, "module-heading": 1, "testament-heading": 1, "verse": 7957},
        "position_stream_sha256": "3359e0c5027e8a534959fe042d14ff20d62ae1c599167ec2763e0002a2357955",
    }
    assert len(positions) == 8246
    assert Counter(position["kind"] for position in positions) == account["bible_position_mapping"]["counts"]
    position_stream = "\n".join(f"{slot}\t{item['kind']}\t{item['key']}" for slot, item in enumerate(positions)).encode("utf-8")
    assert hashlib.sha256(position_stream).hexdigest() == account["bible_position_mapping"]["position_stream_sha256"]
    assert positions[:6] == [
        {"kind": "module-heading", "key": "module-heading"},
        {"kind": "testament-heading", "key": "testament.2", "testament": 2},
        {"kind": "book-heading", "key": "Matt", "testament": 2, "osis_book": "Matt"},
        {"kind": "chapter-heading", "key": "Matt.1", "testament": 2, "osis_book": "Matt", "chapter": 1},
        {"kind": "verse", "key": "Matt.1.1", "testament": 2, "osis_book": "Matt", "chapter": 1, "verse": 1},
        {"kind": "verse", "key": "Matt.1.2", "testament": 2, "osis_book": "Matt", "chapter": 1, "verse": 2},
    ]
    assert positions[-1] == {"kind": "verse", "key": "Rev.22.21", "testament": 2, "osis_book": "Rev", "chapter": 22, "verse": 21}

    tree = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    nodes = tree.xpath("/t:TEI/t:text/t:body/t:div/t:ab", namespaces=TEI)
    assert [node.get("subtype") for node in nodes] == [f"{item['kind']}:{item['key']}" for item in positions]
    assert [int(node.get("n")) for node in nodes] == list(range(8246))


def test_thml_round_trip_preserves_text_order_and_readable_semantics(source, candidate, oracle, baseline_report) -> None:
    assert baseline_report.status == "pass"
    source_slots = oracle._source_slots(source)
    tree = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    nodes = tree.xpath("/t:TEI/t:text/t:body/t:div/t:ab", namespaces=TEI)
    account = json.loads(candidate.member_bytes("source-accountability.json"))

    for slot, payload in enumerate(source_slots):
        if not payload:
            continue
        ranges = oracle._source_byte_ranges(payload)
        source_text, markers = oracle._source_with_gap_tokens(payload, ranges, slot)
        expected, _counts, _unmapped, _warnings = oracle._source_thml_events(source_text, slot, markers)
        assert oracle._tei_events(nodes[slot]) == expected

    assert account["thml_mapping"]["mapped_elements"] == {
        "blockquote": 299,
        "br": 64853,
        "i": 53855,
        "scripRef": 30436,
    }
    assert account["thml_mapping"]["unmapped_markup"] == []
    warnings = account["thml_mapping"]["structural_warnings"]
    assert len(warnings) == 4
    assert {item["slot"] for item in warnings} == {751, 6013, 8028}

    opening = nodes[4]
    assert opening.xpath(".//t:hi[@rend='italic']", namespaces=TEI)
    assert opening.xpath(".//t:lb", namespaces=TEI)
    assert opening.xpath(".//t:ref[@type='scripture'][@n]", namespaces=TEI)
    assert tree.xpath("//t:quote[@type='block']", namespaces=TEI)


def test_candidate_contains_every_ordered_slot_and_explicit_gaps(candidate) -> None:
    tree = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    nodes = tree.xpath("/t:TEI/t:text/t:body/t:div/t:ab", namespaces=TEI)
    assert len(nodes) == 8246
    assert [int(node.get("n")) for node in nodes] == list(range(8246))
    account = json.loads(candidate.member_bytes("source-accountability.json"))
    gaps = tree.xpath("//t:gap[@reason='unrepresentable']", namespaces=TEI)
    assert len(gaps) == account["unrepresentable_range_count"]
    assert all(gap.get("ana") in {"#source-invalid-utf8", "#source-xml-1.0-forbidden-character"} for gap in gaps)


def test_unrepresentable_byte_gaps_keep_exact_source_evidence(source, candidate, oracle, baseline_report) -> None:
    assert baseline_report.status == "pass"

    tree = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    gaps = tree.xpath("//t:gap", namespaces=TEI)
    assert len(gaps) == json.loads(candidate.member_bytes("source-accountability.json"))["unrepresentable_range_count"]
    assert {gap.get("reason") for gap in gaps} == {"unrepresentable"}
    assert not tree.xpath("//t:gap[@reason='illegible']", namespaces=TEI)

    account = json.loads(candidate.member_bytes("source-accountability.json"))
    source_slots = oracle._source_slots(source)
    assert len(account["invalid_utf8_slots"]) == 60
    assert len(account["xml_incompatible_slots"]) == 76
    partial_slots = {item["slot"] for item in account["slots"] if item["state"] == "partial"}
    assert len(partial_slots) == 136
    assert partial_slots == set(account["invalid_utf8_slots"]) | set(account["xml_incompatible_slots"])
    assert account["unrepresentable_byte_counts"] == {"invalid_utf8": 68, "xml_1_0_forbidden": 98}
    assert account["unrepresentable_byte_count"] == 166

    represented_bytes = 0
    gap_bytes = 0
    for slot in partial_slots:
        record = account["slots"][slot]
        raw = source_slots[slot]
        assert record["bytes"] == len(raw)
        assert hashlib.sha256(raw).hexdigest() == record["sha256"]
        ranges = record["byte_ranges"]
        assert ranges
        cursor = 0
        reconstructed = bytearray()
        expected_gap_ids = set()
        for byte_range in ranges:
            assert byte_range["slot"] == slot
            assert byte_range["start"] == cursor
            assert byte_range["end"] > cursor
            assert byte_range["bytes"] == byte_range["end"] - byte_range["start"]
            span = bytes.fromhex(byte_range["hex"])
            assert span == raw[byte_range["start"] : byte_range["end"]]
            assert len(span) == byte_range["bytes"]
            assert hashlib.sha256(span).hexdigest() == byte_range["sha256"]
            reconstructed.extend(span)
            cursor = byte_range["end"]
            if byte_range["state"] == "represented":
                represented_bytes += len(span)
            else:
                gap_bytes += len(span)
                assert byte_range["reason"] == "unrepresentable"
                assert byte_range["cause"] in {"invalid-utf8", "xml-1.0-forbidden-character"}
                expected_gap_ids.add(f"barnes-slot-{slot:05d}-byte-{byte_range['start']:08d}-{byte_range['end']:08d}")
        assert cursor == len(raw)
        assert bytes(reconstructed) == raw
        node = tree.xpath(f"/t:TEI/t:text/t:body/t:div/t:ab[@n='{slot}']", namespaces=TEI)[0]
        assert {gap.get("{http://www.w3.org/XML/1998/namespace}id") for gap in node.xpath(".//t:gap", namespaces=TEI)} == expected_gap_ids
        assert node.get("ana") == "#contains-unrepresentable-source-byte-ranges"
        assert any(byte_range["state"] == "represented" for byte_range in ranges)

    assert represented_bytes == 562804
    assert gap_bytes == 166
    assert len({gap.get("{http://www.w3.org/XML/1998/namespace}id") for gap in gaps}) == len(gaps)


def test_unknown_thml_markup_and_unsupported_attributes_stay_visible(producer) -> None:
    carrier = etree.Element(f"{{{TEI['t']}}}ab")
    source_text = 'before <Future Attr="x">A <i>marked</i> &amp; text</Future> after <scripRef passage="Matt 1:2" extra="y">literal</scripRef>'

    result = producer._convert_thml(carrier, source_text, 9999)

    assert result["mapped_elements"] == {"i": 1}
    assert [item["token"] for item in result["unmapped_markup"]] == [
        '<Future Attr="x">',
        "</Future>",
        '<scripRef passage="Matt 1:2" extra="y">',
        "</scripRef>",
    ]
    assert carrier.text == 'before <Future Attr="x">A '
    assert carrier[0].text == "marked"
    assert carrier[0].tail == ' & text</Future> after <scripRef passage="Matt 1:2" extra="y">literal</scripRef>'


@pytest.mark.parametrize("mutation", ["omit", "reorder", "invent", "position-key"])
def test_oracle_rejects_resealed_candidate_mutations(tmp_path, source, candidate, oracle, mutation) -> None:
    target = tmp_path / mutation
    shutil.copytree(candidate.path, target)
    tree = etree.fromstring((target / "content.tei.xml").read_bytes())
    nodes = tree.xpath("/t:TEI/t:text/t:body/t:div/t:ab", namespaces=TEI)
    if mutation == "omit":
        nodes[0].getparent().remove(nodes[0])
    elif mutation == "reorder":
        parent = nodes[0].getparent()
        parent.remove(nodes[1])
        parent.insert(0, nodes[1])
    elif mutation == "position-key":
        nodes[4].set("subtype", "verse:Matt.1.2")
    else:
        nodes[4].text = "invented source text"
    changed = etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    altered = _reseal(target, "content.tei.xml", changed)
    with pytest.raises(ValueError):
        validate(source, altered, oracle._oracle)


@pytest.mark.parametrize("mutation", ["changed-text", "italic-rend", "scripture-passage", "scripture-version", "linebreak", "blockquote", "source-byte-gap"])
def test_oracle_rejects_thml_semantic_mutations(tmp_path, source, candidate, oracle, mutation) -> None:
    target = tmp_path / mutation
    shutil.copytree(candidate.path, target)
    tree = etree.fromstring((target / "content.tei.xml").read_bytes())
    slots = tree.xpath("/t:TEI/t:text/t:body/t:div/t:ab", namespaces=TEI)
    if mutation == "changed-text":
        slots[4].xpath(".//t:hi", namespaces=TEI)[0].text = "invented text"
    elif mutation == "italic-rend":
        slots[4].xpath(".//t:hi", namespaces=TEI)[0].set("rend", "bold")
    elif mutation == "scripture-passage":
        slots[4].xpath(".//t:ref[@type='scripture'][@n]", namespaces=TEI)[0].set("n", "invented passage")
    elif mutation == "scripture-version":
        tree.xpath("//t:ref[@subtype]", namespaces=TEI)[0].set("subtype", "invented version")
    elif mutation == "linebreak":
        linebreak = slots[4].xpath(".//t:lb", namespaces=TEI)[0]
        linebreak.getparent().remove(linebreak)
    elif mutation == "source-byte-gap":
        tree.xpath("//t:gap", namespaces=TEI)[0].set("n", "0" * 64)
    else:
        tree.xpath("//t:quote", namespaces=TEI)[0].set("type", "inline")
    changed = etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    altered = _reseal(target, "content.tei.xml", changed)
    with pytest.raises(ValueError):
        validate(source, altered, oracle._oracle)


@pytest.mark.parametrize("mutation", ["offset", "hex", "omit-range"])
def test_oracle_rejects_resealed_byte_range_accounting_mutations(tmp_path, source, candidate, oracle, mutation) -> None:
    target = tmp_path / mutation
    shutil.copytree(candidate.path, target)
    account = json.loads((target / "source-accountability.json").read_bytes())
    slot = next(item for item in account["slots"] if item["state"] == "partial")
    if mutation == "offset":
        slot["byte_ranges"][0]["start"] += 1
    elif mutation == "hex":
        slot["byte_ranges"][0]["hex"] = "00" + slot["byte_ranges"][0]["hex"][2:]
    else:
        slot["byte_ranges"].pop(0)
    altered = _reseal(target, "source-accountability.json", _canonical(account))
    with pytest.raises(ValueError):
        validate(source, altered, oracle._oracle)


def test_candidate_reproduces_in_fresh_process(tmp_path, source, candidate, producer) -> None:
    replay = reconstruct(source, tmp_path / "replay", producer._convert)
    assert replay.sha256 == candidate.sha256
    destination = tmp_path / "cli"
    result = __import__("subprocess").run([sys.executable, "build/tools/reconstruct_candidate.py", "--manifest", MANIFEST.relative_to(ROOT).as_posix(), "--destination", str(destination), "--repository-root", str(ROOT)], cwd=ROOT, check=True, capture_output=True, text=True)
    assert json.loads(result.stdout)["candidate"]["sha256"] == candidate.sha256
