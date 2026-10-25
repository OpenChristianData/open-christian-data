"""Check authored JSON text against separately reviewed, source-bound readings."""
from build.lib.text_lint import _select


def verify_reviewed_fields(document, review, source_sha256):
    if (review["contract"] != "ocd-reviewed-json-text-fields-v1"
            or review["source_sha256"] != source_sha256 or not review["fields"]):
        raise ValueError("Reviewed JSON fields have an invalid source binding")
    seen = set()
    for field in review["fields"]:
        pointer = field["pointer"]
        if pointer in seen:
            raise ValueError("Duplicate reviewed JSON field: " + pointer)
        seen.add(pointer)
        if _select(document, pointer) != field["reading"]:
            raise ValueError("Authored text differs from independently reviewed source reading: " + pointer)
