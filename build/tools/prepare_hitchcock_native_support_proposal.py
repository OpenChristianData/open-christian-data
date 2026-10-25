"""Prepare an unapplied, exact-identity Hitchcock lexical adapter proposal."""

from datetime import datetime, timezone
import difflib
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "ocd_kernel/projection/categories/reference_entries.py"
OUT = ROOT / "reports/_logs/hitchcocks-bible-names-dictionary-current-reconciliation-20261002-v1/native-support-proposal"
BEFORE = "ba8a1886ca39b06ba47adb5c4c06c24d118a24612385c0fc4673c212994c88bc"


def main() -> None:
    raw = MODULE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BEFORE:
        raise ValueError("Reference adapter immediate preimage changed")
    text = raw.decode("utf-8")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = text.replace("\r\n", "\n")

    def replace(old: str, new: str, count: int = 1) -> None:
        nonlocal text
        if text.count(old) != count:
            raise ValueError(f"Unexpected proposal match count for {old!r}")
        text = text.replace(old, new)

    replace('_EASTON_ROOT_ID = "eastons-bible-dictionary-candidate"', '''_EASTON_ROOT_ID = "eastons-bible-dictionary-candidate"
_HITCHCOCK_PROFILE = "hitchcock-native-lexical-v1"
_HITCHCOCK_IDENTITY = {
    "work_id": "hitchcocks-bible-names-dictionary",
    "textual_form_id": "hitchcocks-bible-names-dictionary-retained-electronic",
    "edition_id": "hitchcocks-bible-names-dictionary-retained-electronic-witness",
}
_HITCHCOCK_ROOT_ID = "hitchcocks-bible-names-dictionary-candidate"''')
    replace('''    if (selector["tei_entry_profile"] != _EASTON_PROFILE
            or any(identity.get(key) != value for key, value in _EASTON_IDENTITY.items())
            or root.get(XML_ID) != _EASTON_ROOT_ID):
        raise UnsupportedStructure("unsupported-visible: Easton native TEI profile/identity mismatch")''', '''    profiles = {
        _EASTON_PROFILE: (_EASTON_IDENTITY, _EASTON_ROOT_ID),
        _HITCHCOCK_PROFILE: (_HITCHCOCK_IDENTITY, _HITCHCOCK_ROOT_ID),
    }
    selected = selector.get("tei_entry_profile")
    if not isinstance(selected, str) or selected not in profiles:
        raise UnsupportedStructure("unsupported-visible: native lexical TEI profile/identity mismatch")
    expected_identity, expected_root = profiles[selected]
    if (any(identity.get(key) != value for key, value in expected_identity.items())
            or root.get(XML_ID) != expected_root):
        raise UnsupportedStructure("unsupported-visible: native lexical TEI profile/identity mismatch")''')
    replace('def _easton_lexical(entry: ET.Element, ordinal: int, paths: Mapping[ET.Element, str])', 'def _easton_lexical(entry: ET.Element, ordinal: int, paths: Mapping[ET.Element, str], *, work_id: str = "eastons-bible-dictionary")')
    replace('prefix = f"eastons-bible-dictionary-entry-{ordinal:05d}"', 'prefix = f"{work_id}-entry-{ordinal:05d}"', 3)
    replace('def _entries(parts: Sequence[ET.Element], scope: ET.Element | None, parents: Mapping[ET.Element, ET.Element], *, easton: bool = False)', 'def _entries(parts: Sequence[ET.Element], scope: ET.Element | None, parents: Mapping[ET.Element, ET.Element], *, easton: bool = False, work_id: str = "eastons-bible-dictionary")')
    replace('parents[parts[0]].get(XML_ID) != "eastons-bible-dictionary-text"', 'parents[parts[0]].get(XML_ID) != f"{work_id}-text"')
    replace('parts[0].get(XML_ID) != "eastons-bible-dictionary-body"', 'parts[0].get(XML_ID) != f"{work_id}-body"')
    replace('_easton_lexical(entry, source_order, paths)', '_easton_lexical(entry, source_order, paths, work_id=identity["work_id"])')
    replace('parents: Mapping[ET.Element, ET.Element], *, easton: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:', 'parents: Mapping[ET.Element, ET.Element], *, easton: bool = False, work_id: str = "eastons-bible-dictionary") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:')
    replace('_easton_lexical(entry, _source_order(entry, 0, paths), paths)', '_easton_lexical(entry, _source_order(entry, 0, paths), paths, work_id=work_id)')
    replace('_entries(parts, scope, parents, easton=easton)', '_entries(parts, scope, parents, easton=easton, work_id=identity_value["work_id"])')
    replace('_inventory(root, parts, all_entries, selected, paths, parents, easton=easton)', '_inventory(root, parts, all_entries, selected, paths, parents, easton=easton, work_id=identity_value["work_id"])')
    replace('    ns = {"t": TEI_NS}\n    texts = root.xpath', '    work_id = identity["work_id"]\n    ns = {"t": TEI_NS}\n    texts = root.xpath')
    replace('texts[0].get(XML_ID) != "eastons-bible-dictionary-text"', 'texts[0].get(XML_ID) != f"{work_id}-text"')
    replace('body.get(XML_ID) != "eastons-bible-dictionary-body"', 'body.get(XML_ID) != f"{work_id}-body"')
    after = text.replace("\n", newline).encode("utf-8")
    compile(after, str(MODULE), "exec")
    OUT.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "reference_entries.before.py": raw,
        "reference_entries.after.py": after,
        "patch.diff": "".join(difflib.unified_diff(raw.decode().splitlines(True), after.decode().splitlines(True), fromfile="before/reference_entries.py", tofile="after/reference_entries.py")).encode(),
    }
    design = {
        "status": "unapplied-proposal", "created_at": datetime.now(timezone.utc).isoformat(),
        "module": MODULE.relative_to(ROOT).as_posix(), "before_sha256": BEFORE,
        "after_sha256": hashlib.sha256(after).hexdigest(),
        "scope": "One exact Hitchcock profile/three-field identity/root opt-in; literal native prefix derives only from that validated identity. Existing Easton and default shapes unchanged.",
        "no_schema_changes": True,
        "independence": "Producer reads ElementTree orth/def; checker independently traverses lxml and reconstructs literal rows/inventory. Profile admission remains shared, corroborated by independent full JSONL-vs-TEI source proof.",
        "tests": ["Both identities positive, duplicate headwords and literal whitespace conserved", "Missing/unknown/swapped profile or identity/root rejected in both routes", "Native IDs, field order, omission/duplication and unknown attributes rejected", "Saved rows/receipt mutation rejected with producer/renderer disabled", "Existing generic reference-entry and Easton compatibility"],
    }
    artifacts["design.json"] = (json.dumps(design, indent=2) + "\n").encode()
    for name, payload in artifacts.items():
        path = OUT / name
        if path.exists() and path.read_bytes() != payload:
            raise FileExistsError(path)
        if not path.exists():
            path.write_bytes(payload)
    print(json.dumps(design))


if __name__ == "__main__":
    main()
