"""Compile the vendored TEI XSD from a pinned, content-keyed snapshot.

The source files are read on every call.  Only successful ``XMLSchema``
compilations are reused, and the bounded process-local cache is never involved
in validating a candidate document.
"""

from __future__ import annotations

from collections import OrderedDict
from io import BytesIO
from pathlib import Path
from threading import RLock
from typing import Final
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from lxml import etree


_SCHEMA_FILENAMES: Final[tuple[str, ...]] = (
    "tei_all.xsd",
    "tei_all_xml.xsd",
    "tei_all_teix.xsd",
)
_CACHE_MAX_ENTRIES: Final[int] = 4
_COMPILED_SCHEMA_CACHE: OrderedDict[tuple[Path, str, tuple[bytes, ...]], etree.XMLSchema] = OrderedDict()
_CACHE_LOCK = RLock()
_FORBIDDEN_XML_MARKERS: Final[tuple[bytes, ...]] = (b"<!DOCTYPE", b"<!ENTITY")
_XSD_NAMESPACE = "http://www.w3.org/2001/XMLSchema"
_SCHEMA_REFERENCE_ELEMENTS: Final[frozenset[str]] = frozenset(
    {"import", "include", "redefine", "override"}
)


class TeiSchemaDependencyError(ValueError):
    """Raised when an XSD tries to resolve outside the pinned sibling set."""


def _read_schema_snapshots(directory: Path) -> dict[str, bytes]:
    """Read every authority file before checking any of the snapshots."""

    snapshots: dict[str, bytes] = {}
    for filename in _SCHEMA_FILENAMES:
        path = directory / filename
        try:
            snapshots[filename] = path.read_bytes()
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"vendored TEI schema sibling is missing: {path}"
            ) from exc

    parser = etree.XMLParser(
        load_dtd=False,
        no_network=True,
        resolve_entities=False,
        recover=False,
    )
    parsed_roots: dict[str, etree._Element] = {}
    doctype_files: list[str] = []
    for filename, content in snapshots.items():
        upper_content = content.upper()
        if any(marker in upper_content for marker in _FORBIDDEN_XML_MARKERS):
            doctype_files.append(filename)
        try:
            root = etree.fromstring(
                content,
                parser,
                base_url=str(directory / filename),
            )
        except etree.XMLSyntaxError as exc:
            raise TeiSchemaDependencyError(
                f"vendored schema is not a safely parseable XML document: {filename}"
            ) from exc
        parsed_roots[filename] = root
        if root.getroottree().docinfo.doctype:
            doctype_files.append(filename)

    if doctype_files:
        names = ", ".join(dict.fromkeys(doctype_files))
        raise TeiSchemaDependencyError(
            f"DTD or entity declarations are forbidden in vendored schema: {names}"
        )

    for filename, root in parsed_roots.items():
        for element in root.iter():
            if not isinstance(element.tag, str):
                continue
            namespace, _, local_name = element.tag.rpartition("}")
            if namespace != "{" + _XSD_NAMESPACE or local_name not in _SCHEMA_REFERENCE_ELEMENTS:
                continue
            location = element.get("schemaLocation")
            if not location:
                raise TeiSchemaDependencyError(
                    f"schema dependency has no schemaLocation in {filename}"
                )
            _dependency_path(location, directory)
    return snapshots


def _dependency_path(url: str, directory: Path) -> Path:
    """Resolve a loader URL while permitting only direct local siblings."""

    if not url:
        raise TeiSchemaDependencyError("schema dependency has no location")

    # lxml may provide an absolute native path for a file that was resolved
    # from a base URL.  Check this before interpreting URI schemes so that a
    # Windows drive letter is not mistaken for a URI scheme.
    native_path = Path(url)
    parsed = urlsplit(url)
    if native_path.is_absolute():
        raw_path = url
    elif parsed.scheme:
        if parsed.scheme.lower() != "file" or parsed.netloc not in ("", "localhost"):
            raise TeiSchemaDependencyError(f"unexpected external schema dependency: {url}")
        if parsed.query or parsed.fragment:
            raise TeiSchemaDependencyError(f"schema dependency URI has query or fragment: {url}")
        raw_path = url2pathname(unquote(parsed.path))
    else:
        if parsed.query or parsed.fragment:
            raise TeiSchemaDependencyError(f"schema dependency URI has query or fragment: {url}")
        raw_path = unquote(parsed.path)

    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = directory / candidate
    candidate = candidate.resolve()
    if candidate.parent != directory:
        raise TeiSchemaDependencyError(
            f"schema dependency is outside the pinned sibling directory: {url}"
        )
    if candidate.name not in _SCHEMA_FILENAMES:
        raise TeiSchemaDependencyError(f"unexpected schema dependency: {url}")
    return candidate


class _PinnedSchemaResolver(etree.Resolver):
    """Serve only the byte snapshots captured before compilation."""

    def __init__(self, directory: Path, snapshots: dict[str, bytes]) -> None:
        super().__init__()
        self._directory = directory
        self._snapshots = snapshots

    def resolve(self, url: str, pubid: str | None, context: object) -> object:
        del pubid
        path = _dependency_path(url, self._directory)
        # ``_dependency_path`` checks the name and direct parent.  Keep the
        # lookup explicit so a future change cannot silently read from disk.
        content = self._snapshots[path.name]
        return self.resolve_file(
            BytesIO(content),
            context,
            base_url=str(path),
        )


def _cache_key(
    directory: Path,
    root_name: str,
    snapshots: dict[str, bytes],
) -> tuple[Path, str, tuple[bytes, ...]]:
    """Build a key from the resolved source directory and exact file bytes."""

    return (
        directory,
        root_name,
        tuple(snapshots[filename] for filename in _SCHEMA_FILENAMES),
    )


def _compile_snapshot(
    root_path: Path,
    snapshots: dict[str, bytes],
) -> etree.XMLSchema:
    parser = etree.XMLParser(
        load_dtd=False,
        no_network=True,
        resolve_entities=False,
        recover=False,
    )
    parser.resolvers.add(_PinnedSchemaResolver(root_path.parent, snapshots))
    root = etree.fromstring(
        snapshots[root_path.name],
        parser,
        base_url=str(root_path),
    )
    return etree.XMLSchema(etree.ElementTree(root))


def compiled_tei_schema(xsd_path: str | Path) -> etree.XMLSchema:
    """Return a content-keyed compiled schema rooted at ``xsd_path``.

    ``xsd_path`` must name one of the three vendored sibling files.  All three
    are read on every invocation, then imports/includes are resolved only from
    those captured bytes.  A cache hit reuses compilation; candidate validation
    is intentionally outside this helper and is never cached here.
    """

    root_path = Path(xsd_path).expanduser().resolve()
    if root_path.name not in _SCHEMA_FILENAMES:
        raise ValueError(
            "compiled_tei_schema requires one of the vendored TEI XSD filenames"
        )
    directory = root_path.parent
    snapshots = _read_schema_snapshots(directory)
    key = _cache_key(directory, root_path.name, snapshots)

    with _CACHE_LOCK:
        cached = _COMPILED_SCHEMA_CACHE.get(key)
        if cached is not None:
            _COMPILED_SCHEMA_CACHE.move_to_end(key)
            return cached

        compiled = _compile_snapshot(root_path, snapshots)
        _COMPILED_SCHEMA_CACHE[key] = compiled
        _COMPILED_SCHEMA_CACHE.move_to_end(key)
        while len(_COMPILED_SCHEMA_CACHE) > _CACHE_MAX_ENTRIES:
            _COMPILED_SCHEMA_CACHE.popitem(last=False)
        return compiled


__all__ = ["TeiSchemaDependencyError", "compiled_tei_schema"]
