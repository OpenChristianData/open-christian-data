"""Qualify semantic checks with in-memory mutations and explicit applicability."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from lxml import etree

from build.lib.source_fidelity import XML_ID, TEI, compare, digest, parse_tei


def qualify(expectations, candidate: bytes, corroboration: dict) -> dict:
    baseline = compare(expectations, candidate, corroboration)
    if baseline["status"] != "pass":
        return dict(status="not-run", reason="baseline must pass declared claims and parser corroboration", cases=[])
    structural_identity = expectations.profile.get("identity_mode") == "structural-position"
    fidelity_rules = {"omission", "duplication", "invention", "attachment", "order", "role",
                      "attributes", "text", "inline-tail"}

    def locus_for(node):
        return node.get(XML_ID) or node.getroottree().getpath(node)

    results = []
    for mutation, expected_rules in [
        ("omit", {"omission"}), ("duplicate", {"duplication"}),
        ("invent", {"invention"}), ("change-text", {"text"}),
        ("reorder", {"order"}), ("wrong-attachment", {"attachment"}),
        ("change-attribute", {"attributes"}), ("inline-boundary", {"text", "inline-tail"}),
    ]:
        tree = parse_tei(candidate)
        if expectations.scope_id is None:
            scope = tree.xpath("/t:TEI/t:text/t:body", namespaces={"t": TEI})[0]
        else:
            scope = tree.xpath("//*[@xml:id=$identity]", identity=expectations.scope_id)[0]
        nodes = [n for n in scope.iter() if isinstance(n.tag, str)]
        leaves = [n for n in nodes[1:] if len(n) == 0]
        text_leaves = [n for n in leaves if n.text]
        before_values = Counter((n.text or "", n.tail or "") for n in nodes)
        flat_before = "".join(scope.itertext())
        applicable = True
        locus = None
        if mutation in ("omit", "duplicate", "invent", "change-text") and (
                text_leaves if mutation == "change-text" else leaves):
            target = (text_leaves if mutation == "change-text" else leaves)[0]
            locus = locus_for(target)
            parent = target.getparent()
            if mutation == "omit":
                parent.remove(target)
            elif mutation == "change-text":
                target.text += " [mutation]"
            else:
                clone = deepcopy(target)
                if mutation == "invent":
                    clone.set(XML_ID, "fidelity-mutation-invented")
                parent.insert(parent.index(target) + 1, clone)
        elif mutation == "reorder":
            parent = next((n for n in nodes if len(n) > 1
                           and all(isinstance(c.tag, str) for c in list(n)[:2])
                           and (structural_identity or all(c.get(XML_ID) for c in list(n)[:2]))
                           and etree.tostring(n[0]) != etree.tostring(n[1])), None)
            if parent is None:
                applicable = False
            else:
                first = parent[0]
                locus = locus_for(first)
                parent.remove(first)
                parent.insert(1, first)
        elif mutation == "wrong-attachment":
            preferred = sorted(nodes[1:], key=lambda n: 0 if n.tag == f"{{{TEI}}}note" or n.get("type") == "proofs" else 1)
            pair = next(((n, other) for n in preferred if (structural_identity or n.get(XML_ID))
                         for other in nodes if other is not n.getparent() and other is not n
                         and other.tag == n.getparent().tag and other not in n.iterdescendants()
                         and other is not scope), None)
            if pair is None:
                applicable = False
            else:
                target, owner = pair
                locus = locus_for(target)
                target.getparent().remove(target)
                owner.append(target)
        elif mutation == "change-attribute":
            target = next((n for n in nodes if any(k != XML_ID for k in n.attrib)), None)
            if target is None:
                applicable = False
            else:
                attr = next(k for k in target.attrib if k != XML_ID)
                locus = locus_for(target)
                target.set(attr, target.get(attr) + "-mutation")
        elif mutation == "inline-boundary":
            target = next((n for n in nodes[1:] if len(n) == 0 and n.text and n.tail
                           and n.tail.strip()), None)
            if target is None:
                applicable = False
            else:
                locus = locus_for(target)
                target.text += target.tail
                target.tail = ""
        else:
            applicable = False
        if not applicable:
            results.append(dict(mutation=mutation, status="not-applicable", reason="required source feature absent"))
            continue
        changed = etree.tostring(tree, encoding="utf-8")
        actual_nodes = [n for n in scope.iter() if isinstance(n.tag, str)]
        invariants = dict(bytes_changed=digest(changed) != digest(candidate))
        if mutation in ("reorder", "wrong-attachment"):
            invariants["content_multiset_preserved"] = before_values == Counter((n.text or "", n.tail or "") for n in actual_nodes)
        if mutation == "inline-boundary":
            invariants["flattened_text_preserved"] = flat_before == "".join(scope.itertext())
        result = compare(expectations, changed, corroboration)
        detected = {f["rule"] for f in result["findings"]}
        # Position identities prove a changed tree, but cannot always name the
        # moved node after a reorder or reparenting. Require a fidelity failure
        # without pretending the xml:id-specific diagnostic rule was observed.
        position_challenge = structural_identity and mutation in {
            "duplicate", "reorder", "wrong-attachment"}
        detected_fidelity = detected & fidelity_rules
        detected_expected = bool(detected_fidelity) if position_challenge else expected_rules <= detected
        status = ("rejected" if all(invariants.values()) and result["status"] == "fail"
                  and detected_expected else "not-proven")
        results.append(dict(mutation=mutation, status=status, locus=locus, invariants=invariants,
                            expected_rules=sorted(expected_rules) if not position_challenge else [],
                            detection_basis=("any source-fidelity finding for structural-position identity"
                                             if position_challenge else "claim-specific rule"),
                            detected_rules=sorted(detected),
                            candidate_sha256=digest(changed)))
    eligible = [r for r in results if r["status"] != "not-applicable"]
    return dict(status="pass" if eligible and all(r["status"] == "rejected" for r in eligible) else "fail",
                cases=results, applicable=len(eligible),
                not_applicable=len(results) - len(eligible),
                rejected=sum(r["status"] == "rejected" for r in results))
