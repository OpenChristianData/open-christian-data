from copy import deepcopy

import pytest

from build.lib.reviewed_json_fields import verify_reviewed_fields


def test_source_bound_review_rejects_corruption_shared_by_producer_and_checker():
    document = {"headings": [{"reading": "Christ’s Teaching"}]}
    review = {"contract": "ocd-reviewed-json-text-fields-v1", "source_sha256": "scan-sha",
              "fields": [{"pointer": "/headings/0/reading", "reading": "Christ’s Teaching"}]}
    verify_reviewed_fields(document, review, "scan-sha")
    damaged = deepcopy(document)
    damaged["headings"][0]["reading"] = "Christâ€™s Teaching"
    with pytest.raises(ValueError, match="independently reviewed"):
        verify_reviewed_fields(damaged, review, "scan-sha")
    with pytest.raises(ValueError, match="source binding"):
        verify_reviewed_fields(document, review, "other-scan")
