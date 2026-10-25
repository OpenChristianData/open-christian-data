"""WU-13 source-index primitives; these do not claim CVW renderer equivalence."""

from dataclasses import replace
import hashlib

import pytest

from cvw_app.bounded_xml_index import build_index, read_fragment
from cvw_app.renderer_nodes import RendererError


def prepare(tmp_path, content):
    payload = content.encode("utf-8")
    master = tmp_path / "master.xml"
    master.write_bytes(payload)
    binding = {"expected_sha256": hashlib.sha256(payload).hexdigest(),
               "renderer_version": "fixture-renderer-v1"}
    return master, binding, build_index(master, **binding)


def test_duplicate_ids_keep_distinct_exact_source_occurrences(tmp_path):
    master, binding, index = prepare(tmp_path, '<root><p id="same">One</p><p id="same">Two</p></root>')
    assert len(index.elements) == 3
    assert read_fragment(master, index, 1, **binding).payload == b'<p id="same">One</p>'
    assert read_fragment(master, index, 2, **binding).payload == b'<p id="same">Two</p>'
    assert index.elements[1].attributes == index.elements[2].attributes


def test_nested_namespace_and_space_context_is_retained(tmp_path):
    master, binding, index = prepare(tmp_path,
        '<TEI xmlns="urn:tei" xmlns:n="urn:note" xml:space="preserve">'
        '<text><div xml:space="default"><n:note> A <hi>B</hi> C </n:note></div></text></TEI>')
    fragment = read_fragment(master, index, 3, **binding)
    assert fragment.payload == b'<n:note> A <hi>B</hi> C </n:note>'
    assert [entry.ordinal for entry in fragment.ancestors] == [0, 1, 2]
    assert dict(fragment.namespace_bindings)[""] == "urn:tei"
    assert dict(fragment.namespace_bindings)["n"] == "urn:note"
    assert fragment.xml_space == "default"
    assert fragment.locator.expanded_name == "urn:note}note"
    assert fragment.bytes_verified == master.stat().st_size
    # A fragment cannot be passed off as a global CVW page/context projection.
    with pytest.raises(RendererError, match="no equivalent CVW projection adapter"):
        fragment.cvw_presentation()


def test_nested_notes_and_multibyte_text_preserve_exact_bytes(tmp_path):
    master, binding, index = prepare(tmp_path, '<root><p>é<note id="n">α<note>β</note>γ</note>δ</p><empty /></root>')
    assert read_fragment(master, index, 2, **binding).payload.decode() == '<note id="n">α<note>β</note>γ</note>'
    assert read_fragment(master, index, 4, **binding).payload == b'<empty />'


@pytest.mark.parametrize("content", ['<root><p></root>', '<root/>trailing', '<root><p/>',
                                        '<!DOCTYPE r [<!ENTITY e "text">]><r>&e;</r>'])
def test_malformed_or_entity_master_never_produces_index(tmp_path, content):
    with pytest.raises(RendererError):
        prepare(tmp_path, content)


def test_master_change_outside_selection_rejects_before_return(tmp_path):
    master, binding, index = prepare(tmp_path, '<r><p>Selected</p><p>Other</p></r>')
    master.write_bytes(master.read_bytes().replace(b"Other", b"Alter"))
    with pytest.raises(RendererError, match="no longer match"):
        read_fragment(master, index, 1, **binding)


@pytest.mark.parametrize("field,value", [("master_sha256", "0" * 64),
    ("indexer_version", "old"), ("renderer_version", "old")])
def test_binding_mismatch_rejects(tmp_path, field, value):
    master, binding, index = prepare(tmp_path, '<r><p>Text</p></r>')
    with pytest.raises(RendererError, match="binding mismatch"):
        read_fragment(master, replace(index, **{field: value}), 1, **binding)


def test_index_range_tampering_rejects(tmp_path):
    master, binding, index = prepare(tmp_path, '<r><p>Text</p></r>')
    tampered = replace(index, elements=(index.elements[0], replace(index.elements[1], start=0)))
    with pytest.raises(RendererError, match="integrity mismatch"):
        read_fragment(master, tampered, 1, **binding)


def test_limits_and_initial_hash_mismatch_reject(tmp_path):
    master, binding, index = prepare(tmp_path, '<r><p>Text</p></r>')
    with pytest.raises(RendererError, match="fragment byte budget"):
        read_fragment(master, index, 1, max_fragment_bytes=3, **binding)
    with pytest.raises(RendererError, match="element budget"):
        build_index(master, max_elements=1, **binding)
    with pytest.raises(RendererError, match="do not match"):
        build_index(master, **{**binding, "expected_sha256": "0" * 64})


def test_chunk_boundaries_do_not_change_source_ranges(tmp_path, monkeypatch):
    import cvw_app.bounded_xml_index as module
    monkeypatch.setattr(module, "_CHUNK_BYTES", 7)
    master, binding, index = prepare(tmp_path, '<root><long-name>é<empty/> tail</long-name></root>')
    assert read_fragment(master, index, 1, **binding).payload == '<long-name>é<empty/> tail</long-name>'.encode()


def test_unsupported_encoding_rejects(tmp_path):
    master = tmp_path / "utf16.xml"
    payload = '<root><p>text</p></root>'.encode("utf-16")
    master.write_bytes(payload)
    with pytest.raises(RendererError, match="UTF-8"):
        build_index(master, expected_sha256=hashlib.sha256(payload).hexdigest(), renderer_version="v1")
