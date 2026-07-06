from pathlib import Path


def count_sidecars(
    pages_dir: Path,
    *,
    exclude_stems: frozenset[str] = frozenset(),
) -> int:
    """Return the number of sidecar page JSON files, or 0 if the dir does not exist.

    exclude_stems: stems to skip (e.g. duplicate-role images from page_order.json).
    """
    if not pages_dir.exists():
        return 0
    return sum(
        1
        for path in pages_dir.glob("*.json")
        if path.is_file()
        and not path.name.endswith(".rendering-v1.json")
        and path.stem not in exclude_stems
    )
