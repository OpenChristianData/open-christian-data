# OCD Project Journal

Permanent historical record. Newest entries at top. Never trimmed.

---

## 2026-03-31 — Registry: Church Fathers (317 missing authors)

### What was done

Extended `data/authors/registry.json` from 40 to 357 entries by adding all
317 church fathers authors that were producing "Author not in registry" warnings
from the validator.

**Scripts written:**
- `build/scripts/extend_author_registry.py` — adds 317 entries, idempotent
- `build/scripts/patch_author_registry.py` — 17 sourced corrections from
  external verification pass (Wikipedia, Britannica, CCEL, OrthodoxWiki)

**Corrections applied during verification:**
- `andreas-of-caesarea` — dates cleared to null (637 unsupported)
- `arethas-of-caesarea` — death year 935 -> 939
- `theophylact-of-ohrid` — death year 1126 -> null (unsupported)
- `haimo-of-auxerre` — birth year 840 -> null (fabricated)
- `walafrid-strabo` — removed false attribution of Glossa Ordinaria to him
- `agapius-of-hierapolis` — tradition ["patristic"] -> ["orthodox"] (10th-c. Melkite, post-schism)
- `severus-of-antioch`, `jacob-of-edessa`, `cosmas-of-maiuma`, `abba-poemen`,
  `isaac-of-nineveh` — removed "orthodox" (all pre-1054; no strong exception)
- `john-wesley` — added "wesleyan" and "anglican" to tradition
- `cs-lewis` — nationality "British" -> "Irish" (self-identified)
- `gk-chesterton` — display_name corrected to "G. K. Chesterton"; "GK Chesterton"
  demoted to alias (to match structured-text data files)

**Pre-1054 "strong reason" exceptions kept as ["patristic", "orthodox"]:**
John Damascene, Maximus the Confessor, Andrew of Crete, Romanos the Melodist,
Sophronius of Jerusalem, Photios I, Desert Fathers.

### Final state

`py -3 build/validate.py --all` -- 0 errors, 163 warnings.

Remaining warnings:
- ~150 x "missing source_title" completeness warnings (pre-existing, across many datasets)
- 13 x "Author not in registry" from non-church-fathers datasets

### Next session prompt

Prompt ready in:
`02 PERSONAL/Open Christian Data/READY_TO_PASTE_PROMPTS.md`
-- "Registry: Non-Church-Fathers authors (13 missing + source_title gaps)"
