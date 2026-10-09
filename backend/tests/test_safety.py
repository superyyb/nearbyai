"""Hybrid safety: regex first line, unioned with the extractor's fixed hazard families. Copy is fixed in code."""

import pytest

from app.services import safety
from tests.helpers import converse

# Verbatim openings the regex used to miss (from the frozen generalization set).
MISSED_BEFORE = [
    ("my basement flooded after the storm and there's water touching the extension cords down there", "water_near_electrical"),
    ("the outlet in my bathroom is warm to the touch", "overheating_burning"),
    ("my upstairs neighbor's bathtub overflowed and now water is coming through my ceiling light. I rent.", "water_near_electrical"),
    ("house smells like something burning but i cant find where its coming from", "overheating_burning"),
    ("buzzing sound from the electrical panel", "electrical_buzzing"),
    ("Ive got water in the light fixture in the bathroom and its still on, what do i do", "water_near_electrical"),
]


@pytest.mark.parametrize("message,flag", MISSED_BEFORE)
def test_regex_first_line_now_catches_previously_missed_hazards(message, flag):
    r = safety.screen(message)
    assert flag in r.urgent_flags and r.guidance().startswith("For safety")


@pytest.mark.parametrize("message", [
    "water heater pilot light keeps going out",
    "no sparks or burning smell, and the outlet isn't warm",
])
def test_no_false_alarm_on_similar_wording(message):
    r = safety.screen(message)
    assert not r.urgent_flags and not r.redirect_flags


def test_llm_family_adds_guidance_the_regex_missed():
    result, added = safety.with_llm_hazards(safety.screen("the dryer plug looks melty"), ["overheating_burning"])
    assert added in ([], ["overheating_burning"])  # regex may already catch it; either way it is covered
    assert "overheating_burning" in result.urgent_flags


def test_llm_family_does_not_duplicate_a_regex_family():
    base = safety.screen("the outlet is sparking")
    result, added = safety.with_llm_hazards(base, ["sparking_buzzing_electrical"])
    assert added == [] and result.urgent_flags == ["electrical_sparking"]


def test_llm_gas_family_is_a_blocking_redirect():
    result, added = safety.with_llm_hazards(safety.screen("something smells off near the stove"), ["gas_co_fire"])
    assert result.is_redirect and added == ["gas_co_fire"] and "1-800-743-5000" in result.guidance()


def test_llm_hazard_flows_through_the_turn_with_fixed_copy():
    state, results = converse([("the thing behind the TV is getting really toasty", {
        "service_category": "electrical", "issue_summary": "Something behind the TV is getting very hot",
        "hazard_categories": ["overheating_burning"], "hazard_evidence": "getting really toasty"})])
    r = results[-1]
    assert r.message.startswith(safety.URGENT_GUIDANCE["overheating_burning"])
    assert "safety_llm:overheating_burning:getting really toasty" in r.events
    assert r.action.type == "ask_location"  # warn, then continue the lead
    assert state.urgency is None  # the risk is not the customer's timing preference


def test_llm_gas_flag_redirects_but_can_reopen():
    state, results = converse([("weird smell by the stove", {"hazard_categories": ["gas_co_fire"]}),
                               ("no it's not gas, the burner just won't light", {
                                   "service_category": "plumbing", "issue_summary": "Stove burner won't light"})])
    assert results[0].action.type == "safety_redirect"
    assert state.outcome is None  # a later clarification reopens the conversation
