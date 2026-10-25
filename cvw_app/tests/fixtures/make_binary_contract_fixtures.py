"""One-shot generator for ticket 06b deterministic binary-contract fixtures.

Every byte is deterministic: zip entries pin date_time, create_system,
external_attr, compress_type, and entry order, so regeneration is
byte-identical (plan v2 finding C3).
"""

from __future__ import annotations

import hashlib
import json
import struct
import zipfile
from pathlib import Path

ARTIFACTS = Path(__file__).resolve().parents[2] / "fixtures" / "review-v1" / "artifacts" / "binary-contract"
ROOT = ARTIFACTS
ROOT.mkdir(parents=True, exist_ok=True)

_ZIP_DATE = (1980, 1, 1, 0, 0, 0)
_FILE_ATTR = (0o600 << 16)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_bytes(name: str, payload: bytes) -> str:
    path = ROOT / name
    path.write_bytes(payload)
    print(f"{name}: {_digest(path)}")
    return _digest(path)


# --- smallest valid PNG / JPEG / TIFF: 1x1 red pixel via PIL ------------------
def make_image(format_name: str, kwargs: dict | None = None) -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (1, 1), (255, 0, 0)).save(buffer, format=format_name, **(kwargs or {}))
    return buffer.getvalue()


# --- minimal one-page PDF -----------------------------------------------------
def make_pdf() -> bytes:
    objects = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
    )
    stream = b"BT /F1 18 Tf 72 720 Td (Binary Contract PDF Fixture) Tj ET"
    objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    xref = f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        xref += f"{offset:010d} 00000 n \n".encode()
    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    )
    return out + xref + trailer


# --- minimal EPUB with benign + hostile spine documents ----------------------
CONTAINER_XML = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""

OPF = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="uid">urn:uuid:06b-fixture</dc:identifier>
    <dc:title>Binary Contract EPUB Fixture</dc:title>
    <dc:language>en</dc:language>
    <meta property="dcterms:modified">2026-01-01T00:00:00Z</meta>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="ch1"/><itemref idref="ch2"/></spine>
</package>
"""

CH1_BENIGN = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Benign Chapter</title></head>
<body><h1 id="spine-benign-heading">Benign Chapter</h1>
<p id="spine-benign-paragraph">A safe chapter inside the fixture EPUB.</p></body></html>
"""

CH2_HOSTILE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Hostile Chapter</title><script src="https://tracker.example.com/x.js"/></head>
<body onload="steal()">
<h1 id="spine-hostile-heading">Hostile Chapter</h1>
<script>alert('xss')</script>
<p onclick="exfiltrate()">Hostile paragraph with <a href="javascript:alert(1)">a bad link</a>
and <img src="https://pixel.example.com/i.gif" alt="pixel"/> inline.</p>
<iframe src="https://frame.example.com"></iframe>
<form action="https://evil.example.com/post"><input type="text"/></form>
</body></html>
"""


def make_epub() -> bytes:
    buffer = __import__("io").BytesIO()
    entries: list[tuple[str, bytes]] = [
        ("mimetype", b"application/epub+zip"),
        ("META-INF/container.xml", CONTAINER_XML.encode()),
        ("OEBPS/content.opf", OPF.encode()),
        ("OEBPS/ch1.xhtml", CH1_BENIGN.encode()),
        ("OEBPS/ch2.xhtml", CH2_HOSTILE.encode()),
    ]
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=_ZIP_DATE)
            info.compress_type = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = _FILE_ATTR
            zf.writestr(info, data)
    return buffer.getvalue()


def main() -> None:
    digests = {
        "facsimile.png": write_bytes("facsimile.png", make_image("PNG")),
        "facsimile.jpg": write_bytes("facsimile.jpg", make_image("JPEG")),
        "facsimile.tiff": write_bytes("facsimile.tiff", make_image("TIFF")),
        "monograph.pdf": write_bytes("monograph.pdf", make_pdf()),
        "monograph.epub": write_bytes("monograph.epub", make_epub()),
    }
    manifest_path = Path(__file__).with_name("binary_contract_digests.json")
    manifest_path.write_text(json.dumps(digests, indent=1, sort_keys=True) + "\n")
    print(f"digests written: {manifest_path}")


if __name__ == "__main__":
    main()
