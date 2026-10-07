"""Flag real conversations worth reviewing for the eval set.

Flagged conversations become *candidates*; a human promotes useful ones into
data/evaluation/core_cases.json. The core set is never modified automatically.
"""

from app.domain import LeadState, Outcome

TOO_MANY_TURNS = 8


def candidate_reasons(state: LeadState, writer_rejections: int = 0) -> list[str]:
    reasons = []
    if state.category_changes:
        reasons.append("category_changed")
    if state.corrections_seen:
        reasons.append("user_corrected_agent")
    if state.extraction_failures:
        reasons.append("extraction_failed")
    if state.outcome == Outcome.NO_MATCH:
        reasons.append("provider_not_found")
    if state.outcome == Outcome.UNSUPPORTED_CATEGORY:
        reasons.append("unsupported_category")
    if state.user_turns > TOO_MANY_TURNS:
        reasons.append("too_many_turns")
    if writer_rejections:
        reasons.append("writer_guardrail_rejected")
    if state.outcome is None and state.user_turns >= 3:
        reasons.append("no_outcome_yet")
    return reasons
