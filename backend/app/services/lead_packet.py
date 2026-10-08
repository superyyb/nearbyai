"""Provider-facing lead packet: what a real business would receive."""

from app.domain import CATEGORY_LABELS, PILOT_AREAS, LeadState, Provider

URGENCY_LABELS = {
    "emergency": "As soon as possible (customer reports urgent need)",
    "same_day": "Same-day service preferred",
    "within_week": "Within the next few days",
    "flexible": "Flexible timing",
}
DETAIL_LABELS = {
    "water_still_active": ("Water still entering", {True: "Yes", False: "No"}),
    "active_leak": ("Actively leaking", {True: "Yes", False: "No"}),
    "hazard_present": ("Sparks / burning smell / hot fixtures", {True: "Yes — safety guidance given", False: "No"}),
    "likely_source": ("Likely source", {"storm_exterior": "Exterior / storm water", "plumbing": "Plumbing", "unknown": "Unknown"}),
}


def build_packet(state: LeadState, provider: Provider, quality_score: float) -> dict:
    area = PILOT_AREAS.get(state.pilot_area or "", "")
    if state.street_address:
        address = f"{state.street_address}, {state.city or area}, CA {state.zip_code or ''}".strip()
    else:
        location = f"ZIP {state.zip_code}" if state.zip_code else area
        withheld = "street_address" in state.declined_fields
        address = (f"Pending — customer provided {location}; "
                   + ("prefers to share the street address directly." if withheld
                      else "exact address to be confirmed by provider."))
    details = {}
    for field, (label, values) in DETAIL_LABELS.items():
        value = getattr(state.service_details, field)
        if value is not None:
            details[label] = values.get(value, str(value))
        elif field in state.asked_fields:
            details[label] = "Unknown — customer could not confirm"
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
            "safety_flags": state.safety_flags,
        },
        "timing": {
            "preference": URGENCY_LABELS.get(state.urgency, state.preferred_time or "Not stated"),
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
        "quality_score": quality_score,
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
    if s["safety_flags"]:
        lines.append(f"Safety flags: {', '.join(s['safety_flags'])}")
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
