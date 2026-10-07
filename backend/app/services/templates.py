"""Deterministic reference wording for every NextAction.

These templates are the safe fallback: the Claude writer may rephrase them,
but if its output fails a guardrail check the template is sent instead.
"""

from app.domain import CATEGORY_LABELS, PILOT_AREAS, LeadState, NextAction, Provider

QUALIFICATION_QUESTIONS = {
    "water_still_active": "Is water still actively coming in right now?",
    "active_leak": "Is it actively leaking right now?",
    "hazard_present": "Are you seeing any sparks, a burning smell, or outlets or switches that feel hot?",
}
SUPPORTED_SCOPE = "plumbing, water damage, roofing, heating/cooling, and electrical"
PILOT_SCOPE = "Santa Clara, Sunnyvale, and North San Jose (95131, 95134)"
def get_provider_name(provider_id: str) -> str:
    from app.services.provider_search import get_provider

    provider = get_provider(provider_id)
    return provider.name if provider else "that provider"


DEMO_DISCLAIMER = "This demo prepares the lead but does not contact the provider automatically."


def provider_intro(state: LeadState, provider: Provider) -> str:
    area = PILOT_AREAS.get(state.pilot_area or "", "your area")
    label = CATEGORY_LABELS[state.service_category].lower()
    if state.selected_provider_coverage == "verified":
        return f"I found {provider.name}, which handles {label} and lists {area} in its service area."
    return (
        f"I found {provider.name}, which handles {label} and is located near you. "
        f"Their exact service coverage for {area} still needs to be confirmed."
    )


def render(action: NextAction, state: LeadState, provider: Provider | None) -> str:
    t = action.type
    if t == "ask_category" and action.note:
        return action.note
    if t == "ask_category":
        return (
            "I can help with that. Can you tell me a bit about what's going on — for example a leak, "
            "a heating or cooling problem, an electrical issue, or something with the roof?"
        )
    if t == "clarify_category":
        if action.note:
            return action.note
        return (
            "To get you the right kind of pro, can you tell me a bit more — is it a leak, a heating or cooling "
            "problem, an electrical issue, or something with the roof?"
        )
    if t == "unsupported_category":
        return (
            f"Sorry — this assistant currently covers {SUPPORTED_SCOPE} only, so I can't match a provider "
            f"for {action.note or 'that'}. If you also have one of those issues, I'm happy to help with it."
        )
    if t == "ask_location":
        if action.note == "san_jose_needs_zip":
            return "What's the ZIP code of the property in San Jose?"
        return "What's the property address? Just the ZIP code is fine if that's easier."
    if t == "out_of_area":
        return (
            f"Thanks. Right now I only have verified providers in {PILOT_SCOPE}, so I can't confidently match "
            f"a provider for {action.note}. If the property is in one of those areas, send me the ZIP and I'll keep going."
        )
    if t == "ask_qualification":
        return QUALIFICATION_QUESTIONS[action.field]
    if t == "no_match" and action.note == "all_rejected":
        rejected = get_provider_name(state.excluded_provider_ids[-1]) if state.excluded_provider_ids else "that provider"
        return (
            f"Understood — I won't use {rejected}. I don't have another verified "
            f"{CATEGORY_LABELS[state.service_category].lower()} provider for your area right now, "
            "so I can't make a match this time."
        )
    if t == "no_match":
        return (
            f"I couldn't find a provider in my verified list for {CATEGORY_LABELS[state.service_category].lower()} "
            "in that area, so I don't want to guess. I'm sorry I can't match you this time."
        )
    if t == "ask_timing":
        return "Would you prefer help today if someone is available, or is later this week okay?"
    if t == "ask_address":
        return (
            "To prepare the request, what's the street address? If you'd rather give it to the provider "
            "directly, that's fine too."
        )
    if t == "ask_contact":
        missing = (action.field or "").split(",")
        if missing == ["customer_name"]:
            return "And what name should the provider ask for?"
        if missing == ["contact_value"]:
            return "What's the best phone number for the provider to reach you?"
        if action.note == "include_address":
            return (
                "What's your name and the best phone number to reach you? If you'd like, include the street "
                "address too so they can plan the visit."
            )
        return "What's your name and the best phone number to reach you?"
    if t == "ask_consent":
        name = provider.name if provider else "the provider"
        if state.contact_method == "email":
            return f"Is it okay to share your name and email with {name} so they can email you about this service request?"
        return (
            f"Is it okay to share your name and phone number with {name} so they can call or text you "
            "about this service request?"
        )
    if t == "lead_ready":
        return (
            f"Thanks, {state.customer_name}. Your service request is ready to send to {provider.name}. "
            f"{DEMO_DISCLAIMER} If you want to reach them sooner, their number is {provider.phone}."
        )
    if t == "self_serve":
        return (
            f"No problem — I won't share your details. You can contact {provider.name} directly at "
            f"{provider.phone} ({provider.website})."
        )
    if t == "safety_redirect":
        return "Once everyone is safe and the emergency is handled, come back and I can help you find a pro for repairs."
    if t == "empty_input":
        return "I didn't catch that — could you tell me again?"
    if t in ("present_options", "offer_provisional"):
        return action.note
    if t == "already_closed":
        if state.outcome == "ready_to_dispatch" and provider:
            return f"Your request for {provider.name} is ready. If anything changes, tell me and I'll update it."
        if state.outcome == "self_serve" and provider:
            return (f"You can contact {provider.name} directly at {provider.phone}. If you change your mind about "
                    "sharing your details, just tell me.")
        return "If anything changes — a different ZIP code or another issue — just tell me and I'll pick it back up."
    raise ValueError(f"no template for {t}")
