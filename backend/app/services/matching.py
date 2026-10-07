"""Provider selection: hard search, then rerank only when there is a real choice.

  0 candidates  -> no match
  1 candidate   -> select it, skip the LLM
  2+ candidates -> LLM rerank among the supplied IDs; deterministic fallback
The LLM can only return an ID from the candidate list; anything else is ignored.
"""

import re

from app.domain import LeadState, Provider
from app.services.provider_search import search

URGENT = {"emergency", "same_day"}


def deterministic_rank(state: LeadState, candidates: list[Provider]) -> tuple[Provider, str]:
    """Keyword overlap between the job and the provider evidence, plus 24/7 when urgent."""
    job_words = set(re.findall(r"[a-z]+", (state.issue_summary or "").lower())) - {"the", "a", "my", "and", "in", "is", "it", "of"}
    urgent = state.urgency in URGENT or state.service_details.water_still_active or state.service_details.active_leak

    def score(p: Provider) -> tuple[float, str]:
        evidence_words = set(re.findall(r"[a-z]+", p.coverage_evidence.lower()))
        s = len(job_words & evidence_words)
        if urgent and p.emergency_service:
            s += 3
        return s, p.id

    best = max(candidates, key=lambda p: (score(p)[0], [-ord(c) for c in p.id]))
    reason = "24/7 service noted on its official site" if urgent and best.emergency_service else "best keyword match to the job description"
    return best, reason


def select_provider(state: LeadState, llm=None) -> bool:
    """Mutates state with the match. Returns True if a provider was selected."""
    state.asked_fields.append("provider_search")
    result = search(state.service_category, state.pilot_area)
    state.candidate_provider_ids = [p.id for p in result.candidates]
    if not result.candidates:
        return False

    chosen, reason = None, None
    if len(result.candidates) == 1:
        chosen, reason = result.candidates[0], "only eligible provider"
    elif llm is not None and hasattr(llm, "rerank"):
        job = {
            "category": state.service_category.value,
            "issue_summary": state.issue_summary,
            "urgency": state.urgency,
            "details": state.service_details.model_dump(exclude_none=True),
        }
        choice = llm.rerank(job, result.candidates)
        by_id = {p.id: p for p in result.candidates}
        if choice and choice.selected_provider_id in by_id:
            chosen, reason = by_id[choice.selected_provider_id], choice.reason
    if chosen is None:
        chosen, reason = deterministic_rank(state, result.candidates)

    state.selected_provider_id = chosen.id
    state.selected_provider_coverage = result.tier
    state.match_reason = reason
    alternatives = [p for p in result.candidates if p.id != chosen.id]
    state.alternative_provider_id = alternatives[0].id if alternatives else None
    return True
