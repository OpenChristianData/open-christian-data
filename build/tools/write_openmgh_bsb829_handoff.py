"""Write one bsb829 handoff with exact source locators and frozen stage pins."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lxml import etree

from build.tools.audit_openmgh_bsb829_stages import AUDIT, PINS
from build.tools.stage_openmgh_bsb829_inspected import BATCH, PREFLIGHT, ROOT, SOURCE


HANDOFF = ROOT / "plans/2026-09-22-source-preflight/openmgh-bsb829-next-acceptance-stages-20260926.md"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write() -> Path:
    if HANDOFF.exists():
        raise ValueError("bsb829 handoff already exists")
    batch = json.loads((ROOT / BATCH).read_text(encoding="utf-8"))
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    preflight = json.loads((ROOT / PREFLIGHT).read_text(encoding="utf-8"))
    rows = {row["work_id"]: row for row in preflight["works"] if any(
        SOURCE.as_posix() in locator["reference"] for locator in row.get("locators", [])
    )}
    tree = etree.parse(str(ROOT / SOURCE))
    volume = tree.getroot().find("{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body/{http://www.tei-c.org/ns/1.0}div")
    id_to_div = {node.get("{http://www.w3.org/XML/1998/namespace}id"): ordinal
                 for ordinal, div in enumerate(volume, 1) for node in div.iter()
                 if node.get("{http://www.w3.org/XML/1998/namespace}id")}
    source_receipt = SOURCE.parent.parent / "acquisition-receipt.json"
    out = [
        "# openMGH bsb00000829 extracted XML — September 26, 2026",
        "",
        "**Status: 13 exact work-local electronic witness generations staged and independently preflighted; no canonical install.**",
        "",
        f"The retained text source is `{SOURCE.as_posix()}`, {batch['source_bytes']:,} bytes, SHA-256 `{batch['source_sha256']}`. Its [acquisition receipt](../../{source_receipt.as_posix()}) has SHA-256 `{_sha(ROOT / source_receipt)}`. The ZIP is the retained download package; the extracted XML alone supplies text and source-oracle comparison.",
        "",
        f"The volume has {batch['source_volume_work_div_count']} direct work divisions and {batch['inspected_identity_count']} declared work identities. Fifteen identities have exclusive whole-work divisions. The incomplete disputation and mixed Lamentatio/Excusatio division are held; the other thirteen are staged. Forty-eight more identities share source divisions and are held pending work-local part/range decisions. The [inspected batch receipt]({BATCH.name}) (SHA-256 `{_sha(ROOT / BATCH)}`) accounts for every identity, candidate, boundary, and exclusion.",
        "",
        "Each selected division has a source-checked opening, ending, neighboring label, full top-level part list, and no external fragment target. Each selected division's complete XML tree is preserved in its independently addressable TEI candidate. The source oracle checks element, attribute, text, and order equality; TEI P5 XSD checks structure. A fresh process reproduced each candidate. The staged master changes the reviewed header while retaining the candidate body. Source-evidenced Latin and the prose or poetry category are bound in each stage. Each actual staged master produced one row and passed its independent native checker. The bsb829 stage uses an in-process adapter for the shared normalizer while retaining the original bsb829 batch contract and exact receipt pin; it does not edit the shared route.",
        "",
        "| Work | Div / 21 | Category | Source XML IDs (first → last) | Stage receipt SHA-256 | Master SHA-256 |",
        "| --- | ---: | --- | --- | --- | --- |",
    ]
    for item in audit["works"]:
        work_id = item["work_id"]
        inspected = next(x for x in batch["works"] if x["work_id"] == work_id)
        ids = f"`#{inspected['start_xml_id']}` → `#{inspected['end_xml_id']}`"
        out.append(
            f"| `{work_id}` | {item['source_div_ordinal']} | {item['category']} | {ids} | "
            f"[{Path(item['stage_receipt']).name}]({Path(item['stage_receipt']).name}) `{item['stage_receipt_sha256']}` | "
            f"`{item['accepted_master_sha256']}` |"
        )
    out.extend([
        "",
        f"The [independent stage audit]({AUDIT.name}) (SHA-256 `{_sha(AUDIT)}`) matched {audit['candidate_files_checked']} candidate files, {audit['canonical_work_files_checked']} unchanged canonical work files, {audit['staged_work_files_checked']} staged work files, and {audit['source_sidecars_checked']} work-local source sidecars. The [frozen pins]({PINS.name}) (SHA-256 `{_sha(PINS)}`) bind the exact stage receipts, source XML, acquisition receipt, source evidence, and staging code.",
        "",
        "The bsb829 installer at `build/tools/install_openmgh_bsb829_next.py` defaults to read-only preflight and pins this exact receipt set. Its optional apply path uses the existing journaled work/profile/manifest transaction. The focused fixture check rejected a tampered source and receipt, rolled back after both source-sidecar swaps to the exact preimage, then completed an isolated install with one independently checked actual-master row. `tests/test_install_openmgh_bsb829_next.py` passed 2/2. Syntax and Ruff passed on the bsb829 files. No canonical apply or corpus view refresh was performed.",
        "",
        "## Holds with exact extracted-XML locators",
        "",
        "All IDs below are fragments of the pinned extracted XML path above. A shared volume container does not by itself establish a work-local selection.",
        "",
        "| Held work identity | Source div / 21 | Declared XML locator IDs | Reason |",
        "| --- | ---: | --- | --- |",
    ])
    for work_id in sorted(batch["holds"], key=lambda key: (id_to_div[rows[key]["locators"][0]["reference"].split("#", 1)[1]], key)):
        locators = [loc["reference"].split("#", 1)[1] for loc in rows[work_id]["locators"]]
        ordinal = id_to_div[locators[0]]
        if any(id_to_div[value] != ordinal for value in locators):
            raise ValueError(f"cross-div held locator: {work_id}")
        ids = "; ".join(f"`#{value}`" for value in locators)
        out.append(f"| `{work_id}` | {ordinal} | {ids} | {batch['holds'][work_id]} |")
    out.extend([
        "",
        "The source division and part boundaries named in this table are the next review loci. For the disputation, decide whether the unfinished electronic fragment can be an accepted fragment; for Lamentatio, separate the following Excusatio. The selected verse divisions preserve their source-native `ab`/`div` structure without inferred lines or stanzas.",
        "",
        "This staging does not establish close visual comparison, human acceptance, print collation, rights clearance, a refreshed corpus view, release selection, or publication. The scope remains the extracted electronic witness and its 13 selected divisions.",
        "",
    ])
    HANDOFF.write_text("\n".join(out), encoding="utf-8")
    return HANDOFF


def main() -> int:
    print(write())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
