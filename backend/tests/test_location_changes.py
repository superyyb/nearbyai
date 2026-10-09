"""Only a change of service area invalidates the provider match (found while testing field edits: a street-only
change cleared the match and re-asked consent for the same provider)."""

from tests.helpers import AC_ISSUE, SANTA_CLARA, converse

TO_LEAD = [
    ("My AC blows warm air", AC_ISSUE),
    ("Santa Clara", SANTA_CLARA),
    ("today", {"urgency": "same_day"}),
    ("Sam, 408-555-0100, 10 Main St", {"customer_name": "Sam", "contact_method": "phone",
                                       "contact_value": "408-555-0100", "street_address": "10 Main St"}),
    ("yes", {"consent_to_share": True}),
]


def lead_then(*turns):
    state, results = converse(TO_LEAD + list(turns))
    assert results[len(TO_LEAD) - 1].lead is not None
    return state, results


def test_new_street_address_in_the_same_area_keeps_provider_and_consent():
    state, results = lead_then(("use 22 Oak Ave instead", {"street_address": "22 Oak Ave", "corrections": ["street_address"]}))
    assert results[-1].lead and results[-1].action.type == "lead_ready"
    assert state.selected_provider_id == "dg-heating-air-conditioning" and state.consent_to_share is True


def test_zip_in_the_same_area_keeps_the_match():
    state, results = lead_then(("actually it's 95051", {"zip_code": "95051", "corrections": ["zip_code"]}))
    assert state.pilot_area == "santa_clara" and state.selected_provider_id == "dg-heating-air-conditioning"
    assert results[-1].lead is not None
