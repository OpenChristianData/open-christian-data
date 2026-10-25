from __future__ import annotations

import hashlib
import io
import struct
import zipfile
import zlib

import pytest

from cvw_app import review_renderers
from cvw_app.review_contract import _source_presentation
from cvw_app.review_renderers import DEFAULT_RENDERER_REGISTRY, RendererError


MEDIA_TYPE = "application/vnd.crosswire.sword-zcom"
PATHS = {
    "nt.czv": "modules/comments/zcom/barnes/nt.czv",
    "nt.czz": "modules/comments/zcom/barnes/nt.czz",
    "nt.czs": "modules/comments/zcom/barnes/nt.czs",
    "barnes-conf": "mods.d/barnes.conf",
}


def _context(monkeypatch, carrier: bytes = b"A <source>carrier</source>", *, order=None, compression=zipfile.ZIP_DEFLATED):
    members = {
        "nt.czv": struct.pack("<IIH", 0, 0, len(carrier)),
        "nt.czz": zlib.compress(carrier) + b"\0" * 1_024,
        "nt.czs": struct.pack("<III", 0, len(zlib.compress(carrier) + b"\0" * 1_024), len(carrier)),
        "barnes-conf": b"[Barnes]\r\nModDrv=zCom\r\n",
    }
    names = list(PATHS) if order is None else order
    zipped = io.BytesIO()
    with zipfile.ZipFile(zipped, "w", compression) as archive:
        for name in names:
            archive.writestr(PATHS[name], members[name])
    archive_bytes = zipped.getvalue()
    monkeypatch.setattr(review_renderers, "_BARNES_ZCOM_ARCHIVE_SHA256", hashlib.sha256(archive_bytes).hexdigest())
    monkeypatch.setattr(review_renderers, "_BARNES_ZCOM_MEMBERS", {
        name: (len(members[name]), hashlib.sha256(members[name]).hexdigest(), PATHS[name])
        for name in ("nt.czv", "nt.czz", "nt.czs")
    })
    monkeypatch.setattr(review_renderers, "_BARNES_ZCOM_CONF", (len(members["barnes-conf"]), hashlib.sha256(members["barnes-conf"]).hexdigest(), PATHS["barnes-conf"]))
    return {"retained-archive": archive_bytes, **members, "__selected_name__": b"retained-archive", "__source_set_sha256__": b"8" * 64}


def _render(context):
    return DEFAULT_RENDERER_REGISTRY.render("barnes-zcom-reader", MEDIA_TYPE, context)


def test_zip_default_remains_unsupported_without_barnes_manifest_route():
    assert _source_presentation(__import__("pathlib").Path("arbitrary.zip")) == (
        "application/zip", "unsupported-binary", "source-location"
    )


def test_exact_fixture_preserves_numeric_slot_and_escapes_invalid_utf8(monkeypatch):
    rendered, supported = _render(_context(monkeypatch, b"bad\xffbyte"))
    assert supported is True
    source_node = next(node for node in rendered["nodes"] if node["text"].startswith("Source slot 00000:"))
    assert "Source slot 00000" in source_node["text"]
    assert "WARNING: invalid UTF-8; exact bytes hex: 626164ff62797465" in source_node["text"]
    assert "book" not in source_node["text"].lower()


def test_exact_fixture_escapes_xml_incompatible_control(monkeypatch):
    rendered, _ = _render(_context(monkeypatch, b"before\x01after"))
    source_node = next(node for node in rendered["nodes"] if node["text"].startswith("Source slot 00000:"))
    assert "WARNING: XML-incompatible character escaped" in source_node["text"]
    assert "before\\u0001after" in source_node["text"]


def test_rejects_extracted_member_hash_mismatch(monkeypatch):
    context = _context(monkeypatch)
    context["nt.czv"] = context["nt.czv"][:-1] + b"\x01"
    with pytest.raises(RendererError, match="member identity drifted: nt.czv"):
        _render(context)


@pytest.mark.parametrize(
    ("order", "compression", "message"),
    [
        (["nt.czz", "nt.czv", "nt.czs", "barnes-conf"], zipfile.ZIP_DEFLATED, "member order or scope drifted"),
        (None, zipfile.ZIP_STORED, "compression method drifted"),
    ],
)
def test_rejects_archive_order_or_compression_drift(monkeypatch, order, compression, message):
    with pytest.raises(RendererError, match=message):
        _render(_context(monkeypatch, order=order, compression=compression))


def test_rejects_malformed_zlib_block(monkeypatch):
    context = _context(monkeypatch, b"payload")
    context["nt.czz"] = b"notzlib!"
    context["nt.czs"] = struct.pack("<III", 0, len(context["nt.czz"]), 7)
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in PATHS:
            archive.writestr(PATHS[name], context[name])
    context["retained-archive"] = archive_buffer.getvalue()
    monkeypatch.setattr(review_renderers, "_BARNES_ZCOM_ARCHIVE_SHA256", hashlib.sha256(context["retained-archive"]).hexdigest())
    monkeypatch.setattr(review_renderers, "_BARNES_ZCOM_MEMBERS", {
        **review_renderers._BARNES_ZCOM_MEMBERS,
        "nt.czz": (len(context["nt.czz"]), hashlib.sha256(context["nt.czz"]).hexdigest(), PATHS["nt.czz"]),
        "nt.czs": (len(context["nt.czs"]), hashlib.sha256(context["nt.czs"]).hexdigest(), PATHS["nt.czs"]),
    })
    with pytest.raises(RendererError, match="cannot be decompressed"):
        _render(context)
