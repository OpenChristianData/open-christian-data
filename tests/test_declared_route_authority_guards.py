"""Rejected manifest authority must stop these routes before any data access."""

import importlib

import pytest

from build.tools.pre_commit_pytest import AUTHORITY_GUARD_ROUTES, CANDIDATE_GUARD_ROUTES
from tests.test_cli_input_guards import _contract_case


# This fixed scope does not shrink if a route loses its verification call.


class _InvalidAuthority(ValueError):
    pass


class _RejectedManifest:
    def verify(self):
        raise _InvalidAuthority("fixture manifest authority rejected")

    def __getattr__(self, name):
        raise AssertionError(f"route accessed source {name} before authority verification")


class _UnreadCandidate:
    def __getattr__(self, name):
        raise AssertionError(f"oracle accessed candidate {name} before authority verification")


@pytest.mark.parametrize(
    ("source", "name", "arity"),
    [_contract_case(*route) for route in AUTHORITY_GUARD_ROUTES],
    ids=[source for source, _, _ in AUTHORITY_GUARD_ROUTES],
)
def test_rejected_manifest_stops_route_before_source_or_candidate_reads(source, name, arity):
    module = importlib.import_module(source.removesuffix(".py").replace("/", "."))
    route = getattr(module, name)
    arguments = (_RejectedManifest(),) if arity == 1 else (_RejectedManifest(), _UnreadCandidate())

    with pytest.raises(_InvalidAuthority, match="fixture manifest authority rejected"):
        route(*arguments)




class _InvalidCandidate(ValueError):
    pass


class _RejectedCandidate(_UnreadCandidate):
    def verify_integrity(self):
        raise _InvalidCandidate("fixture candidate integrity rejected")


class _UnreadManifest:
    def __getattr__(self, name):
        raise AssertionError(f"oracle accessed source {name} before candidate verification")


@pytest.mark.parametrize(
    ("source", "name", "arity"),
    [_contract_case(*route) for route in CANDIDATE_GUARD_ROUTES],
    ids=[source for source, _, _ in CANDIDATE_GUARD_ROUTES],
)
def test_rejected_candidate_stops_oracle_before_source_or_member_reads(source, name, arity):
    assert arity == 2
    module = importlib.import_module(source.removesuffix(".py").replace("/", "."))
    route = getattr(module, name)

    with pytest.raises(_InvalidCandidate, match="fixture candidate integrity rejected"):
        route(_UnreadManifest(), _RejectedCandidate())


