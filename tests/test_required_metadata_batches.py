"""Keep the approved work-specific translator repair bound to its evidence."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import SourceManifest

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "plans/2026-08-31-library-pipeline-redesign/artifacts"


def test_pelagians_translator_matches_work_specific_retained_assignment() -> None:
    evidence = json.loads((ARTIFACTS / "META-001/08-required-translator-evidence.json").read_text(encoding="utf-8"))
    source = evidence["primary_source"]
    content = resolve_repo_path(ROOT, source["path"]).read_bytes()
    assert hashlib.sha256(content).hexdigest() == source["sha256"]
    lines = content.decode("utf-8").splitlines()
    assignment = "\n".join(lines[2138:2144])
    assert "Against Two Letters of the Pelagians" in assignment
    assert "only the first was from the pen of Dr. Holmes" in assignment
    assert "the rest being the work of Dr. Robert Ernest Wallis" in assignment
    config = json.loads((ROOT / evidence["authority"]["path"]).read_text(encoding="utf-8"))
    assert config["translator"] == "Robert Ernest Wallis"
    assert config["contributors"] == ["Robert Ernest Wallis (translator)", "Philip Schaff (series editor)"]
    assert config["author"] == "Augustine of Hippo"


def test_repaired_config_is_bound_by_verified_source_manifest() -> None:
    evidence = json.loads((ARTIFACTS / "META-001/08-required-translator-evidence.json").read_text(encoding="utf-8"))
    original_raw = (ROOT / evidence["binding_dependency"]["path"]).read_bytes()
    assert hashlib.sha256(original_raw).hexdigest() == "fc1824fc52a968aff16cdfe42246a1f69fa3d3e2cd659d82aefbbf98dfd50d12"
    original = json.loads(original_raw)
    runtime_path = ROOT / "tests/fixtures/reconstruction-runtime/npnf105.source-manifest.json"
    current = json.loads(runtime_path.read_bytes())
    restored = deepcopy(current)
    for field in ("implementation_sha256", "import_closure_sha256"):
        restored["validator"][field] = original["validator"][field]
    assert restored == original
    manifest = SourceManifest.load(runtime_path, repository_root=ROOT)
    manifest.verify()
    row = manifest.record["authorities"][10]
    assert row["path"] == evidence["authority"]["path"]
    content = (ROOT / row["path"]).read_bytes()
    assert row["bytes"] == len(content)
    assert row["sha256"] == hashlib.sha256(content).hexdigest()


def test_npnf105_contents_assigns_each_work_translator() -> None:
    """The retained contents allocation governs every work, not the series editor."""
    import xml.etree.ElementTree as ET

    evidence = json.loads((ARTIFACTS / "META-002/39-npnf105-contents-allocation.json").read_text(encoding="utf-8"))
    content = resolve_repo_path(ROOT, evidence["source"]["path"]).read_bytes()
    assert hashlib.sha256(content).hexdigest() == evidence["source"]["sha256"]
    tree = ET.fromstring(content)

    def text_at(identifier: str) -> str:
        elements = [element for element in tree.iter() if element.get("id") == identifier or element.get("{http://www.w3.org/XML/1998/namespace}id") == identifier]
        assert len(elements) == 1, identifier
        return " ".join("".join(elements[0].itertext()).split())

    allocation = text_at("iii-p74")
    assert "marked wth an asterisk above were translated by Dr. Wallis" in allocation
    assert "the others by Dr. Holmes" in allocation
    scopes = [
        ("merits-forgiveness-sins", "iii-p10"),
        ("spirit-and-letter", "iii-p15"),
        ("nature-and-grace", "iii-p19"),
        ("perfection-in-righteousness", "iii-p24"),
        ("proceedings-of-pelagius", "iii-p28"),
        ("grace-of-christ-original-sin", "iii-p33"),
        ("marriage-and-concupiscence", "iii-p38"),
        ("soul-and-its-origin", "iii-p46"),
        ("against-two-letters-pelagians", "iii-p54"),
        ("grace-and-free-will", "iii-p61"),
        ("rebuke-and-grace", "iii-p66"),
        ("predestination-of-saints", "iii-p70"),
    ]
    for suffix, identifier in scopes:
        expected = "Robert Ernest Wallis" if text_at(identifier).startswith("*") else "Peter Holmes"
        config = json.loads((ROOT / f"sources/structured-text/augustine-{suffix}/config.json").read_text(encoding="utf-8"))
        assert config["translator"] == expected, suffix
        assert config["contributors"] == [f"{expected} (translator)", "Philip Schaff (series editor)"], suffix
    # Gift of Perseverance is a separately listed component of the existing
    # Predestination work scope and has the same starred translator allocation.
    assert text_at("iii-p72").startswith("*")
