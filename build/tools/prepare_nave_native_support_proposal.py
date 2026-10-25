"""Freeze an unapplied Nave-only topical dispatch successor for review."""

import difflib
import json
from pathlib import Path

from build.tools.prepare_nave_current import ROOT, LOG, digest, save, json_bytes


def main():
    directory = LOG / "native-support-proposal-v2"
    current = ROOT / "ocd_kernel/projection/categories/topical_indexes.py"
    before = current.read_bytes()
    # Capture all exact bytes for coordinator review; do not infer a full hash
    # from the short identity supplied by another owner.
    if not digest(before).startswith("35043166"):
        raise ValueError("Nave proposal requires frozen reviewed Torrey successor")
    text = before.decode().replace("\r\n", "\n")
    producer = "def project_topical_indexes_document(tei_path, *, identity, language, representation_revision, edition_title):\n"
    checker = "def verify_topical_indexes_document(tei_path, rows, receipt, *, identity, language, representation_revision, edition_title):\n    \"\"\"Recompute complete rows and receipt with an independent XPath traversal.\"\"\"\n"
    additions = [
        (producer, "    if identity.get('work_id') == 'naves-topical-bible':\n        from .topical_nave import project_nave_native\n        return project_nave_native(tei_path, identity=identity, language=language, representation_revision=representation_revision, edition_title=edition_title)\n"),
        (checker, "    if identity.get('work_id') == 'naves-topical-bible':\n        from .topical_nave import verify_nave_native\n        return verify_nave_native(tei_path, rows, receipt, identity=identity, language=language, representation_revision=representation_revision, edition_title=edition_title)\n"),
    ]
    for needle, addition in additions:
        if text.count(needle) != 1:
            raise ValueError("Exact topical dispatch seam differs")
        text = text.replace(needle, needle + addition)
    after = text.encode()
    # Preserve original line-ending materialization when constructing the delta.
    if b"\r\n" in before:
        after = after.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    module = ROOT / "build/tei/nave_native_projection_proposal.py"
    module_after = module.read_bytes().replace(b"parents[2]", b"parents[3]", 1)
    compile(module_after, "topical_nave.py", "exec")
    save(directory / "topical_indexes.before.py", before)
    save(directory / "topical_indexes.after.py", after)
    save(directory / "topical_nave.after.py", module_after)
    diff = "".join(difflib.unified_diff(before.decode().splitlines(keepends=True), after.decode().splitlines(keepends=True), fromfile="topical_indexes.before.py", tofile="topical_indexes.after.py"))
    save(directory / "dispatch.diff", diff.encode())
    design = {
        "status": "unapplied-proposal", "existing_file": current.relative_to(ROOT).as_posix(), "before_sha256": digest(before), "after_sha256": digest(after),
        "new_module": "ocd_kernel/projection/categories/topical_nave.py", "new_module_sha256": digest(module_after),
        "unchanged_surfaces": ["Torrey/default topical branches", "all schemas", "native_content", "native_content_check", "reference_entries", "acceptance/installer"],
        "scope": "Exact Nave work/form/edition/electronic title/source aggregate/config/root;5322ordered native entries. No fallback for unknown identity, markup or attribute.",
        "public_mapping": "One topic row for each entryFree, including duplicate keys. Literal dictionary key remains topic, distinct from payload@n. One complete def item; ordered source-classified scripture/topic refs retain exact visible label/target without parsing. Render literal text/tails with newline for lb and two-space-per-depth indentation for native list items. Master/private receipt preserve full native XML; no XML-preserving public claim.",
        "independent_checker": "Separate lxml traversal/rendering and complete row/private inventory reconstruction; no producer calls. Grammar constants/schema are shared declarative constraints; actual primary fidelity is separately proven with the binary source/native oracle and coordinator direct comparison.",
        "canonical_prerequisite": "Edition category alone absentâ†’topical-indexes; no canonical mutation before exact stage/preimages/root clearance.",
        "test_plan": ["Actual full5322candidate/P5/producer-disabled independent checker", "output omission/duplication/text/reference target/order/receipt alteration rejects", "source/header identity/namespaces/unknown attrs/omission/attachments reject by intended shape or saved receipt mismatch", "list depth and literal whitespace/source labels preserved", "default and Torrey exact unchanged branch compatibility"],
        "apply_condition": "Root reviewed exact before/after bytes and focused proof; wait until Torrey private release freeze closes. No schema changes.",
    }
    save(directory / "design.json", json_bytes(design))
    print(json.dumps(design))


if __name__ == "__main__":
    main()
