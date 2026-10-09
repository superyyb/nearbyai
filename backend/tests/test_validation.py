"""Per-field validation of typed values (found by manual testing: a 9-digit number was silently dropped twice and
the user was sent to self-serve with "I won't share your details", although they never declined)."""

import pytest

from app.domain import LeadState
from app.services.agent import handle_turn
from app.services.rules_llm import RulesLLM
from app.services.validation import correction_message, normalize_zip
from tests.helpers import AC_ISSUE, SANTA_CLARA, converse

MATCHED_TO_CONTACT = [("My AC blows warm air", AC_ISSUE), ("Santa Clara", SANTA_CLARA), ("today", {"urgency": "same_day"})]


def contact(raw, **extra):
    return {"contact_value": raw, "contact_method": "phone", **extra}


# ---------- A: valid values are saved, even several in one message ----------

def test_multi_field_message_with_a_valid_bare_number_saves_everything_and_asks_consent():
    state, results = converse(MATCHED_TO_CONTACT + [("yy, 4085550187, 1450 Lafayette St",
                                                     contact("4085550187", customer_name="yy",
                                                             street_address="1450 Lafayette St"))])
    assert (state.customer_name, state.contact_value, state.street_address) == ("yy", "(408) 555-0187", "1450 Lafayette St")
    assert state.consent_to_share is None and results[-1].action.type == "ask_consent"


@pytest.mark.parametrize("raw", ["4085550187", "(408) 555-0187", "408-555-0187", "+1 408 555 0187", "1-408-555-0187"])
def test_phone_formats_normalize(raw):
    state, _ = converse(MATCHED_TO_CONTACT + [("sam " + raw, contact(raw, customer_name="Sam"))])
    assert state.contact_value == "(408) 555-0187"


@pytest.mark.parametrize("raw,expected", [("95050", "95050"), ("95050-1234", "95050"), (" 95134 ", "95134"),
                                          ("9505", None), ("950501", None)])
def test_zip_normalization(raw, expected):
    assert normalize_zip(raw) == expected


def test_zip_plus4_is_accepted_for_matching():
    state, results = converse([("My AC blows warm air", AC_ISSUE), ("95050-1234", {"zip_code": "95050-1234"})])
    assert state.zip_code == "95050" and state.pilot_area == "santa_clara" and state.selected_provider_id


# ---------- B: an invalid value is asked for again, specifically, without losing the rest ----------

def test_nine_digit_number_keeps_name_and_address_and_asks_only_for_the_phone():
    state, results = converse(MATCHED_TO_CONTACT + [("yy, 669222192, 1450 Lafayette St",
                                                     contact("669222192", customer_name="yy",
                                                             street_address="1450 Lafayette St"))])
    r = results[-1]
    assert state.customer_name == "yy" and state.street_address == "1450 Lafayette St" and state.contact_value is None
    assert r.action.type == "ask_correction"
    assert "669-222-192" in r.message and "9 digits" in r.message and "US numbers have 10" in r.message
    assert state.consent_to_share is None and state.outcome is None


def test_correct_number_after_an_invalid_one_continues_to_consent():
    state, results = converse(MATCHED_TO_CONTACT + [
        ("yy, 669222192", contact("669222192", customer_name="yy")),
        ("4085550187", contact("4085550187"))])
    assert state.contact_value == "(408) 555-0187" and state.invalid_field is None
    assert results[-1].action.type == "ask_consent"


def test_repeated_invalid_numbers_escalate_and_never_become_a_refusal():
    turns = MATCHED_TO_CONTACT + [("yy, 669222192", contact("669222192", customer_name="yy"))]
    turns += [("669222192", contact("669222192"))] * 3
    state, results = converse(turns)
    tail = [r.message for r in results[-4:]]
    assert "Could you double-check it?" in tail[0]
    assert "for example 408-555-0142" in tail[1]
    assert "an email address works too" in tail[2] and "contact DG Heating & Air Conditioning directly" in tail[2]
    assert state.outcome is None and all("won't share" not in m for m in tail)
    assert all(r.action.type == "ask_correction" for r in results[-4:])


def test_invalid_attempts_do_not_count_toward_the_contact_ask_limit():
    turns = MATCHED_TO_CONTACT + [("yy, 669222192", contact("669222192", customer_name="yy")),
                                  ("669222192", contact("669222192")),
                                  ("4085550187", contact("4085550187"))]
    state, results = converse(turns)
    assert state.asked_fields.count("contact") == 1 and results[-1].action.type == "ask_consent"


def test_four_digit_zip_is_asked_for_again():
    state, results = converse([("My AC blows warm air", AC_ISSUE), ("9505", {"zip_code": "9505"})])
    assert results[-1].action.type == "ask_correction" and "5-digit ZIP" in results[-1].message
    assert state.pilot_area is None and state.selected_provider_id is None


def test_malformed_email_is_asked_for_again():
    state, results = converse(MATCHED_TO_CONTACT + [("sam, sam@example", {"contact_value": "sam@example",
                                                                          "contact_method": "email",
                                                                          "customer_name": "Sam"})])
    assert results[-1].action.type == "ask_correction" and "doesn't look complete" in results[-1].message
    assert state.customer_name == "Sam"


def test_invalid_number_during_a_phone_edit_keeps_the_edit_pending():
    lead = MATCHED_TO_CONTACT + [("Sam, 408-555-0100", contact("408-555-0100", customer_name="Sam")),
                                 ("yes", {"consent_to_share": True})]
    state, results = converse(lead + [("can I change my phone number?", {"edit_field": "phone", "edit_kind": "wants_change"}),
                                      ("323459110", contact("323459110"))])
    r = results[-1]
    assert r.action.type == "ask_correction" and r.lead is None and "is ready" not in r.message
    assert state.pending_edit == "phone" and state.outcome is None
    state, results = converse([("4085550199", contact("4085550199"))], state)
    assert results[-1].lead and results[-1].lead["customer"]["contact"] == "(408) 555-0199"


# ---------- consent stays unknown until asked; only an explicit no is a refusal ----------

def test_explicit_refusal_is_the_only_path_to_declined_wording():
    state, results = converse(MATCHED_TO_CONTACT + [("Sam, 408-555-0100", contact("408-555-0100", customer_name="Sam")),
                                                    ("no, don't share my number", {"consent_to_share": False})])
    assert state.outcome == "self_serve" and "won't share your details" in results[-1].message


def test_giving_up_without_a_refusal_does_not_claim_one():
    state, results = converse(MATCHED_TO_CONTACT + [("hmm", {}), ("not now", {})])
    r = results[-1]
    assert state.outcome == "self_serve" and r.action.note == "contact_not_provided"
    assert "won't share" not in r.message and "send me your name and phone number" in r.message


def test_rules_backend_captures_a_short_number_for_validation():
    state = LeadState(conversation_id="x")
    history = []
    for m in ["My AC blows warm air", "Santa Clara", "today", "yy, 669222192"]:
        r = handle_turn(state, m, RulesLLM(), history)
        history.append(m)
    assert r.action.type == "ask_correction" and state.invalid_field == "phone"


def test_correction_wording_tiers():
    assert "Could you double-check it?" in correction_message("phone", "669222192", 1)
    assert "for example" in correction_message("phone", "669222192", 2)
    assert "the city name works too" in correction_message("zip_code", "9505", 3)
