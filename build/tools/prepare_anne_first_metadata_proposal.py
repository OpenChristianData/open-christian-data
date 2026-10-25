"""Save an unapplied source-backed category/language amendment for Anne first."""

from __future__ import annotations

import difflib
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "library/works/anne-askew-first-examinacyon/work.json"
OUT = ROOT / "reports/_logs/anne-askew-first-private-release-20261002-v1"
BEFORE = "cf78e6942703699cb020bbcc5908436693f0112b94eee488d2c82f088e281ae4"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    original = WORK.read_bytes()
    if sha(original) != BEFORE:
        raise ValueError("Anne current work metadata preimage changed")
    value = json.loads(original)
    if value["work_id"] != "anne-askew-first-examinacyon" or len(value["textual_forms"]) != 1:
        raise ValueError("Anne work identity/form shape differs")
    form = value["textual_forms"][0]
    if form["textual_form_id"] != "anne-askew-first-examinacyon-tcp-retained" or len(form["editions"]) != 1:
        raise ValueError("Anne retained form differs")
    edition = form["editions"][0]
    if edition["edition_id"] != "anne-askew-first-examinacyon-tcp-electronic":
        raise ValueError("Anne retained edition differs")
    if any(key in form for key in ("language",)) or any(key in edition for key in ("category", "language")):
        raise ValueError("Anne metadata proposal fields already exist")
    form["language"] = "en"
    edition["language"] = "en"
    edition["category"] = "prose"
    successor = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    diff = "".join(difflib.unified_diff(original.decode().splitlines(True), successor.decode().splitlines(True), fromfile="before/work.json", tofile="after/work.json")).encode("utf-8")
    proposal = {
        "contract": "ocd-anne-first-metadata-proposal-v1",
        "status": "unapplied-for-coordinator-review",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "path": WORK.relative_to(ROOT).as_posix(),
        "before_sha256": BEFORE,
        "after_sha256": sha(successor),
        "diff_sha256": sha(diff),
        "fields": {"textual_forms[0].language": "en", "textual_forms[0].editions[0].language": "en", "textual_forms[0].editions[0].category": "prose"},
        "evidence": ["retained A22076 header language ident=eng and text xml:lang=eng", "distinct A22095 later examination uses prose/en categorization"],
        "scope": "No title, creator, print exemplar, acceptance, source, or master edit",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    for name, content in {
        "work-metadata-successor.json": successor,
        "work-metadata-proposal.patch": diff,
        "work-metadata-proposal.json": (json.dumps(proposal, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(),
    }.items():
        path = OUT / name
        with path.open("xb") as stream:
            stream.write(content)
    print(json.dumps({"status": proposal["status"], "before_sha256": BEFORE, "after_sha256": sha(successor), "proposal_sha256": sha((OUT / "work-metadata-proposal.json").read_bytes())}))


if __name__ == "__main__":
    main()
