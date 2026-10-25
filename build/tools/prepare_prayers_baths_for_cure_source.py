"""Create the current A47235 source profile, policy, and pinned manifest."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tei.prayers_baths_for_cure_oracle import _closure_digest, _inspect


ROOT = Path(__file__).resolve().parents[2]
WORK = "prayers-baths-for-cure"
LOCAL = ROOT / "sources/structured-text" / WORK
SOURCE = "raw/tcp/high-range/A47235/A47235.xml"
SOURCE_ID = "tcp-a47235-pinned-tei-p5"


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _binding(path: str, name: str, role: str) -> dict:
    content = (ROOT / path).read_bytes()
    return dict(name=name, path=path, role=role, bytes=len(content), sha256=sha256(content).hexdigest())


def main() -> None:
    source = (ROOT / SOURCE).read_bytes()
    if len(source) != 69708 or sha256(source).hexdigest() != "741b3c5faf5c90d1735563fc793fdc5cd7eebc9118d2707a731742f82f8e0117":
        raise ValueError("A47235 retained acquisition bytes drifted")
    _, counts, census, features = _inspect(source)
    readme = (LOCAL / "README.md").read_bytes()
    profile = dict(contract="ocd-tcp-a47235-complete-source-profile-v1", source_id=SOURCE_ID,
                   source_bytes=len(source), source_sha256=sha256(source).hexdigest(),
                   element_counts=counts, source_census=census, source_features=features)
    policy = dict(contract="ocd-tcp-a47235-exact-source-policy-v1", source_id=SOURCE_ID,
                  readme_sha256=sha256(readme).hexdigest(),
                  accountability=dict(contract="ocd-tcp-a47235-accountability-v1", source_path=SOURCE,
                                      projection="exact-source-bytes-v1", omitted_elements=0,
                                      duplicated_elements=0, unresolved_elements=0,
                                      representation="Full retained A47235 TEI, including title page, descriptive map, prayer division, headings, gaps, unclear text, page breaks, encoded characters, text and tails"),
                  provenance=dict(contract="ocd-tcp-a47235-provenance-v1", status="nonaccepted",
                                  tcp_id="A47235", source_path=SOURCE,
                                  source_sha256=sha256(source).hexdigest(),
                                  download_url="https://raw.githubusercontent.com/textcreationpartnership/A47235/master/A47235.xml",
                                  rights_scope="TCP Phase I keyboarded and encoded text: CC0 1.0; no page images acquired or claimed",
                                  attribution="Text Creation Partnership requests due credit and attribution to the original source; see README.source.md",
                                  canonical_write=False, publication_authorized=False),
                  unresolved=[dict(id="baths-a47235-print-collation", status="unresolved",
                                   question="Will the TCP keying be collated with its print exemplar?",
                                   evidence="This exact-byte electronic witness includes no page images."),
                              dict(id="baths-a47235-human-review", status="unresolved",
                                   question="Will a human separately decide textual, identity, rights, and publication status?",
                                   evidence="Source preservation and technical validation do not provide those decisions.")],
                  required=["complete retained TEI source byte equality", "full element/text/attribute census",
                            "TCP A47235 title-page map, prayer division, unclear text and encoded glyph", "TEI P5 validity",
                            "visible TCP source attribution and text-only rights scope", "nonaccepted package status"])
    profile_name = f"sources/structured-text/{WORK}/{WORK}.reconstruction-profile.json"
    policy_name = f"sources/structured-text/{WORK}/{WORK}.validation-policy.json"
    _write(ROOT / profile_name, profile)
    _write(ROOT / policy_name, policy)
    converter = "build/tei/prayers_baths_for_cure_reconstruction.py"
    oracle = "build/tei/prayers_baths_for_cure_oracle.py"
    package_schema = "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"
    manifest = dict(contract="ocd-source-manifest-v1", source_id=SOURCE_ID,
                    authorities=[_binding(SOURCE, "retained-tei-p5", "primary-source"),
                                 _binding("raw/tcp/high-range/A47235/acquisition-receipt.json", "acquisition-receipt", "source-acquisition-evidence"),
                                 _binding(f"sources/structured-text/{WORK}/README.md", "source-local-attribution-readme", "source-attribution-readme"),
                                 _binding(profile_name, "reconstruction-profile", "complete-source-feature-profile"),
                                 _binding(policy_name, "validation-policy", "independent-validation-policy"),
                                 _binding("ocd_kernel/tei/vendor/xsd/tei_all.xsd", "tei-p5-xsd", "tei-validation-schema"),
                                 _binding(package_schema, "candidate-package-schema", "candidate-package-schema")],
                    converter=dict(id="ocd-tcp-a47235-exact-tei-p5", version="1", callable="_convert",
                                   implementation_path=converter, implementation_sha256=sha256((ROOT / converter).read_bytes()).hexdigest()),
                    validator=dict(id="ocd-tcp-a47235-exact-source-oracle", version="1", callable="_oracle",
                                   implementation_path=oracle, implementation_sha256=sha256((ROOT / oracle).read_bytes()).hexdigest(),
                                   import_closure_sha256=_closure_digest()),
                    package_schema=dict(path=package_schema, sha256=sha256((ROOT / package_schema).read_bytes()).hexdigest()))
    _write(LOCAL / f"{WORK}.source-manifest.json", manifest)
    print(json.dumps({"source_sha256": profile["source_sha256"], "element_count": census["elements"],
                      "manifest_sha256": sha256((LOCAL / f"{WORK}.source-manifest.json").read_bytes()).hexdigest()}, sort_keys=True))


if __name__ == "__main__":
    main()
