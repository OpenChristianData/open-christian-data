"""Capture bounded exact-source Denney title, body, and index comparisons."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from cvw_app.capture_review import capture

EXTERNAL = Path('D:/Library/Open Christian Data/candidate-reviews')
RECEIPT = EXTERNAL / 'expositors-lib034-denney-pair-cvw-session-20260927-v1/f4ba7d0e5a764507a7dbf4005a5f7013.receipt.json'
ORIGIN = 'http://127.0.0.1:52832'
WORK = 'expositors-bible--james-denney'
MEMBERS = {
    'denney-expositor2cor': dict(manifest='012ca883db5990c71aff5757610963473aee64f9ac0faf54a3787fcdd7480964',
                                package='a68cdeafe81d1f8df7056ab89b866cf4b345eb7974ccaf941dd88c10919ef66e',
                                body='iii', body_anchor='denney-expositor2cor-iii-p1.3',
                                back='xxxi', back_anchor='denney-expositor2cor-xxxi.i-p0.1'),
    'denney-expositorthess': dict(manifest='4e80ca0e3a008a730c3b2656c5e54ff19d0c981e17b2973da6c30048202d82d9',
                                 package='861a6bb31aae00e4f2010d53a52971d7de1ce3b25ad5f495e9d3593bfb525796',
                                 body='ii', body_anchor='denney-expositorthess-ii.i-p1.2',
                                 back='iv', back_anchor='denney-expositorthess-iv.i-p0.1'),
}


def _query(member: str, detail: dict, source_location: str, tei_location: str,
           source_segment: int, tei_segment: int) -> str:
    return urlencode(dict(left_stage='source', left_artifact='source-' + detail['manifest'],
                          left_version=detail['manifest'], left_location=source_location,
                          right_stage='tei', right_artifact='tei-' + detail['package'],
                          right_version=detail['package'], right_location=tei_location,
                          linked='false', correspondence='absent',
                          left_segment_start=source_segment, left_segment_limit=1,
                          right_segment_start=tei_segment, right_segment_limit=1))


def main() -> None:
    rows = []
    for member, detail in MEMBERS.items():
        for label, location in (('opening', 'start'), ('first-body', detail['body']), ('index', detail['back'])):
            tei_location = ('start' if label == 'opening' else
                            detail['body_anchor'] if label == 'first-body' else detail['back_anchor'])
            probe = ORIGIN + '/api/review/v1/works/' + WORK + '/compare?' + _query(
                member, detail, location, tei_location, 0, 0)
            with urlopen(probe, timeout=30) as response:
                view = json.load(response)
            left = view['left']['paging']['location_segment']
            right = view['right']['paging']['location_segment']
            if (left is None or right is None or
                    view['left']['recorded_context']['state'] != 'exact' or
                    view['right']['recorded_context']['state'] != 'exact'):
                raise ValueError(f'{member} {label} location is not governed')
            route = ORIGIN + '/review/works/' + WORK + '?' + urlencode(dict(
                mode='compare', leftStage='source', leftArtifact='source-' + detail['manifest'],
                leftVersion=detail['manifest'], leftLocation=location,
                rightStage='tei', rightArtifact='tei-' + detail['package'],
                rightVersion=detail['package'], rightLocation=tei_location,
                linked='false', correspondence='absent', focus='agent',
                leftSegmentStart=left, leftSegmentLimit=1,
                rightSegmentStart=right, rightSegmentLimit=1))
            version = 'v1' if label == 'opening' else 'v2'
            destination = EXTERNAL / (WORK + '-' + member + '-readable-cvw-' + label + '-20260927-' + version)
            if destination.exists():
                if label == 'opening' and (destination / 'frame.png').is_file():
                    continue
                raise ValueError(f'fresh Denney CVW capture destination required: {destination}')
            evidence = capture(receipt=RECEIPT, route=route, destination=destination)
            if evidence['page_errors']:
                raise ValueError(f'{member} {label} visual capture page error')
            rows.append(dict(member=member, label=label, destination=destination.as_posix(),
                             left_segment=left, right_segment=right,
                             frame_sha256=evidence['files']['frame.png']))
    print(json.dumps(rows, sort_keys=True))


if __name__ == '__main__':
    main()
