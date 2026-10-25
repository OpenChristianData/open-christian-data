"""Convert the independently checked Douay reading companion to release Markdown."""

from __future__ import annotations

import argparse
import hashlib
import html as html_std
import json
import re
from pathlib import Path

from lxml import html


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "reports/_logs/original-douay-rheims-current-reconciliation-20261002-v1"
SOURCE = BASE / "readable-companion-v2"
DEFAULT_OUT = BASE / "readable-companion-v2-release"
PRE = re.compile(r'<pre style="white-space: pre-wrap">(.*?)</pre>', re.DOTALL)
INLINE = re.compile(r'<(?:em|span class="[^"]+")>.*?</(?:em|span)>', re.DOTALL)


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def markdown_escape(value: str) -> str:
    # Entities preserve literal angle brackets without violating the release
    # notice policy. Markdown metacharacters remain literal outside source style.
    value = value.replace("\\", "\\\\")
    for marker in ("*", "_", "`", "[", "]"):
        value = value.replace(marker, "\\" + marker)
    return html_std.escape(value, quote=False)


def inline_markdown(node) -> str:
    parts = [markdown_escape(node.text or "")]
    for child in node:
        if child.tag == "em":
            value = inline_markdown(child)
            literal = child.text_content()
            if literal[:1].isspace() or literal[-1:].isspace():
                parts.append("〔italic: " + value + "〕")
            else:
                parts.append("*" + value + "*")
        elif child.tag == "span":
            role = {"source-small-caps": "small caps", "source-reference-title-sub": "reference title subscript"}.get(child.get("class"))
            if role is None:
                raise ValueError("Unknown source style in readable companion")
            parts.append(f"〔{role}: {inline_markdown(child)}〕")
        elif child.tag == "br":
            parts.append("  \n")
        else:
            raise ValueError(f"Unexpected markup in readable source: {child.tag}")
        parts.append(markdown_escape(child.tail or ""))
    return "".join(parts)


def convert(payload: bytes) -> bytes:
    source = payload.decode("utf-8")

    def pre_replacement(match: re.Match[str]) -> str:
        node = html.fragment_fromstring("<div>" + match.group(1) + "</div>")
        return inline_markdown(node)

    value = PRE.sub(pre_replacement, source)

    def inline_replacement(match: re.Match[str]) -> str:
        node = html.fragment_fromstring("<div>" + match.group() + "</div>")
        return inline_markdown(node)

    value = INLINE.sub(inline_replacement, value)
    value = value.replace(
        "Italic and small-cap renditions follow the retained inline markup.",
        "Italic and small-cap renditions follow the retained inline markup; "
        "〔italic: ...〕 preserves italic spans whose source spaces prevent Markdown emphasis.",
    )
    value = re.sub(
        r"^(Continued in source order at .*)$",
        lambda match: match.group(1).replace(" > ", " / "),
        value,
        flags=re.MULTILINE,
    )
    if "<" in value or ">" in value or "\r" in value or "\x00" in value:
        raise ValueError("Release notice has HTML, a literal angle bracket, or invalid line endings")
    if not value.endswith("\n"):
        value += "\n"
    result = value.encode("utf-8")
    if not result or len(result) > 65536:
        raise ValueError("Release notice exceeds 64 KiB; split at a source field boundary")
    return result


def build(output: Path) -> dict:
    manifest_path = SOURCE / "manifest.json"
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if source_manifest["status"] != "pass" or source_manifest["nonverse_fields"] != 25145:
        raise ValueError("Complete checked readable companion required")
    parts = []
    for entry in source_manifest["parts"]:
        relative = Path(entry["path"])
        raw = (SOURCE / relative).read_bytes()
        if digest(raw) != entry["sha256"]:
            raise ValueError(f"Readable source part changed: {relative}")
        try:
            rendered = convert(raw)
        except ValueError as exc:
            raise ValueError(f"{relative}: {exc}") from exc
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(rendered)
        parts.append({"path": relative.as_posix(), "sha256": digest(rendered), "bytes": len(rendered), "member": entry["member"], "fields": entry["fields"]})
    result = {"status": "pass", "source_manifest_sha256": digest(manifest_path.read_bytes()), "source_crosswalk_sha256": digest((SOURCE / "private-crosswalk.json").read_bytes()), "source_candidate_sha256": source_manifest["source_sha256"], "notice_parts": len(parts), "nonverse_fields": source_manifest["nonverse_fields"], "literal_nonverse_bytes": source_manifest["literal_nonverse_bytes"], "parts": parts}
    (output / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    report = build(args.output)
    print(json.dumps({key: value for key, value in report.items() if key != "parts"}, indent=2))


if __name__ == "__main__":
    main()
