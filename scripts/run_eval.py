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
    ap.add_argument("--judge", action="store_true", help="run the provider-perspective LLM judge")
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
        from app.evaluation.provider_judge import ClaudeJudge, run_judge

        judge_report = run_judge(ClaudeJudge(client, model), [r.lead for r in runs if r.lead])

    print_report(args, metrics, runs, judge_report, stability)
    write_report(args, metrics, runs, judge_report, stability)


def print_report(args, metrics, runs, judge_report, stability) -> None:
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
        "avg_lead_quality": "Avg lead quality (0-100)",
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
        print("\n Provider-perspective judge:")
        for k, v in judge_report.items():
            print(f"  {k}: {v}")
    elif not args.judge:
        print("\n Provider judge: skipped (run with --judge; needs ANTHROPIC_API_KEY)")


def write_report(args, metrics, runs, judge_report, stability) -> None:
    out_dir = ROOT / "data/evaluation/reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.backend}_{args.simulator}"
    payload = {
        "config": vars(args),
        "metrics": metrics,
        "judge": judge_report,
        "stability": stability,
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
