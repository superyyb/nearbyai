"""Deterministic funnel: given LeadState, decide the single next step.

Priority (see SPEC.md):
  terminal -> safety redirect -> unsupported -> category -> disambiguation
  -> location -> category qualification -> provider match -> timing
  -> name + contact (+ optional street address, asked once) -> consent -> ready

The function is pure: it reads state and returns a NextAction. Side effects
(provider search, outcome changes) happen in the orchestrator.
"""

from app.domain import (
    BLOCKING_QUALIFICATION,
    Category,
    TERMINAL_OUTCOMES,
    LeadState,
    NextAction,
    question_answered,
)
from app.services import timing
from app.services.ambiguity import AmbiguityRule

MAX_CATEGORY_ASKS = 3
MAX_CONTACT_ASKS = 2
MAX_CONSENT_ASKS = 2
MAX_TIMING_ASKS = 2


def asked(state: LeadState, field: str) -> int:
    return state.asked_fields.count(field)


def decide(
    state: LeadState,
    *,
    redirect: bool = False,
    ambiguity: AmbiguityRule | None = None,
    llm_needs_clarification: bool = False,
) -> NextAction:
    if state.outcome in TERMINAL_OUTCOMES:
        return NextAction(type="already_closed")

    if redirect:
        return NextAction(type="safety_redirect")

    # --- possible utility outage: a contractor can't fix an area-wide outage, so check scope first ---
    if state.utility_signal:
        if state.outage_scope == "neighbors_affected":
            return NextAction(type="utility_redirect", note=state.utility_signal)
        if state.outage_scope is None and asked(state, "outage_scope") == 0:
            return NextAction(type="clarify_outage", field="outage_scope")
        if state.service_category is None:
            # Only this home (or unknown after asking): it's a job for the matching trade.
            state.service_category = Category.PLUMBING if state.utility_signal == "water" else Category.ELECTRICAL
            state.category_confirmed = True

    # --- what is the job? ---
    if state.service_category is None:
        if state.unsupported_service:
            return NextAction(type="unsupported_category", note=state.unsupported_service)
        if state.candidate_categories and asked(state, "category_clarification") == 0:
            return NextAction(type="clarify_category", field="service_category")
        if asked(state, "service_category") >= MAX_CATEGORY_ASKS:
            # Don't loop forever: after repeated vague answers, close honestly as out of scope.
            return NextAction(type="unsupported_category", note="this request")
        return NextAction(type="ask_category", field="service_category")

    if not state.category_confirmed:
        if (ambiguity or llm_needs_clarification) and asked(state, "category_clarification") == 0:
            return NextAction(
                type="clarify_category",
                field="service_category",
                note=ambiguity.question if ambiguity else None,
            )
        # Either unambiguous, or we already asked once: accept the best category.
        state.category_confirmed = True

    # --- where? ---
    if state.pilot_area is None:
        if state.zip_code or (state.city and state.city.strip().lower() not in {"san jose"}):
            return NextAction(type="out_of_area", note=state.zip_code or state.city)
        return NextAction(type="ask_location", field="zip_code", note="san_jose_needs_zip" if state.city else None)

    # --- category-specific qualification (each asked at most once) ---
    for field in BLOCKING_QUALIFICATION[state.service_category]:
        if not question_answered(state.service_details, field) and asked(state, field) == 0:
            return NextAction(type="ask_qualification", field=field)

    # --- provider ---
    if state.selected_provider_id is None:
        searched = "provider_search" in state.asked_fields
        return NextAction(type="no_match" if searched else "match_provider")

    # --- timing ---
    if not timing.has_timing(state):
        if asked(state, "timing") < MAX_TIMING_ASKS:
            return NextAction(type="ask_timing", field="urgency")

    # --- contact ---
    if "contact" in state.declined_fields or "customer_name" in state.declined_fields:
        return NextAction(type="self_serve", note="declined_contact")
    missing_contact = [f for f in ("customer_name", "contact_value") if getattr(state, f) is None]
    if missing_contact:
        if asked(state, "contact") >= MAX_CONTACT_ASKS:
            return NextAction(type="self_serve", note="contact_not_provided")
        # The street address rides along with the contact question (optional, never blocking),
        # so asking for it costs no extra turn.
        want_address = (
            state.street_address is None
            and asked(state, "street_address") == 0
            and "street_address" not in state.declined_fields
        )
        return NextAction(
            type="ask_contact", field=",".join(missing_contact), note="include_address" if want_address else None
        )

    # --- consent ---
    if state.consent_to_share is False or "consent" in state.declined_fields:
        return NextAction(type="self_serve", note="declined_consent")
    if state.consent_to_share is None:
        if asked(state, "consent") >= MAX_CONSENT_ASKS:
            return NextAction(type="self_serve", note="consent_not_given")
        return NextAction(type="ask_consent", field="consent_to_share")

    return NextAction(type="lead_ready")
