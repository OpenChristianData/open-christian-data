"""patch_kd_cross_refs.py

One-shot patch script: correct confirmed OCR/transcription errors in the
Keil-Delitzsch HelloAO source JSON files.  Each fix replaces a wrong biblical
citation in the raw commentary prose with the verified correct citation.

Fixes applied (all in raw/helloao_local/api/c/keil-delitzsch/):

  1. EZK/32.json    "Ezekiel 276:20"  -> "Ezekiel 26:20"
                    (extra '7' inserted by OCR; context = Ezek 26:20 pit/Sheol)

  2. ISA/57.json    "Ezra 23:17"      -> "Ezek 23:17"
                    (book name corrupted; context = concubitus = Ezek 23:17)

  3. HOS/*.json     "Amos 12:13"      -> "Amos 7:13"   (all 14 Hosea chapters)
                    (chapter 12->7; context = "king's sanctuary" = Amos 7:13)

  4. JOL/*.json     "Joel 9:13"       -> "Amos 9:13"   (all 3 Joel chapters)
                    (book name corrupted; context = mountains dripping wine = Amos 9:13)

  5. JOL/2.json     "Joel 2:39"       -> "Acts 2:39"
                    (book name corrupted; context = "promise is unto you and
                    your children" = Acts 2:39, Peter quoting Joel at Pentecost)

  6. DAN/7.json     "Mark 18:26"      -> "Mark 14:62"
                    (chapter 18->14, verse 26->62; context = Son of Man on clouds
                    = Mark 14:62, cited alongside Matt 24:30, Matt 26:64, Rev 1:7)

  7. NUM/1.json     "Num 38:25"       -> "Exod 38:25"
                    (book name corrupted; context = census contribution of
                    603,550 men = Exod 38:25-26)

Run: py -3 build/patch_kd_cross_refs.py
Idempotent: re-running produces no changes and prints 0 replacements per file.
"""

import json
import os

RAW_DIR = os.path.join(
    os.path.dirname(__file__), "..", "raw", "helloao_local", "api", "c", "keil-delitzsch"
)
RAW_DIR = os.path.normpath(RAW_DIR)


def patch_file(fpath, replacements):
    """Apply a list of (old, new) text replacements to a JSON file.

    Loads the file as raw text (preserving formatting), applies replacements,
    then round-trips through json.loads/dumps to verify the result is valid JSON.
    Returns the number of replacements made.
    """
    raw = open(fpath, encoding="utf-8").read()
    n_replaced = 0
    for old, new in replacements:
        count = raw.count(old)
        if count:
            raw = raw.replace(old, new)
            n_replaced += count
    # Verify valid JSON after patching
    try:
        json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Patch produced invalid JSON in {fpath} — restore from git and investigate: {exc}"
        ) from exc
    if n_replaced:
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(raw)
    return n_replaced


def main():
    total = 0

    # Fix 1: EZK/32.json -- "Ezekiel 276:20" -> "Ezekiel 26:20"
    fpath = os.path.join(RAW_DIR, "EZK", "32.json")
    n = patch_file(fpath, [("Ezekiel 276:20", "Ezekiel 26:20")])
    print(f"EZK/32.json: {n} replacement(s) -- Ezekiel 276:20 -> 26:20")
    total += n

    # Fix 2: ISA/57.json -- "Ezra 23:17" -> "Ezek 23:17"
    fpath = os.path.join(RAW_DIR, "ISA", "57.json")
    n = patch_file(fpath, [("Ezra 23:17", "Ezek 23:17")])
    print(f"ISA/57.json: {n} replacement(s) -- Ezra 23:17 -> Ezek 23:17")
    total += n

    # Fix 3: HOS/*.json -- "Amos 12:13" -> "Amos 7:13" (book intro repeated in all chapters)
    hos_dir = os.path.join(RAW_DIR, "HOS")
    hos_n = 0
    for fname in sorted(os.listdir(hos_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(hos_dir, fname)
        n = patch_file(fpath, [("Amos 12:13", "Amos 7:13")])
        hos_n += n
    print(f"HOS/*.json:  {hos_n} replacement(s) -- Amos 12:13 -> Amos 7:13")
    total += hos_n

    # Fix 4: JOL/*.json -- "Joel 9:13" -> "Amos 9:13" (book intro repeated in all chapters)
    jol_dir = os.path.join(RAW_DIR, "JOL")
    jol_n = 0
    for fname in sorted(os.listdir(jol_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(jol_dir, fname)
        n = patch_file(fpath, [("Joel 9:13", "Amos 9:13")])
        jol_n += n
    print(f"JOL/*.json:  {jol_n} replacement(s) -- Joel 9:13 -> Amos 9:13")
    total += jol_n

    # Fix 5: JOL/2.json -- "Joel 2:39" -> "Acts 2:39"
    fpath = os.path.join(RAW_DIR, "JOL", "2.json")
    n = patch_file(fpath, [("Joel 2:39", "Acts 2:39")])
    print(f"JOL/2.json:  {n} replacement(s) -- Joel 2:39 -> Acts 2:39")
    total += n

    # Fix 6: DAN/7.json -- "Mark 18:26" -> "Mark 14:62"
    fpath = os.path.join(RAW_DIR, "DAN", "7.json")
    n = patch_file(fpath, [("Mark 18:26", "Mark 14:62")])
    print(f"DAN/7.json:  {n} replacement(s) -- Mark 18:26 -> Mark 14:62")
    total += n

    # Fix 7: NUM/1.json -- "Num 38:25" -> "Exod 38:25"
    # The source text has "Num 38:25-26"; fixing the book name restores the
    # correct Exodus citation. The "-26" suffix is handled by parse_thml_refs
    # (range start only), so only the "Num 38:25" token matters for extraction.
    fpath = os.path.join(RAW_DIR, "NUM", "1.json")
    n = patch_file(fpath, [("Num 38:25", "Exod 38:25")])
    print(f"NUM/1.json:  {n} replacement(s) -- Num 38:25 -> Exod 38:25")
    total += n

    print(f"\nTotal replacements: {total}")
    if total == 0:
        print("(already applied -- idempotent re-run)")


if __name__ == "__main__":
    main()
