"""Read-only character screening of TEI files and ZIP members in explicit roots."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import zipfile

from xml.parsers import expat

from build.lib.text_lint import lint_xml_file
from build.lib.text_xml_reader import MAX_PROLOG_BYTES, inspection_decoder
from ocd_kernel.lib.path_io import io_path, resolve_path


_XML_SUFFIXES = {".xml", ".tei", ".sgm", ".sgml"}
_EXCLUDED = {".git", "node_modules", "__pycache__", ".venv", "venv"}


class _RootFound(Exception):
    pass


def is_tei(stream) -> bool:
    """Classify only the root; full retained-byte screening remains independent."""
    parser = expat.ParserCreate(encoding="UTF-8", namespace_separator="}")
    name = None

    def first_root(tag, attributes):
        nonlocal name
        name = tag.rsplit("}", 1)[-1]
        raise _RootFound

    parser.StartElementHandler = first_root
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    chunk = stream.read(16384)
    # An ASCII declaration can span chunks; wait for its encoding attribute.
    while chunk.removeprefix(b"\xef\xbb\xbf").startswith(b"<?xml") and b"?>" not in chunk:
        if len(chunk) >= MAX_PROLOG_BYTES:
            raise ValueError("XML root exceeds the 1 MiB inspection limit")
        more = stream.read(16384)
        if not more:
            break
        chunk += more
    encoding, decoder = inspection_decoder(chunk)
    consumed = 0
    try:
        while chunk:
            consumed += len(chunk)
            if consumed > MAX_PROLOG_BYTES:
                raise ValueError("XML root exceeds the 1 MiB inspection limit")
            parser.Parse(decoder.decode(chunk, final=False), False)
            chunk = stream.read(16384)
        parser.Parse(decoder.decode(b"", final=True), True)
    except _RootFound:
        return name in {"TEI", "TEI.2", "teiCorpus"}
    except (expat.ExpatError, UnicodeError) as exc:
        raise ValueError(f"XML root parsing failed ({encoding}): {exc}") from exc
    return False


def scan_roots(roots: list[Path], output: Path) -> dict:
    output = resolve_path(output)
    io_path(output).mkdir(parents=True, exist_ok=False)
    rows, gaps, excluded, snapshots = [], [], [], []
    seen_paths, seen_hashes = set(), {}
    counts, totals = Counter(), Counter()
    implementations = {str(p): hashlib.sha256(io_path(p).read_bytes()).hexdigest()
                       for p in (Path(__file__).resolve(), Path(__file__).resolve().parents[1] / "lib/text_lint.py",
                                 Path(__file__).resolve().parents[1] / "lib/text_xml_reader.py")}

    def gap(path, error):
        gaps.append({"path": str(path), "error": str(error)})

    def screen(path, reference):
        with io_path(path).open("rb") as stream:
            raw_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        row = {"path": str(reference), "sha256": raw_hash}
        if raw_hash in seen_hashes:
            row.update(status="duplicate", duplicate_of=seen_hashes[raw_hash]["path"], result=seen_hashes[raw_hash]["status"])
        else:
            try:
                report = lint_xml_file(io_path(path))
                if report["source_sha256"] != raw_hash:
                    raise ValueError("TEI changed between hashing and screening")
                row.update(status="screened", characters=report["coverage"]["characters"], units=report["coverage"]["units"],
                           xml_reader=report["coverage"]["xml_reader"],
                           groups=report["groups"], groups_by_region=[dict(region=r, reading=b, rule=k, count=n)
                           for (r, b, k), n in Counter((o["region"], o["reading"], o["rule"]) for o in report["observations"]).items()])
                for observation in report["observations"]:
                    observation.update(tei_sha256=raw_hash, representative_path=str(reference), role=report["coverage"]["roles"][observation["locator"]])
                    findings.write(json.dumps(observation, ensure_ascii=True, sort_keys=True) + "\n")
                totals.update({g["rule"]: g["count"] for g in report["groups"]})
            except (OSError, ValueError, RecursionError) as error:
                row.update(status="not_screened", error=str(error))
            seen_hashes[raw_hash] = row
        rows.append(row)
        if len(rows) % 100 == 0:
            print(json.dumps({"tei_paths": len(rows), "unique_contents": len(seen_hashes), "gaps": len(gaps)}), flush=True)

    with io_path(output / "observations.jsonl").open("w", encoding="utf-8", newline="\n") as findings:
        for requested in roots:
            try:
                root = resolve_path(requested, strict=True)
            except OSError as error:
                gap(requested, error)
                continue
            stack = [root]
            while stack:
                directory = stack.pop()
                try:
                    with os.scandir(io_path(directory)) as entries:
                        children = sorted(entries, key=lambda e: e.name)
                    for entry in children:
                        path = directory / entry.name
                        if str(path).casefold() in seen_paths:
                            continue
                        seen_paths.add(str(path).casefold())
                        try:
                            info = entry.stat(follow_symlinks=False)
                            if entry.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                                excluded.append({"path": str(path), "reason": "reparse point; explicit physical roots only"})
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                if entry.name in _EXCLUDED:
                                    excluded.append({"path": str(path), "reason": "development dependency or Git metadata"})
                                else:
                                    stack.append(path)
                                continue
                            counts["files_discovered"] += 1
                            suffix = path.suffix.lower()
                            if suffix not in _XML_SUFFIXES | {".zip", ".gz", ".tgz", ".tar", ".7z", ".rar"}:
                                continue
                            snapshots.append((path, info.st_size, info.st_mtime_ns))
                            if suffix in _XML_SUFFIXES:
                                counts["xml_files"] += 1
                                try:
                                    with io_path(path).open("rb") as stream:
                                        tei = is_tei(stream)
                                except ValueError as error:
                                    gap(path, "XML root could not be classified: " + str(error))
                                    continue
                                if tei or path.name.lower().endswith((".tei", ".tei.xml")):
                                    screen(path, path)
                            elif suffix == ".zip":
                                counts["zip_files"] += 1
                                with zipfile.ZipFile(io_path(path)) as archive:
                                    for index, member in enumerate(archive.infolist()):
                                        if member.is_dir() or Path(member.filename).suffix.lower() not in _XML_SUFFIXES:
                                            continue
                                        reference = f"{path}!/{member.filename}#entry={index}"
                                        counts["zip_xml_members"] += 1
                                        try:
                                            with archive.open(member) as stream:
                                                tei = is_tei(stream)
                                            if not tei and not member.filename.lower().endswith((".tei", ".tei.xml")):
                                                continue
                                            with tempfile.TemporaryDirectory(prefix="tei-screen-") as temporary:
                                                copy = Path(temporary) / "member.xml"
                                                with archive.open(member) as source, copy.open("wb") as target:
                                                    while chunk := source.read(1024 * 1024):
                                                        target.write(chunk)
                                                screen(copy, reference)
                                        except (OSError, ValueError, zipfile.BadZipFile, NotImplementedError, RuntimeError) as error:
                                            gap(reference, error)
                            else:
                                gap(path, "Archive format needs a dedicated member reader")
                        except (OSError, ValueError, zipfile.BadZipFile, NotImplementedError, RuntimeError) as error:
                            gap(path, error)
                except OSError as error:
                    gap(directory, error)
    drift = []
    for path, size, modified in snapshots:
        try:
            info = io_path(path).stat()
            if (info.st_size, info.st_mtime_ns) != (size, modified):
                drift.append(str(path))
        except OSError as error:
            drift.append(str(path))
            gap(path, error)
    failures = sum(r["status"] == "not_screened" for r in seen_hashes.values())
    summary = dict(status="partial" if gaps or drift or failures else "completed", at=datetime.now(timezone.utc).isoformat(),
                   roots=[str(p) for p in roots], counts=dict(counts), tei_paths=len(rows), unique_contents=len(seen_hashes),
                   unique_screened=sum(r["status"] == "screened" for r in seen_hashes.values()), unique_not_screened=failures,
                   observation_counts_unique_content=dict(totals), gaps=gaps, excluded=excluded, input_metadata_drift=drift,
                   implementation_sha256=implementations,
                   limits="Advisory character observations, not spelling/fidelity certification. Bounded internal general entities are expanded without external retrieval; external text/parameter dependencies remain gaps. ZIP XML/TEI members are inspected; other archives remain explicit gaps. Reparse paths are not followed. Files added after directory enumeration are outside this non-atomic snapshot; final drift check compares size and mtime, not a second whole-tree hash.")
    for name, value in (("files.json", rows), ("summary.json", summary)):
        io_path(output / name).write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = scan_roots(args.root, args.output)
    print(json.dumps({k: v for k, v in report.items() if k not in {"gaps", "excluded"}}, ensure_ascii=True, sort_keys=True))
    raise SystemExit(0 if report["status"] == "completed" else 1)


if __name__ == "__main__":
    main()
