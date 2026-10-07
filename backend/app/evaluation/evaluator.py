"""Run simulated conversations through the real orchestrator and score them."""

import re
import statistics
from dataclasses import dataclass, field

from app.domain import LeadState, Outcome
from app.services.agent import handle_turn
from app.services.llm import UNVERIFIED_PROVIDER_CLAIMS
from app.services.provider_search import load_providers
from app.services.safety import affirmed

MAX_USER_TURNS = 10  # beyond this the funnel has failed; recorded as abandoned (eval_timeout)
SAFETY_HOTLINES = {"18007435000"}  # PG&E gas emergency line used in safety guidance
PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}|1-800-\d{3}-\d{4}")


@dataclass
class CaseRun:
    case: dict
    state: LeadState
    transcript: list[dict]
    lead: dict | None
    provider_mentions: list[dict] = field(default_factory=list)  # per agent message
    failures: list[str] = field(default_factory=list)


def run_case(case: dict, llm, simulator) -> CaseRun:
    state = LeadState(conversation_id=f"eval-{case['id']}")
    history: list[str] = []
    transcript: list[dict] = []
    lead = None
    message = case["opening"]
    mentions = []
    for _ in range(MAX_USER_TURNS):
        result = handle_turn(state, message, llm, history)
        history.append(message)
        transcript.append({"role": "user", "content": message})
        transcript.append(
            {"role": "assistant", "content": result.message, "action": result.action.type, "events": result.events,
             "wording": result.wording_source}
        )
        mentions.append(_provider_mentions(result.message, state))
        if result.lead:
            lead = result.lead
        if state.outcome is not None:
            break
        message = simulator.reply(result.message, result.action.type, state.last_question_field)
    timed_out = state.outcome is None
    if timed_out:
        state.outcome = Outcome.ABANDONED
    run = CaseRun(case, state, transcript, lead, mentions)
    run.failures = check_expectations(run)
    if timed_out:
        run.failures.insert(0, f"eval_timeout after {MAX_USER_TURNS} user turns")
    return run


def _provider_mentions(text: str, state: LeadState) -> dict:
    providers = load_providers()
    named = [p for p in providers.values() if p.name.lower() in text.lower()]
    allowed = {re.sub(r"\D", "", p.phone) for p in providers.values()} | SAFETY_HOTLINES
    if state.contact_value:
        allowed.add(re.sub(r"\D", "", state.contact_value))
    phones = [re.sub(r"\D", "", m) for m in PHONE_RE.findall(text)]
    ungrounded = [p for p in phones if p not in allowed and p[-10:] not in allowed]
    claims_verified = bool(re.search(r"lists .+ in its service area|serves (your|the) (area|zip|city)", text, re.I))
    invented = bool(affirmed(UNVERIFIED_PROVIDER_CLAIMS, text))
    return {
        "providers": [p.id for p in named],
        "has_provider_fact": bool(named or phones),
        "ungrounded_phones": ungrounded,
        "claims_verified_coverage": claims_verified,
        "invented_provider_claim": invented,
        "coverage": state.selected_provider_coverage,
    }


def check_expectations(run: CaseRun) -> list[str]:
    exp, s, fails = run.case["expected"], run.state, []
    if s.outcome != exp["outcome"]:
        fails.append(f"outcome {s.outcome} != expected {exp['outcome']}")
    if exp.get("service_category") and s.service_category != exp["service_category"]:
        fails.append(f"category {s.service_category} != expected {exp['service_category']}")
    if exp.get("should_clarify") and not any(t.get("action") == "clarify_category" for t in run.transcript):
        fails.append("did not ask a disambiguation question")
    if exp.get("safety_guidance") and not s.safety_flags:
        fails.append("no safety guidance given")
    if exp.get("secondary_issue") and not s.secondary_issues:
        fails.append("secondary issue not captured")
    if exp.get("rejects_first_provider"):
        if not s.excluded_provider_ids:
            fails.append("rejection was not recorded")
        elif s.selected_provider_id in s.excluded_provider_ids:
            fails.append("rejected provider was selected again")
        if not any("provider_feedback:reject" in e for t in run.transcript for e in t.get("events", [])):
            fails.append("no provider-rejection event")
    if exp.get("answers_without_inventing"):
        replies = [t["content"] for t in run.transcript if t["role"] == "assistant"]
        if not any("verified" in r and ("pricing" in r or "review" in r) for r in replies):
            fails.append("provider question was not answered honestly")
    if exp.get("final_zip_code") and s.zip_code != exp["final_zip_code"]:
        fails.append(f"zip {s.zip_code} != expected {exp['final_zip_code']}")
    return fails


def compute_metrics(runs: list[CaseRun]) -> dict:
    providers = load_providers()
    pct = lambda n, d: round(100 * n / d, 1) if d else None  # noqa: E731

    labeled = [r for r in runs if r.case["expected"].get("service_category")]
    cat_ok = sum(r.state.service_category == r.case["expected"]["service_category"] for r in labeled)
    convertible = [r for r in runs if r.case["expected"]["outcome"] == Outcome.READY_TO_DISPATCH]
    converted = [r for r in convertible if r.state.outcome == Outcome.READY_TO_DISPATCH]
    useful_eligible = [r for r in runs if r.case["expected"]["outcome"] in (Outcome.READY_TO_DISPATCH, Outcome.SELF_SERVE)]
    useful = [r for r in useful_eligible if r.state.outcome in (Outcome.READY_TO_DISPATCH, Outcome.SELF_SERVE)]
    success_turns = [r.state.user_turns for r in runs if r.state.outcome == Outcome.READY_TO_DISPATCH]

    fact_msgs = [m for r in runs for m in r.provider_mentions if m["has_provider_fact"]]
    grounded = [m for m in fact_msgs if not m["ungrounded_phones"] and not m["invented_provider_claim"]]
    coverage_msgs = [m for m in fact_msgs if m["providers"]]
    coverage_truthful = [m for m in coverage_msgs if not (m["claims_verified_coverage"] and m["coverage"] != "verified")]

    selected = [r for r in runs if r.state.selected_provider_id]
    eligible = []
    for r in selected:
        p = providers.get(r.state.selected_provider_id)
        if p and r.state.service_category in p.service_categories and p.coverage.get(r.state.pilot_area) in ("verified", "provisional"):
            eligible.append(r)
    dispatched = [r for r in runs if r.state.outcome == Outcome.READY_TO_DISPATCH]
    consent_ok = [r for r in dispatched if r.state.consent_to_share is True]
    scores = [r.lead["quality_score"] for r in runs if r.lead]

    return {
        "cases": len(runs),
        "outcome_accuracy": pct(sum(not any(f.startswith("outcome") for f in r.failures) for r in runs), len(runs)),
        "service_category_accuracy": pct(cat_ok, len(labeled)),
        "dispatchable_lead_rate": pct(len(converted), len(convertible)),
        "useful_resolution_rate": pct(len(useful), len(useful_eligible)),
        "median_user_turns_to_lead": statistics.median(success_turns) if success_turns else None,
        "mean_user_turns_to_lead": round(statistics.mean(success_turns), 2) if success_turns else None,
        "provider_grounding": pct(len(grounded), len(fact_msgs)),
        "coverage_truthfulness": pct(len(coverage_truthful), len(coverage_msgs)),
        "provider_eligibility": pct(len(eligible), len(selected)),
        "consent_correctness": pct(len(consent_ok), len(dispatched)),
        "avg_lead_quality": round(statistics.mean(scores), 1) if scores else None,
        "cases_passed": sum(not r.failures for r in runs),
    }
