import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools.ocr_ensemble_compare import compare_ocr_texts  # noqa: E402


def test_single_token_insertion_is_one_disagreement_record():
    result = compare_ocr_texts(
        [
            ("first", "Grace and peace be multiplied unto you."),
            ("second", "Grace abundant and peace be multiplied unto you."),
        ]
    )

    assert result["counts"]["total_disagreements"] == 1
    assert result["disagreement_records"] == [
        {
            "index": 1,
            "classification": "content disagreement",
            "sources": {"first": "", "second": "abundant"},
        }
    ]
