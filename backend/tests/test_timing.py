"""The user's preferred visit time (found by manual testing: "I prefer this afternoon after 2pm" was extracted, but
the lead only said "Same-day service preferred" and the reply didn't confirm the time)."""

from datetime import date

import pytest

from app.domain import LeadState
from app.services import timing
from app.services.agent import handle_turn
from app.services.lead_packet import render_text
from app.services.llm import guardrail_violations
from app.services.rules_llm import RulesLLM
from tests.helpers import AC_ISSUE, SANTA_CLARA, converse

THURSDAY = date(2026, 10, 8)
TO_TIMING = [("My AC blows warm air", AC_ISSUE), ("Santa Clara", SANTA_CLARA)]
AFTER_2PM = ("I prefer this afternoon after 2pm", {"urgency": "same_day", "preferred_time": "this afternoon after 2pm",
                                                   "preferred_day": "today", "preferred_window": "after 2 PM"})
CONTACT_AND_CONSENT = [("Sam, 408-555-0100", {"customer_name": "Sam", "contact_method": "phone",
                                              "contact_value": "408-555-0100"}),
                       ("yes", {"consent_to_share": True})]


@pytest.fixture(autouse=True)
def on_thursday(monkeypatch):
    monkeypatch.setattr(timing, "local_today", lambda: THURSDAY)


def to_lead(time_turn):
    state, results = converse(TO_TIMING + [time_turn] + CONTACT_AND_CONSENT)
    assert results[-1].lead is not None
    return state, results


# ---------- resolving the day to a date ----------

@pytest.mark.parametrize("day,expected", [
    ("today", date(2026, 10, 8)), ("tomorrow", date(2026, 10, 9)), ("saturday", date(2026, 10, 10)),
    ("monday", date(2026, 10, 12)), ("wednesday", date(2026, 10, 14)),
    ("thursday", None),  # said on a Thursday: today or next week? Don't guess.
    ("other", None), (None, None),
])
def test_resolve_day(day, expected):
    assert timing.resolve_day(day, THURSDAY) == expected


# ---------- the lead keeps the specific time, anchored to a date ----------

def test_specific_time_is_kept_next_to_the_urgency_in_the_lead():
    state, results = to_lead(AFTER_2PM)
    lead = results[-1].lead
    assert lead["timing"]["preference"] == "Same-day service preferred — Thursday, Oct 8 after 2 PM"
    assert lead["timing"]["customer_words"] == "this afternoon after 2pm"
    assert "Timing: Same-day service preferred — Thursday, Oct 8 after 2 PM (availability not confirmed)" in render_text(lead)
    assert timing.progress_label(state) == "Same-day · after 2 PM"


def test_the_date_is_fixed_when_the_time_is_said(monkeypatch):
    state, _ = converse(TO_TIMING + [AFTER_2PM])
    monkeypatch.setattr(timing, "local_today", lambda: date(2026, 10, 9))  # the conversation continues next day
    state, results = converse(CONTACT_AND_CONSENT, state)
    assert "Thursday, Oct 8 after 2 PM" in results[-1].lead["timing"]["preference"]


def test_same_day_without_a_time_is_still_anchored_to_the_date():
    state, results = to_lead(("today please", {"urgency": "same_day", "preferred_time": "today"}))
    assert results[-1].lead["timing"]["preference"] == "Same-day service preferred — Thursday, Oct 8"
    assert timing.progress_label(state) == "Same-day service preferred"


def test_weekday_and_window():
    state, results = to_lead(("Saturday morning works", {"urgency": "within_week", "preferred_time": "Saturday morning",
                                                         "preferred_day": "saturday", "preferred_window": "morning"}))
    assert results[-1].lead["timing"]["preference"] == "Within the next few days — Saturday, Oct 10 morning"
    assert timing.progress_label(state) == "Next few days · Saturday morning"


def test_a_period_is_not_turned_into_a_date():
    state, results = to_lead(("sometime this weekend", {"urgency": "within_week", "preferred_time": "this weekend",
                                                        "preferred_day": "other"}))
    assert results[-1].lead["timing"]["preference"] == "Within the next few days — this weekend"
    assert state.preferred_date is None


def test_a_time_without_urgency_still_counts_as_timing():
    state, results = to_lead(("after 4pm", {"preferred_time": "after 4pm", "preferred_window": "after 4 PM"}))
    assert results[-1].lead["timing"]["preference"] == "after 4 PM"


# ---------- the reply confirms a specific time once, without implying it's booked ----------

def test_specific_time_is_confirmed_before_the_next_question():
    _, results = converse(TO_TIMING + [AFTER_2PM])
    message = results[-1].message
    assert message.startswith("Got it — I'll note that you'd prefer today after 2 PM. "
                              "The provider would still need to confirm that time.")
    assert "What's your name and the best phone number" in message
    assert "timing_confirmed" in results[-1].events


def test_confirmation_is_said_once():
    _, results = to_lead(AFTER_2PM)
    assert ["I'll note" in r.message for r in results[2:]] == [True, False, False]


def test_plain_today_is_not_confirmed_back():
    _, results = converse(TO_TIMING + [("today", {"urgency": "same_day", "preferred_time": "today"})])
    assert "I'll note" not in results[-1].message


def test_confirmation_passes_the_writer_guardrails():
    state, _ = converse(TO_TIMING + [AFTER_2PM])
    assert guardrail_violations(timing.confirmation(state), set(), set(), False) == []


def test_rephrase_must_keep_the_time_and_that_it_is_unconfirmed():
    state, _ = converse(TO_TIMING + [AFTER_2PM])
    assert timing.confirmation_kept("Noted — today after 2 PM, though the provider still has to confirm it.", state)
    assert not timing.confirmation_kept("Noted, this afternoon works. What's your name?", state)
    assert not timing.confirmation_kept("Noted — today after 2 PM. What's your name?", state)


# ---------- changing the time ----------

def test_a_corrected_time_replaces_the_old_one_as_a_whole():
    state, results = to_lead(AFTER_2PM)
    state, results = converse([("actually tomorrow morning instead", {
        "urgency": "within_week", "preferred_time": "tomorrow morning", "preferred_day": "tomorrow",
        "preferred_window": "morning", "corrections": ["urgency"]})], state)
    r = results[-1]
    assert r.lead["timing"]["preference"] == "Within the next few days — Friday, Oct 9 morning"
    assert r.message.startswith("I've updated your request. Got it — I'll note that you'd prefer tomorrow morning.")
    assert state.consent_to_share is True  # same provider, same request: consent stands


def test_changing_only_the_time_of_day_keeps_the_day_and_urgency():
    state, _ = to_lead(AFTER_2PM)
    state, results = converse([("can they come after 4pm instead?", {
        "preferred_time": "after 4pm", "preferred_window": "after 4 PM", "corrections": ["urgency"]})], state)
    assert results[-1].lead["timing"]["preference"] == "Same-day service preferred — Thursday, Oct 8 after 4 PM"


def test_same_day_and_window_restated_with_a_new_window_keeps_the_date(monkeypatch):
    state, _ = to_lead(AFTER_2PM)
    monkeypatch.setattr(timing, "local_today", lambda: date(2026, 10, 9))
    state, results = converse([("make it after 4pm", {
        "urgency": "same_day", "preferred_day": "today", "preferred_time": "after 4pm",
        "preferred_window": "after 4 PM", "corrections": ["urgency"]})], state)
    assert state.preferred_date == "2026-10-08"


def test_a_new_day_drops_the_old_urgency_and_window():
    state, _ = to_lead(AFTER_2PM)
    state, results = converse([("could they come Saturday instead?", {
        "preferred_time": "Saturday", "preferred_day": "saturday", "corrections": ["urgency"]})], state)
    assert results[-1].lead["timing"]["preference"] == "Saturday, Oct 10"


def test_timing_edit_clears_every_timing_field():
    state, _ = to_lead(AFTER_2PM)
    state, results = converse([("can I change the time?", {"edit_field": "timing", "edit_kind": "wants_change"})], state)
    # The old value stays until the new one arrives; "current_value_wrong" clears it.
    state, results = converse([("the time I gave is wrong", {"edit_field": "timing", "edit_kind": "current_value_wrong"})],
                              state)
    assert (state.urgency, state.preferred_time, state.preferred_day, state.preferred_window, state.preferred_date) == \
        (None, None, None, None, None)


# ---------- the offline rule-based backend ----------

def test_rules_backend_reads_a_simple_day_and_time():
    state = LeadState(conversation_id="x")
    history = []
    for m in ["My AC blows warm air", "Santa Clara", "this afternoon after 2pm"]:
        r = handle_turn(state, m, RulesLLM(), history)
        history.append(m)
    assert (state.preferred_day, state.preferred_window, state.preferred_date) == ("today", "after 2 PM", "2026-10-08")
    assert "I'll note that you'd prefer today after 2 PM" in r.message
