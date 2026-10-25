"""Closed declared source-member sets, independent of retained fixture availability."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import pytest
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories import liturgies, liturgies_bcp1549, liturgies_bcp1559


def records(profile):
    source=dict(source_path='aggregate.json', source_sha256='a'*64, source_bytes=17)
    retained=[dict(path=f"raw/bcp-full-text/{profile.IDENTITY['work_id']}/{name}",
                   sha256=sha256(b'fixture').hexdigest(), bytes=7) for name in sorted(profile.MEMBERS)]
    acquired=dict(source_kind='retained-member-set',retained_files=retained,**source)
    included=[dict(position=n,**member) for n,member in enumerate(retained,1)]
    return source,acquired,included


@pytest.mark.parametrize('profile',[liturgies_bcp1549,liturgies_bcp1559])
def test_exact_declared_member_set_and_inventory_order(profile,monkeypatch):
    source,acquired,included=records(profile)
    monkeypatch.setattr('ocd_kernel.library._common.io_path',lambda p:type('Fixture',(),{'read_bytes':lambda self:b'fixture'})())
    monkeypatch.setattr('ocd_kernel.lib.storage_topology.resolve_repo_path',lambda root,p:Path(p))
    result=liturgies._bcp_retained_html_aggregate_member(Path.cwd(),profile.IDENTITY,acquired,source,included)
    assert result==dict(path='aggregate.json',sha256='a'*64,bytes=17)


@pytest.mark.parametrize('case',['foreign-member','changed-hash','changed-byte-count','duplicate-position','aggregate-pointer','subset','identity'])
def test_member_binding_rejects_unknown_or_changed_source(case,monkeypatch):
    profile=liturgies_bcp1559
    source,acquired,included=records(profile);identity=deepcopy(profile.IDENTITY)
    monkeypatch.setattr('ocd_kernel.library._common.io_path',lambda p:type('Fixture',(),{'read_bytes':lambda self:b'fixture'})())
    monkeypatch.setattr('ocd_kernel.lib.storage_topology.resolve_repo_path',lambda root,p:Path(p))
    if case=='foreign-member':acquired['retained_files'][0]['path']=included[0]['path']='raw/bcp-full-text/bcp-1559/Unknown.htm'
    elif case=='changed-hash':acquired['retained_files'][0]['sha256']=included[0]['sha256']='b'*64
    elif case=='changed-byte-count':acquired['retained_files'][0]['bytes']=included[0]['bytes']=8
    elif case=='duplicate-position':included[-1]['position']=1
    elif case=='aggregate-pointer':source['source_sha256']='c'*64
    elif case=='subset':included.pop()
    else:identity['edition_id']='foreign'
    with pytest.raises(PipelineError):
        liturgies._bcp_retained_html_aggregate_member(Path.cwd(),identity,acquired,source,included)
