"""Strict byte-bound text decoding. No source transcoding or statistical guessing."""

from __future__ import annotations
import codecs
import re
from cvw_app.renderer_nodes import RendererError

_CHARSET = re.compile(rb"charset\s*=\s*[\"\']?([A-Za-z0-9_.:-]+)", re.I)
_XML = re.compile(rb"^\s*<\?xml[^>]*encoding\s*=\s*[\"\']([^\"\']+)", re.I)
_ALLOWED = {
    "utf-8",
    "utf-8-sig",
    "iso8859-1",
    "cp1252",
    "ascii",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
}


def decode_text(payload: bytes, media_type: str) -> tuple[str, str]:
    declarations = []
    if media_type in {
        "text/html",
        "application/xhtml+xml",
        "application/xml",
        "application/tei+xml",
    }:
        header = payload[:1024]
        # Only actual meta tags can declare an HTML charset; prose cannot.
        for tag in re.findall(rb"<meta\b[^>]*>", header, re.I):
            declarations.extend(
                m.group(1).decode("ascii") for m in _CHARSET.finditer(tag)
            )
        xml = _XML.search(header)
        if xml:
            declarations.append(xml.group(1).decode("ascii"))
    try:
        encodings = {codecs.lookup(value).name for value in declarations}
    except LookupError as error:
        raise RendererError("declared text encoding is unsupported") from error
    if len(encodings) > 1:
        raise RendererError("conflicting declared text encodings")
    encoding = next(iter(encodings), "utf-8")
    if media_type == "text/html" and encoding in {"iso8859-1", "ascii"}:
        encoding = "cp1252"
    if encoding not in _ALLOWED:
        raise RendererError(f"declared text encoding is not supported: {encoding}")
    if payload.startswith(codecs.BOM_UTF8):
        if encodings and encoding != "utf-8":
            raise RendererError("text BOM conflicts with declared encoding")
        encoding = "utf-8-sig"
    elif payload.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        if encodings and encoding not in {"utf-16", "utf-16-le", "utf-16-be"}:
            raise RendererError("text BOM conflicts with declared encoding")
        encoding = "utf-16"
    try:
        return payload.decode(encoding, errors="strict"), encoding
    except UnicodeDecodeError as error:
        raise RendererError(f"text bytes do not match {encoding}: {error}") from error
