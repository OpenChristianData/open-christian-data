"""Exact accepted Wesley collection and closed heading-carrier guards."""
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories import native_documents
from ocd_kernel.projection.native_content import WESLEY_PROFILE, project_content
from ocd_kernel.projection.native_content_check import observe_content

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / ('library/works/john-wesley-sermons/forms/'
                 'john-wesley-sermons-retained-electronic-en/editions/'
                 'john-wesley-sermons-retained-electronic-edition/master.tei.xml')


@pytest.mark.requires_local_artifacts
def test_wesley_collection_requires_exact_accepted_identity_and_acquisition():
    raw = MASTER.read_bytes()
    args = dict(identity=native_documents._WESLEY_IDENTITY, raw=raw,
                language='en', category='sermons', collection=True,
                projection_profile=None, source_base=None,
                acquisition_id=native_documents._WESLEY_ACQUISITION,
                allow_acceptance_metadata=True)
    assert native_documents.is_source_collection(MASTER)
    assert native_documents._wesley_route(**args)
    for changed in ({'raw':raw+b' '}, {'acquisition_id':'wrong-acquisition'},
                    {'collection':False}, {'category':'prose'},
                    {'identity':dict(native_documents._WESLEY_IDENTITY, edition_id='wrong')}):
        with pytest.raises(PipelineError, match='exact accepted master and context'):
            native_documents._wesley_route(**(args | changed))


def test_wesley_heading_carrier_is_scoped_and_independently_observed():
    from xml.etree import ElementTree as ET
    fragment = b'<ab xmlns="http://www.tei-c.org/ns/1.0" type="thml-h2">Title</ab>'
    projected = project_content(ET.fromstring(fragment), source_profile=WESLEY_PROFILE)
    observed, readable = observe_content(fragment, source_profile=WESLEY_PROFILE)
    assert projected == observed
    assert readable == 'Title'
    with pytest.raises(PipelineError):
        project_content(ET.fromstring(fragment))
    with pytest.raises(ValueError):
        observe_content(fragment)
