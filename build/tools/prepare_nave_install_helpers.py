"""Retain Nave-local guarded installer/rollback wrappers from the closed pattern."""

from pathlib import Path


def main():
    base = Path(__file__).resolve().parent
    text = (base / "install_hitchcock_current.py").read_text(encoding="utf-8")
    text = text.replace("Hitchcock", "Nave").replace("hitchcock", "nave").replace("reference-entries", "topical-indexes").replace("receipt[\"rows\"] != 2622", "receipt[\"rows\"] != 5322")
    text = text.replace("EDITION_ID, SOURCE_SHA, digest", "EDITION_ID, digest")
    text = text.replace("WORK, EDITION, TITLE", "WORK, EDITION, TITLE, SOURCE_SHA")
    old = '    print(json.dumps(install(ROOT, args.stage, args.receipt_sha256, args.evidence)))'
    new = '''    result = install(ROOT, args.stage, args.receipt_sha256, args.evidence)
    staged = json.loads((args.stage / "stage-receipt.json").read_bytes())
    notices = {}
    for relative, expected in staged["paired_notices"].items():
        raw = io_path(args.stage / relative).read_bytes()
        if digest(raw) != expected:
            raise PipelineError("Frozen staged Nave notice differs")
        save(ROOT / relative, raw)
        notices[relative] = digest(io_path(ROOT / relative).read_bytes())
    save(args.evidence / "notice-delivery.json", json_bytes({"status": "pass", "delivered": notices}))
    print(json.dumps(result))'''
    if old not in text:
        raise ValueError("Maintained installer entry point differs")
    text = text.replace(old, new)
    target = base / "install_nave_current.py"
    if target.exists() and target.read_text(encoding="utf-8") != text:
        raise FileExistsError(target)
    target.write_text(text, encoding="utf-8", newline="\n")
    text = (base / "prove_hitchcock_install_rollback.py").read_text(encoding="utf-8")
    text = text.replace("Hitchcock", "Nave").replace("hitchcock", "nave")
    target = base / "prove_nave_install_rollback.py"
    if target.exists() and target.read_text(encoding="utf-8") != text:
        raise FileExistsError(target)
    target.write_text(text, encoding="utf-8", newline="\n")
    compile((base / "install_nave_current.py").read_text(), "install_nave_current.py", "exec")
    compile(text, "prove_nave_install_rollback.py", "exec")
    print("Nave-local wrappers prepared; no installation performed")


if __name__ == "__main__":
    main()
