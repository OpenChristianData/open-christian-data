"""Generate the reviewed 21-work, config-free exclusive-manifest packet."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ocd_kernel.library._common import PipelineError, write_json


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = "plans/2026-09-22-source-preflight/whole-library-handoff-inventory-20260926.json"
OUTPUT = "plans/2026-09-22-source-preflight/exclusive-single-manifest-21-sidecar-batch-20260926.json"


def _ref(path: str) -> dict[str, str]:
    return {"path": path, "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest()}


SOURCES = {
    "baltimore-catechism-no-2": ("Project Gutenberg", "https://www.gutenberg.org/ebooks/14552", "metadata/source-evidence/catalog/baltimore-catechism-no-2.json"),
    "catechism-for-young-children": ("NonlinearFruit/Creeds.json", "https://github.com/NonlinearFruit/Creeds.json", "sources/catechism-for-young-children/LIB-062.README.md"),
    "darby": ("scrollmapper/bible_databases", "https://github.com/scrollmapper/bible_databases", "sources/bible-text/darby/config.json"),
    "didache-prayers": ("Wikisource", "https://en.wikisource.org/wiki/Didache_(Lake_translation)", "sources/prayers/didache/config.json"),
    "donne-devotions-upon-emergent-occasions": ("Project Gutenberg", "https://www.gutenberg.org/ebooks/23772", "sources/structured-text/donne-devotions-upon-emergent-occasions/LIB-068.README.source.md"),
    "eastons-bible-dictionary": ("JWBickel/BibleDictionaries", "https://huggingface.co/datasets/JWBickel/BibleDictionaries", "sources/eastons-bible-dictionary/README.md"),
    "hitchcocks-bible-names-dictionary": ("JWBickel/BibleDictionaries", "https://huggingface.co/datasets/JWBickel/BibleDictionaries", "sources/hitchcocks-bible-names-dictionary/README.md"),
    "newman-apologia-pro-vita-sua": ("Project Gutenberg", "https://www.gutenberg.org/ebooks/22088", "sources/structured-text/newman-apologia-pro-vita-sua/LIB-068.README.source.md"),
    "rutherford-letters": ("Christian Classics Ethereal Library", "https://www.ccel.org/ccel/rutherford/letters.xml", "metadata/source-evidence/catalog/rutherford-letters.json"),
    "schleitheim-confession-1527": ("Anabaptists.org", "https://www.anabaptists.org/history/the-schleitheim-confession.html", "sources/doctrinal-documents/schleitheim-confession-1527/config.json"),
    "smiths-bible-dictionary": ("JWBickel/BibleDictionaries", "https://huggingface.co/datasets/JWBickel/BibleDictionaries", "sources/smiths-bible-dictionary/README.md"),
    "sum-of-saving-knowledge": ("The Westminster Standard", "https://thewestminsterstandard.org/the-sum-of-saving-knowledge/", "sources/doctrinal-documents/sum-of-saving-knowledge/config.json"),
    "torreys-topical-textbook": ("JWBickel/BibleDictionaries", "https://huggingface.co/datasets/JWBickel/BibleDictionaries", "sources/torreys-topical-textbook/README.md"),
    "westminster-larger-catechism": ("NonlinearFruit/Creeds.json", "https://github.com/NonlinearFruit/Creeds.json", "sources/westminster-larger-catechism/LIB-062.README.md"),
    **{f"schaff-history-vol-{number}": (
        "Christian Classics Ethereal Library",
        f"https://www.ccel.org/ccel/schaff/hcc{number}.xml",
        f"sources/structured-text/schaff-history-vol-{number}/config.json",
    ) for number in (1, 2, 3, 5, 6, 7, 8)},
}

MEDIA_TYPES = {".txt": "text/plain", ".json": "application/json",
               ".jsonl": "application/x-ndjson", ".xml": "application/xml",
               ".html": "text/html"}


def generate() -> dict[str, object]:
    inventory = json.loads((ROOT / INVENTORY).read_text(encoding="utf-8"))
    indexed = {work["work_id"]: work for work in inventory["works"]}
    if len(SOURCES) != 21 or not set(SOURCES).issubset(indexed):
        raise PipelineError("exclusive manifest 21-work census changed")
    entries = []
    for wid, (provider, url, url_evidence) in sorted(SOURCES.items()):
        item = indexed[wid]
        if (item["handoff_group"] != "explicit-source-manifest"
                or item["editions"] or len(item["source_manifests"]) != 1):
            raise PipelineError(f"{wid} current inventory group changed")
        manifest_info = item["source_manifests"][0]
        if manifest_info.get("work_ids") != [wid] or manifest_info.get("config_bindings"):
            raise PipelineError(f"{wid} manifest is not exclusively config-free")
        manifest_ref = _ref(manifest_info["path"])
        if manifest_ref["sha256"] != manifest_info["sha256"]:
            raise PipelineError(f"{wid} handoff manifest hash changed")
        manifest = json.loads((ROOT / manifest_ref["path"]).read_text(encoding="utf-8"))
        primary = [a for a in manifest["authorities"] if a.get("role") == "primary-source"]
        if len(primary) != 1 or primary[0]["path"].lower().endswith(".zip"):
            raise PipelineError(f"{wid} retained textual source is not singular")
        source = primary[0]
        if url not in (ROOT / url_evidence).read_text(encoding="utf-8"):
            raise PipelineError(f"{wid} URL is absent from local evidence")
        if (ROOT / source["path"]).stat().st_size != source["bytes"] or _ref(source["path"])["sha256"] != source["sha256"]:
            raise PipelineError(f"{wid} retained source bytes changed")
        warnings = [
            "Rights and attribution for this exact retained electronic witness require source-specific review; acquired status does not mean accepted TEI or publication authorization.",
            "The retained member establishes an electronic witness only; print-edition identity and completeness require separate review.",
        ]
        if provider == "Project Gutenberg":
            warnings.append("Preserve the Project Gutenberg header, license, and production credits in any downstream use; the retained notice instructs users outside the United States to check local law.")
        elif provider == "JWBickel/BibleDictionaries":
            warnings.append("Credit JWBickel/BibleDictionaries; the modern structured JSONL license is unresolved.")
        elif provider == "NonlinearFruit/Creeds.json":
            warnings.append("The provider README grants Unlicense to this non-exception member; preserve the source-local attribution notice and embedded historical SourceUrl separately.")
        elif provider == "Christian Classics Ethereal Library":
            warnings.append("Preserve CCEL source attribution and distinguish its electronic file from any claimed print edition.")
        elif provider == "Wikisource":
            warnings.append("Retained PD-old and PD-US templates are source claims; Wikisource contribution and translation rights remain to be checked.")
        elif wid == "schleitheim-confession-1527":
            warnings.append("The hosted English translation carries Rod and Staff Publishers attribution context; its rights are unresolved.")
        scope = (f"Complete retained textual member {source['path']}; this electronic witness "
                 "does not establish print-edition identity, accepted TEI, rights clearance, "
                 "or publication authorization.")
        entries.append({
            "work_id": wid,
            "work": _ref(f"library/works/{wid}/work.json"),
            "state": _ref(f"library/works/{wid}/state.json"),
            "source_manifest": manifest_ref,
            "metadata_evidence": _ref(f"metadata/source-evidence/catalog/{wid}.json"),
            "url_evidence": _ref(url_evidence),
            "primary_source": source,
            "textual_form_id": f"{wid}-retained-electronic",
            "edition_id": f"{wid}-retained-electronic-witness",
            "acquisition_id": f"{wid}-retained-source",
            "edition_title": f"{provider} retained electronic witness",
            "provider": provider,
            "url": url,
            "language": "en",
            "media_type": MEDIA_TYPES[Path(source["path"]).suffix.lower()],
            "source_scope": scope,
            "warnings": warnings,
        })
    return {"contract": "ocd-library-sidecar-batch-v1", "entries": entries}


if __name__ == "__main__":
    write_json(ROOT / OUTPUT, generate())
    print(f"wrote {len(SOURCES)} entries to {OUTPUT}")
