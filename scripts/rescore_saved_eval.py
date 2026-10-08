"""Re-apply corrected evaluator checks to a saved eval report, without calling any model.

Used once for the final run: the exact-phrase "answers_without_inventing" check rejected a correct reply that
answered both provider questions in one sentence. The original report is left untouched; this writes a separate
rescored file recording both the original and the corrected result.

    cd backend && uv run python ../scripts/rescore_saved_eval.py ../data/evaluation/reports/final_scenarios_claude.json
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.evaluation.evaluator import provider_questions_answered_honestly  # noqa: E402

CORRECTED_CHECK = "answers_without_inventing"


def main(path: str) -> None:
    src = Path(path)
    report = json.loads(src.read_text())
    changes = []
    for case in report["cases"]:
        if not case["expected"].get(CORRECTED_CHECK):
            continue
        old = [f for f in case["failures"] if "provider question" in f]
        ok, why = provider_questions_answered_honestly(case["transcript"], ("reviews", "price"))
        new = [] if ok else [f"provider questions not answered honestly: {why}"]
        kept = [f for f in case["failures"] if f not in old]
        if old != new:
            changes.append({"case": case["id"], "original_failures": old, "rescored_failures": new})
        case["failures"] = kept + new

    passed = sum(not c["failures"] for c in report["cases"])
    rescored = {
        "note": ("Corrected evaluator assertion re-applied to the saved transcripts; no model calls were rerun. "
                 f"Original report: {src.name}"),
        "corrected_check": CORRECTED_CHECK,
        "original_cases_passed": report["metrics"]["cases_passed"],
        "rescored_cases_passed": passed,
        "cases": len(report["cases"]),
        "changes": changes,
    }
    out = src.with_name(src.stem + "_rescored.json")
    out.write_text(json.dumps(rescored, indent=2) + "\n")
    print(json.dumps(rescored, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
