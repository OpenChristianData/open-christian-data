"""Focused tests for the pinned, content-keyed TEI XSD compiler."""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from build.lib import tei_xsd
from build.lib.tei_xsd import compiled_tei_schema


_MAIN_SCHEMA = b'''<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           targetNamespace="urn:main"
           xmlns:main="urn:main"
           xmlns:teix="urn:teix"
           xmlns:xmls="urn:xml">
  <xs:import namespace="urn:teix" schemaLocation="tei_all_teix.xsd"/>
  <xs:import namespace="urn:xml" schemaLocation="tei_all_xml.xsd"/>
  <!-- Dependency scanning must skip comments and inspect only XSD elements. -->
  <xs:element name="root" type="teix:RootType"/>
</xs:schema>
'''

_TEIX_SCHEMA = b'''<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           targetNamespace="urn:teix"
           xmlns:teix="urn:teix"
           xmlns:main="urn:main"
           xmlns:xmls="urn:xml">
  <xs:import namespace="urn:main" schemaLocation="tei_all.xsd"/>
  <xs:import namespace="urn:xml" schemaLocation="tei_all_xml.xsd"/>
  <xs:complexType name="RootType">
    <xs:simpleContent>
      <xs:extension base="xs:string"/>
    </xs:simpleContent>
  </xs:complexType>
</xs:schema>
'''

_XML_SCHEMA = b'''<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           targetNamespace="urn:xml"
           xmlns:xmls="urn:xml"
           xmlns:main="urn:main"
           xmlns:teix="urn:teix">
  <xs:import namespace="urn:main" schemaLocation="tei_all.xsd"/>
  <xs:import namespace="urn:teix" schemaLocation="tei_all_teix.xsd"/>
  <xs:simpleType name="Flag">
    <xs:restriction base="xs:string">
      <xs:enumeration value="yes"/>
      <xs:enumeration value="no"/>
    </xs:restriction>
  </xs:simpleType>
</xs:schema>
'''


def _write_schema_set(directory: Path) -> dict[str, Path]:
    values = {
        "tei_all.xsd": _MAIN_SCHEMA,
        "tei_all_xml.xsd": _XML_SCHEMA,
        "tei_all_teix.xsd": _TEIX_SCHEMA,
    }
    paths: dict[str, Path] = {}
    for filename, content in values.items():
        path = directory / filename
        path.write_bytes(content)
        paths[filename] = path
    return paths


def test_unchanged_snapshot_reuses_compilation_and_not_validation_result(tmp_path: Path) -> None:
    paths = _write_schema_set(tmp_path)
    schema = compiled_tei_schema(paths["tei_all.xsd"])
    assert compiled_tei_schema(paths["tei_all.xsd"]) is schema

    good = etree.fromstring(b'<root xmlns="urn:main">valid</root>')
    schema.assertValid(good)
    bad = etree.fromstring(b'<root xmlns="urn:main"><unexpected/></root>')
    with pytest.raises(etree.DocumentInvalid):
        schema.assertValid(bad)
    assert compiled_tei_schema(paths["tei_all.xsd"]) is schema


def test_main_and_imported_byte_changes_invalidate_the_cache(tmp_path: Path) -> None:
    paths = _write_schema_set(tmp_path)
    first = compiled_tei_schema(paths["tei_all.xsd"])

    paths["tei_all.xsd"].write_bytes(_MAIN_SCHEMA.replace(b'name="root"', b'name="changed"'))
    second = compiled_tei_schema(paths["tei_all.xsd"])
    assert second is not first

    paths["tei_all_teix.xsd"].write_bytes(_TEIX_SCHEMA.replace(b'base="xs:string"', b'base="xs:int"'))
    third = compiled_tei_schema(paths["tei_all.xsd"])
    assert third is not second
    with pytest.raises(etree.DocumentInvalid):
        third.assertValid(etree.fromstring(b'<changed xmlns="urn:main">not-an-int</changed>'))

    paths["tei_all_xml.xsd"].write_bytes(
        _XML_SCHEMA.replace(b'value="yes"', b'value="changed"')
    )
    fourth = compiled_tei_schema(paths["tei_all.xsd"])
    assert fourth is not third


def test_changed_semantic_rule_is_recompiled_and_rejected(tmp_path: Path) -> None:
    paths = _write_schema_set(tmp_path)
    original = paths["tei_all.xsd"].read_bytes()
    first = compiled_tei_schema(paths["tei_all.xsd"])

    paths["tei_all.xsd"].write_bytes(
        original.replace(b'type="teix:RootType"', b'type="teix:MissingType"')
    )
    with pytest.raises(etree.XMLSchemaParseError):
        compiled_tei_schema(paths["tei_all.xsd"])

    paths["tei_all.xsd"].write_bytes(original)
    assert compiled_tei_schema(paths["tei_all.xsd"]) is first


def test_all_siblings_are_read_even_on_a_cache_hit(tmp_path: Path) -> None:
    paths = _write_schema_set(tmp_path)
    compiled_tei_schema(paths["tei_all.xsd"])
    paths["tei_all_xml.xsd"].unlink()
    with pytest.raises(FileNotFoundError, match="tei_all_xml.xsd"):
        compiled_tei_schema(paths["tei_all.xsd"])


def test_missing_and_unexpected_dependencies_fail_closed(tmp_path: Path) -> None:
    paths = _write_schema_set(tmp_path)
    paths["tei_all.xsd"].write_bytes(
        _MAIN_SCHEMA.replace(
            b'schemaLocation="tei_all_teix.xsd"',
            b'schemaLocation="https://example.invalid/tei_all_teix.xsd"',
        )
    )
    with pytest.raises(tei_xsd.TeiSchemaDependencyError, match="external"):
        compiled_tei_schema(paths["tei_all.xsd"])

    paths["tei_all.xsd"].write_bytes(
        _MAIN_SCHEMA.replace(
            b"?>\n",
            b'?>\n<!DOCTYPE xs:schema [<!ENTITY forbidden "x">]>\n',
            1,
        )
    )
    with pytest.raises(tei_xsd.TeiSchemaDependencyError, match="DTD|entity"):
        compiled_tei_schema(paths["tei_all.xsd"])


def test_cache_is_bounded_to_process_local_compilations(tmp_path: Path) -> None:
    for index in range(tei_xsd._CACHE_MAX_ENTRIES + 2):
        directory = tmp_path / str(index)
        directory.mkdir()
        paths = _write_schema_set(directory)
        compiled_tei_schema(paths["tei_all.xsd"])
    assert len(tei_xsd._COMPILED_SCHEMA_CACHE) <= tei_xsd._CACHE_MAX_ENTRIES
