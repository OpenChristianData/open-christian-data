"""WU-02 candidate boundary controls for the selected ThML route."""

from lxml import etree
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.selected_thml_check import check_selected_thml
from tests.test_selected_thml_lifecycle import _fixture


@pytest.mark.parametrize("mutation", ["truncate", "append"])
def test_independent_checker_rejects_candidate_boundary_mutation(tmp_path, monkeypatch, mutation):
    root, _, acquisition, work, candidate = _fixture(tmp_path, "anthology", monkeypatch)
    tree = etree.parse(str(candidate))
    body = tree.xpath("//*[local-name()='body']")[0]
    first = body[0]
    if mutation == "truncate":
        first.remove(first[-1])
    else:
        body.append(etree.fromstring("<div xmlns='http://www.tei-c.org/ns/1.0'><head>Invented sibling</head><p>Invented.</p></div>"))
    tree.write(str(candidate), encoding="utf-8", xml_declaration=True)
    with pytest.raises(PipelineError):
        check_selected_thml(root, acquisition, work, candidate)
