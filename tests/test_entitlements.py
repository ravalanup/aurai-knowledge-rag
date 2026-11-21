import pytest
from qdrant_client import models

from aurai_knowledge.entitlements import Entitlement, EntitlementError, parse_policy
from aurai_knowledge.models import Classification
from aurai_knowledge.store import entitlement_filter


def test_groups_combine_and_highest_ceiling_wins(policy):
    ent = policy.resolve(frozenset({"workspace-members", "knowledge-ops"}))
    assert ent.ceilings["ops-reports"] == Classification.CONFIDENTIAL
    assert ent.ceilings["guest-services"] == Classification.INTERNAL
    assert ent.ceilings["hr-policies"] == Classification.INTERNAL
    assert "finance-reporting" not in ent.collections


def test_unknown_groups_and_admins_get_nothing(policy):
    assert policy.resolve(frozenset({"workspace-admins"})).is_empty()
    assert policy.resolve(frozenset({"some-other-group"})).is_empty()
    assert policy.resolve(frozenset()).is_empty()


def test_permits_checks_collection_and_ceiling(policy):
    ent = policy.resolve(frozenset({"workspace-builders"}))
    assert ent.permits("ops-reports", Classification.INTERNAL)
    assert not ent.permits("ops-reports", Classification.CONFIDENTIAL)
    assert not ent.permits("finance-reporting", Classification.PUBLIC)


def test_narrowing_never_widens(policy):
    ent = policy.resolve(frozenset({"workspace-members"}))
    narrowed = ent.narrowed(["hr-policies", "finance-reporting", "does-not-exist"])
    assert narrowed.collections == {"hr-policies"}
    assert ent.narrowed(None) is ent


def test_filter_has_one_branch_per_collection_with_ceiling(policy):
    ent = policy.resolve(frozenset({"workspace-builders"}))
    flt = entitlement_filter(ent)
    assert len(flt.should) == 3
    branch = next(b for b in flt.should if b.must[0].match.value == "ops-reports")
    assert branch.must[1].range == models.Range(lte=int(Classification.INTERNAL))


def test_empty_entitlement_can_never_become_a_filter():
    with pytest.raises(ValueError):
        entitlement_filter(Entitlement({}))


@pytest.mark.parametrize(
    "data,message",
    [
        ({"version": 2}, "version: 1"),
        ({"version": 1, "collections": []}, "non-empty"),
        ({"version": 1, "collections": ["a"], "grants": [{"collections": {"a": "internal"}}]}, "needs a 'group'"),
        (
            {"version": 1, "collections": ["a"], "grants": [{"group": "g", "collections": {"b": "internal"}}]},
            "unknown collection",
        ),
        (
            {"version": 1, "collections": ["a"], "grants": [{"group": "g", "collections": {"a": "secret"}}]},
            "unknown classification",
        ),
        (
            {"version": 1, "collections": ["a"], "grants": [{"group": "g"}, {"group": "g"}]},
            "more than one grant",
        ),
    ],
)
def test_invalid_policies_are_rejected(data, message):
    with pytest.raises(EntitlementError, match=message):
        parse_policy(data)
