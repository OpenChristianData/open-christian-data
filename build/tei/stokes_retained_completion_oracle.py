"""Independent direct retained-source/actual-readable-DOM Stokes review."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from copy import deepcopy
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from lxml import etree

from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts

ROOT = Path(__file__).resolve().parents[2]
NS = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE = {
    "stokes-expositoracts1": ("raw/ccel/expositors-bible/stokes_expositoracts1.xml", "a6d7b301d9fd13ff5d298093eca5caa7463505684b0e4eae951ef2fc0fda34f6", 4669, 4612, ["xxiv", "xxv"]),
    "stokes-expositoracts2": ("raw/ccel/expositors-bible/stokes_expositoracts2.xml", "2f6cbaf722c823db42d7e63dda7b6ef17f691bc83e7fedc563df51440d15edf8", 5892, 5827, ["xxii", "xxiii"]),
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


_IMPORT_PATHS = (
    'ocd_kernel/__init__.py', 'ocd_kernel/lib/__init__.py',
    'ocd_kernel/lib/path_io.py', 'ocd_kernel/lib/storage_topology.py',
    'ocd_kernel/reconstruction/__init__.py',
    'ocd_kernel/reconstruction/contract.py', 'ocd_kernel/reconstruction/verifier.py',
)


def _fresh_import_paths(root):
    script = '''
import importlib.util, json, sys
from pathlib import Path
root = Path(sys.argv[1]).resolve(strict=True)
sys.path.insert(0, str(root))
before = set(sys.modules)
spec = importlib.util.spec_from_file_location('_stokes_closure_probe', root / 'build/tei/stokes_retained_completion_oracle.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
paths = set()
for name in set(sys.modules) - before:
    filename = getattr(sys.modules[name], '__file__', None)
    if filename is None or name == spec.name: continue
    try: paths.add(Path(filename).resolve(strict=True).relative_to(root).as_posix())
    except ValueError: pass
print(json.dumps(sorted(paths)))
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(root)], check=True, capture_output=True, text=True)
    paths = json.loads(result.stdout)
    if not isinstance(paths, list) or not all(isinstance(x, str) for x in paths):
        raise ValueError('Stokes fresh first-party import probe malformed')
    return tuple(paths)


def _closure(root=ROOT):
    root = root.resolve(strict=True)
    observed = _fresh_import_paths(root)
    if observed != _IMPORT_PATHS:
        raise ValueError(f'Stokes first-party import closure changed: expected {_IMPORT_PATHS!r}, observed {observed!r}')
    return sha(canonical({name: sha((root / name).read_bytes()) for name in observed}))


def _import_closure_sha256(repository_root):
    return _closure(repository_root)


def check(member_id, tei_bytes, account_bytes, *, root=ROOT):
    rel, digest, full_count, body_count, backs = SOURCE[member_id]
    raw = (root / rel).read_bytes()
    if sha(raw) != digest:
        raise ValueError("Stokes independent raw identity changed")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, remove_comments=False, remove_pis=False, huge_tree=True)
    source = etree.fromstring(raw, parser)
    body = source.find("ThML.body")
    tree = etree.fromstring(tei_bytes, parser)
    schema = etree.XMLSchema(etree.parse(str(root / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")))
    schema.assertValid(tree)
    text = tree.find(NS + "text")
    if text is None or [x.tag for x in text] != [NS + p for p in ["front", "body", "back"]]:
        raise ValueError("Stokes independent native regions changed")
    if text[0].text != body.text or text[1].text or text[2].text:
        raise ValueError("Stokes independent readable body envelope differs")
    expected_regions = {"front": ["i", "ii", "iii"], "body": [], "back": backs}
    expected_regions["body"] = [x.get("id") for x in body if isinstance(x.tag, str) and x.get("id") not in expected_regions["front"] + backs]
    for part in text:
        if [x.get(XML_ID) for x in part if isinstance(x.tag, str)] != [member_id + "-" + k for k in expected_regions[etree.QName(part).localname]]:
            raise ValueError("Stokes source front/chapters/printed-and-generated-index attachment differs")
    nodes = []
    def walk(parent, path=()):
        for index, child in enumerate(parent):
            child_path = path + (index,)
            nodes.append((child_path, child))
            walk(child, child_path)
    walk(body)
    if sum(isinstance(x.tag, str) for x in source.iter()) != full_count or sum(isinstance(x.tag, str) for x in body.iter()) != body_count:
        raise ValueError("Stokes independent complete source census differs")
    # Independently derive the bounded administrative-comment whitespace join.
    # Actual readable content is checked against this source view, never a ledger.
    readable_source = deepcopy(body)
    original_elements = [x for x in body.iter() if isinstance(x.tag, str)]
    readable_elements = [x for x in readable_source.iter() if isinstance(x.tag, str)]
    readable_by_source = dict(zip(original_elements, readable_elements, strict=True))
    allowed_comments = {'added reason="AutoIndexing"', '/added'}
    for kind in ['scripCom', 'cite', 'foreign', 'pb']:
        allowed_comments.add('added reason="insertIndex" class="' + kind + '"')
    for kind in ['scripCom', 'cite', 'foreign']:
        allowed_comments.update(['Start of automatically inserted ' + kind + ' index', 'End of ' + kind + ' index'])
    allowed_comments.update(['Start of automatically inserted pb index', 'End of page index'])
    for comment in list(readable_source.iter()):
        if isinstance(comment.tag, str): continue
        if comment.tag is not etree.Comment or (comment.text or '').strip() not in allowed_comments or (comment.tail or '').strip():
            raise ValueError('Stokes unknown or meaningful administrative source comment')
        parent = comment.getparent(); previous = comment.getprevious()
        if comment.tail is not None:
            if previous is None: parent.text = (parent.text or '') + comment.tail
            else: previous.tail = (previous.tail or '') + comment.tail
        parent.remove(comment)
    actual = [node for part in text for child in part for node in child.iter()]
    if len(actual) != len(nodes) - 18 or any(not isinstance(x.tag, str) for x in actual):
        raise ValueError("Stokes actual readable feature/comment count differs")
    account = json.loads(account_bytes)
    if account.get("feature_count") != len(nodes) or len(account.get("features", [])) != len(nodes):
        raise ValueError("Stokes source account census differs")
    id_set = {node.get("id") for _, node in nodes if isinstance(node.tag, str) and node.get("id")}
    broken = [(node.get('id'), node.get('href')) for _, node in nodes if isinstance(node.tag, str) and node.tag == 'a' and (node.get('href') or '').startswith('#') and node.get('href')[1:] not in id_set]
    expected_broken = [('xxiv-p1.462', '#Five'), ('xxiv-p1.723', '#Five')] + [(None, href) for href in ['#', '#', '#', '#', '#', '#foreign', '#', '#', '#', '#ministræ', '#', '#', '#']]
    if broken != (expected_broken if member_id.endswith('acts1') else []):
        raise ValueError('Stokes exact source-broken link census differs')
    source_positions = {node: index for index, node in enumerate(original_elements[1:])}
    by_path = {}
    element_position = 0
    for ordinal, ((path, left), ledger) in enumerate(zip(nodes, account["features"], strict=True), 1):
        source_tag = left.tag if isinstance(left.tag, str) else "#comment" if left.tag is etree.Comment else "#pi"
        source_record = dict(ordinal=ordinal, source_path=list(path), source_parent_path=list(path[:-1]), source_child_index=path[-1], source_tag=source_tag, source_attributes=dict(left.attrib), source_text=left.text, source_tail=left.tail)
        if any(ledger.get(key) != value for key, value in source_record.items()):
            raise ValueError(f"Stokes independent complete source fields differ at {path}")
        if not isinstance(left.tag, str):
            if left.tag is not etree.Comment or ledger.get('disposition') != 'source-comment-ledger-exact-whitespace-join':
                raise ValueError('Stokes administrative comment disposition differs')
            continue
        right = actual[element_position]; element_position += 1
        expected_readable = readable_by_source[left]
        if expected_readable.text != right.text or expected_readable.tail != right.tail:
            raise ValueError(f"Stokes actual readable direct/tail text differs at {path}")
        if left.getparent() is not body:
            if right.getparent() is not actual[source_positions[left.getparent()]]:
                raise ValueError(f"Stokes actual readable attachment differs at {path}")
        elif right.getparent() not in list(text):
            raise ValueError("Stokes actual source root attachment differs")
        identity = member_id + "-" + left.get("id") if left.get("id") else f"{member_id}-feature-{ordinal:06d}"
        attrs = {XML_ID: identity}
        tag = left.tag
        mapped = {"p": "p", "a": "ref", "b": "hi", "i": "hi", "small": "hi", "em": "hi", "cite": "hi", "sup": "hi", "sub": "hi", "br": "lb", "pb": "pb", "note": "note", "scripRef": "ref", "scripCom": "milestone", "insertIndex": "milestone", "hr": "milestone", "span": "seg", "verse": "lg", "l": "l", "div": "quote", "blockquote": "quote", "ul": "list", "li": "item", "table": "table", "tr": "row", "td": "cell"}
        if re.fullmatch(r"div[1-4]", tag):
            out_tag = "div"; attrs["type"] = "source-" + tag
            if left.get("title"): attrs["n"] = left.get("title")
        elif re.fullmatch(r"h[1-6]", tag):
            out_tag = "p"; attrs["rend"] = "source-" + tag
        else:
            if tag not in mapped: raise ValueError("Stokes independent source feature not in finite mapping: " + tag)
            out_tag = mapped[tag]
        if tag == "div":
            out_tag = "div" if left.get("class") == "Index" else "quote"
            attrs["type"] = "source-index" if out_tag == "div" else "source-div"
            if left.get("title"): attrs["n"] = left.get("title")
        rend_by_tag = {"b": "bold", "i": "italic", "small": "small", "em": "emphasis", "cite": "source-citation", "sup": "superscript", "sub": "subscript"}
        if tag in rend_by_tag: attrs["rend"] = rend_by_tag[tag]
        if tag in {"span", "verse", "blockquote", "br"}: attrs["type"] = {"span": "thml-span", "verse": "source-stanza", "blockquote": "source-blockquote", "br": "source-br"}[tag]
        if tag == "a":
            href = left.get("href")
            if href is None:
                out_tag = "seg" if left.text or len(left) else "anchor"; attrs["type"] = "source-anchor"
            elif href.startswith("#"):
                if href[1:] not in id_set:
                    out_tag = 'seg'; attrs.update(type='source-unresolved-link', n=href)
                else: attrs["target"] = "#" + member_id + "-" + href[1:]
            else: attrs["target"] = href
        if tag == "scripRef" and left.get("osisRef"): attrs["target"] = left.get("osisRef")
        if tag in {"scripCom", "insertIndex", "hr"}:
            attrs["unit"] = "horizontal-rule" if tag == "hr" else tag
            if tag == "scripCom":
                if left.get("passage") is not None: attrs["n"] = left.get("passage")
                if left.get("osisRef") is not None: attrs["corresp"] = left.get("osisRef")
            if tag == "insertIndex" and left.get("type") is not None: attrs["n"] = left.get("type")
        if tag == "pb" and left.get("n") is not None: attrs["n"] = left.get("n")
        if tag == "note":
            attrs.update({key: left.get(key) for key in ["n", "place", "type"] if left.get(key) is not None})
            if left.get("anchored") is not None: attrs["anchored"] = {"yes": "true", "no": "false"}.get(left.get("anchored"), left.get("anchored"))
        if tag == "td": attrs.update({out: left.get(old) for old, out in [("colspan", "cols"), ("rowspan", "rows")] if left.get(old) is not None})
        if tag == 'table':
            attrs.update({key: left.get(key) for key in ['rows', 'cols'] if left.get(key) is not None})
            if left.get('summary'): attrs['n'] = left.get('summary')
        rend = [attrs["rend"]] if "rend" in attrs else []
        if left.get("class"): rend.append("source-class-" + quote(left.get("class"), safe="-_."))
        if left.get("dir"): rend.append("source-dir-" + left.get("dir"))
        if left.get("style"):
            if out_tag in {"div", "p", "hi", "seg", "table", "cell", "milestone"}: attrs["style"] = left.get("style")
            else: rend.append("source-style-" + quote(left.get("style"), safe="-_."))
        if rend: attrs["rend"] = " ".join(rend)
        if right.tag != NS + out_tag or dict(right.attrib) != attrs:
            raise ValueError(f"Stokes actual semantic tag/attributes differ at {path}: {dict(right.attrib)} != {attrs}")
        if ledger.get("tei_id") != identity or ledger.get("tei_tag") != out_tag or ledger.get("tei_attributes") != attrs or ledger.get("disposition") != "native-element":
            raise ValueError("Stokes actual native binding differs from account")
        by_path[path] = right
    # Undo only independently verified whitespace joins on ACTUAL readable payloads,
    # then recreate the exact administrative comments already matched to raw.
    # Comments are ledger-retained, while all readable source elements are native.
    restored = etree.Element("ThML.body", dict(body.attrib)); restored.text = text[0].text; restored.tail = account["source_body_tail"]
    restored_paths = {(): restored}
    for path, source_node in nodes:
        if source_node.tag is etree.Comment:
            row = account['features'][next(i for i, (p, _) in enumerate(nodes) if p == path)]
            recovered = etree.Comment(row['source_text']); recovered.tail = row['source_tail']
        else:
            observed = by_path[path]
            recovered = etree.Element(source_node.tag, dict(source_node.attrib))
            for field in ['text', 'tail']:
                original = getattr(source_node, field)
                normalized = getattr(readable_by_source[source_node], field)
                actual_value = getattr(observed, field)
                if normalized != actual_value or not (normalized or '').startswith(original or ''):
                    raise ValueError('Stokes exact comment whitespace inverse differs')
                # Joins append only known whitespace; preserve original None/empty
                # boundary from source evidence, and take all payload from actual DOM.
                setattr(recovered, field, actual_value[:len(original)] if original is not None else None)
        restored_paths[path[:-1]].append(recovered); restored_paths[path] = recovered
    if etree.tostring(restored, method="c14n", with_comments=True) != etree.tostring(body, method="c14n", with_comments=True):
        raise ValueError("Stokes inverse actual readable DOM differs from entire retained source body")
    full_nodes = [x for x in source.iter() if isinstance(x.tag, str)]; positions = {x: n for n, x in enumerate(full_nodes, 1)}
    administration = []
    for node in full_nodes:
        if node is body or body in node.iterancestors(): continue
        parent = node.getparent()
        administration.append(dict(ordinal=positions[node], source_tag=node.tag, attributes=dict(node.attrib), text=node.text or "", tail=node.tail or "", parent_ordinal=positions.get(parent), child_index=list(parent).index(node) if parent is not None else 0,
            disposition="retained source administration; literal metadata summarized in header; CSS retained as rendering authority"))
    if account.get("retained_administration") != administration or account.get("source_body_text") != body.text or account.get("source_body_attributes") != dict(body.attrib) or account.get("source_body_tail") != body.tail:
        raise ValueError("Stokes full administration/envelope accounting differs")
    prolog = [dict(node_kind='comment' if node.tag is etree.Comment else 'pi', target=node.target if node.tag is etree.PI else None, text=node.text, tail=node.tail) for node in reversed(list(source.itersiblings(preceding=True)))]
    auxiliaries = [dict(node_kind='comment' if node.tag is etree.Comment else 'pi', target=node.target if node.tag is etree.PI else None, text=node.text, tail=node.tail, parent_selector=source.getroottree().getpath(node.getparent()), child_index=list(node.getparent()).index(node)) for node in source.iter() if not isinstance(node.tag, str) and body not in node.iterancestors()]
    if account.get('source_prolog') != prolog or account.get('retained_nonbody_auxiliaries') != auxiliaries:
        raise ValueError('Stokes source prolog/header comments including copyright evidence differ')
    if account.get('root_disposition') != expected_regions or account.get('source_sha256') != digest or account.get('source') != dict(path=rel, bytes=len(raw), sha256=digest):
        raise ValueError('Stokes complete source body region/binding account differs')
    header = source.find("ThML.head")
    expected_metadata = [("title", header.findtext("electronicEdInfo/DC/DC.Title")), ("author", header.findtext("electronicEdInfo/DC/DC.Creator[@sub='Author'][@scheme='short-form']")), ("editor", header.findtext("electronicEdInfo/DC/DC.Creator[@sub='Editor'][@scheme='short-form']"))]
    for key, value in expected_metadata:
        if tree.findtext(NS + "teiHeader/" + NS + "fileDesc/" + NS + "titleStmt/" + NS + key) != value: raise ValueError("Stokes literal primary metadata differs")
    return dict(status="pass", member_id=member_id, source_sha256=digest, candidate_sha256=sha(tei_bytes), full_source_elements=full_count, readable_elements=body_count - 1,
        source_comments=sum(x.tag is etree.Comment for _, x in nodes), administrative_comment_disposition='ledger-retained; exact source fields and independently derived whitespace joins verified; no visible source elements dropped', source_tag_counts=dict(Counter(x.tag for _, x in nodes if isinstance(x.tag, str))),
        source_broken_local_links=[dict(source_id=identity, href=href) for identity, href in broken],
        actual_readable_body_inverse_c14n_equal=True, all_direct_tail_attributes_attachment_order_equal=True, p5="pass", complete_source_administration_accounted=True,
        root_disposition=expected_regions, source_body_c14n_sha256=sha(etree.tostring(body, method="c14n", with_comments=True)))


def oracle(manifest, candidate):
    manifest.verify(); candidate.verify_integrity()
    member_id = str(manifest.record["scope"]["member_id"])
    check(member_id, candidate.member_bytes("content.tei.xml"), candidate.member_bytes("source-accountability.json"))
    authorities = {x["role"]: x["sha256"] for x in manifest.record["authorities"]}
    facts = MechanicalFacts(validator_implementation_sha256=sha(Path(__file__).read_bytes()), validator_import_closure_sha256=_closure(manifest.repository_root), source_sha256=SOURCE[member_id][1], profile_sha256=authorities["complete-source-feature-profile"], package_schema_sha256=authorities["candidate-package-schema"], xsd_sha256=authorities["tei-validation-schema"], policy_sha256=authorities["independent-validation-policy"], findings=())
    return verify_mechanical_facts(manifest, candidate, facts).as_record()


oracle.oracle_id = "ocd-stokes-direct-retained-readable-source-oracle"
oracle.oracle_version = "1"
