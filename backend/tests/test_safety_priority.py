"""User preference, observed facts, and the system's risk assessment are kept apart (found by manual testing: water
dripping through a ceiling light produced "Timing: As soon as possible (customer reports urgent need)" although the
user never gave a timing, and "Sparks / burning smell / hot fixtures: Yes" although they said "no sparks")."""

import pytest

from app.domain import LeadState, Provider
from app.services import safety, timing
from app.services.lead_packet import render_text
from app.services.matching import deterministic_rank
from tests.helpers import AC_ISSUE, SANTA_CLARA, converse

LIGHT = ("Water is dripping through the ceiling light, and the light is still on.", {
    "service_category": "water_damage_restoration", "category_confirmed": True,
    "issue_summary": "Water is dripping through a ceiling light fixture that is still on.",
    "hazard_categories": ["electrical_water"], "water_still_active": True})
NO_SPARKS = ("No, I don't see any sparks or plumbing", {"sparks_present": False})
ZIP = ("95050", {"zip_code": "95050"})
CONTACT = ("Test User, 408-555-0142", {"customer_name": "Test User", "contact_method": "phone",
                                       "contact_value": "408-555-0142"})
CONSENT = ("sure", {"consent_to_share": True})


def lead_text(results) -> str:
    assert results[-1].lead is not None
    return render_text(results[-1].lead)


# ---------- a safety risk is not the customer's timing ----------

def test_hazard_without_timing_warns_keeps_timing_unknown_and_still_asks_it():
    state, results = converse([LIGHT, NO_SPARKS, ZIP])
    assert results[0].message.startswith("For safety:")
    assert state.urgency is None and "water_near_electrical" in state.safety_flags
    assert results[-1].action.type == "ask_timing"


def test_hazard_plus_asap_is_the_customers_urgency():
    state, results = converse([LIGHT, NO_SPARKS, ZIP, ("ASAP please", {"urgency": "emergency"}), CONTACT, CONSENT])
    assert "Timing: As soon as possible — customer requested urgent service" in lead_text(results)


def test_safety_risk_alone_never_claims_the_customer_asked_for_urgency():
    state, results = converse([LIGHT, NO_SPARKS, ZIP, ("hmm", {}), ("not sure", {}), CONTACT, CONSENT])
    text = lead_text(results)
    assert "customer reports" not in text and "customer requested" not in text
    assert "Timing: Not stated by the customer" in text
    assert ("Safety priority: Urgent — Water near an electrical fixture, outlet, or panel. "
            "Safety guidance was given to the customer.") in text


def test_unanswered_timing_does_not_block_the_lead():
    # Before: the funnel moved on after two asks, but the validator required timing, so the user was asked for
    # their contact details again and again.
    state, results = converse([("My AC blows warm air", AC_ISSUE), ("Santa Clara", SANTA_CLARA),
                               ("hmm", {}), ("not sure", {}), CONTACT, CONSENT])
    assert results[-1].action.type == "lead_ready" and results[-1].lead
    assert results[-1].lead["timing"]["preference"] == "Not stated by the customer"


# ---------- observed facts are specific and latest-wins, one fact at a time ----------

def test_no_sparks_keeps_the_water_electrical_hazard():
    state, results = converse([LIGHT, NO_SPARKS])
    assert "water_near_electrical" in state.safety_flags and state.service_details.sparks_present is False


def test_lead_reports_no_sparks_instead_of_a_broad_yes():
    _, results = converse([LIGHT, NO_SPARKS, ZIP, ("today", {"urgency": "same_day"}), CONTACT, CONSENT])
    text = lead_text(results)
    assert "Sparks observed: No" in text
    assert "Sparks / burning smell / hot fixtures" not in text


def test_a_later_statement_about_the_same_fact_wins():
    state, _ = converse([("the outlet sparked", {"service_category": "electrical", "sparks_present": True}),
                         ("actually no, there were no sparks, just a pop", {"sparks_present": False})])
    assert state.service_details.sparks_present is False


def test_plain_no_to_the_electrical_question_answers_all_three():
    state, results = converse([("my kitchen lights flicker", {"service_category": "electrical",
                                                              "issue_summary": "Kitchen lights flicker"}),
                               ZIP,
                               ("no, nothing like that", {"sparks_present": False, "burning_smell_present": False,
                                                          "hot_fixture_present": False})])
    assert results[1].action.type == "ask_qualification" and results[1].action.field == "electrical_symptoms"
    assert results[-1].action.type == "ask_timing"


def test_one_answered_symptom_counts_as_answering_the_question():
    state, results = converse([("my kitchen lights flicker, no sparks", {
        "service_category": "electrical", "issue_summary": "Kitchen lights flicker", "sparks_present": False}), ZIP])
    assert results[-1].action.type == "ask_timing"


# ---------- the provider sees plain language and only the facts for its trade ----------

def test_no_internal_flag_names_reach_the_lead():
    _, results = converse([LIGHT, NO_SPARKS, ZIP, ("today", {"urgency": "same_day"}), CONTACT, CONSENT])
    text = lead_text(results)
    for flag in list(safety.URGENT_GUIDANCE) + list(safety.REDIRECT_GUIDANCE):
        assert flag not in text
    assert "Safety flags" not in text


def test_water_damage_lead_shows_no_roofing_or_electrical_question_fields():
    light = (LIGHT[0], {**LIGHT[1], "active_leak": True})
    _, results = converse([light, ZIP, ("today", {"urgency": "same_day"}), CONTACT, CONSENT])
    details = results[-1].lead["service"]["details"]
    assert "Actively leaking" not in details and "Sparks, burning smell, or heat" not in details
    assert details["Water still entering"] == "Yes"


@pytest.mark.parametrize("flag", list(safety.URGENT_GUIDANCE))
def test_every_warn_and_continue_flag_has_provider_wording(flag):
    assert flag in safety.SAFETY_DISPLAY


# ---------- 24/7 is still preferred for a safety risk, without faking the customer's timing ----------

def _provider(pid: str, emergency: bool) -> Provider:
    return Provider(id=pid, name=pid, service_categories=["water_damage_restoration"], phone="408-555-0000",
                    website="https://example.com", coverage={"santa_clara": "verified"},
                    coverage_evidence="water damage restoration", emergency_service=emergency,
                    source_url="https://example.com")


def test_safety_risk_still_prefers_a_24_7_provider_when_timing_is_unknown():
    state = LeadState(conversation_id="x", service_category="water_damage_restoration",
                      issue_summary="Ceiling light dripping", safety_flags=["water_near_electrical"])
    ranked, reason = deterministic_rank(state, [_provider("a-daytime", False), _provider("b-24-7", True)])
    assert ranked[0].id == "b-24-7" and "24/7" in reason
    assert state.urgency is None
    calm = state.model_copy(update={"safety_flags": []})
    assert deterministic_rank(calm, [_provider("a-daytime", False), _provider("b-24-7", True)])[0][0].id == "a-daytime"


def test_progress_panel_shows_no_timing_for_a_safety_risk_alone():
    state, _ = converse([LIGHT, NO_SPARKS, ZIP])
    assert timing.progress_label(state) is None


def test_rules_backend_does_not_read_im_not_sure_as_a_name():
    from app.services.rules_llm import RulesLLM

    up = RulesLLM().extract(LeadState(conversation_id="x"), "I'm not sure", "urgency").updates
    assert up.customer_name is None


def test_progress_panel_does_not_show_the_provider_wording_to_the_user():
    state, _ = converse([LIGHT, NO_SPARKS, ZIP, ("ASAP please", {"urgency": "emergency"})])
    assert timing.progress_label(state) == "As soon as possible"
