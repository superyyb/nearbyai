"""Deterministic answers to user questions and to requests the system can't fulfil.

The LLM only classifies *which* questions were asked (question_topics). The answer
content comes from here, built from the provider record and fixed product
facts, so price, ratings, licensing, or availability can never be invented.
Anything not in the record is answered with "I don't have verified ...".
"""

from app.domain import CATEGORY_LABELS, PILOT_AREAS, LeadState, Outcome, Provider

WHY_NEED = {
    "zip_or_address": (
        "The ZIP code lets me find providers that actually serve your area. The street address is optional; "
        "it just helps the provider plan the visit."
    ),
    "phone": (
        "Your name and number go into the service request so the provider can reach you — only if you say yes, "
        "and only to the one provider you choose. You can also skip that and contact them yourself."
    ),
    "name": "The provider uses your name when they call about the request. You can also contact them yourself instead.",
    "timing": "Your timing preference tells the provider how urgent the job is; it isn't a booked appointment.",
    "water_still_active": "Whether water is still coming in changes how quickly a provider needs to respond.",
    "active_leak": "Whether it's actively leaking changes how quickly a provider needs to respond.",
    "hazard_present": "Sparks, a burning smell, or hot fixtures can be a fire risk, so I check for safety first.",
    "consent": "I only share your details with a provider if you explicitly say yes.",
}


def _coverage_phrase(state: LeadState) -> str:
    area = PILOT_AREAS.get(state.pilot_area or "", "your area")
    if state.selected_provider_coverage == "verified":
        return f"its official site lists {area} in its service area"
    return f"it's located near {area}, though its exact coverage there is unconfirmed"


def answer_question(topic: str, info_field: str | None, state: LeadState, provider: Provider | None) -> str:
    provider_topics = {"why_this_provider", "price", "reviews", "availability", "hours_or_24_7", "distance",
                       "license_or_insurance"}
    if topic in provider_topics and provider is None:
        return "I haven't matched a provider yet — once I do, I can tell you what I know about them."
    name = provider.name if provider else ""

    if topic == "why_this_provider":
        label = CATEGORY_LABELS[state.service_category].lower()
        extra = " Its site also mentions 24/7 service." if provider.emergency_service else ""
        return (
            f"I suggested {name} because it handles {label} and {_coverage_phrase(state)}.{extra} "
            "Recommendations come from a verified local dataset, not paid placement."
        )
    if topic == "price":
        return (f"I don't have verified pricing for {name}, so I don't want to guess. "
                f"They can quote you when they get in touch, or you can check {provider.website}.")
    if topic == "reviews":
        return (f"I don't have verified review or rating data for {name}, so I can't vouch for quality beyond "
                "the official-site information I used. If you'd prefer, I can suggest another verified provider.")
    if topic == "availability":
        extra = " Their site does mention 24/7 service." if provider.emergency_service else ""
        return (f"I can't confirm when {name} is available. I'll include your timing preference in the request, "
                f"and they'll confirm when they contact you.{extra}")
    if topic == "hours_or_24_7":
        if provider.emergency_service:
            return (f"{name}'s official site mentions 24/7 service, but I can't confirm they'll be available "
                    "for your request specifically.")
        return f"I don't have verified hours for {name}."
    if topic == "distance":
        where = f"{name} is based in {provider.city}" if provider.city else f"I don't have {name}'s exact location"
        return f"{where}; I haven't calculated travel distance to your address."
    if topic == "license_or_insurance":
        return (f"I don't have verified license or insurance details for {name}. You can ask them directly, "
                "or look them up with California's CSLB contractor license lookup.")
    if topic == "why_need_info":
        return WHY_NEED.get(info_field or "", "I only ask for what a provider needs to understand and act on the request.")
    if topic == "data_privacy":
        return ("In this demo your messages are stored so the service can be evaluated and improved. Your contact "
                "details are only included in a request to the single provider you approve, and nothing is sent "
                "automatically.")
    if topic == "is_this_a_person":
        return "I'm an automated assistant, not a person."
    if topic == "sponsorship":
        return ("No — I'm not paid by providers. Recommendations come from a verified local dataset, chosen by "
                "service type, coverage, and fit for your issue.")
    if topic == "request_status":
        if state.outcome == Outcome.READY_TO_DISPATCH and provider:
            return (f"Your request is prepared but hasn't been sent — this demo doesn't contact providers "
                    f"automatically. You can reach {name} directly at {provider.phone}.")
        return "Nothing has been sent to any provider."
    return "I don't have verified information on that."


def answer_request(action: str, provider: Provider | None) -> str:
    """Requests outside the system's capabilities: be explicit about what it can and cannot do."""
    reach = f" You can reach {provider.name} directly at {provider.phone}." if provider else ""
    if action in ("call_provider", "send_now"):
        return f"I can't call or message providers myself — this demo prepares the request for you.{reach}"
    if action == "book_appointment":
        return ("I can't book appointments or confirm a time. I'll note your preferred timing, and the provider "
                f"confirms the schedule with you.{reach}")
    if action == "guarantee":
        return "I can't guarantee timing or availability; the provider confirms that directly."
    # "unclear" means the request didn't fit a known kind - not that it's impossible.
    return ("I'm not sure I understood. Do you want to change something in the request, ask about the provider, "
            "or something else?")
