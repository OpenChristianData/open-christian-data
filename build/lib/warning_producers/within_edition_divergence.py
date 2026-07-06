"""Within-edition divergence warning producer."""

from __future__ import annotations


from build.lib.warning_producers import WARNING_OUTPUT_SCHEMA, build_warning


PRODUCER_ID = "within_edition_divergence"
SIGNATURE_VERSION = 1
WARNING_CODES = {
    "WITHIN_EDITION_DIVERGENCE": {
        "severity": "warning",
        "description": "Renderings that claim the same edition diverge beyond review thresholds.",
        "signature_fields": ["code", "resource_id"],
    },
}
APPLIES_TO_RESOURCE_TYPES = None
REQUIRES_CAPABILITIES = {}
CONSUMES = []
PRODUCES_SCHEMA = WARNING_OUTPUT_SCHEMA
SCOPE = "resource_local"
BLOCK_COUNT_PARITY_FLOOR = 0.80
ANCHOR_GRAPH_DENSITY_FLOOR = 0.30
AUTO_RESOLVE_RATE_FLOOR = 0.70


def run(record: dict, meta: dict, upstream_outputs: dict) -> dict:
    renderings = meta.get("renderings")
    if not isinstance(renderings, list) or len(renderings) < 2:
        return {"warnings": []}
    block_counts = [item.get("block_count") for item in renderings if isinstance(item, dict)]
    numeric_counts = [count for count in block_counts if isinstance(count, int | float) and count > 0]
    if len(numeric_counts) < 2:
        return {"warnings": []}
    max_count = max(numeric_counts)
    min_count = min(numeric_counts)
    block_count_parity = min_count / max_count
    anchor_density = min(
        (item.get("anchor_graph_density") for item in renderings if isinstance(item, dict)),
        default=None,
    )
    auto_resolve_rate = min(
        (item.get("auto_resolve_rate") for item in renderings if isinstance(item, dict)),
        default=None,
    )
    divergent = (
        block_count_parity < BLOCK_COUNT_PARITY_FLOOR
        or (isinstance(anchor_density, int | float) and anchor_density < ANCHOR_GRAPH_DENSITY_FLOOR)
        or (isinstance(auto_resolve_rate, int | float) and auto_resolve_rate < AUTO_RESOLVE_RATE_FLOOR)
    )
    if not divergent:
        return {"warnings": []}
    resource_id = meta.get("resource_id")
    return {
        "warnings": [
            build_warning(
                producer=__import__(__name__, fromlist=[""]),
                code="WITHIN_EDITION_DIVERGENCE",
                entry_id=None,
                field_path="renderings",
                message="Renderings claiming the same edition diverge beyond review thresholds.",
                evidence={
                    "resource_id": resource_id,
                    "block_count_parity": block_count_parity,
                    "anchor_graph_density": anchor_density,
                    "auto_resolve_rate": auto_resolve_rate,
                },
                signature_values={"resource_id": resource_id},
            )
        ]
    }
