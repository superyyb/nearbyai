"""Provider selection: hard search, then rerank only when there is a real choice.

  0 candidates  -> no match
  1 candidate   -> select it, skip the LLM
  2+ candidates -> LLM rerank among the supplied IDs; deterministic fallback
The LLM can only return an ID from the candidate list; anything else is ignored.
"""

import re

from app.domain import LeadState, Provider
from app.services import safety
from app.services.provider_search import search
from app.services.telemetry import TELEMETRY

URGENT = {"emergency", "same_day"}


def deterministic_rank(state: LeadState, candidates: list[Provider]) -> tuple[list[Provider], str]:
    """Keyword overlap between the job and the provider evidence, plus 24/7 when urgent."""
    job_words = set(re.findall(r"[a-z]+", (state.issue_summary or "").lower())) - {"the", "a", "my", "and", "in", "is", "it", "of"}
    # 24/7 matters when the customer asked for urgent help or the system sees a safety risk; the two stay separate.
    urgent = (state.urgency in URGENT or state.service_details.water_still_active or state.service_details.active_leak
              or bool(safety.urgent_risks(state)))

    def score(p: Provider) -> int:
        s = len(job_words & set(re.findall(r"[a-z]+", p.coverage_evidence.lower())))
        return s + (3 if urgent and p.emergency_service else 0)

    ranked = sorted(candidates, key=lambda p: (-score(p), p.id))
    if not ranked:
        return [], ""
    reason = "24/7 service noted on its official site" if urgent and ranked[0].emergency_service else "best keyword match to the job description"
    return ranked, reason


def _rank(state: LeadState, candidates: list[Provider], llm) -> tuple[list[Provider], str]:
    if len(candidates) == 1:
        TELEMETRY.fallback("rerank_skipped_single_candidate")
        return candidates, "only eligible provider"
    if llm is not None and hasattr(llm, "rerank"):
        job = {
            "category": state.service_category.value,
            "issue_summary": state.issue_summary,
            "urgency": state.urgency,
            "safety_risk": [safety.SAFETY_DISPLAY[f] for f in safety.urgent_risks(state)],
            "details": state.service_details.model_dump(exclude_none=True),
        }
        result = llm.rerank(job, candidates)
        by_id = {p.id: p for p in candidates}
        ranked_ids = [i for i in dict.fromkeys(result.ranked_provider_ids) if i in by_id] if result else []
        if ranked_ids:
            # Any candidate the model left out keeps its deterministic position after the ranked ones.
            rest, _ = deterministic_rank(state, [p for p in candidates if p.id not in ranked_ids])
            return [by_id[i] for i in ranked_ids] + rest, result.reason
        TELEMETRY.fallback("rerank_invalid_or_failed")
    return deterministic_rank(state, candidates)


def _select(state: LeadState, provider_id: str | None) -> None:
    state.selected_provider_id = provider_id
    remaining = [i for i in state.candidate_provider_ids if i not in state.excluded_provider_ids
                 and i not in state.shown_provider_ids and i != provider_id]
    state.alternative_provider_id = remaining[0] if remaining else None


def select_provider(state: LeadState, llm=None) -> bool:
    """Search, rank, and select. Mutates state; returns True if a provider was selected.
    Providers the user rejected are never candidates again in this conversation."""
    state.asked_fields.append("provider_search")
    result = search(state.service_category, state.pilot_area)
    candidates = [p for p in result.candidates if p.id not in state.excluded_provider_ids]
    state.candidate_provider_ids = []
    if not candidates:
        state.selected_provider_id = None
        return False
    ranked, reason = _rank(state, candidates, llm)
    state.candidate_provider_ids = [p.id for p in ranked]
    state.selected_provider_coverage = result.tier
    state.match_reason = reason
    _select(state, ranked[0].id)
    return True


def switch_provider(state: LeadState, feedback: str, reason: str | None) -> str | None:
    """Handle "not this one" / "any other options?" without a new search or LLM call:
    move to the next provider in the existing ranked list.

    Returns the previous provider id. Consent is reset because it was given for that provider.
    If nothing is left, a rejected provider is dropped (selected becomes None -> no_match);
    a plain request for alternatives keeps the current provider.
    """
    current = state.selected_provider_id
    if current is None:
        return None
    if feedback == "reject":
        if current not in state.excluded_provider_ids:
            state.excluded_provider_ids.append(current)
        state.provider_feedback[current] = reason or "rejected by user"
    elif current not in state.shown_provider_ids:
        state.shown_provider_ids.append(current)

    remaining = [i for i in state.candidate_provider_ids
                 if i != current and i not in state.excluded_provider_ids and i not in state.shown_provider_ids]
    if not remaining and feedback == "want_alternative":
        # Nothing new to show; keep the current match.
        state.shown_provider_ids.remove(current)
        return current
    _select(state, remaining[0] if remaining else None)
    state.match_reason = "next-ranked eligible provider after user feedback" if remaining else None
    state.consent_to_share = None
    state.asked_fields = [f for f in state.asked_fields if f != "consent"]
    return current
