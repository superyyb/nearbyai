"""Provider-facing lead packet: what a real business would receive."""

from app.domain import (
    BLOCKING_QUALIFICATION,
    CATEGORY_LABELS,
    ELECTRICAL_FACTS,
    PILOT_AREAS,
    Category,
    LeadState,
    Provider,
    question_answered,
)
from app.services import safety, timing

URGENCY_LABELS = {
    "emergency": "As soon as possible — customer requested urgent service",
    "same_day": "Same-day service preferred",
    "within_week": "Within the next few days",
    "flexible": "Flexible timing",
}
YES_NO = {True: "Yes", False: "No"}
DETAIL_LABELS = {
    "water_still_active": ("Water still entering", YES_NO),
    "active_leak": ("Actively leaking", YES_NO),
    "sparks_present": ("Sparks observed", YES_NO),
    "burning_smell_present": ("Burning smell", YES_NO),
    "hot_fixture_present": ("Hot outlet, switch, or fixture", YES_NO),
    # The source is inferred from the user's words ("after the storm"), not diagnosed, so the lead says so.
    "likely_source": ("Suspected source", {"storm_exterior": "Storm-related water intrusion (exact source not confirmed)",
                                           "plumbing": "Plumbing (not confirmed)", "unknown": "Unknown"}),
}


# Only the facts that matter to the matched trade, plus electrical observations for any trade (a safety fact).
TRADE_DETAILS = {
    Category.WATER_DAMAGE: ["water_still_active", "likely_source"],
    Category.PLUMBING: ["active_leak", "water_still_active"],
    Category.ROOFING: ["active_leak", "likely_source"],
    Category.HVAC: [],
    Category.ELECTRICAL: [],
}
UNKNOWN_LABELS = {"electrical_symptoms": "Sparks, burning smell, or heat"}


def _details(state: LeadState) -> dict:
    details = {}
    for field in TRADE_DETAILS[state.service_category] + ELECTRICAL_FACTS:
        value = getattr(state.service_details, field)
        if value is not None:
            label, values = DETAIL_LABELS[field]
            details[label] = values.get(value, str(value))
    # A blocking question that was asked but couldn't be answered: say so instead of leaving it out.
    for question in BLOCKING_QUALIFICATION[state.service_category]:
        if question in state.asked_fields and not question_answered(state.service_details, question):
            label = UNKNOWN_LABELS.get(question) or DETAIL_LABELS[question][0]
            details[label] = "Unknown — customer could not confirm"
    return details


def build_packet(state: LeadState, provider: Provider, completeness_score: float) -> dict:
    area = PILOT_AREAS.get(state.pilot_area or "", "")
    if state.street_address:
        address = f"{state.street_address}, {state.city or area}, CA {state.zip_code or ''}".strip()
    else:
        location = f"ZIP {state.zip_code}" if state.zip_code else area
        withheld = "street_address" in state.declined_fields
        address = (f"Pending — customer provided {location}; "
                   + ("prefers to share the street address directly." if withheld
                      else "exact address to be confirmed by provider."))
    details = _details(state)
    if state.utility_signal:
        details["Nearby homes also affected"] = {"home_only": "No — only this home", "unknown": "Customer unsure"}.get(
            state.outage_scope, "Not asked")
    coverage = (
        f"Verified — {area} listed on provider's official site"
        if state.selected_provider_coverage == "verified"
        else "Provisional — provider located nearby; service area unconfirmed"
    )
    return {
        "customer": {
            "name": state.customer_name,
            "contact_method": state.contact_method,
            "contact": state.contact_value,
            "contact_permission": "Yes — explicit consent to share with this provider" if state.consent_to_share else "No",
            "contact_preferences": state.contact_preferences,
            "relationship_to_property": state.property_relationship or "Not stated",
        },
        "property": {"address": address, "address_status": state.address_status, "area": area},
        "service": {
            "category": CATEGORY_LABELS[state.service_category],
            "problem": state.issue_summary,
            "details": details,
            "observed_impacts": state.observed_impacts,
            "secondary_issues": state.secondary_issues,
            "safety_priority": safety.priority_text(state),
        },
        "timing": {
            "preference": timing.provider_label(state),
            "preferred_date": state.preferred_date,
            "customer_words": state.preferred_time,
            "availability": "Not confirmed",
        },
        "matched_provider": {
            "id": provider.id,
            "name": provider.name,
            "phone": provider.phone,
            "website": provider.website,
            "address": provider.address,
            "coverage": coverage,
            "match_reason": state.match_reason,
            "source_url": provider.source_url,
            "verified_at": provider.verified_at,
        },
        "prototype_status": "Lead prepared for dispatch. No provider has been contacted automatically.",
        "completeness_score": completeness_score,
    }


def render_text(packet: dict) -> str:
    c, p, s, t, m = (packet[k] for k in ("customer", "property", "service", "timing", "matched_provider"))
    lines = [
        "NEW SERVICE LEAD",
        "",
        f"Customer: {c['name']}",
        f"Contact: {c['contact']} ({c['contact_method']})",
        f"Contact permission: {c['contact_permission']}",
        *([f"Contact preferences: {c['contact_preferences']}"] if c.get("contact_preferences") else []),
        f"Relationship: {c['relationship_to_property']}",
        "",
        f"Property: {p['address']}",
        "",
        f"Service: {s['category']}",
        f"Problem: {s['problem']}",
    ]
    lines += [f"  {k}: {v}" for k, v in s["details"].items()]
    if s.get("observed_impacts"):
        lines.append(f"Observed impact: {'; '.join(s['observed_impacts'])}")
    if s["secondary_issues"]:
        lines.append(f"Also mentioned (not part of this lead): {'; '.join(s['secondary_issues'])}")
    if s.get("safety_priority"):
        lines.append(f"Safety priority: {s['safety_priority']}")
    lines += [
        "",
        f"Timing: {t['preference']} (availability {t['availability'].lower()})",
        "",
        f"Matched provider: {m['name']}",
        f"  {m['phone']} · {m['website']}",
        f"  Coverage: {m['coverage']}",
        f"  Source: {m['source_url']} (verified {m['verified_at']})",
        "",
        packet["prototype_status"],
    ]
    return "\n".join(lines)
