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


# ---------- user control over the provider ----------

ELECTRICAL_SUNNYVALE = [
    ("my kitchen outlets stopped working", {"service_category": "electrical", "issue_summary": "Kitchen outlets dead"}),
    ("Sunnyvale", {"city": "Sunnyvale"}),
    ("no sparks", {"hazard_present": False}),
]  # Sunnyvale electrical: 3 verified + 2 provisional providers in the dataset


def test_show_options_then_choose_by_name():
    state, results = converse(MATCHED + [("show me my options", {"provider_feedback": "show_options"})])
    r = results[-1]
    assert r.action.type == "present_options" and r.message.count("(408)") + r.message.count("(669)") <= 3
    state, results = converse([("EVS please", {"provider_feedback": "choose_named", "named_provider": "EVS"})], state)
    assert state.selected_provider_id == "evs-mechanical" and results[-1].action.type == "ask_timing"


def test_explicit_choice_restores_a_rejected_provider():
    state, _ = converse(MATCHED + [("not DG", {"provider_feedback": "reject"})])
    assert "dg-heating-air-conditioning" in state.excluded_provider_ids
    state, results = converse([("actually DG is fine", {"provider_feedback": "choose_named", "named_provider": "DG"})], state)
    assert state.selected_provider_id == "dg-heating-air-conditioning"
    assert "dg-heating-air-conditioning" not in state.excluded_provider_ids


def test_choosing_an_ineligible_provider_is_refused_with_reason():
    state, results = converse(MATCHED + [("use Wooding Electric", {"provider_feedback": "choose_named",
                                                                   "named_provider": "Wooding Electric"})])
    assert "can't confirm that Wooding Electric handles hvac" in results[-1].message
    assert state.selected_provider_id == "dg-heating-air-conditioning"


def test_choosing_an_unknown_provider_is_refused():
    state, results = converse(MATCHED + [("use ABC Plumbing", {"provider_feedback": "choose_named",
                                                               "named_provider": "ABC Plumbing"})])
    assert "don't have ABC Plumbing in my verified list" in results[-1].message


def test_rejecting_a_named_non_current_provider_excludes_it_without_switching():
    state, _ = converse(MATCHED)
    current = state.selected_provider_id
    state, results = converse([("and never EVS", {"provider_feedback": "reject", "named_provider": "EVS"})], state)
    assert "evs-mechanical" in state.excluded_provider_ids and state.selected_provider_id == current


def exhaust_verified(state):
    while state.selected_provider_coverage == "verified" and state.selected_provider_id:
        state, results = converse([("not them", {"provider_feedback": "reject"})], state)
    return state, results


def test_verified_exhausted_offers_provisional_and_accepting_uses_it():
    state, _ = converse(ELECTRICAL_SUNNYVALE)
    state, results = exhaust_verified(state)
    assert results[-1].action.type == "offer_provisional" and "haven't confirmed they serve Sunnyvale" in results[-1].message
    state, results = converse([("yes", {"provider_feedback": "accept_offer"})], state)
    assert state.selected_provider_coverage == "provisional" and state.selected_provider_id
    provider = results[-1].provider
    assert provider.coverage["sunnyvale"] == "provisional"


def test_declining_provisional_offer_is_honest_no_match():
    state, _ = converse(ELECTRICAL_SUNNYVALE)
    state, _ = exhaust_verified(state)
    state, results = converse([("no", {"provider_feedback": "decline_offer"})], state)
    assert state.outcome == "no_match" and results[-1].action.note == "all_rejected"


def test_unanswered_provisional_offer_is_repeated_once():
    state, _ = converse(ELECTRICAL_SUNNYVALE)
    state, _ = exhaust_verified(state)
    state, results = converse([("hmm", {})], state)
    assert results[-1].action.type == "offer_provisional"


def test_hvac_has_no_provisional_so_exhausting_verified_is_no_match():
    state, _ = converse(MATCHED)
    state, results = exhaust_verified(state)
    assert state.outcome == "no_match" and results[-1].action.note == "all_rejected"


# ---------- safety interrupts and scope boundaries ----------

from app.services import ambiguity, safety  # noqa: E402
from app.services.rules_llm import RulesLLM  # noqa: E402
from app.domain import LeadState  # noqa: E402
from app.services.agent import handle_turn  # noqa: E402


@pytest.mark.parametrize("message,flag", [
    ("The furnace has a burning smell coming from the vents", "hvac_burning_smell"),
    ("Raw sewage is coming up through the shower drain", "sewage_backup"),
    ("The ceiling is sagging with water above the bed", "ceiling_sagging"),
    ("A tree fell on the house and went through the roof", "tree_on_house"),
])
def test_new_urgent_hazards_get_specific_guidance(message, flag):
    r = safety.screen(message)
    assert flag in r.urgent_flags and not r.is_redirect
    assert r.guidance()


def test_hvac_burning_smell_does_not_get_breaker_guidance():
    r = safety.screen("there's a burning smell from the heater")
    assert r.urgent_flags == ["hvac_burning_smell"] and "thermostat" in r.guidance()


def test_hazard_interrupts_funnel_then_continues():
    state = LeadState(conversation_id="x")
    r = handle_turn(state, "Raw sewage is backing up into my basement toilet", RulesLLM(), [])
    assert r.message.startswith("For safety: avoid contact with the sewage")
    assert state.service_category == "plumbing" and r.action.type == "ask_location"


@pytest.mark.parametrize("message,expected", [
    ("My dishwasher is leaking all over the kitchen floor", "plumbing"),
    ("My dishwasher won't drain", "appliance repair"),
    ("The garage door is stuck", "unsupported"),
    ("I'm locked out of my house", "unsupported"),
])
def test_scope_policy_for_borderline_jobs(message, expected):
    state = LeadState(conversation_id="x")
    r = handle_turn(state, message, RulesLLM(), [])
    if expected == "plumbing":
        assert state.service_category == "plumbing"
    else:
        assert r.action.type == "unsupported_category"
        if expected != "unsupported":
            assert state.unsupported_service == expected


@pytest.mark.parametrize("text,rule", [
    ("The wall next to my bed feels warm", "warm_wall"),
    ("There's a buzzing sound in the hallway", "buzzing"),
    ("There's a buzzing sound from the outlet", None),  # already resolved: clearly electrical
])
def test_new_ambiguity_rules(text, rule):
    found = ambiguity.detect(text)
    assert (found.name if found else None) == rule


# ---------- corrections, partial answers, many facts at once, sharing preferences ----------

def test_everything_in_one_message_skips_straight_to_consent():
    state, results = converse([("AC broken in 95050, today please, I'm Alex 408-555-0123",
                                {**AC_ISSUE, "zip_code": "95050", "urgency": "same_day", "customer_name": "Alex",
                                 "contact_value": "408-555-0123", "street_address": "1450 Lafayette St"})])
    assert results[-1].action.type == "ask_consent" and state.user_turns == 1


def test_timing_correction_updates_state():
    state, _ = converse(MATCHED + [("today", {"urgency": "same_day"}),
                                   ("actually tomorrow is better", {"urgency": "within_week", "corrections": ["urgency"]})])
    assert state.urgency == "within_week"


def test_job_address_correction_replaces_billing_address():
    state, _ = converse([("AC broken at 10 Main St, Santa Clara", {**AC_ISSUE, "street_address": "10 Main St", **SANTA_CLARA}),
                         ("that's my billing address, the job is at 22 Oak Ave",
                          {"street_address": "22 Oak Ave", "corrections": ["street_address"]})])
    assert state.street_address == "22 Oak Ave"


def test_water_started_again_updates_qualification():
    state, _ = converse([("basement flooded", {"service_category": "water_damage_restoration",
                                               "issue_summary": "Basement flooded after storm"}),
                         ("95050", {"zip_code": "95050"}),
                         ("no it stopped", {"water_still_active": False}),
                         ("oh no, it started coming in again", {"water_still_active": True,
                                                                 "corrections": ["water_still_active"]})])
    assert state.service_details.water_still_active is True


def test_refusing_contact_is_self_serve_not_a_loop():
    state, results = converse(MATCHED + [("today", {"urgency": "same_day"}),
                                         ("I'd rather not give my number", {"declined_fields": ["contact"]})])
    assert state.outcome == "self_serve" and results[-1].provider.phone in results[-1].message


def test_unknown_zip_with_pilot_city_still_matches():
    state, results = converse([("My AC doesn't work", AC_ISSUE),
                               ("I am in Santa Clara. I don't know the ZIP code", SANTA_CLARA)])
    assert state.pilot_area == "santa_clara" and state.selected_provider_id


def test_vague_category_does_not_loop_forever():
    state, results = converse([("help", {}), ("not sure", {}), ("idk", {}), ("dunno", {})])
    assert state.outcome == "unsupported_category" and state.user_turns <= 4


def test_withholding_a_given_address_removes_it_from_the_lead():
    turns = [("AC broken at 10 Main St, Santa Clara", {**AC_ISSUE, "street_address": "10 Main St", **SANTA_CLARA}),
             ("today", {"urgency": "same_day"}),
             ("Sam 408-555-0100, but don't share my address until they call",
              {"customer_name": "Sam", "contact_value": "408-555-0100", "declined_fields": ["street_address"],
               "contact_preferences": "calls only"}),
             ("yes", {"consent_to_share": True})]
    state, results = converse(turns)
    lead = results[-1].lead
    assert lead and "10 Main St" not in str(lead)
    assert "prefers to share the street address directly" in lead["property"]["address"]
    assert lead["customer"]["contact_preferences"] == "calls only"
