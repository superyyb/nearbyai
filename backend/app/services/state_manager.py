"""Merge validated extraction output into LeadState.

Rules:
- Fill unknown fields from the latest message.
- Overwrite a known field only when the extractor marks it as a correction.
- A category change clears category-specific qualification facts and any
  provider match, since both depend on the category.
- A location change clears the provider match.
"""

import re

from app.domain import (
    PILOT_CITIES,
    PILOT_ZIPS,
    QUALIFICATION_FIELDS,
    Category,
    ExtractionResult,
    LeadState,
    ServiceDetails,
)

ZIP_RE = re.compile(r"^\d{5}$")
PHONE_RE = re.compile(r"\D")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SIMPLE_FIELDS = [
    "issue_summary",
    "street_address",
    "city",
    "zip_code",
    "urgency",
    "preferred_time",
    "customer_name",
    "property_relationship",
    "contact_method",
    "contact_value",
    "contact_preferences",
    "insurance_intent",
]
AREA_FIELDS = {"city", "zip_code"}  # fields that decide the pilot area


def normalize_contact(method: str | None, value: str | None) -> tuple[str | None, str | None]:
    """Returns (method, normalized_value) or (None, None) if the value is not a valid contact."""
    if not value:
        return None, None
    value = value.strip()
    if EMAIL_RE.match(value):
        return "email", value.lower()
    digits = PHONE_RE.sub("", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return "phone", f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return None, None


def resolve_pilot_area(zip_code: str | None, city: str | None) -> str | None:
    if zip_code:
        return PILOT_ZIPS.get(zip_code)
    if city:
        return PILOT_CITIES.get(city.strip().lower())
    return None


def _clear_match(state: LeadState) -> None:
    state.candidate_provider_ids = []
    state.selected_provider_id = None
    state.selected_provider_coverage = None
    state.alternative_provider_id = None
    state.match_reason = None
    # Consent was given for a specific provider; it does not carry over.
    state.consent_to_share = None
    # A new category/location needs a fresh search and a fresh consent question.
    state.asked_fields = [f for f in state.asked_fields if f not in ("consent", "provider_search")]


def merge(state: LeadState, result: ExtractionResult) -> list[str]:
    """Mutates state in place. Returns human-readable notes for logging."""
    notes: list[str] = []
    up = result.updates
    corrections = set(result.corrections)
    if corrections:
        state.corrections_seen += 1

    # Contact is normalized before merge so invalid values never enter state.
    if up.contact_value is not None:
        method, value = normalize_contact(up.contact_method, up.contact_value)
        if value is None:
            notes.append(f"rejected invalid contact value {up.contact_value!r}")
        up.contact_method, up.contact_value = method, value

    if up.zip_code is not None and not ZIP_RE.match(up.zip_code.strip()):
        notes.append(f"rejected invalid zip {up.zip_code!r}")
        up.zip_code = None

    # --- category ---
    if up.unsupported_service and up.service_category is None:
        if state.service_category is None or "service_category" in corrections:
            state.unsupported_service = up.unsupported_service or "unspecified service"
            state.service_category = None
    elif up.service_category is not None:
        new_cat = Category(up.service_category)
        if state.service_category is None:
            state.service_category = new_cat
            state.unsupported_service = None
        elif new_cat != state.service_category and (
            "service_category" in corrections or not state.category_confirmed
        ):
            notes.append(f"category changed {state.service_category} -> {new_cat}")
            state.service_category = new_cat
            state.category_changes += 1
            state.service_details = ServiceDetails()
            _clear_match(state)
        if "service_category" in corrections:
            # The user told us the category directly; no need to disambiguate.
            state.category_confirmed = True
    if up.candidate_categories:
        state.candidate_categories = list(dict.fromkeys(up.candidate_categories))

    # --- simple fields ---
    location_inputs_changed = False
    for field in SIMPLE_FIELDS:
        new = getattr(up, field)
        if new is None:
            continue
        old = getattr(state, field)
        if old is None or field in corrections or (field == "issue_summary"):
            if old is not None and old != new and field in AREA_FIELDS:
                location_inputs_changed = True
            setattr(state, field, new)

    # Utility outage: the signal sticks once seen; the scope is latest-wins ("actually it's only my house").
    if up.utility_signal and state.utility_signal is None:
        state.utility_signal = up.utility_signal
    # "unknown" only counts as an answer when we just asked about the outage scope. Unprompted, it usually means
    # "I don't know what's wrong" (found by manual testing), and accepting it skipped the scope question.
    if up.outage_scope is not None and (up.outage_scope != "unknown" or state.last_question_field == "outage_scope"):
        state.outage_scope = up.outage_scope

    # Consent is always latest-wins: a revocation must apply even after a lead is prepared,
    # and a user who changes their mind can grant it later.
    if up.consent_to_share is not None:
        state.consent_to_share = up.consent_to_share

    for impact in up.observed_impacts:
        if impact not in state.observed_impacts:
            state.observed_impacts.append(impact)

    if up.secondary_issues:
        for issue in up.secondary_issues:
            if issue not in state.secondary_issues:
                state.secondary_issues.append(issue)

    # --- category-specific details ---
    for field in QUALIFICATION_FIELDS:
        new = getattr(up, field)
        if new is None:
            continue
        if getattr(state.service_details, field) is None or field in corrections:
            setattr(state.service_details, field, new)

    # "I can't tell" overrides an earlier inference and counts as asked, so it is not re-asked
    # and the lead says "unknown" instead of a guessed yes/no.
    for field in up.unknown_facts:
        if field in QUALIFICATION_FIELDS:
            setattr(state.service_details, field, None)
            if field not in state.asked_fields:
                state.asked_fields.append(field)

    for field in up.declined_fields:
        if field not in state.declined_fields:
            state.declined_fields.append(field)
        if field == "street_address" and state.street_address:
            # The user withheld an address they gave earlier: it must not go into the lead.
            # (ZIP/area are unchanged, so the provider match stays valid.)
            state.street_address = None

    # --- derived location ---
    # Provider eligibility depends on the pilot area, so only an area change invalidates the match. A new street
    # address, or a ZIP in the same area, keeps the provider and the consent given for it.
    area_changed = False
    if up.zip_code or up.city or location_inputs_changed:
        new_area = resolve_pilot_area(state.zip_code, state.city)
        area_changed = new_area != state.pilot_area
        state.pilot_area = new_area
    if area_changed and state.selected_provider_id:
        notes.append("service area changed; provider match cleared")
        _clear_match(state)

    return notes
