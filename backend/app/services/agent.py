"""Per-turn orchestration. Deterministic control flow; LLM only at the edges.

  1. safety screen (deterministic)
  2. LLM extraction -> validated ExtractionResult (retry inside the LLM layer)
  3. merge into LeadState (corrections, invalidation)
  4. explicit user intent first (provider feedback, questions, impossible requests),
     then ambiguity rules + funnel decision — the funnel is the default path, not a script
  5. provider match when prerequisites are met (rerank only if 2+)
  6. lead validation when the funnel reaches the end
  7. wording: deterministic template, optionally rephrased by the LLM and
     rejected if it breaks a guardrail
"""

import logging
from dataclasses import dataclass, field

from app.domain import CATEGORY_LABELS, TERMINAL_OUTCOMES, LeadState, NextAction, Outcome, Provider
from app.services import (
    ambiguity,
    answers,
    clarification,
    edits,
    mitigation,
    validation,
    next_action,
    provider_intents,
    safety,
    templates,
    timing,
)
from app.services.lead_packet import build_packet
from app.services.lead_validator import validate_lead
from app.services.llm import ExtractionFailed, guardrail_violations
from app.services.matching import select_provider
from app.services.provider_search import get_provider
from app.services.rules_llm import CATEGORY_LABELS_SHORT
from app.services.state_manager import merge
from app.services.telemetry import TELEMETRY

log = logging.getLogger(__name__)

# Fields the funnel records as "asked" when it asks them.
ASKED_KEY = {
    "ask_category": "service_category",
    "clarify_category": "category_clarification",
    "clarify_outage": "outage_scope",
    "ask_location": "zip_code",
    "ask_timing": "timing",
    "ask_address": "street_address",
    "ask_contact": "contact",
    "ask_consent": "consent",
}
OUTCOME_FOR_ACTION = {
    "safety_redirect": Outcome.SAFETY_REDIRECT,
    "unsupported_category": Outcome.UNSUPPORTED_CATEGORY,
    "utility_redirect": Outcome.UTILITY_REDIRECT,
    "out_of_area": Outcome.NO_MATCH,
    "no_match": Outcome.NO_MATCH,
    "self_serve": Outcome.SELF_SERVE,
    "lead_ready": Outcome.READY_TO_DISPATCH,
}


@dataclass
class TurnResult:
    message: str
    action: NextAction
    state: LeadState
    lead: dict | None = None
    provider: Provider | None = None
    alternative: Provider | None = None
    events: list[str] = field(default_factory=list)
    wording_source: str = "template"
    lead_withdrawn: bool = False


MAX_MESSAGE_CHARS = 2000
MAX_ANSWERS_PER_TURN = 3


def _trim(message: str) -> str:
    """Keep the start and end of very long messages; facts tend to be at either end of a long story."""
    message = message.strip()
    if len(message) <= MAX_MESSAGE_CHARS:
        return message
    return message[:1500] + " … " + message[-500:]


# Fields whose change makes a finished conversation worth reopening.
MATERIAL_FIELDS = {
    "service_category", "unsupported_service", "zip_code", "city", "street_address", "pilot_area", "urgency",
    "preferred_time", "preferred_day", "preferred_window", "customer_name", "contact_value", "consent_to_share", "selected_provider_id",
    "excluded_provider_ids", "service_details", "utility_signal", "outage_scope", "pending_edit",
    "invalid_field",
}


def _fingerprint(state: LeadState) -> dict:
    return state.model_dump(include=MATERIAL_FIELDS, mode="json")


def handle_turn(state: LeadState, message: str, llm, user_history: list[str]) -> TurnResult:
    message = _trim(message)
    if not message:
        # Not a turn: nothing to extract, nothing changes.
        action = NextAction(type="empty_input")
        return TurnResult(templates.render(action, state, None), action, state)
    events: list[str] = []
    safety_text = ""  # deterministic; never rewritten by the LLM
    prefixes: list[str] = []

    # Outcomes are not dead ends: a later message can change the request (new ZIP, another issue,
    # withdrawn consent, a different provider). Reopen only when something material changed.
    prior_outcome = state.outcome if state.outcome in TERMINAL_OUTCOMES else None
    before = _fingerprint(state)
    lead_withdrawn = False

    state.user_turns += 1
    conversation_text = " ".join(user_history + [message])

    # 1. safety, part one: the regex screen works even if extraction fails
    screen = safety.screen(message)

    # 2-3. extraction + merge
    llm_needs_clarification = False
    prior_category = state.service_category
    prior_secondary = list(state.secondary_issues)
    prior_impacts = list(state.observed_impacts)
    prior_details = state.service_details.model_dump()
    prior_when = timing.user_when(state)
    extraction = None
    try:
        extraction = llm.extract(state, message, state.last_question_field)
        llm_needs_clarification = extraction.updates.needs_clarification
        events += merge(state, extraction)
    except ExtractionFailed as e:
        state.extraction_failures += 1
        TELEMETRY.fallback("extraction_failed")
        events.append(f"extraction_failed:{e}")
        log.warning("extraction failed; keeping prior state: %s", e)

    # 1. safety, part two: union with the extractor's hazard families, then apply fixed guidance
    if extraction and extraction.updates.hazard_categories:
        screen, llm_added = safety.with_llm_hazards(screen, extraction.updates.hazard_categories)
        if llm_added:
            events.append(f"safety_llm:{','.join(llm_added)}:{extraction.updates.hazard_evidence or ''}")
    if screen.redirect_flags or screen.urgent_flags:
        new_flags = [f for f in screen.redirect_flags + screen.urgent_flags if f not in state.safety_flags]
        state.safety_flags.extend(new_flags)
        if screen.is_redirect:
            safety_text = screen.guidance()
        elif new_flags and not state.safety_guidance_given:
            safety_text = screen.guidance()
            state.safety_guidance_given = True
            # The risk is recorded in safety_flags; it is never written into the customer's timing preference.
            events.append(f"safety_urgent:{','.join(new_flags)}")

    if prior_category and state.service_category != prior_category:
        events.append("category_changed")
    new_secondary = [s for s in state.secondary_issues if s not in prior_secondary]
    if new_secondary and state.service_category:
        other = new_secondary[0].rstrip(".")
        prefixes.append(
            f"I've noted the other issue ({other}) so it isn't lost, but let's get the "
            f"{CATEGORY_LABELS_SHORT[state.service_category]} problem handled first."
        )

    up = extraction.updates if extraction else None

    # A field edit announced without the new value: hold the request and ask for the value.
    edit_action = None
    edit_completed = False  # a pending edit got its new value this turn
    if up and up.edit_field and up.edit_kind and not screen.is_redirect:
        if edits.value_provided(up.edit_field, up):
            events.append(f"edit_applied:{up.edit_field}")  # the value came in the same message
        else:
            if up.edit_kind == "current_value_wrong":
                edits.invalidate(state, up.edit_field)
            state.pending_edit, state.pending_edit_turn = up.edit_field, state.user_turns
            edit_action = NextAction(type="ask_edit", field=f"edit:{up.edit_field}",
                                     note=edits.QUESTIONS[(up.edit_field, up.edit_kind)])
            events.append(f"edit_requested:{up.edit_field}:{up.edit_kind}")
    invalid_now = bool(state.invalid_field and state.invalid_turn == state.user_turns)
    if invalid_now and state.pending_edit:
        pass  # the user tried to give the new value but it's invalid: the edit stays pending
    elif state.pending_edit and state.user_turns > state.pending_edit_turn:
        # The turn after the edit request: either the new value arrived (merged as a correction above), or the
        # user moved on - a kept old value stands, a cleared one is asked for by the normal funnel.
        edit_completed = bool(up and edits.value_provided(state.pending_edit, up))
        events.append(f"edit_resolved:{state.pending_edit}:{'value' if edit_completed else 'none'}")
        state.pending_edit = None

    # Explicit intent about providers outranks the next funnel question.
    intent_turn = False  # user spent this turn on something other than our last question
    intent = provider_intents.handle(state, up) if up and not screen.is_redirect else None
    if intent is None and state.offered_provider_id and not screen.is_redirect:
        intent = provider_intents.reoffer(state)  # the offer wasn't answered; ask once more
    all_rejected = bool(intent and intent.all_rejected)
    if intent:
        intent_turn = True
        events += intent.events
        if intent.prefix:
            prefixes.append(intent.prefix)

    # Questions and requests the system can't fulfil: answer first, then resume the funnel.
    if up and (up.question_topics or up.requested_action) and not screen.is_redirect and not edit_action:
        intent_turn = True
        current = get_provider(state.selected_provider_id) if state.selected_provider_id else None
        # Answer every question in the message (a user asking "are they good? how much?" expects both).
        topics = [t for t in dict.fromkeys(up.question_topics) if not (t == "other" and up.requested_action == "unclear")]
        for topic in topics[:MAX_ANSWERS_PER_TURN]:
            prefixes.append(answers.answer_question(topic, up.question_info_field, state, current))
            events.append(f"user_question:{topic}")
        if up.requested_action:
            prefixes.append(answers.answer_request(up.requested_action, current))
            events.append(f"requested_action:{up.requested_action}")

    if prior_outcome is not None:
        changed = _fingerprint(state) != before
        if not changed and not screen.is_redirect:
            action = NextAction(type="already_closed")
            provider = get_provider(state.selected_provider_id) if state.selected_provider_id else None
            # An unclear request gets the clarifying question alone, not "your request is ready" tacked on.
            closing = [] if (up and up.requested_action == "unclear") else [templates.render(action, state, provider)]
            message_out = " ".join(prefixes + closing)
            state.last_agent_message = message_out
            return TurnResult(message_out, action, state, None, provider, None, events)
        state.outcome = None
        events.append(f"reopened_from:{prior_outcome}")
        if prior_outcome == Outcome.READY_TO_DISPATCH:
            lead_withdrawn = True  # superseded; the wording depends on whether a new lead is prepared below

    # 4-5. funnel
    rule = ambiguity.detect(conversation_text) if not state.category_confirmed else None
    if rule and state.service_category is None and not state.unsupported_service:
        # Known ambiguous pattern the extractor could not classify: seed candidates so we disambiguate
        # instead of asking an open-ended category question.
        state.candidate_categories = list(rule.candidates)
        state.service_category = rule.candidates[0]
        if state.issue_summary is None:
            state.issue_summary = message[:240]
    if invalid_now and not screen.is_redirect:
        # Only the invalid field is asked for again; this isn't an unanswered ask and never a refusal.
        current = get_provider(state.selected_provider_id) if state.selected_provider_id else None
        attempt = state.invalid_attempts.get(state.invalid_field, 1)
        action = NextAction(type="ask_correction", field=f"correct:{state.invalid_field}",
                            note=validation.correction_message(state.invalid_field, state.invalid_raw, attempt, current))
        events.append(f"invalid_value:{state.invalid_field}:attempt{attempt}")
        intent_turn = True
    elif edit_action:
        action = edit_action  # ask for the new value; the funnel resumes next turn
        intent_turn = True
    elif intent and intent.action:
        action = intent.action  # e.g. list options or a provisional offer; the funnel resumes next turn
    else:
        action = next_action.decide(
            state, redirect=screen.is_redirect, ambiguity=rule, llm_needs_clarification=llm_needs_clarification
        )
    # Clarifying question: the LLM proposes one in the user's terms; code validates it, then falls back to a
    # curated rule question, and only then to the generic category template.
    if action.type in ("ask_category", "clarify_category", "clarify_outage"):
        rule_question = None if action.type == "clarify_outage" else (action.note or (rule.question if rule else None))
        question, source, rejected = clarification.choose_question(
            state, up.suggested_question if up else None, rule_question
        )
        action.note = question
        events.append(f"clarification_source:{source}")
        if rejected:
            TELEMETRY.fallback("clarification_question_rejected")
            events.append(f"clarification_rejected:{rejected}")

    if all_rejected and action.type == "no_match":
        action.note = "all_rejected"
    newly_matched = False
    if action.type == "match_provider":
        newly_matched = select_provider(state, llm)
        events.append(f"provider_search:{len(state.candidate_provider_ids)} candidates")
        action = next_action.decide(state)
    provider = get_provider(state.selected_provider_id) if state.selected_provider_id else None
    alternative = get_provider(state.alternative_provider_id) if state.alternative_provider_id else None
    if newly_matched and provider:
        prefixes.append(templates.provider_intro(state, provider))

    # 6. validation gate
    lead = None
    if action.type == "lead_ready":
        result = validate_lead(state, provider)
        state.missing_blocking_fields = result.missing_fields
        if result.valid:
            lead = build_packet(state, provider, result.completeness_score)
        else:
            # Should not happen if the funnel is correct; never dispatch an invalid lead.
            events.append(f"validation_failed:{result.missing_fields + result.errors}")
            action = NextAction(type="ask_contact", field="customer_name,contact_value")

    if edit_completed and lead and not lead_withdrawn:
        prefixes.insert(0, "I've updated your request.")
    if lead_withdrawn:
        if lead:
            prefixes.insert(0, "I've updated your request.")
        elif action.type == "ask_edit":
            prefixes.insert(0, "I'll hold your request until it's updated.")
        else:
            prefixes.insert(0, "I've withdrawn the request I prepared earlier.")

    if action.type in OUTCOME_FOR_ACTION:
        state.outcome = OUTCOME_FOR_ACTION[action.type]
    # Re-asking after an intent turn is not a second unanswered ask, so it doesn't count toward ask limits.
    if action.type in ASKED_KEY and not intent_turn:
        state.asked_fields.append(ASKED_KEY[action.type])
    if action.note == "include_address":
        state.asked_fields.append("street_address")
    elif action.type == "ask_qualification":
        state.asked_fields.append(action.field)
    state.last_question_field = action.field
    if action.type == "ask_timing":
        state.last_question_field = "urgency"

    # A specific visit time is confirmed back once, when it's given, without implying it's booked.
    timing_note = ""
    if (timing.is_specific(state) and timing.user_when(state) != prior_when
            and action.type not in ("safety_redirect", "utility_redirect", "unsupported_category")):
        timing_note = timing.confirmation(state)
        prefixes.append(timing_note)
        events.append("timing_confirmed")

    # A fixed damage-limiting tip (at most once), kept verbatim like safety copy.
    mitigation_text = ""
    if action.type not in ("safety_redirect", "utility_redirect", "unsupported_category", "already_closed"):
        tip = mitigation.tip_for(state, conversation_text)
        if tip:
            state.mitigation_given.append(tip[0])
            mitigation_text = tip[1]
            events.append(f"mitigation:{tip[0]}")

    new_context = (
        state.user_turns == 1
        or state.service_category != prior_category
        or state.observed_impacts != prior_impacts
        or state.service_details.model_dump() != prior_details
        or state.secondary_issues != prior_secondary
    )

    # 7. wording (order: acknowledgement -> fixed tip -> next question; the tip must survive verbatim)
    reference = " ".join(prefixes + ([mitigation_text] if mitigation_text else []) + [templates.render(action, state, provider)])
    body, source = reference, "template"
    if hasattr(llm, "write") and action.type != "safety_redirect":
        shown = [p for p in (provider, alternative) if p]
        allowed_phones = {p.phone for p in shown} | ({state.contact_value} if state.contact_value else set())
        if action.type == "ask_correction":
            allowed_phones.add(validation.EXAMPLES["phone"])
        allowed_urls = {p.website for p in shown} | {p.source_url for p in shown}
        context = {
            "next_step": action.type,
            "category": CATEGORY_LABELS.get(state.service_category) if state.service_category else None,
            "provider_facts": provider.model_dump(include={"name", "phone", "website"}) if provider else None,
            "provider_coverage": state.selected_provider_coverage,
            "safety_guidance_already_shown": bool(safety_text),
            "damage_tip_verbatim": mitigation_text or None,
            # Acknowledge the situation only when it's new: the first reply, or a structured new fact this turn.
            # (Comparing summary text would fire every turn, since the extractor rewrites the summary each time.)
            "user_situation": state.issue_summary if new_context else None,
            "observed_impacts": state.observed_impacts if new_context else [],
            "is_first_reply": state.user_turns == 1,
            "previous_assistant_message": state.last_agent_message,
        }
        candidate = llm.write(reference, context)
        if not candidate:
            TELEMETRY.fallback("writer_unavailable")
        else:
            violations = guardrail_violations(
                candidate, allowed_phones, allowed_urls, state.selected_provider_coverage == "provisional"
            )
            if mitigation_text and mitigation_text not in candidate:
                violations.append("damage tip dropped or altered")
            if timing_note and not timing.confirmation_kept(candidate, state):
                violations.append("preferred time dropped or not marked as unconfirmed")
            if clarification.is_category_menu(candidate) and not clarification.is_category_menu(reference):
                violations.append("rewrote a targeted question into a category menu")
            if violations:
                TELEMETRY.fallback("writer_guardrail_rejected")
                events.append(f"writer_rejected:{violations}")
            else:
                body, source = candidate, "llm"
    message_out = f"{safety_text} {body}".strip()
    state.last_agent_message = message_out

    return TurnResult(message_out, action, state, lead, provider, alternative, events, source, lead_withdrawn)
