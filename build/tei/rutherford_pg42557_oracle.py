"""Check Rutherford's source relationships independently of its converter."""

from hashlib import sha256
import json
from pathlib import Path
import platform
import re
import sys

from lxml import etree, html

NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _import_closure_sha256():
    paths = [Path(__file__), Path(html.__file__), Path(etree.__file__)]
    return sha256(_canonical([{"path": p.name, "sha256": sha256(p.read_bytes()).hexdigest()} for p in paths])).hexdigest()


def _oracle(manifest, candidate):
    raw = manifest.authority_path("retained-source").read_bytes()
    source = html.document_fromstring(raw, parser=html.HTMLParser(encoding="utf-8")).find("body")
    target = etree.fromstring(candidate.member_bytes("content.tei.xml"), etree.XMLParser(resolve_entities=False, no_network=True))
    text = target.find(f"{{{NS}}}text")
    findings = []
    norm = lambda e: " ".join("".join(e.itertext()).split())
    if source is None or text is None:
        raise ValueError("Missing source or TEI reading body")
    if norm(source) != norm(text):
        findings.append("Complete source body wording/order differs")
    footer = source.find("footer")
    excluded = set(footer.iter()) if footer is not None else set()
    selected = [e for e in source.iter() if e not in excluded and isinstance(e.tag, str)]
    headings = [(e.tag, norm(e)) for e in selected if re.fullmatch("h[1-6]", e.tag)]
    actual = [(e.get("rend", "").removeprefix("source-"), norm(e)) for e in text.iter(f"{{{NS}}}head")]
    if headings != actual:
        findings.append("Heading level, wording, or order differs")
    expected_ids = [e.get("id") for e in selected if e.get("id")]
    if footer is not None and footer.get("id"):
        expected_ids.append(footer.get("id"))
    if expected_ids != [e.get(XML_ID) for e in text.iter() if e.get(XML_ID)]:
        findings.append("Source anchors or their order differ")
    inline_tags = {"i", "em", "b", "strong", "small", "abbr", "cite", "sup", "sub", "ins", "span"}
    expected_emphasis = [(e.tag, e.get("class", ""), norm(e)) for e in selected
                         if e.tag in inline_tags and not (e.tag == "span" and "pagenum" in e.get("class", "").split())]
    actual_emphasis = [((e.get("rend") or "").split()[0], " ".join((e.get("rend") or "").split()[1:]), norm(e))
                       for e in text.iter(f"{{{NS}}}hi")]
    if expected_emphasis != actual_emphasis:
        findings.append("Inline emphasis or annotation order/content differs")
    numbered = [norm(e) for e in selected if e.tag == "h2" and re.match(r"^[IVXLCDM]+\.", norm(e))]
    if len(numbered) != 365:
        findings.append(f"Expected 365 letter headings, observed {len(numbered)}")
    for source_tag, target_tag in (("p", "p"), ("a", "ref"), ("img", "graphic")):
        if source_tag == "p":
            expected = [(e.get("id"), norm(e)) for e in selected if e.tag == "p"]
            observed = [(e.get(XML_ID), norm(e)) for e in text.iter(f"{{{NS}}}p") if e.get("rend") == "source-p"]
        elif source_tag == "a":
            expected = [(e.get("href"), norm(e)) for e in selected if e.tag == "a" and e.get("href")]
            observed = [(e.get("target"), norm(e)) for e in text.iter(f"{{{NS}}}ref")]
        else:
            expected = [(e.get("src"), e.get("alt")) for e in selected if e.tag == "img"]
            observed = [(e.get("url"), e.get("n")) for e in text.iter(f"{{{NS}}}graphic")]
        if expected != observed:
            findings.append(f"Ordered {source_tag} relationships differ")
    tables = [[[(norm(c), c.get("colspan"), c.get("rowspan")) for c in row if c.tag in ("td", "th")]
               for row in table.iter("tr")] for table in selected if table.tag == "table"]
    actual_tables = [[[(norm(c), c.get("cols"), c.get("rows")) for c in row]
                      for row in table.iter(f"{{{NS}}}row")] for table in text.iter(f"{{{NS}}}table")]
    if tables != actual_tables:
        findings.append("Table rows, cells, attachment, or spans differ")
    if not etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-validation-schema")))).validate(target):
        findings.append("TEI P5 schema failed")
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    if sha256(raw).hexdigest() != profile["source_sha256"]:
        findings.append("Source profile binding differs")
    roles = {a["role"]: a for a in manifest.record["authorities"]}
    result = {"status": "fail" if findings else "pass", "oracle_id": _oracle.oracle_id, "oracle_version": "1",
            "implementation_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "import_closure_sha256": _import_closure_sha256(),
            "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
            "source_manifest_sha256": manifest.sha256, "candidate_sha256": candidate.sha256,
            "profile_sha256": roles["complete-source-feature-profile"]["sha256"],
            "package_schema_sha256": roles["candidate-package-schema"]["sha256"],
            "source_sha256": roles["primary-source"]["sha256"],
            "xsd_sha256": roles["tei-validation-schema"]["sha256"],
            "policy_sha256": roles["independent-validation-policy"]["sha256"],
            "findings": findings}
    result["result_sha256"] = sha256(_canonical(result)).hexdigest()
    return result


_oracle.oracle_id = "ocd-rutherford-pg42557-independent-html-reader"
_oracle.oracle_version = "1"
