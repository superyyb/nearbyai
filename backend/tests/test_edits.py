"""Field edits announced before the new value, and unclear requests (found by manual testing:
"Can I change my address?" got "That's not something I can do here", and "I just gave you wrong phone number"
got "Your request is ready")."""

import pytest

from app.services import answers
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
    assert results[len(TO_LEAD) - 1].lead is not None  # a lead was ready before the edit
    return state, results


# ---------- "I want to change X": keep the old value until the new one arrives ----------

def test_wants_change_holds_the_request_and_asks_for_the_new_value():
    state, results = lead_then(("Can I change my address?", {"edit_field": "street_address", "edit_kind": "wants_change"}))
    r = results[-1]
    assert r.action.type == "ask_edit" and "new address where you need service" in r.message
    assert r.lead_withdrawn and state.outcome is None and state.pending_edit == "street_address"
    assert state.street_address == "10 Main St"  # kept until replaced
    assert "can't" not in r.message and "not something I can do" not in r.message


def test_new_value_after_wants_change_updates_the_lead():
    state, results = lead_then(("Can I change my address?", {"edit_field": "street_address", "edit_kind": "wants_change"}),
                               ("22 Oak Ave", {"street_address": "22 Oak Ave"}))  # no correction flag needed
    r = results[-1]
    assert r.lead and "22 Oak Ave" in r.lead["property"]["address"] and r.message.startswith("I've updated your request.")
    assert state.pending_edit is None


def test_never_mind_after_wants_change_restores_the_lead():
    state, results = lead_then(("can I change the time?", {"edit_field": "timing", "edit_kind": "wants_change"}),
                               ("never mind, today is fine", {}))
    assert results[-1].lead is not None and state.outcome == "ready_to_dispatch" and state.urgency == "same_day"


# ---------- "X is wrong": the old value is invalid now ----------

def test_wrong_phone_clears_it_and_makes_the_lead_undispatchable():
    state, results = lead_then(("I just gave you wrong phone number", {"edit_field": "phone", "edit_kind": "current_value_wrong"}))
    r = results[-1]
    assert state.contact_value is None and state.outcome is None and r.lead_withdrawn and r.lead is None
    assert "correct phone number" in r.message


def test_correct_phone_after_wrong_rebuilds_lead_without_reasking_consent():
    state, results = lead_then(("that's not my number", {"edit_field": "phone", "edit_kind": "current_value_wrong"}),
                               ("408-555-0199", {"contact_value": "408-555-0199"}))
    r = results[-1]
    assert r.lead and r.lead["customer"]["contact"] == "(408) 555-0199"
    assert r.action.type == "lead_ready"  # same provider, same request: consent stands


def test_wrong_phone_then_no_number_asks_again_instead_of_giving_up():
    state, results = lead_then(("my phone number is wrong", {"edit_field": "phone", "edit_kind": "current_value_wrong"}),
                               ("hmm let me check", {}))
    assert results[-1].action.type == "ask_contact" and state.outcome is None


def test_wrong_zip_clears_the_match_and_new_zip_rematches():
    state, results = lead_then(("the ZIP I gave is wrong", {"edit_field": "zip_code", "edit_kind": "current_value_wrong"}),
                               ("it's 95134", {"zip_code": "95134"}))
    assert state.pilot_area == "north_san_jose" and state.selected_provider_id
    assert results[-2].action.type == "ask_edit" and results[-2].lead is None


def test_changing_the_problem_rematches_for_the_new_trade():
    state, results = lead_then(("actually the problem is different", {"edit_field": "issue", "edit_kind": "wants_change"}),
                               ("it's the roof leaking, not the AC", {"service_category": "roofing",
                                                                      "issue_summary": "Roof leaking"}))
    # The old HVAC match is gone; roofing first asks its qualification question, then matches a roofer.
    assert state.service_category == "roofing" and state.selected_provider_id is None
    assert results[-1].action.type == "ask_qualification" and results[-1].action.field == "active_leak"


def test_edit_with_the_value_in_the_same_message_applies_directly():
    state, results = lead_then(("my number was wrong, use 408-555-0177", {
        "edit_field": "phone", "edit_kind": "current_value_wrong", "contact_value": "408-555-0177"}))
    r = results[-1]
    assert state.pending_edit is None and r.lead and r.lead["customer"]["contact"] == "(408) 555-0177"


# ---------- unclear requests are not "impossible" ----------

def test_unclear_request_after_lead_gets_a_clarifying_question_only():
    state, results = lead_then(("can you do the other thing", {"requested_action": "unclear", "question_topics": ["other"]}))
    r = results[-1]
    assert r.message.startswith("I'm not sure I understood")
    assert "not something I can do" not in r.message and "verified information" not in r.message
    assert "is ready" not in r.message and state.outcome == "ready_to_dispatch"


def test_thanks_after_lead_still_gets_the_closing_message():
    state, results = lead_then(("thanks!", {}))
    assert results[-1].action.type == "already_closed" and "is ready" in results[-1].message


@pytest.mark.parametrize("action", ["call_provider", "book_appointment", "send_now", "guarantee"])
def test_only_truly_impossible_requests_say_cant(action):
    assert "can't" in answers.answer_request(action, None)


def test_unclear_never_claims_impossibility():
    assert "can't" not in answers.answer_request("unclear", None)
