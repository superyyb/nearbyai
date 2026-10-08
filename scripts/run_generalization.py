"""First-turn generalization eval over a frozen set of 112 openings the agent's author didn't write.

Measures whether the first reply engages with what the user actually said, instead of falling back to a
generic category menu. Hard checks are code; the optional judge (a different model from the agent) only
scores soft quality.

    cd backend && uv run python ../scripts/run_generalization.py [--backend rules|anthropic] [--judge] [--label NAME]
"""

import argparse
import json
import os
import re
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from pydantic import BaseModel, Field  # noqa: E402

from app.config import settings  # noqa: E402,F401  (loads .env)
from app.domain import LeadState  # noqa: E402
from app.services.agent import handle_turn  # noqa: E402
from app.services.llm import guardrail_violations  # noqa: E402
from app.services.provider_search import load_providers  # noqa: E402
from app.services.rules_llm import RulesLLM  # noqa: E402
from app.services.telemetry import TELEMETRY  # noqa: E402

JUDGE_MODEL = "claude-opus-5-5"
SAFETY_HOTLINES = {"(800) 743-5000", "1-800-743-5000"}
CATEGORY_FAMILIES = [
    re.compile(r"\b(leak\w*|plumb\w*|pipes?)\b", re.I),
    re.compile(r"\b(heat\w*|cool\w*|hvac|a/?c|air condition\w*)\b", re.I),
    re.compile(r"\belectric\w*\b", re.I),
    re.compile(r"\broof\w*\b", re.I),
]
CLARIFY_ACTIONS = {"ask_category", "clarify_category", "clarify_outage"}
NEIGHBOR_RE = re.compile(r"\b(neighbou?rs?|nearby (homes|houses)|other homes|your (street|block|area)|whole (street|block|neighborhood)|just your (home|house))\b", re.I)


def is_generic_menu(text: str) -> bool:
    return sum(bool(rx.search(text)) for rx in CATEGORY_FAMILIES) >= 3


class FirstTurnVerdict(BaseModel):
    score: int = Field(description="1-5")
    issue: str = Field(description="Main problem with the reply, or '' if none.")


JUDGE_SYSTEM = """You review the first reply of a home-services intake assistant. The assistant can match the user
with a verified local plumber, roofer, HVAC company, electrician, or water-damage restoration company in Santa
Clara, Sunnyvale, or North San Jose; it cannot do other services and never books or dispatches anyone itself.
Score the reply 1-5:
5 = uses what the user said and takes the most useful next step (a targeted question that resolves the key
    unknown, safety guidance first when warranted, or an honest out-of-scope answer)
3 = acceptable but generic, or asks something less useful than it could
1 = ignores what the user said, asks for information already given, or gives wrong/unsafe guidance
Judge only the reply's handling of the conversation, not its wording style."""


def run_one(item: dict, llm) -> dict:
    state = LeadState(conversation_id=item["id"])
    result = handle_turn(state, item["text"], llm, [])
    provider = result.provider
    allowed_phones = SAFETY_HOTLINES | ({provider.phone} if provider else set())
    allowed_urls = {provider.website, provider.source_url} if provider else set()
    violations = guardrail_violations(result.message, allowed_phones, allowed_urls,
                                      state.selected_provider_coverage == "provisional")
    # "one question" is a writer-style rule; safety text plus a question is fine on a first turn.
    violations = [v for v in violations if v not in ("more than one question", "too long")]
    return {
        "id": item["id"], "text": item["text"], "tags": item["tags"], "expect": item.get("expect"),
        "reply": result.message, "action": result.action.type, "outcome": state.outcome,
        "category": state.service_category, "provider": provider.id if provider else None,
        "pilot_area": state.pilot_area, "safety_flags": state.safety_flags, "events": result.events,
        # Only a clarifying question can be a "menu"; an out-of-scope reply legitimately lists what is supported.
        "generic_menu": result.action.type in CLARIFY_ACTIONS and is_generic_menu(result.message),
        "violations": violations,
    }


def check_label(r: dict) -> bool | None:
    exp = r["expect"]
    if exp is None:
        return None
    reply, outcome = r["reply"], r["outcome"]
    if exp == "safety_redirect":
        return outcome == "safety_redirect"
    if exp == "safety_guidance":
        return outcome == "safety_redirect" or reply.startswith("For safety") or bool(r["safety_flags"])
    if exp == "utility_redirect":
        return outcome == "utility_redirect"
    if exp == "utility_check":
        return r["action"] == "clarify_outage" or bool(NEIGHBOR_RE.search(reply)) or outcome == "utility_redirect"
    if exp == "home_only_outage":
        return r["category"] == "electrical" and outcome != "utility_redirect"
    if exp == "unsupported":
        return outcome == "unsupported_category"
    if exp in ("not_home_problem", "no_symptom"):
        return r["provider"] is None and outcome not in ("ready_to_dispatch",)
    raise ValueError(exp)


def judge(client, item: dict) -> FirstTurnVerdict | None:
    resp = TELEMETRY.track(
        "judge", JUDGE_MODEL, client.messages.parse,
        max_tokens=2000, output_config={"effort": "low"}, system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": f"User's first message:\n{item['text']}\n\nAssistant reply:\n{item['reply']}"}],
        output_format=FirstTurnVerdict,
    )
    return resp.parsed_output


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["rules", "anthropic"], default="anthropic")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--label", default="current", help="name for the report, e.g. before / after")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--only-expect", help="comma-separated labels to run a targeted subset, e.g. safety_guidance")
    args = ap.parse_args()

    items = json.loads((ROOT / "data/evaluation/generalization_openings.json").read_text())
    if args.only_expect:
        items = [it for it in items if it.get("expect") in set(args.only_expect.split(","))]
    if args.backend == "anthropic":
        from app.services.llm import ClaudeLLM

        llm = ClaudeLLM()
    else:
        llm = RulesLLM()
    load_providers()  # warm the cache before threads start
    TELEMETRY.reset()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda it: run_one(it, llm), items))

    if args.judge:
        import anthropic

        client = anthropic.Anthropic()
        symptomatic = [r for r in results if r["expect"] not in ("not_home_problem", "no_symptom")]
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            verdicts = list(pool.map(lambda r: judge(client, r), symptomatic))
        for r, v in zip(symptomatic, verdicts):
            r["judge_score"], r["judge_issue"] = (v.score, v.issue) if v else (None, None)

    symptomatic = [r for r in results if r["expect"] not in ("not_home_problem", "no_symptom")]
    clarifying = [r for r in symptomatic if r["action"] in CLARIFY_ACTIONS]
    labeled = [r for r in results if r["expect"]]
    for r in labeled:
        r["label_ok"] = check_label(r)
    by_label: dict[str, list[bool]] = {}
    for r in labeled:
        by_label.setdefault(r["expect"], []).append(r["label_ok"])

    pct = lambda n, d: round(100 * n / d, 1) if d else None  # noqa: E731
    metrics = {
        "openings": len(results),
        "generic_fallback_rate": pct(sum(r["generic_menu"] for r in symptomatic), len(symptomatic)),
        "contextual_clarification_rate": pct(sum(not r["generic_menu"] for r in clarifying), len(clarifying)),
        "clarifying_replies": len(clarifying),
        "premature_provider": sum(1 for r in results if r["provider"] and not r["pilot_area"]),
        "hard_violations": sum(1 for r in results if r["violations"]),
        "labeled_accuracy": pct(sum(r["label_ok"] for r in labeled), len(labeled)),
        "labeled_by_expectation": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(by_label.items())},
    }
    scores = [r["judge_score"] for r in results if r.get("judge_score")]
    if scores:
        metrics["judge_mean_score"] = round(statistics.mean(scores), 2)
        metrics["judge_low_scores(<=2)"] = sum(s <= 2 for s in scores)
    usage = TELEMETRY.summary()
    metrics["cost_usd"] = usage["total_cost_usd"]

    print(json.dumps(metrics, indent=1))
    print("\nGeneric-menu replies:")
    for r in symptomatic:
        if r["generic_menu"]:
            print(f"  {r['id']} {r['text'][:70]!r}")
    print("\nLabel misses:")
    for r in labeled:
        if not r["label_ok"]:
            print(f"  {r['id']} [{r['expect']}] {r['text'][:60]!r} -> {r['action']}/{r['outcome']}")
    out = ROOT / "data/evaluation/reports" / f"generalization_{args.backend}_{args.label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"metrics": metrics, "results": results, "llm_usage": usage}, indent=1, default=str))
    print(f"\nreport: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
