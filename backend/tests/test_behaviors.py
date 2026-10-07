"""Conversation-behavior regression matrix (deterministic).

Each test pins one state transition for a kind of thing real users do mid-funnel.
The extractor's understanding is scripted, so these test orchestration only;
language understanding is covered by the Claude intent probes.
"""

import pytest

from app.services.llm import guardrail_violations
from tests.helpers import AC_ISSUE, SANTA_CLARA, converse

MATCHED = [("My AC blows warm air", AC_ISSUE), ("Santa Clara", SANTA_CLARA)]


# ---------- questions interrupt the funnel, get a grounded answer, then the funnel resumes ----------

@pytest.mark.parametrize("topic,expected", [
    ("price", "don't have verified pricing"),
    ("reviews", "don't have verified review"),
    ("license_or_insurance", "don't have verified license"),
    ("availability", "can't confirm when"),
    ("why_this_provider", "not paid placement"),
    ("sponsorship", "not paid by providers"),
    ("is_this_a_person", "automated assistant"),
    ("request_status", "Nothing has been sent"),
])
def test_provider_question_is_answered_then_funnel_resumes(topic, expected):
    state, results = converse(MATCHED + [("question", {"question_topic": topic})])
    r = results[-1]
    assert expected in r.message
    assert r.action.type == "ask_timing"  # resumes the question we were on
    assert state.asked_fields.count("timing") == 1  # the re-ask is not counted as a second unanswered ask


def test_question_before_any_match_does_not_invent_a_provider():
    state, results = converse([("How much does it cost?", {"question_topic": "price", **AC_ISSUE})])
    assert "haven't matched a provider yet" in results[-1].message
    assert results[-1].action.type == "ask_location"


def test_why_do_you_need_my_phone_explains_and_reasks():
    turns = MATCHED + [("today", {"urgency": "same_day"}),
                       ("why do you need my number?", {"question_topic": "why_need_info", "question_info_field": "phone"})]
    state, results = converse(turns)
    assert "only to the one provider you choose" in results[-1].message
    assert results[-1].action.type == "ask_contact"


@pytest.mark.parametrize("action,expected", [
    ("call_provider", "can't call or message providers"),
    ("book_appointment", "can't book appointments"),
    ("guarantee", "can't guarantee"),
])
def test_impossible_requests_are_declined_honestly(action, expected):
    state, results = converse(MATCHED + [("please do it", {"requested_action": action})])
    msg, provider = results[-1].message, results[-1].provider
    assert expected in msg
    assert guardrail_violations(msg, {provider.phone}, {provider.website}, False) == []


def test_question_and_answer_in_same_message_are_both_used():
    state, results = converse(MATCHED + [("Today please — are they licensed?",
                                          {"urgency": "same_day", "question_topic": "license_or_insurance"})])
    assert state.urgency == "same_day"
    assert "don't have verified license" in results[-1].message
    assert results[-1].action.type == "ask_contact"


def test_guardrail_rejects_invented_price_rating_or_license():
    for text in ("They charge $150 for a visit.", "They're rated 4.8 stars.", "They are licensed and insured.",
                 "A top-rated company."):
        assert guardrail_violations(text, set(), set(), False), text
    assert not guardrail_violations("I don't have verified license or insurance details for them.", set(), set(), False)


def test_guardrail_allows_honest_negations_of_forbidden_claims():
    for text in ("I can't guarantee timing.", "Nothing has been booked or scheduled.", "They haven't been contacted."):
        assert guardrail_violations(text, set(), set(), False) == [], text
    assert guardrail_violations("Your appointment is booked for 3pm.", set(), set(), False)


# ---------- outcomes are recoverable; consent can change after a lead is prepared ----------

TO_LEAD = MATCHED + [
    ("today", {"urgency": "same_day"}),
    ("Sam, 408-555-0100", {"customer_name": "Sam", "contact_method": "phone", "contact_value": "408-555-0100"}),
    ("yes", {"consent_to_share": True}),
]


def test_revoking_consent_after_lead_withdraws_it():
    state, results = converse(TO_LEAD + [("Actually don't share my number", {"consent_to_share": False})])
    assert results[-2].lead is not None  # a lead had been prepared
    r = results[-1]
    assert r.lead_withdrawn and r.lead is None
    assert state.outcome == "self_serve"
    assert "withdrawn" in r.message and r.provider.phone in r.message


def test_granting_consent_after_self_serve_prepares_lead():
    turns = TO_LEAD[:-1] + [("no", {"consent_to_share": False}), ("ok fine, you can share it", {"consent_to_share": True})]
    state, results = converse(turns)
    assert results[-2].action.type == "self_serve"
    assert state.outcome == "ready_to_dispatch" and results[-1].lead is not None


def test_changing_phone_after_lead_updates_it():
    state, results = converse(TO_LEAD + [("use 408-555-0199 instead",
                                          {"contact_value": "408-555-0199", "corrections": ["contact_value"]})])
    r = results[-1]
    assert r.lead_withdrawn and r.lead is not None  # old lead superseded by an updated one
    assert r.lead["customer"]["contact"] == "(408) 555-0199"
    assert r.message.startswith("I've updated your request.")


def test_thanks_after_lead_does_not_duplicate_it():
    state, results = converse(TO_LEAD + [("thanks!", {})])
    r = results[-1]
    assert r.action.type == "already_closed" and r.lead is None and not r.lead_withdrawn
    assert state.outcome == "ready_to_dispatch"


def test_question_after_lead_is_answered_without_reopening():
    state, results = converse(TO_LEAD + [("did you send it already?", {"question_topic": "request_status"})])
    r = results[-1]
    assert "hasn't been sent" in r.message and state.outcome == "ready_to_dispatch" and not r.lead_withdrawn


def test_out_of_area_then_pilot_zip_continues():
    turns = [("My AC blows warm air", AC_ISSUE), ("94301", {"zip_code": "94301"}),
             ("oh it's actually 95050", {"zip_code": "95050", "corrections": ["zip_code"]})]
    state, results = converse(turns)
    assert results[1].action.type == "out_of_area"
    assert state.outcome is None and state.selected_provider_id and results[-1].action.type == "ask_timing"


def test_unsupported_then_supported_issue_continues():
    turns = [("termites", {"unsupported_service": "pest control"}),
             ("my AC is also broken", AC_ISSUE)]
    state, results = converse(turns)
    assert results[0].action.type == "unsupported_category"
    assert state.service_category == "hvac" and results[-1].action.type == "ask_location"
