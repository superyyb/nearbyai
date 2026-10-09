"""Possible utility outages: ask whether it's only this home before sending a contractor."""

from app.domain import LeadState
from app.services.agent import handle_turn
from app.services.rules_llm import RulesLLM
from tests.helpers import converse

NO_WATER = {"service_category": "plumbing", "issue_summary": "No running water anywhere in the home",
            "utility_signal": "water"}


def test_no_water_asks_home_only_vs_neighbors_first():
    state, results = converse([("There is no water in my home", NO_WATER)])
    r = results[-1]
    assert r.action.type == "clarify_outage"
    assert "nearby homes" in r.message or "neighbors" in r.message


def test_neighbors_affected_is_utility_redirect_with_no_invented_numbers():
    state, results = converse([("There is no water in my home", NO_WATER),
                               ("the whole street is out", {"outage_scope": "neighbors_affected"})])
    r = results[-1]
    assert state.outcome == "utility_redirect" and r.provider is None
    assert "water provider" in r.message and not any(ch.isdigit() for ch in r.message)


def test_only_this_home_continues_to_plumbing_funnel():
    state, results = converse([("There is no water in my home", NO_WATER),
                               ("just my house, neighbors are fine", {"outage_scope": "home_only"}),
                               ("95050", {"zip_code": "95050"})])
    assert state.service_category == "plumbing" and state.selected_provider_id
    assert results[-1].action.type == "ask_timing"


def test_neighbors_affected_stated_upfront_redirects_immediately():
    state, results = converse([("Power is out on our whole block", {"utility_signal": "power",
                                                                    "outage_scope": "neighbors_affected"})])
    assert state.outcome == "utility_redirect" and "electric utility" in results[-1].message


def test_unknown_scope_after_asking_continues_and_lead_says_unsure():
    turns = [("no power in the house", {"utility_signal": "power", "issue_summary": "Whole home has no power"}),
             ("no idea", {"outage_scope": "unknown"}),
             ("95054", {"zip_code": "95054"}),
             ("no sparks", {"sparks_present": False}),
             ("today", {"urgency": "same_day"}),
             ("Sam 408-555-0100", {"customer_name": "Sam", "contact_value": "408-555-0100"}),
             ("yes", {"consent_to_share": True})]
    state, results = converse(turns)
    lead = results[-1].lead
    assert state.service_category == "electrical" and lead
    assert lead["service"]["details"]["Nearby homes also affected"] == "Customer unsure"


def test_utility_redirect_reopens_when_user_corrects_scope():
    state, results = converse([("There is no water in my home", NO_WATER),
                               ("neighbors too", {"outage_scope": "neighbors_affected"}),
                               ("actually I checked, only our house", {"outage_scope": "home_only"})])
    assert state.outcome is None and results[-1].action.type == "ask_location"


def test_partial_outage_is_not_a_utility_issue_in_rules_backend():
    state = LeadState(conversation_id="x")
    handle_turn(state, "power went out in half my house, the other half is fine", RulesLLM(), [])
    assert state.utility_signal is None


def test_rules_backend_detects_outage_and_scope():
    state = LeadState(conversation_id="x")
    r = handle_turn(state, "no water in the whole house", RulesLLM(), [])
    assert r.action.type == "clarify_outage"
    r = handle_turn(state, "my neighbors have no water too", RulesLLM(), ["no water in the whole house"])
    assert state.outcome == "utility_redirect"


# Found by manual testing: "there is no electricity in my house. I don't know what is going wrong" was extracted
# with outage_scope="unknown", which skipped the scope question and sent the lead straight to an electrician.

def test_unprompted_unknown_scope_does_not_skip_the_scope_question():
    state, results = converse([("there is no electricity in my house. I don't know what is going wrong",
                                {"utility_signal": "power", "outage_scope": "unknown",
                                 "issue_summary": "No power in the whole house"})])
    assert results[-1].action.type == "clarify_outage" and state.outage_scope is None


def test_unprompted_unknown_scope_for_water_is_ignored_too():
    state, results = converse([("no water at all, no idea why", {**NO_WATER, "outage_scope": "unknown"})])
    assert results[-1].action.type == "clarify_outage"


def test_scope_is_asked_before_any_provider_and_only_once():
    state, results = converse([("no power in the house, not sure what's wrong",
                                {"utility_signal": "power", "outage_scope": "unknown", "city": "Santa Clara"}),
                               ("no sparks or anything", {"sparks_present": False, "burning_smell_present": False, "hot_fixture_present": False})])
    assert results[0].action.type == "clarify_outage" and results[0].provider is None
    # The user didn't answer the scope question; it is asked once, then the electrical funnel continues.
    assert state.asked_fields.count("outage_scope") == 1 and state.service_category == "electrical"


def test_unknown_after_being_asked_is_accepted_and_continues():
    state, results = converse([("no power in the house", {"utility_signal": "power"}),
                               ("I don't know if the neighbors have power", {"outage_scope": "unknown"})])
    assert state.outage_scope == "unknown" and results[-1].action.type != "clarify_outage"


def test_volunteered_unknown_qualification_fact_is_still_accepted():
    # Different from outage scope: "I'm not home, I can't check if water is still coming in" is a real answer
    # even when volunteered, so unknown_facts are accepted without the question being asked first.
    state, _ = converse([("neighbor says water is pooling in my basement, I can't check if it's still coming in",
                          {"service_category": "water_damage_restoration", "issue_summary": "Water pooling in basement",
                           "unknown_facts": ["water_still_active"]})])
    assert "water_still_active" in state.asked_fields
