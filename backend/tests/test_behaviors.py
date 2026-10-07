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
