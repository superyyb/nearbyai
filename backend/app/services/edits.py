"""Field edits announced before the new value arrives.

"Can I change my address?" and "I gave you the wrong phone number" carry an intent but no value. Value-bearing
corrections ("it's actually 95134") were already handled by state_manager.merge; this module adds the pending
state in between:

  wants_change         -> keep the old value, hold the request, ask for the new value
  current_value_wrong  -> clear the old value now (the lead can't be dispatched with it), ask for the new value

On the next turn the pending field is treated as a correction, so the new value overrides the old one and the
existing invalidation runs (a new ZIP re-matches the provider, a new category clears category facts). If no value
comes, the edit is dropped: a kept old value stands, a cleared one is asked for by the normal funnel.

Consent is not reset for contact edits: it covers sharing the customer's details with the same provider for the
same request, and a user-corrected number doesn't change either.
"""

from app.domain import LeadState
from app.services.state_manager import _clear_match

# Editable field -> the extraction fields that carry its new value (treated as corrections while pending).
VALUE_FIELDS = {
    "street_address": {"street_address", "city", "zip_code"},
    "zip_code": {"zip_code", "city", "street_address"},
    "phone": {"contact_value", "contact_method"},
    "name": {"customer_name"},
    "timing": {"urgency", "preferred_time", "preferred_day", "preferred_window"},
    "issue": {"service_category", "issue_summary"},
}
# Funnel ask-counters to reset when a field is invalidated, so asking again doesn't count against ask limits.
ASK_KEYS = {
    "street_address": {"street_address"},
    "zip_code": {"zip_code", "provider_search"},
    "phone": {"contact"},
    "name": {"contact"},
    "timing": {"timing"},
    "issue": set(),
}

QUESTIONS = {
    ("street_address", "wants_change"): "Sure — what's the new address where you need service?",
    ("street_address", "current_value_wrong"): "No problem — what's the correct address where you need service?",
    ("zip_code", "wants_change"): "Sure — what's the ZIP code or address where you need service?",
    ("zip_code", "current_value_wrong"): "No problem — what's the correct ZIP code or address where you need service?",
    ("phone", "wants_change"): "Sure — what's the best phone number to use?",
    ("phone", "current_value_wrong"): "No problem — what's the correct phone number?",
    ("name", "wants_change"): "Sure — what name should the provider ask for?",
    ("name", "current_value_wrong"): "Sorry about that — what's the correct name?",
    ("timing", "wants_change"): "Sure — when would you like help?",
    ("timing", "current_value_wrong"): "No problem — when would you like help?",
    ("issue", "wants_change"): "Sure — what's going on?",
    ("issue", "current_value_wrong"): "Got it — what's the problem you're seeing?",
}


def value_provided(field: str, up) -> bool:
    return any(getattr(up, f, None) for f in VALUE_FIELDS[field] if f != "contact_method")


def invalidate(state: LeadState, field: str) -> None:
    """Clear a value the user said is wrong, plus what was derived from it."""
    if field == "street_address":
        state.street_address = None
    elif field == "zip_code":
        state.zip_code = state.city = state.street_address = state.pilot_area = None
        _clear_match(state)  # coverage and provider depend on location
    elif field == "phone":
        state.contact_value = state.contact_method = None
    elif field == "name":
        state.customer_name = None
    elif field == "timing":
        from app.services import timing

        timing.clear(state)
    state.asked_fields = [f for f in state.asked_fields if f not in ASK_KEYS[field]]
    state.declined_fields = [f for f in state.declined_fields if f != field]
