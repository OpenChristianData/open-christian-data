"""Exact L811 accepted-context selector proposal; no shared dispatch is changed."""
from hashlib import sha256
from pathlib import Path
import json

from ocd_kernel.lib.path_io import io_path
from ocd_kernel.library._common import PipelineError

IDENTITY = dict(work_id='eusebius-commentarii-in-psalmos', textual_form_id='pta-english',
                edition_id='pta-ef861ab3-commentarii-psalmos')
MASTER = 'b67b84fe42425800cabcd99f923e26d866b34f4123e37d65dca8e0922577acae'
ACQUISITION = 'pta-l811-retained-ef861ab3'
ACQUISITION_SHA = '3d4c2b5aebde505b6f6fda0c7d96a01c22e8d6170f2624e2390b6a432f01aaeb'
DESCRIPTOR_SHA = 'edc49a81cc88d745e0aefa9d101945938eef1bbcf9006afaa85975af7c4c54cc'
REVISION = 'eusebius-l811-retained-complete-20261004-v1'
TITLE = 'Commentarii in Psalmos, retained PTA Greek Tomes I-III'
PROFILE = 'ocd-prose-eusebius-l811-pta-three-tome-critical-v1'


def select(root, context):
    """Called after maintained acceptance validation, only this stable identity."""
    if context['identity'] != IDENTITY:
        return False
    accepted = context['accepted']
    authority = context['authority']
    acquisition_bytes = io_path(Path(root) / authority['acquisition']['path']).read_bytes()
    acquisition = json.loads(acquisition_bytes)
    source = accepted['source']
    descriptor = io_path(Path(root) / acquisition['source_path']).read_bytes()
    if (context['language'] != 'grc' or context['edition_title'] != TITLE
            or context['representation_revision'] != REVISION
            or authority['master']['sha256'] != MASTER
            or accepted['identity'] != IDENTITY | dict(acquisition_id=ACQUISITION)
            or sha256(acquisition_bytes).hexdigest() != ACQUISITION_SHA
            or authority['acquisition']['sha256'] != ACQUISITION_SHA
            or acquisition['source_kind'] != 'retained-member-set'
            or acquisition['source_sha256'] != DESCRIPTOR_SHA
            or acquisition['source_bytes'] != 1604
            or sha256(descriptor).hexdigest() != DESCRIPTOR_SHA or len(descriptor) != 1604
            or any(source[key] != acquisition[key] for key in
                   ('source_kind', 'source_path', 'source_sha256', 'source_bytes', 'source_scope'))):
        raise PipelineError('Exact L811 accepted Greek identity/master/member-set context differs')
    return True
