"""Advisory semantic checks: flags request review and never change decisions."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping


def semantic_alerts(claim: Mapping[str, Any]) -> list[str]:
    """Surface recurring role, date-event, and scope risks in supported claims.

    Text cues deliberately remain advisory: absence of a flag is not evidence
    that a claim is correct, and a flagged quotation may support several roles.
    """
    evidence = claim["evidence"]
    if evidence["classification"] != "supported":
        return []
    scope = claim["scope"]
    semantics = claim.get("semantics", {})
    predicate = scope["predicate"].lower()
    role_words = " ".join((predicate, scope["event_role"].lower())).replace("_", " ")
    excerpts = " ".join(json.dumps(binding["locator"]["expected"], ensure_ascii=False)
                        for binding in evidence.get("bindings", [])
                        if binding.get("role") == "primary").lower()
    flags = []
    is_translator = semantics.get("role") == "translator" or (
        not semantics and re.search(r"\btranslators?\b", role_words)
    )
    if is_translator and re.search(r"\beditor\b|\bedited by\b|\bed\.", excerpts):
        flags.append("contributor_role: source includes editorial credit; verify that the claimed translator is explicitly credited for this work")
    typed_event = semantics.get("kind") == "publication_event"
    if not typed_event and re.search(r"first.{0,12}pub|original.{0,12}(?:pub|date|year)", predicate):
        flags.append("publication_event: verify first publication independently of the date printed in the retained edition")
    elif not typed_event and re.search(r"(?:^|[_\s])(?:dates?|years?)(?:[_\s]|$)|^chronology$", predicate):
        flags.append("publication_event_unspecified: distinguish the printed edition date, first publication, translation, and transcription events")
    if re.search(r"\b(?:volume|series|collection|compilation)\b", excerpts) and not re.search(
        r"\b(?:volume|series|collection|compilation)\b", str(scope.get("entity", "")), re.I
    ):
        flags.append("evidence_scope: source names a collection or volume; verify applicability to this individual subject")
    return flags
