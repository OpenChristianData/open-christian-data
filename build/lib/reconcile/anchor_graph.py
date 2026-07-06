"""anchor_graph — identify the pd_anchor and partition renderings by role."""

from __future__ import annotations


def build_anchor_graph(renderings: list[dict], catalog: dict) -> dict:
    """Return anchor graph identifying anchor and attestor renderings.

    Raises ValueError if:
    - no rendering matches catalog["pd_anchor"]
    - more than one rendering has role=="pd_anchor"
    """
    expected_anchor_id = catalog["pd_anchor"]

    # Guard: multiple pd_anchor roles
    pd_anchor_roles = [r for r in renderings if r.get("role") == "pd_anchor"]
    if len(pd_anchor_roles) > 1:
        raise ValueError(
            f"Multiple renderings have role=='pd_anchor': "
            f"{[r['rendering_id'] for r in pd_anchor_roles]}"
        )

    # Find anchor by rendering_id
    anchor_rendering = None
    for r in renderings:
        if r["rendering_id"] == expected_anchor_id:
            anchor_rendering = r
            break

    if anchor_rendering is None:
        raise ValueError(
            f"pd_anchor rendering_id '{expected_anchor_id}' not found in renderings list. "
            f"Available: {[r['rendering_id'] for r in renderings]}"
        )

    attestor_renderings = [r for r in renderings if r["rendering_id"] != expected_anchor_id]

    return {
        "anchor_rendering_id": expected_anchor_id,
        "anchor_rendering": anchor_rendering,
        "attestor_renderings": attestor_renderings,
    }
