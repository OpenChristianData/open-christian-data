"""Prepare Nave's unchanged-body private release using the closed cached pattern."""

from pathlib import Path


def main():
    base = Path(__file__).resolve().parent
    text = (base / "complete_hitchcock_private_release.py").read_text(encoding="utf-8")
    text = text.replace("Hitchcock", "Nave").replace("hitchcock", "nave").replace("hitchcocks-bible-names-dictionary", "naves-topical-bible")
    text = text.replace("naves-bible-names-dictionary", "naves-topical-bible")
    text = text.replace("WORK_ID, SOURCE, SOURCE_SHA, digest", "WORK_ID, digest")
    text = text.replace("WORK, EDITION, ADAPTER_SHA", "WORK, EDITION, ADAPTER_SHA, DISPATCH_SHA, SOURCE_SHA")
    text = text.replace("categories.reference_entries", "categories.topical_indexes")
    text = text.replace("project_accepted_reference_entries", "project_accepted_topical_indexes").replace("verify_accepted_reference_entries", "verify_accepted_topical_indexes")
    text = text.replace("reference_entries", "topical_indexes").replace("reference-entries", "topical-indexes")
    text = text.replace('SOURCE_NOTICE = Path("sources/topical-indexes") / WORK_ID / "README.source.md"', 'SOURCE_NOTICE = Path("sources/topical-indexes") / WORK_ID / "README.source.md"\nSOURCE = ROOT / EDITION / "source-member-set.json"')
    text = text.replace('hash_path(ROOT / "ocd_kernel/projection/categories/topical_indexes.py") != ADAPTER_SHA', 'hash_path(ROOT / "ocd_kernel/projection/categories/topical_indexes.py") != DISPATCH_SHA or hash_path(ROOT / "ocd_kernel/projection/categories/topical_nave.py") != ADAPTER_SHA')
    text = text.replace('LOG / "native-support-proposal/coordinator-reviewed-freeze.json"', 'LOG / "native-support-proposal-v2/coordinator-adapter-clearance.json"')
    text = text.replace('"ocd_kernel/projection/categories/catechisms.py"', '"ocd_kernel/projection/categories/topical_nave.py"')
    text = text.replace('    direct_inputs += sorted((LOG / "notice-preflight-repair").glob("*"))\n    direct_inputs += [LOG / "private-release.log", LOG / "private-release.log.exit"]\n', '')
    text = text.replace('len(actual["rows"]) != 2622 or sum(len(row["definition_blocks"]) for row in actual["rows"]) != 2622', 'len(actual["rows"]) != 5322 or sum(len(item["references"]) for row in actual["rows"] for item in row["items"]) != 82303')
    text = text.replace('"rows": 2622, "definition_blocks": 2622', '"rows": 5322, "literal_references": 82303')
    text = text.replace('"rows": 2622', '"rows": 5322').replace('58229', '1410060')
    text = text.replace('nave-accepted-v1', 'nave-accepted-v1')
    text = text.replace('    direct_inputs += sorted((ROOT / "sources" / WORK_ID).glob("*"))', '''    direct_inputs += sorted((ROOT / "sources" / WORK_ID).glob("*"))
    direct_inputs += sorted((ROOT / "raw/naves_topical/modules/lexdict/zld/nave").glob("*"))
    direct_inputs += [ROOT / "raw/naves_topical/mods.d/nave.conf", ROOT / "raw/naves_topical/Nave.zip", LOG / "category-prerequisite-result.json"] if (LOG / "category-prerequisite-result.json").exists() else [ROOT / "raw/naves_topical/mods.d/nave.conf", ROOT / "raw/naves_topical/Nave.zip"]''')
    target = base / "complete_nave_private_release.py"
    if target.exists() and target.read_text(encoding="utf-8") != text:
        raise FileExistsError(target)
    compile(text, str(target), "exec")
    target.write_text(text, encoding="utf-8", newline="\n")
    print("Nave private release helper prepared; no release gates executed")


if __name__ == "__main__":
    main()
