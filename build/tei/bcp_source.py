"""Shared BCP HTML extraction for liturgy TEI census and conversion."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from html import unescape
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

from build.lib.paths import REPO_ROOT
from build.parsers import bcp1662, bcp1928, bcp_full_text

RAW_ROOT = REPO_ROOT / "raw"
FULL_TEXT_DIR = "bcp-full-text"

SPEAKER_RE = re.compile(
    r"^\s*(?P<label>"
    r"Priest|Minister|Answer|Aunswere|People|All|Bishop|Deacon|Reader|Clerk"
    r")\s*\.?\s*(?P<body>.*)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BcpEvent:
    feature: str
    xml_id: str
    text: str
    source_path: str
    label: str = ""
    div_type: str = ""
    speaker: str = ""
    service_id: str = ""


@dataclass(frozen=True)
class BcpEdition:
    slug: str
    title: str
    author: str
    year: int
    source_url: str
    source_kind: str
    files: tuple[Path, ...]
    events: tuple[BcpEvent, ...]
    translator: str | None = None


def slugify(value: str) -> str:
    value = unescape(value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value)
    value = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return value or "item"


def normalise_text(value: str) -> str:
    value = unescape(value).replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def source_id(*parts: str) -> str:
    cleaned = [slugify(part) for part in parts if part]
    return "bcp-" + "-".join(cleaned)


def source_rel(path: Path, raw_root: Path) -> str:
    try:
        rel = path.resolve().relative_to(raw_root.resolve()).as_posix()
        return f"raw/{rel}"
    except ValueError:
        return path.resolve().as_posix()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decode(path: Path) -> str:
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


def _visible_text(node: Tag) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag) and child.name and child.name.lower() == "img":
            parts.append(child.get("alt", ""))
        elif isinstance(child, Tag) and child.name and child.name.lower() == "br":
            parts.append("\n")
        elif isinstance(child, Tag):
            parts.append(_visible_text(child))
    return normalise_text(" ".join(parts))


def _is_rubric(node: Tag, text: str) -> bool:
    if not text:
        return False
    own_colour = str(node.get("color", ""))
    if re.search("red|#ff|#7f|#999", own_colour, re.IGNORECASE):
        return True
    italic_text = " ".join(_visible_text(tag) for tag in node.find_all(["i", "em"]))
    if italic_text and len(italic_text) >= max(8, int(len(text) * 0.75)):
        return True
    return text.startswith(("¶", "Then ", "Here ", "Note,"))


def _speaker_segments(text: str) -> list[tuple[str, str, str]]:
    pattern = re.compile(
        r"(?i)(?<![A-Za-z])(?P<label>Priest|Minister|Answer|Aunswere|People|All|Bishop|Deacon|Reader|Clerk)\s*\.\s*"
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return []
    segments: list[tuple[str, str, str]] = []
    first = matches[0]
    prefix = normalise_text(text[: first.start()])
    if prefix:
        segments.append(("text", "", prefix))
    for index, match in enumerate(matches):
        label = match.group("label").title()
        if label == "Aunswere":
            label = "Answer"
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = normalise_text(text[match.end() : end])
        if body:
            segments.append(("speaker", label, body))
    return segments


def _append_text_event(
    events: list[BcpEvent],
    *,
    edition: str,
    service_id: str,
    path: Path,
    raw_root: Path,
    ordinal: int,
    text: str,
    rubric: bool,
) -> None:
    speaker_segments = _speaker_segments(text)
    if speaker_segments:
        for kind, speaker, body in speaker_segments:
            if kind == "speaker":
                events.append(
                    BcpEvent(
                        feature="speaker_units",
                        xml_id=source_id(edition, path.stem, "sp", str(len(events) + 1), speaker),
                        text=body,
                        source_path=source_rel(path, raw_root),
                        speaker=speaker,
                        service_id=service_id,
                    )
                )
            else:
                events.append(
                    BcpEvent(
                        feature="rubrics" if rubric else "paragraphs",
                        xml_id=source_id(edition, path.stem, "block", str(ordinal), str(len(events) + 1)),
                        text=body,
                        source_path=source_rel(path, raw_root),
                        service_id=service_id,
                    )
                )
        return
    events.append(
        BcpEvent(
            feature="rubrics" if rubric else "paragraphs",
            xml_id=source_id(edition, path.stem, "block", str(ordinal)),
            text=text,
            source_path=source_rel(path, raw_root),
            service_id=service_id,
        )
    )


def _service_title_from_html(html: str, fallback: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    if title_tag:
        title = normalise_text(title_tag.get_text(" "))
        if ": " in title:
            return title.split(": ", 1)[1].strip().rstrip(".")
        if title:
            return title.rstrip(".")
    return fallback.rstrip(".")


def _justus_content_cells(soup: BeautifulSoup) -> list[Tag]:
    cells: list[Tag] = []
    for table in soup.find_all("table"):
        if str(table.get("width", "")) not in {"600", "90%"}:
            continue
        for cell in table.find_all("td"):
            width = str(cell.get("width", ""))
            if width == "150":
                continue
            if width in {"450", "100%", ""}:
                cells.append(cell)
    return cells


def _events_from_justus_page(edition: str, path: Path, title: str, raw_root: Path) -> list[BcpEvent]:
    html = _decode(path)
    soup = BeautifulSoup(html, "html.parser")
    service_id = source_id(edition, path.stem)
    events = [
        BcpEvent("services", service_id, title, source_rel(path, raw_root), label=title, div_type="service")
    ]
    ordinal = 0
    for cell in _justus_content_cells(soup):
        for node in cell.find_all(["p", "div", "blockquote", "hr"], recursive=False):
            if not isinstance(node, Tag):
                continue
            tag = (node.name or "").lower()
            if tag == "hr":
                ordinal += 1
                events.append(
                    BcpEvent(
                        "labels",
                        source_id(edition, path.stem, "break", str(ordinal)),
                        "section break",
                        source_rel(path, raw_root),
                        label="section break",
                        service_id=service_id,
                    )
                )
                continue
            text = _visible_text(node)
            if not text or text.lower().startswith("return to"):
                continue
            ordinal += 1
            align = str(node.get("align", "")).lower()
            if align == "center":
                events.append(
                    BcpEvent(
                        "labels",
                        source_id(edition, path.stem, "label", str(ordinal)),
                        text,
                        source_rel(path, raw_root),
                        label=text,
                        service_id=service_id,
                    )
                )
                continue
            _append_text_event(
                events,
                edition=edition,
                service_id=service_id,
                path=path,
                raw_root=raw_root,
                ordinal=ordinal,
                text=text,
                rubric=_is_rubric(node, text),
            )
    return events


def _events_from_eskimo_page(edition: str, path: Path, title: str, raw_root: Path) -> list[BcpEvent]:
    html = _decode(path)
    soup = BeautifulSoup(html, "html.parser")
    body = soup.find("body") or soup
    service_id = source_id(edition, path.stem)
    events = [
        BcpEvent("services", service_id, title, source_rel(path, raw_root), label=title, div_type="service")
    ]
    ordinal = 0
    for node in body.find_all(["h2", "h3", "center", "font", "p", "strong"], recursive=False):
        text = _visible_text(node)
        if not text or text.lower() in {"next", "previous", "back"}:
            continue
        ordinal += 1
        tag = (node.name or "").lower()
        if tag in {"h2", "h3", "center"} and len(text.split()) <= 20:
            anchor = node.find("a", attrs={"name": True})
            anchor_id = str(anchor.get("name")) if anchor else f"label-{ordinal}"
            events.append(
                BcpEvent(
                    "labels",
                    source_id(edition, path.stem, anchor_id),
                    text,
                    source_rel(path, raw_root),
                    label=text,
                    service_id=service_id,
                )
            )
            continue
        _append_text_event(
            events,
            edition=edition,
            service_id=service_id,
            path=path,
            raw_root=raw_root,
            ordinal=ordinal,
            text=text,
            rubric=_is_rubric(node, text),
        )
    return events


def _collect_events_1662(raw_root: Path) -> list[BcpEvent]:
    events: list[BcpEvent] = []
    for filename, _description in bcp1662.SOURCE_PAGES:
        path = raw_root / "bcp1662" / filename
        html = _decode(path)
        items, errors = bcp1662.extract_collects_from_html(html, filename)
        if errors:
            raise ValueError(f"{filename}: {errors} collect parse errors")
        for item in items:
            collect_id = source_id("bcp-1662", item["anchor"], "collect")
            events.append(
                BcpEvent(
                    "collects",
                    collect_id,
                    item["text"],
                    source_rel(path, raw_root),
                    label=item["title"],
                    div_type="collect",
                )
            )
    return events


def _collect_events_1928(raw_root: Path) -> list[BcpEvent]:
    service_id = source_id("bcp-1928", "collects")
    events: list[BcpEvent] = [
        BcpEvent(
            "services",
            service_id,
            "Collects, Epistles, and Gospels",
            "manual:bcp1928.SOURCE_PAGES",
            label="Collects, Epistles, and Gospels",
            div_type="service",
        )
    ]
    for filename in bcp1928.SOURCE_PAGES:
        path = raw_root / "bcp-1928" / filename
        records, errors = bcp1928.extract_collects_from_html(path.read_bytes(), filename)
        if errors:
            raise ValueError(f"{filename}: {errors} collect parse errors")
        for record in records:
            events.append(
                BcpEvent(
                    "collects",
                    source_id("bcp-1928", record["prayer_id"], "collect"),
                    record["content_blocks"][0],
                    source_rel(path, raw_root),
                    label=record.get("title") or record["prayer_id"],
                    div_type="collect",
                    service_id=service_id,
                )
            )
    committed = {event.xml_id for event in events}
    for key, entry in bcp1928.MANUAL_COLLECTS.items():
        xml_id = source_id("bcp-1928", key, "collect")
        if xml_id in committed:
            continue
        events.append(
            BcpEvent(
                "collects",
                xml_id,
                entry["text"],
                "manual:bcp1928.MANUAL_COLLECTS",
                label=entry["title"],
                div_type="collect",
                service_id=service_id,
            )
        )
    return events


def load_bcp_edition(slug: str, raw_root: Path | None = None) -> BcpEdition:
    root = Path(raw_root) if raw_root is not None else RAW_ROOT
    if slug == "bcp-1928-collects":
        files = tuple(root.joinpath("bcp-1928", name) for name in bcp1928.SOURCE_PAGES)
        return BcpEdition(
            slug=slug,
            title="The Book of Common Prayer (1928) Collects",
            author="Protestant Episcopal Church in the United States of America",
            year=1928,
            source_url=bcp1928.BASE_URL,
            source_kind="episcopalnet_collects",
            files=files,
            events=tuple(_collect_events_1928(root)),
            translator=None,
        )

    cfg = bcp_full_text.EDITIONS[slug]
    events: list[BcpEvent] = []
    files: list[Path] = []
    if cfg["source"] == "justus":
        source_dir = root / FULL_TEXT_DIR / slug
        services = []
        for path in sorted(source_dir.glob("*.htm*")):
            if path.name.startswith("_") or path.name.startswith("PDF"):
                continue
            title = _service_title_from_html(_decode(path), path.stem)
            services.append((path, title))
        for path, title in services:
            files.append(path)
            events.extend(_events_from_justus_page(slug, path, title, root))
    else:
        source_dir = root / FULL_TEXT_DIR / slug
        for rel_path, title in cfg["services"]:
            path = source_dir / rel_path.replace("/", "__")
            files.append(path)
            events.extend(_events_from_eskimo_page(slug, path, title, root))
        events.extend(_collect_events_1662(root))

    return BcpEdition(
        slug=slug,
        title=str(cfg["title"]),
        author=str(cfg["author"]),
        year=int(cfg["year"]),
        source_url=str(cfg["base_url"]),
        source_kind=str(cfg["source"]),
        files=tuple(files),
        events=tuple(events),
        translator=None,
    )


def feature_payload(events: tuple[BcpEvent, ...], feature: str) -> dict[str, object]:
    if feature == "labels":
        ids = [event.xml_id for event in events if event.feature == "labels"]
        ids.extend(f"{event.xml_id}-label" for event in events if event.feature == "collects")
        return {"count": len(ids), "ids": ids}
    matching = [event for event in events if event.feature == feature]
    return {"count": len(matching), "ids": [event.xml_id for event in matching]}
