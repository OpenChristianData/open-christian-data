"""Create the current A41072 source profile, policy, and pinned manifest."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tei.fell_a41072_oracle import _closure_digest, _inspect


ROOT = Path(__file__).resolve().parents[2]
WORK = "fell-womens-speaking-justified"
LOCAL = ROOT / "sources/structured-text" / WORK
SOURCE = "raw/tcp/high-range/A41072/A41072.xml"
SOURCE_ID = "tcp-a41072-pinned-tei-p5"


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _binding(path: str, name: str, role: str) -> dict:
    content = (ROOT / path).read_bytes()
    return dict(name=name, path=path, role=role, bytes=len(content), sha256=sha256(content).hexdigest())


def main() -> None:
    source = (ROOT / SOURCE).read_bytes()
    _, counts, census, features = _inspect(source)
    readme = (LOCAL / "README.md").read_bytes()
    profile = dict(contract="ocd-tcp-a41072-complete-source-profile-v1", source_id=SOURCE_ID,
                   source_bytes=len(source), source_sha256=sha256(source).hexdigest(),
                   element_counts=counts, source_census=census, source_features=features)
    policy = dict(contract="ocd-tcp-a41072-exact-source-policy-v1", source_id=SOURCE_ID,
                  readme_sha256=sha256(readme).hexdigest(),
                  accountability=dict(contract="ocd-tcp-a41072-accountability-v1", source_path=SOURCE,
                                      projection="exact-source-bytes-v1", omitted_elements=0,
                                      duplicated_elements=0, unresolved_elements=0,
                                      representation="Full retained A41072 TEI, including source divisions, paratext, gaps, page breaks, encoded characters, text and tails"),
                  provenance=dict(contract="ocd-tcp-a41072-provenance-v1", status="nonaccepted",
                                  tcp_id="A41072", source_path=SOURCE,
                                  source_sha256=sha256(source).hexdigest(),
                                  download_url="https://raw.githubusercontent.com/textcreationpartnership/A41072/master/A41072.xml",
                                  rights_scope="TCP Phase I keyboarded and encoded text: CC0 1.0; no page images acquired or claimed",
                                  attribution="Text Creation Partnership requests due credit and attribution to the original source; see README.source.md",
                                  canonical_write=False, publication_authorized=False),
                  unresolved=[dict(id="fell-a41072-print-collation", status="unresolved",
                                   question="Will the TCP keying be collated with its print exemplar?",
                                   evidence="This exact-byte electronic witness includes no page images."),
                              dict(id="fell-a41072-human-review", status="unresolved",
                                   question="Will a human separately decide textual, identity, rights, and publication status?",
                                   evidence="Source preservation and technical validation do not provide those decisions.")],
                  required=["complete retained TEI source byte equality", "full element/text/attribute census",
                            "TCP A41072 source identity and source-defined divisions", "TEI P5 validity",
                            "visible TCP source attribution and text-only rights scope", "nonaccepted package status"])
    profile_name = f"sources/structured-text/{WORK}/{WORK}.reconstruction-profile.json"
    policy_name = f"sources/structured-text/{WORK}/{WORK}.validation-policy.json"
    _write(ROOT / profile_name, profile)
    _write(ROOT / policy_name, policy)
    converter = "build/tei/fell_a41072_reconstruction.py"
    oracle = "build/tei/fell_a41072_oracle.py"
    package_schema = "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"
    manifest = dict(contract="ocd-source-manifest-v1", source_id=SOURCE_ID,
                    authorities=[_binding(SOURCE, "retained-tei-p5", "primary-source"),
                                 _binding("raw/tcp/high-range/A41072/acquisition-receipt.json", "acquisition-receipt", "source-acquisition-evidence"),
                                 _binding(f"sources/structured-text/{WORK}/README.md", "source-local-attribution-readme", "source-attribution-readme"),
                                 _binding(profile_name, "reconstruction-profile", "complete-source-feature-profile"),
                                 _binding(policy_name, "validation-policy", "independent-validation-policy"),
                                 _binding("ocd_kernel/tei/vendor/xsd/tei_all.xsd", "tei-p5-xsd", "tei-validation-schema"),
                                 _binding(package_schema, "candidate-package-schema", "candidate-package-schema")],
                    converter=dict(id="ocd-tcp-a41072-exact-tei-p5", version="1", callable="_convert",
                                   implementation_path=converter, implementation_sha256=sha256((ROOT / converter).read_bytes()).hexdigest()),
                    validator=dict(id="ocd-tcp-a41072-exact-source-oracle", version="1", callable="_oracle",
                                   implementation_path=oracle, implementation_sha256=sha256((ROOT / oracle).read_bytes()).hexdigest(),
                                   import_closure_sha256=_closure_digest()),
                    package_schema=dict(path=package_schema, sha256=sha256((ROOT / package_schema).read_bytes()).hexdigest()))
    _write(LOCAL / f"{WORK}.source-manifest.json", manifest)
    print(json.dumps({"source_sha256": profile["source_sha256"], "element_count": census["elements"],
                      "manifest_sha256": sha256((LOCAL / f"{WORK}.source-manifest.json").read_bytes()).hexdigest()}, sort_keys=True))


if __name__ == "__main__":
    main()
