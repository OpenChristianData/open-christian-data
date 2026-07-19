"""CI guard: every source-transliteration lexicon entry must have a fixture file.

Guards the kernel-packaged source-transliteration lexicons.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
LEXICON_DIR = _REPO_ROOT / "ocd_kernel" / "lib" / "source_transliteration_lexicons"
FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "source_transliteration"


def test_source_transliteration_lexicons_dir_exists():
    assert LEXICON_DIR.exists(), f"Missing {LEXICON_DIR}"


def test_fixture_dir_exists():
    assert FIXTURE_DIR.exists(), f"Missing {FIXTURE_DIR}"


def test_every_lexicon_entry_has_fixture():
    """Every rule_id in every source-transliteration lexicon has a fixture file."""
    import yaml
    missing = []
    for yaml_path in sorted(LEXICON_DIR.glob("*.yaml")):
        content = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or []
        lang = yaml_path.stem
        for entry in content:
            rule_id = entry.get("rule_id", "")
            fixture_path = FIXTURE_DIR / lang / f"{rule_id.replace('.', '_')}.json"
            if not fixture_path.exists():
                missing.append(str(fixture_path))
    assert not missing, f"Missing fixtures for: {missing}"
