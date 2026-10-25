"""Read-only ZIP census and source-HTML image-reference accounting."""
from __future__ import annotations

from collections import Counter
import hashlib
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
import posixpath
from urllib.parse import unquote, urlsplit
from zipfile import BadZipFile, ZipFile


class _Images(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images = []
        self.in_body = False
        self.has_base = False

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.in_body = True
        if tag == "base":
            self.has_base = True
        if tag == "img":
            values = dict(attrs)
            self.images.append(dict(ordinal=len(self.images) + 1,
                                    line=self.getpos()[0], source_region="body" if self.in_body else "outside-explicit-body", src=values.get("src"),
                                    alt=values.get("alt"), srcset=values.get("srcset")))

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        if tag == "body":
            self.in_body = False


def inventory_zip(path: Path, *, html_member: str | None = None,
                  encoding: str = "utf-8", max_bytes: int = 64 * 1024 * 1024) -> dict:
    """Hash every member without extraction; classify img references separately.

    HTMLParser identifies literal img attributes, not browser-recovered topology.
    CSS, SVG, picture/source, srcset and scripts require source-specific review.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    data = Path(path).read_bytes()
    members, findings, references = [], [], []
    payloads = {}
    try:
        with ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            counts = Counter(item.filename for item in entries)
            for name, count in sorted(counts.items()):
                if count != 1:
                    findings.append(dict(code="duplicate-member", member=name, count=count))
            for ordinal, info in enumerate(entries, 1):
                record = dict(ordinal=ordinal, path=info.filename, directory=info.is_dir(), bytes=info.file_size)
                members.append(record)
                if info.is_dir():
                    record["status"] = "directory"
                    continue
                if info.file_size > max_bytes:
                    record["status"] = "not-read"
                    findings.append(dict(code="member-size-limit", member=info.filename))
                    continue
                try:
                    content = archive.read(info)
                except (BadZipFile, RuntimeError, NotImplementedError) as exc:
                    record["status"] = "not-read"
                    findings.append(dict(code="member-read-failure", member=info.filename, message=str(exc)))
                    continue
                record.update(status="hashed", sha256=hashlib.sha256(content).hexdigest())
                if info.filename == html_member:
                    payloads[info.filename] = content
    except BadZipFile as exc:
        raise ValueError(f"invalid ZIP: {exc}") from exc
    referenced = set()
    if html_member is not None:
        if html_member not in payloads or counts.get(html_member) != 1:
            findings.append(dict(code="html-member-unavailable-or-ambiguous", member=html_member))
        else:
            parser = _Images()
            parser.feed(payloads[html_member].decode(encoding, errors="strict"))
            parser.close()
            if parser.has_base:
                findings.append(dict(code="html-base-needs-source-reader", member=html_member))
            for item in parser.images:
                ref = dict(item)
                references.append(ref)
                src = item["src"]
                if item["srcset"]:
                    findings.append(dict(code="srcset-needs-source-reader", ordinal=item["ordinal"]))
                if not src:
                    ref["status"] = "missing-src"
                    findings.append(dict(code="image-src-missing", ordinal=item["ordinal"]))
                    continue
                if parser.has_base:
                    ref["status"] = "unsupported-base-resolution"
                    continue
                parsed = urlsplit(src)
                if parsed.scheme or parsed.netloc:
                    ref["status"] = "external-reference"
                    findings.append(dict(code="image-outside-retained-archive", ordinal=item["ordinal"], src=src))
                    continue
                decoded = unquote(parsed.path, errors="strict")
                target = posixpath.normpath(posixpath.join(posixpath.dirname(html_member), decoded))
                if not decoded or decoded.startswith("/") or "\\" in decoded or target == ".." or target.startswith("../"):
                    ref["status"] = "unsupported-path"
                    findings.append(dict(code="image-path-outside-archive", ordinal=item["ordinal"], src=src))
                    continue
                matches = [m for m in members if m["path"] == target and m.get("status") == "hashed"]
                ref["member"] = target
                if len(matches) != 1:
                    ref["status"] = "missing-or-ambiguous"
                    findings.append(dict(code="image-member-cardinality", member=target, count=len(matches)))
                    continue
                ref.update(status="retained", sha256=matches[0]["sha256"])
                referenced.add(target)
    for record in members:
        record["role"] = ("directory" if record["directory"] else "selected-html" if record["path"] == html_member
                          else "html-referenced-image" if record["path"] in referenced else "other-retained-member")
    if Path(path).read_bytes() != data:
        raise ValueError("archive changed during inventory")
    return dict(status="blocked" if findings else "inventoried", archive_sha256=hashlib.sha256(data).hexdigest(),
                entries=len(members), directories=sum(m["directory"] for m in members),
                file_payloads=sum(not m["directory"] for m in members), members=members,
                html_member=html_member, image_references=references, diagnostics=findings,
                source_fidelity="not-assessed", visual_equivalence="not-assessed",
                limits="Literal HTML img/src accounting only; CSS, SVG, picture/source and script-generated media are unassessed. Other retained members are not automatically excluded or nonsemantic.")
