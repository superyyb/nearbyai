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
from app.services import ambiguity, answers, next_action, provider_intents, safety, templates
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
    "ask_location": "zip_code",
    "ask_timing": "timing",
    "ask_address": "street_address",
    "ask_contact": "contact",
    "ask_consent": "consent",
}
OUTCOME_FOR_ACTION = {
    "safety_redirect": Outcome.SAFETY_REDIRECT,
    "unsupported_category": Outcome.UNSUPPORTED_CATEGORY,
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
    "preferred_time", "customer_name", "contact_value", "consent_to_share", "selected_provider_id",
    "excluded_provider_ids", "service_details",
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

    # 1. safety
    screen = safety.screen(message)
    if screen.redirect_flags or screen.urgent_flags:
        new_flags = [f for f in screen.redirect_flags + screen.urgent_flags if f not in state.safety_flags]
        state.safety_flags.extend(new_flags)
        if screen.is_redirect:
            safety_text = screen.guidance()
        elif new_flags and not state.safety_guidance_given:
            safety_text = screen.guidance()
            state.safety_guidance_given = True
            if state.urgency is None:
                state.urgency = "emergency"
            events.append(f"safety_urgent:{','.join(new_flags)}")

    # 2-3. extraction + merge
    llm_needs_clarification = False
    prior_category = state.service_category
    prior_secondary = list(state.secondary_issues)
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

    if prior_category and state.service_category != prior_category:
        events.append("category_changed")
    new_secondary = [s for s in state.secondary_issues if s not in prior_secondary]
    if new_secondary and state.service_category:
        other = new_secondary[0].rstrip(".")
        prefixes.append(
            f"I've noted the other issue ({other}) so it isn't lost, but let's get the "
            f"{CATEGORY_LABELS_SHORT[state.service_category]} problem handled first."
        )

    # Explicit intent about providers outranks the next funnel question.
    intent_turn = False  # user spent this turn on something other than our last question
    up = extraction.updates if extraction else None
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
    if up and (up.question_topics or up.requested_action) and not screen.is_redirect:
        intent_turn = True
        current = get_provider(state.selected_provider_id) if state.selected_provider_id else None
        # Answer every question in the message (a user asking "are they good? how much?" expects both).
        for topic in list(dict.fromkeys(up.question_topics))[:MAX_ANSWERS_PER_TURN]:
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
            message_out = " ".join(prefixes + [templates.render(action, state, provider)])
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
    if intent and intent.action:
        action = intent.action  # e.g. list options or a provisional offer; the funnel resumes next turn
    else:
        action = next_action.decide(
            state, redirect=screen.is_redirect, ambiguity=rule, llm_needs_clarification=llm_needs_clarification
        )
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
            lead = build_packet(state, provider, result.quality_score)
        else:
            # Should not happen if the funnel is correct; never dispatch an invalid lead.
            events.append(f"validation_failed:{result.missing_fields + result.errors}")
            action = NextAction(type="ask_contact", field="customer_name,contact_value")

    if lead_withdrawn:
        prefixes.insert(0, "I've updated your request." if lead else "I've withdrawn the request I prepared earlier.")

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

    # 7. wording
    reference = " ".join(prefixes + [templates.render(action, state, provider)])
    body, source = reference, "template"
    if hasattr(llm, "write") and action.type != "safety_redirect":
        shown = [p for p in (provider, alternative) if p]
        allowed_phones = {p.phone for p in shown} | ({state.contact_value} if state.contact_value else set())
        allowed_urls = {p.website for p in shown} | {p.source_url for p in shown}
        context = {
            "next_step": action.type,
            "category": CATEGORY_LABELS.get(state.service_category) if state.service_category else None,
            "provider_facts": provider.model_dump(include={"name", "phone", "website"}) if provider else None,
            "provider_coverage": state.selected_provider_coverage,
            "safety_guidance_already_shown": bool(safety_text),
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
            if violations:
                TELEMETRY.fallback("writer_guardrail_rejected")
                events.append(f"writer_rejected:{violations}")
            else:
                body, source = candidate, "llm"
    message_out = f"{safety_text} {body}".strip()
    state.last_agent_message = message_out

    return TurnResult(message_out, action, state, lead, provider, alternative, events, source, lead_withdrawn)
