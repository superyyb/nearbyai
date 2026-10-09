"""Deterministic invariants: these must hold regardless of which LLM is used."""

import pytest

from app.domain import Category, ExtractedFields, ExtractionResult, LeadState, Outcome, ServiceDetails
from app.services import next_action, safety
from app.services.agent import handle_turn
from app.services.lead_validator import validate_lead
from app.services.llm import guardrail_violations
from app.services.provider_search import coverage_matrix, get_provider, load_providers, search
from app.services.rules_llm import RulesLLM
from app.services.state_manager import merge, normalize_contact


def run(messages: list[str]) -> tuple[LeadState, list]:
    state, history, results = LeadState(conversation_id="t"), [], []
    for m in messages:
        results.append(handle_turn(state, m, RulesLLM(), history))
        history.append(m)
    return state, results


def ready_state(**overrides) -> LeadState:
    s = LeadState(
        conversation_id="t",
        service_category=Category.WATER_DAMAGE,
        category_confirmed=True,
        issue_summary="Basement water after storm, stopped this morning",
        service_details=ServiceDetails(water_still_active=False),
        zip_code="95050",
        pilot_area="santa_clara",
        urgency="same_day",
        customer_name="Test User",
        contact_method="phone",
        contact_value="(408) 555-0142",
        consent_to_share=True,
        selected_provider_id="911-restoration-of-san-jose",
        selected_provider_coverage="verified",
    )
    return s.model_copy(update=overrides)


# ---------- provider data ----------

def test_every_pilot_cell_has_an_eligible_provider():
    for (cat, area), counts in coverage_matrix().items():
        assert counts.get("verified", 0) + counts.get("provisional", 0) >= 2, (cat, area, counts)


def test_search_prefers_verified_over_provisional():
    result = search(Category.WATER_DAMAGE, "sunnyvale")
    assert result.tier == "verified"
    assert all(p.coverage["sunnyvale"] == "verified" for p in result.candidates)


def test_search_never_returns_unknown_coverage():
    for cat in Category:
        for area in ("santa_clara", "sunnyvale", "north_san_jose"):
            for p in search(cat, area).candidates:
                assert p.coverage[area] in ("verified", "provisional")
                assert cat in p.service_categories


def test_provider_records_have_provenance():
    for p in load_providers().values():
        assert p.source_url.startswith("https://") and p.verified_at and p.phone


# ---------- validator ----------

def test_complete_lead_is_valid():
    s = ready_state()
    r = validate_lead(s, get_provider(s.selected_provider_id))
    assert r.valid, r
    assert r.completeness_score >= 90


def test_no_dispatch_without_explicit_consent():
    for consent in (None, False):
        s = ready_state(consent_to_share=consent)
        assert not validate_lead(s, get_provider(s.selected_provider_id)).valid


def test_missing_street_address_is_pending_not_blocking():
    s = ready_state(street_address=None)
    r = validate_lead(s, get_provider(s.selected_provider_id))
    assert r.valid and r.completeness_breakdown["location"] < 20


def test_wrong_category_provider_is_rejected():
    s = ready_state(selected_provider_id="wci-electric")
    r = validate_lead(s, get_provider("wci-electric"))
    assert not r.valid and any("does not offer" in e for e in r.errors)


def test_unknown_coverage_provider_is_rejected():
    # SERVPRO of Santa Clara has 'unknown' coverage for Sunnyvale.
    s = ready_state(selected_provider_id="servpro-of-santa-clara", pilot_area="sunnyvale", zip_code="94086")
    assert not validate_lead(s, get_provider("servpro-of-santa-clara")).valid


# ---------- state merge ----------

def test_correction_overwrites_and_category_change_clears_details():
    s = ready_state()
    merge(s, ExtractionResult(updates=ExtractedFields(service_category=Category.ROOFING), corrections=["service_category"]))
    assert s.service_category == Category.ROOFING
    assert s.service_details.water_still_active is None
    assert s.selected_provider_id is None and s.consent_to_share is None


def test_non_correction_does_not_overwrite():
    s = ready_state()
    merge(s, ExtractionResult(updates=ExtractedFields(zip_code="95134")))
    assert s.zip_code == "95050"


def test_zip_correction_reruns_matching():
    s = ready_state()
    merge(s, ExtractionResult(updates=ExtractedFields(zip_code="95134"), corrections=["zip_code"]))
    assert s.pilot_area == "north_san_jose" and s.selected_provider_id is None


def test_invalid_values_never_enter_state():
    s = LeadState(conversation_id="t")
    merge(s, ExtractionResult(updates=ExtractedFields(zip_code="9505", contact_value="555-12")))
    assert s.zip_code is None and s.contact_value is None


@pytest.mark.parametrize("raw,expected", [
    ("408-555-0142", "(408) 555-0142"),
    ("+1 (408) 555 0142", "(408) 555-0142"),
    ("A@B.com", "a@b.com"),
    ("12345", None),
])
def test_normalize_contact(raw, expected):
    assert normalize_contact(None, raw)[1] == expected


# ---------- safety ----------

def test_gas_leak_is_redirect():
    assert safety.screen("I smell gas near the stove").is_redirect


def test_sparking_is_urgent_not_redirect():
    r = safety.screen("the outlet is sparking")
    assert not r.is_redirect and r.urgent_flags == ["electrical_sparking"]


# ---------- end-to-end funnel (rules backend) ----------

def test_happy_path_converts_in_six_turns():
    state, results = run([
        "Water started coming into my basement last night after the storm.",
        "123 Main St, Santa Clara, CA 95050",
        "No, it stopped this morning",
        "yes today if possible",
        "Test User, 408-555-0142",
        "yes",
    ])
    assert state.outcome == Outcome.READY_TO_DISPATCH
    assert state.user_turns == 6
    assert results[-1].lead["matched_provider"]["coverage"].startswith("Verified")


def test_declined_consent_is_self_serve_not_lead():
    state, results = run(["my toilet is overflowing", "95051", "today", "Sam, 408-555-0100", "no"])
    assert state.outcome == Outcome.SELF_SERVE
    assert results[-1].lead is None


def test_out_of_area_is_no_match():
    state, _ = run(["AC is blowing warm air", "94301"])
    assert state.outcome == Outcome.NO_MATCH


def test_unsupported_category():
    state, _ = run(["I have termites in my garage"])
    assert state.outcome == Outcome.UNSUPPORTED_CATEGORY


def test_gas_is_safety_redirect():
    state, results = run(["I smell gas in the kitchen"])
    assert state.outcome == Outcome.SAFETY_REDIRECT
    assert "911" in results[0].message


def test_ambiguous_ceiling_asks_disambiguation_first():
    _, results = run(["There's a brown stain on my ceiling that keeps growing"])
    assert results[0].action.type == "clarify_category"


def test_closed_conversation_stays_closed():
    state, results = run(["I smell gas", "ok what now"])
    assert results[-1].action.type == "already_closed"


# ---------- writer guardrails ----------

def test_guardrail_rejects_ungrounded_phone_and_booking_claims():
    allowed = {"(408) 449-4904"}
    assert guardrail_violations("Call them at (408) 449-4904.", allowed, set(), False) == []
    assert guardrail_violations("Call (650) 111-2222.", allowed, set(), False)
    assert guardrail_violations("Your appointment is booked!", allowed, set(), False)
    assert guardrail_violations("They serve your area.", allowed, set(), provisional=True)


def test_address_rides_with_contact_question_once():
    s = ready_state(consent_to_share=None, customer_name=None, contact_value=None, street_address=None)
    first = next_action.decide(s)
    assert first.type == "ask_contact" and first.note == "include_address"
    s.asked_fields.append("street_address")
    assert next_action.decide(s).note is None


@pytest.mark.parametrize("message,redirect,urgent", [
    ("No, nothing like that. No sparks or burning smell.", [], []),
    ("I don't smell gas, the stove is fine", [], []),
    ("No, I do see sparks coming from it", [], ["electrical_sparking"]),
    ("No, but I smell gas near the water heater", ["gas_leak"], []),
    ("The outlet is sparking and there's no breaker label", [], ["electrical_sparking"]),
])
def test_safety_screen_respects_negation(message, redirect, urgent):
    r = safety.screen(message)
    assert r.redirect_flags == redirect and r.urgent_flags == urgent


def test_denying_hazard_does_not_mark_lead_urgent():
    state, results = run(["my kitchen lights keep flickering", "95050", "no sparks or burning smell"])
    assert state.safety_flags == [] and state.urgency is None
    assert results[-1].action.type == "ask_timing"


def test_unknown_fact_overrides_earlier_inference():
    s = ready_state()
    s.service_details.water_still_active = True  # inferred earlier
    merge(s, ExtractionResult(updates=ExtractedFields(unknown_facts=["water_still_active"])))
    assert s.service_details.water_still_active is None
    assert "water_still_active" in s.asked_fields
    r = validate_lead(s, get_provider(s.selected_provider_id))
    assert r.valid  # asked-but-unknown is acceptable; the provider confirms on the call


def test_lead_packet_says_unknown_instead_of_guessing():
    from app.services.lead_packet import build_packet

    s = ready_state(service_details=ServiceDetails())
    s.asked_fields.append("water_still_active")
    packet = build_packet(s, get_provider(s.selected_provider_id), 90)
    assert packet["service"]["details"]["Water still entering"].startswith("Unknown")


def test_wire_schema_maps_unknown():
    from tests.helpers import wire_defaults

    up = wire_defaults(water_still_active="unknown", sparks_present="yes").to_result().updates
    assert up.water_still_active is None and up.unknown_facts == ["water_still_active"] and up.sparks_present is True


# ---------- provider rejection / alternatives (found by manual testing) ----------

def matched_hvac_state() -> LeadState:
    """Mirrors the manual-test failure: AC in Santa Clara, provider presented, timing not yet asked."""
    state, results = run(["My home AC doesn't work", "I am in Santa Clara. I don't know the ZIP code"])
    assert results[-1].action.type == "ask_timing" and state.selected_provider_id
    return state


def test_rejected_provider_is_replaced_and_funnel_continues():
    state = matched_hvac_state()
    rejected = state.selected_provider_id
    r = handle_turn(state, "Any other options? I don't like them, bad experience last time.", RulesLLM(), [])
    assert rejected in state.excluded_provider_ids
    assert state.selected_provider_id not in (None, rejected)
    assert get_provider(state.selected_provider_id).coverage["santa_clara"] == "verified"
    assert r.action.type == "ask_timing"  # conversation continues, not reset
    assert r.message.startswith("Understood — I won't use")


def test_rejected_provider_never_reselected_after_new_search():
    state = matched_hvac_state()
    rejected = state.selected_provider_id
    handle_turn(state, "I don't want them", RulesLLM(), [])
    # A location change triggers a fresh search; the rejected provider must stay out.
    merge(state, ExtractionResult(updates=ExtractedFields(zip_code="95134"), corrections=["zip_code"]))
    from app.services.matching import select_provider
    select_provider(state)
    assert rejected not in state.candidate_provider_ids and state.selected_provider_id != rejected


def test_switching_provider_clears_consent():
    from app.services.matching import switch_provider

    s = ready_state(candidate_provider_ids=["911-restoration-of-san-jose", "roto-rooter-plumbing-water-cleanup-santa-clara"])
    s.asked_fields.append("consent")
    switch_provider(s, "reject", "bad reviews")
    assert s.consent_to_share is None and "consent" not in s.asked_fields
    assert not validate_lead(s, get_provider(s.selected_provider_id)).valid


def test_rejecting_every_verified_provider_is_honest_no_match():
    state = matched_hvac_state()
    for _ in range(len(state.candidate_provider_ids)):
        r = handle_turn(state, "I don't like that one either", RulesLLM(), [])
    assert state.outcome == Outcome.NO_MATCH and r.action.note == "all_rejected"
    assert state.selected_provider_id is None


def test_request_for_alternative_without_rejection_keeps_provider_eligible():
    state = matched_hvac_state()
    first = state.selected_provider_id
    handle_turn(state, "Are there any other options?", RulesLLM(), [])
    assert first in state.shown_provider_ids and first not in state.excluded_provider_ids
    assert state.selected_provider_id != first
