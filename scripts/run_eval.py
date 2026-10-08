"""Run the core evaluation suite.

    cd backend
    uv run python ../scripts/run_eval.py                      # offline: rules backend + structured simulator
    uv run python ../scripts/run_eval.py --backend anthropic  # Claude extraction/wording
    uv run python ../scripts/run_eval.py --backend anthropic --simulator claude --judge --repeat-tags ambiguous,correction --repeat 3

Writes data/evaluation/reports/<backend>_<simulator>.json and .md (metrics, failures, transcripts, lead packets).
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.config import settings  # noqa: E402,F401  (loads .env)
from app.evaluation.evaluator import compute_metrics, run_case  # noqa: E402
from app.evaluation.simulator import ClaudeSimulator, StructuredSimulator  # noqa: E402
from app.services.lead_packet import render_text  # noqa: E402
from app.services.rules_llm import RulesLLM  # noqa: E402
from app.services.telemetry import TELEMETRY  # noqa: E402

TARGETS = {
    "provider_grounding": 100.0,
    "coverage_truthfulness": 100.0,
    "provider_eligibility": 100.0,
    "consent_correctness": 100.0,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["rules", "anthropic"], default="rules")
    ap.add_argument("--simulator", choices=["structured", "claude"], default="structured")
    ap.add_argument("--cases", help="comma-separated case ids")
    ap.add_argument("--judge", action="store_true",
                    help="milestone only: provider-perspective Opus judge on the generated leads + paired controls")
    ap.add_argument("--judge-controls", type=int, default=6, help="number of paired degraded controls")
    ap.add_argument("--repeat", type=int, default=1, help="extra runs for cases with --repeat-tags")
    ap.add_argument("--repeat-tags", default="", help="tags of high-risk cases to repeat")
    args = ap.parse_args()

    cases = json.loads((ROOT / "data/evaluation/core_cases.json").read_text())
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in cases if c["id"] in wanted]

    client = None
    if args.backend == "anthropic" or args.simulator == "claude" or args.judge:
        import anthropic

        client = anthropic.Anthropic()
    if args.backend == "anthropic":
        from app.services.llm import ClaudeLLM

        llm = ClaudeLLM()
    else:
        llm = RulesLLM()
    model = os.getenv("LLM_MODEL", "claude-sonnet-5-5")

    def make_sim(case):
        return ClaudeSimulator(case, client, model) if args.simulator == "claude" else StructuredSimulator(case)

    TELEMETRY.reset()
    runs = [run_case(c, llm, make_sim(c)) for c in cases]

    stability = {}
    repeat_tags = set(filter(None, args.repeat_tags.split(",")))
    if args.repeat > 1 and repeat_tags:
        for c in cases:
            if repeat_tags & set(c["tags"]):
                outcomes = [run_case(c, llm, make_sim(c)).state.outcome for _ in range(args.repeat - 1)]
                outcomes.append(next(r.state.outcome for r in runs if r.case["id"] == c["id"]))
                stability[c["id"]] = {"outcomes": [str(o) for o in outcomes], "stable": len(set(outcomes)) == 1}

    metrics = compute_metrics(runs)
    judge_report = None
    if args.judge:
        from app.evaluation.provider_judge import ClaudeJudge, run_provider_judge

        # The judge is a different, fixed model from the agent (Opus vs. Sonnet).
        judge_report = run_provider_judge(ClaudeJudge(client), [r.lead for r in runs if r.lead], args.judge_controls)

    usage = TELEMETRY.summary()
    usage["fallback_rates"] = fallback_rates(usage)
    print_report(args, metrics, runs, judge_report, stability, usage)
    write_report(args, metrics, runs, judge_report, stability, usage)


def fallback_rates(usage: dict) -> dict:
    """How often deterministic code covered for the model, per responsibility."""
    calls = {k: v["calls"] for k, v in usage["by_call_type"].items()}
    fb = usage["deterministic_fallbacks"]
    rate = lambda n, d: f"{n}/{d} ({100 * n / d:.1f}%)" if d else "n/a"  # noqa: E731
    # Each failed extraction turn makes up to N attempts; count turns, not attempts.
    extraction_turns = calls.get("extraction", 0) and (calls["extraction"] - fb.get("extraction_retries", 0))
    return {
        "extraction_failed_turns": rate(fb.get("extraction_failed", 0), extraction_turns),
        "response_fell_back_to_template": rate(
            fb.get("writer_guardrail_rejected", 0) + fb.get("writer_unavailable", 0), calls.get("response", 0)
        ),
        "rerank_fell_back_to_keyword": rate(fb.get("rerank_invalid_or_failed", 0), calls.get("rerank", 0)),
        "rerank_skipped_single_candidate": fb.get("rerank_skipped_single_candidate", 0),
        "server_side_model_fallbacks": sum(v["server_fallbacks"] for v in usage["by_call_type"].values()),
    }


def print_report(args, metrics, runs, judge_report, stability, usage) -> None:
    print("=" * 52)
    print(f" Home Service Agent Evaluation  ({args.backend} / {args.simulator} sim)")
    print("=" * 52)
    labels = {
        "cases": "Cases",
        "cases_passed": "Cases passing all checks",
        "outcome_accuracy": "Outcome accuracy %",
        "service_category_accuracy": "Service category accuracy %",
        "dispatchable_lead_rate": "Dispatchable lead rate %",
        "useful_resolution_rate": "Useful resolution rate %",
        "median_user_turns_to_lead": "Median user turns to lead",
        "mean_user_turns_to_lead": "Mean user turns to lead",
        "provider_grounding": "Provider grounding %",
        "coverage_truthfulness": "Coverage truthfulness %",
        "provider_eligibility": "Provider eligibility %",
        "consent_correctness": "Consent correctness %",
        "avg_lead_completeness": "Avg lead completeness (0-100)",
    }
    for key, label in labels.items():
        value = metrics[key]
        flag = "  <-- BELOW TARGET" if key in TARGETS and value is not None and value < TARGETS[key] else ""
        print(f" {label:<32}{value if value is not None else 'n/a':>10}{flag}")
    failed = [r for r in runs if r.failures]
    if failed:
        print("\n Failures:")
        for r in failed:
            print(f"  - {r.case['id']}: {'; '.join(r.failures)}")
    if stability:
        print("\n Stability (repeated runs):")
        for cid, s in stability.items():
            print(f"  - {cid}: {'stable' if s['stable'] else 'VARIES'} {s['outcomes']}")
    if judge_report:
        print("\n Provider-perspective judge (soft quality only; hard rules are checked by code):")
        for k, v in judge_report.get("summary", judge_report).items():
            print(f"  {k}: {v}")
    elif not args.judge:
        print("\n Provider judge: skipped (run with --judge; needs ANTHROPIC_API_KEY)")
    if usage["total_calls"]:
        print("\n LLM usage (list-price estimate):")
        print(f"  {'call type':<12}{'calls':>6}{'in tok':>10}{'cached':>9}{'out tok':>9}{'avg ms':>8}{'p95 ms':>8}{'cost $':>9}")
        for name, r in usage["by_call_type"].items():
            print(f"  {name:<12}{r['calls']:>6}{r['input_tokens']:>10}{r['cache_read_tokens']:>9}{r['output_tokens']:>9}"
                  f"{r['avg_latency_ms']:>8}{r['p95_latency_ms']:>8}{r['cost_usd']:>9.3f}")
        print(f"  total cost ${usage['total_cost_usd']:.3f} over {usage['total_calls']} calls")
        print("\n Fallback rates:")
        for k, v in usage["fallback_rates"].items():
            print(f"  {k}: {v}")


def write_report(args, metrics, runs, judge_report, stability, usage) -> None:
    out_dir = ROOT / "data/evaluation/reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.backend}_{args.simulator}"
    payload = {
        "config": vars(args),
        "metrics": metrics,
        "judge": judge_report,
        "stability": stability,
        "llm_usage": usage,
        "cases": [
            {
                "id": r.case["id"],
                "outcome": r.state.outcome,
                "expected": r.case["expected"],
                "user_turns": r.state.user_turns,
                "failures": r.failures,
                "transcript": r.transcript,
                "lead": r.lead,
            }
            for r in runs
        ],
    }
    (out_dir / f"{stem}.json").write_text(json.dumps(payload, indent=2, default=str))

    md = [f"# Eval report — {args.backend} backend, {args.simulator} simulator", "", "| Metric | Value |", "|---|---|"]
    md += [f"| {k} | {v} |" for k, v in metrics.items()]
    if usage["total_calls"]:
        md += ["", "## LLM usage (list-price estimate)", "", "| Call type | Calls | Input tok | Output tok | Avg ms | p95 ms | Cost $ |",
               "|---|---|---|---|---|---|---|"]
        md += [f"| {k} | {r['calls']} | {r['input_tokens']} | {r['output_tokens']} | {r['avg_latency_ms']} | "
               f"{r['p95_latency_ms']} | {r['cost_usd']:.3f} |" for k, r in usage["by_call_type"].items()]
        md += ["", "| Fallback | Rate |", "|---|---|"] + [f"| {k} | {v} |" for k, v in usage["fallback_rates"].items()]
    for r in runs:
        status = "PASS" if not r.failures else "FAIL: " + "; ".join(r.failures)
        md += ["", f"## {r.case['id']} — {r.state.outcome} ({r.state.user_turns} user turns) — {status}", ""]
        for t in r.transcript:
            who = "**User**" if t["role"] == "user" else f"**Agent** _({t.get('action')})_"
            md.append(f"- {who}: {t['content']}")
        if r.lead:
            md += ["", "```", render_text(r.lead), "```"]
    (out_dir / f"{stem}.md").write_text("\n".join(md) + "\n")
    print(f"\n Report written to data/evaluation/reports/{stem}.json|.md")


if __name__ == "__main__":
    main()
