"""Deterministic lead validation. Only this module can make a lead dispatchable.

Validator = pass/fail on business invariants.
Completeness score = interpretable 0-100 measure of how many of the fields a provider needs are present. It is not
a judgment of lead quality; whether a provider would act on the lead is measured by the provider-perspective judge.
"""

from app.domain import BLOCKING_QUALIFICATION, LeadState, Provider, ValidationResult
from app.services import timing
from app.services.state_manager import normalize_contact

ELIGIBLE_COVERAGE = {"verified", "provisional"}


def validate_lead(state: LeadState, provider: Provider | None) -> ValidationResult:
    missing: list[str] = []
    errors: list[str] = []

    # Customer need
    if state.service_category is None:
        missing.append("service_category")
    if not state.issue_summary or len(state.issue_summary.split()) < 3:
        missing.append("issue_summary")
    if state.service_category is not None:
        for field in BLOCKING_QUALIFICATION[state.service_category]:
            # Asked-but-unknown is acceptable: the provider can confirm on the call.
            if getattr(state.service_details, field) is None and field not in state.asked_fields:
                missing.append(field)

    # Location
    if state.pilot_area is None:
        missing.append("zip_code")

    # Timing
    if not timing.has_timing(state):
        missing.append("urgency")

    # Contact
    if not state.customer_name:
        missing.append("customer_name")
    method, value = normalize_contact(state.contact_method, state.contact_value)
    if value is None:
        missing.append("contact_value")
    if state.consent_to_share is not True:
        missing.append("consent_to_share")

    # Provider
    if provider is None:
        missing.append("provider")
    else:
        if not provider.phone.strip():
            errors.append(f"provider {provider.id} has no phone number")
        if state.service_category not in provider.service_categories:
            errors.append(f"provider {provider.id} does not offer {state.service_category}")
        coverage = provider.coverage.get(state.pilot_area or "", "unknown")
        if coverage not in ELIGIBLE_COVERAGE:
            errors.append(f"provider {provider.id} coverage for {state.pilot_area} is {coverage}")
        if state.selected_provider_coverage and coverage != state.selected_provider_coverage:
            errors.append("selected coverage label does not match provider record")

    score, breakdown = completeness_score(state, provider)
    return ValidationResult(
        valid=not missing and not errors,
        missing_fields=missing,
        errors=errors,
        completeness_score=score,
        completeness_breakdown=breakdown,
    )


def completeness_score(state: LeadState, provider: Provider | None) -> tuple[float, dict[str, float]]:
    b: dict[str, float] = {}

    # 25 — issue completeness
    issue = 0.0
    if state.issue_summary and len(state.issue_summary.split()) >= 3:
        issue += 15
    qual_fields = BLOCKING_QUALIFICATION.get(state.service_category, []) if state.service_category else []
    if qual_fields:
        known = sum(getattr(state.service_details, f) is not None for f in qual_fields)
        issue += 10 * known / len(qual_fields)
    elif state.service_category:
        issue += 10
    b["issue"] = issue

    # 25 — provider / category / coverage compatibility
    compat = 0.0
    if provider and state.service_category in provider.service_categories:
        coverage = provider.coverage.get(state.pilot_area or "", "unknown")
        compat = {"verified": 25.0, "provisional": 15.0}.get(coverage, 0.0)
    b["provider_fit"] = compat

    # 20 — location completeness
    b["location"] = 20.0 if state.street_address and state.pilot_area else (12.0 if state.pilot_area else 0.0)

    # 15 — timing
    b["timing"] = 15.0 if timing.has_timing(state) else 0.0

    # 15 — contact readiness
    contact = 0.0
    if state.customer_name:
        contact += 5
    if normalize_contact(state.contact_method, state.contact_value)[1]:
        contact += 5
    if state.consent_to_share is True:
        contact += 5
    b["contact"] = contact

    return round(sum(b.values()), 1), b
