"""Rebind L605's exact sources, implementations, and validation authorities."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from ocd_kernel.lib.storage_topology import resolve_repo_path

FOLDER="sources/manifest-acquisitions/open-english-bible-2025-6"
def sha(data:bytes)->str: return hashlib.sha256(data).hexdigest()
def canonical(value:object)->bytes: return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode("utf-8")
def build_manifest(root:Path)->bytes:
    root=Path(root).resolve(strict=True)
    profile=json.loads((root/FOLDER/"profile.json").read_text(encoding="utf-8"))
    authorities=[]; source_members=[]
    def add(name,logical,role):
        path=resolve_repo_path(root,logical).resolve(strict=True); data=path.read_bytes()
        authorities.append({"name":name,"path":logical,"role":role,"bytes":len(data),"sha256":sha(data)})
    for variant in profile["variants"]:
        add(variant["archive"]["authority_name"],variant["archive"]["path"],"primary-source")
        add(variant["receipt"]["authority_name"],variant["receipt"]["path"],"source-acquisition-evidence")
        add(variant["inventory"]["authority_name"],variant["inventory"]["path"],"source-acquisition-evidence")
        for entry in variant["archive_entries"]:
            if entry["is_directory"]: continue
            name=entry["authority_name"]; logical=entry["extraction_path"]
            add(name,logical,"extracted-source-member")
            source_members.append({"name":name,"logical_name":entry["name"],"path":logical,"role":"extracted-source-member","bytes":entry["bytes"],"sha256":entry["sha256"]})
    for name,path,role in [
        ("readme",f"{FOLDER}/README.source.md","source-description"),
        ("profile",f"{FOLDER}/profile.json","complete-source-feature-profile"),
        ("policy",f"{FOLDER}/policy.json","independent-validation-policy"),
        ("profile-generator","build/tei/open_english_bible_2025_6_profile.py","source-accounting-generator"),
        ("manifest-generator","build/tei/open_english_bible_2025_6_manifest.py","source-manifest-generator"),
        ("converter-implementation","build/tei/open_english_bible_2025_6.py","converter-implementation"),
        ("validator-implementation","build/tei/open_english_bible_2025_6_oracle.py","independent-validator-implementation"),
        ("tei-validation-schema","ocd_kernel/tei/vendor/xsd/tei_all.xsd","tei-validation-schema"),
        ("candidate-package-schema","ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json","candidate-package-schema")]:
        add(name,path,role)
    by_name={x["name"]:x for x in authorities}
    converter={"id":"ocd-open-english-bible-2025-6-usfm-to-tei","version":"1","implementation_path":"build/tei/open_english_bible_2025_6.py","implementation_sha256":by_name["converter-implementation"]["sha256"],"callable":"_convert"}
    oracle_path=resolve_repo_path(root,"build/tei/open_english_bible_2025_6_oracle.py").resolve(strict=True)
    closure=sha(canonical([{"path":oracle_path.name,"sha256":sha(oracle_path.read_bytes())}]))
    validator={"id":"ocd-open-english-bible-2025-6-independent-source-oracle","version":"1","implementation_path":"build/tei/open_english_bible_2025_6_oracle.py","implementation_sha256":by_name["validator-implementation"]["sha256"],"import_closure_sha256":closure,"callable":"_oracle"}
    package_schema={"path":"ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json","sha256":by_name["candidate-package-schema"]["sha256"]}
    return canonical({"contract":"ocd-source-manifest-v1","source_id":profile["source_id"],"work_id":profile["work_id"],"authorities":authorities,"source_members":source_members,"converter":converter,"validator":validator,"package_schema":package_schema})
def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--write",action="store_true"); args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]; content=build_manifest(root)
    if args.write:
        output=root/FOLDER/"reconstruction-source-manifest.json"; output.write_bytes(content)
        print(f"wrote {output} ({len(content)} bytes, sha256 {sha(content)})")
    else: print(sha(content),len(content))
if __name__=="__main__": main()
