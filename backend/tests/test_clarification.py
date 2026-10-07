"""Contextual clarification: the LLM proposes the question, code validates it, the generic menu is last."""

import pytest

from app.domain import Category, LeadState
from app.services.clarification import choose_question, is_category_menu, question_issues
from tests.helpers import converse

GOOD = "Is it only your home, or are your neighbors out of water too?"


@pytest.mark.parametrize("question,issue", [
    ("Is it a leak, a heating or cooling problem, an electrical issue, or something with the roof?", "generic category menu"),
    ("Is it only your home? Or the whole street?", "must contain exactly one question"),
    ("Should I send DG Heating & Air Conditioning?", "mentions a provider"),
    ("What's the best phone number to reach you?", "asks for contact details during clarification"),
    ("Can you call (408) 555-0100?", "contains a phone number or URL"),
])
def test_validator_rejects_bad_proposals(question, issue):
    assert issue in question_issues(question, LeadState(conversation_id="x"))


def test_validator_rejects_asking_for_a_known_location():
    state = LeadState(conversation_id="x", pilot_area="santa_clara")
    assert "asks for a location that is already known" in question_issues("What's your ZIP code?", state)


def test_validator_accepts_a_targeted_question():
    assert question_issues(GOOD, LeadState(conversation_id="x")) == []


def test_choice_order_llm_then_rule_then_generic():
    state = LeadState(conversation_id="x")
    assert choose_question(state, GOOD, "rule?")[:2] == (GOOD, "llm")
    q, source, rejected = choose_question(state, "Plumbing, HVAC, electrical, or roof?", "Rule question?")
    assert (q, source) == ("Rule question?", "rule") and "generic category menu" in rejected
    assert choose_question(state, None, None)[:2] == (None, "generic")


def test_no_water_regression_uses_the_targeted_question():
    # Manual test: "There is no water in my home" got the 5-category menu although Claude had understood it.
    state, results = converse([("Hi, I have water issue. There is no water in my home", {
        "service_category": "plumbing", "candidate_categories": ["plumbing"], "needs_clarification": True,
        "issue_summary": "No running water anywhere in the home", "suggested_question": GOOD,
    })])
    r = results[-1]
    assert r.message == GOOD and not is_category_menu(r.message)
    assert "clarification_source:llm" in r.events


def test_invalid_proposal_falls_back_to_rule_question_for_known_pattern():
    state, results = converse([("There's a brown stain on my ceiling", {
        "service_category": "roofing", "candidate_categories": ["roofing", "plumbing"], "needs_clarification": True,
        "suggested_question": "Is this plumbing, HVAC, electrical, or roofing?",
    })])
    assert "rains" in results[-1].message and "clarification_source:rule" in results[-1].events


def test_generic_template_only_when_nothing_better_exists():
    state, results = converse([("help", {})])
    assert "clarification_source:generic" in results[-1].events


def test_ask_category_uses_the_llm_question_too():
    state, results = converse([("something's off with my house", {
        "suggested_question": "What are you noticing — water, no power, a smell, or something not working?"})])
    assert results[-1].action.type == "ask_category"
    assert results[-1].message.startswith("What are you noticing")
