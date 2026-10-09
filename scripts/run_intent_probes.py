"""Language-understanding probes: one extraction call per phrasing, no full conversation.

Checks that Claude maps varied human wording onto the right conversation events
(provider feedback, questions, impossible requests, consent changes, scope),
and that ordinary answers do NOT trigger them (negative controls). The
orchestration behind each event is covered by deterministic tests.

    cd backend && uv run python ../scripts/run_intent_probes.py [--backend rules|anthropic] [--ids a,b]
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
from app.domain import Category, LeadState, ServiceDetails  # noqa: E402
from app.services.rules_llm import RulesLLM  # noqa: E402
from app.services.telemetry import TELEMETRY  # noqa: E402


def context_state(name: str) -> tuple[LeadState, str | None]:
    """Conversation positions the probes are asked from."""
    hvac_matched = dict(
        conversation_id="probe", service_category=Category.HVAC, category_confirmed=True,
        issue_summary="AC runs but blows warm air", city="Santa Clara", pilot_area="santa_clara",
        candidate_provider_ids=["dg-heating-air-conditioning", "evs-mechanical", "promax-service-group"],
        selected_provider_id="dg-heating-air-conditioning", selected_provider_coverage="verified",
    )
    if name == "start":
        return LeadState(conversation_id="probe"), None
    if name == "start_location":
        return LeadState(conversation_id="probe", service_category=Category.HVAC, issue_summary="AC broken"), "zip_code"
    if name == "matched":
        return LeadState(**hvac_matched), "urgency"
    if name == "contact_question":
        return LeadState(**hvac_matched, urgency="same_day"), "customer_name,contact_value"
    if name == "consent_question":
        return LeadState(**hvac_matched, urgency="same_day", customer_name="Sam",
                         contact_method="phone", contact_value="(408) 555-0100"), "consent_to_share"
    if name == "lead_ready":
        return LeadState(**hvac_matched, urgency="same_day", customer_name="Sam", contact_method="phone",
                         contact_value="(408) 555-0100", street_address="10 Main St", consent_to_share=True,
                         outcome="ready_to_dispatch"), None
    if name == "provisional_offer":
        return LeadState(conversation_id="probe", service_category=Category.ELECTRICAL, city="Sunnyvale",
                         pilot_area="sunnyvale", issue_summary="Kitchen outlets dead",
                         offered_provider_id="wooding-electric"), "provisional_offer"
    if name == "water_question":
        return LeadState(conversation_id="probe", service_category=Category.WATER_DAMAGE, zip_code="94089",
                         pilot_area="sunnyvale", issue_summary="Neighbor reports water pooling in basement",
                         service_details=ServiceDetails()), "water_still_active"
    raise ValueError(name)


def _plain(value):
    return value.value if isinstance(value, Category) else value


def check(updates, expect: dict) -> list[str]:
    misses = []
    for key, want in expect.items():
        if key.endswith("_contains"):
            got = getattr(updates, key.removesuffix("_contains"))
            ok = got is not None and want.lower() in (" ".join(got) if isinstance(got, list) else str(got)).lower()
        elif key.endswith("_nonempty"):
            got = getattr(updates, key.removesuffix("_nonempty"))
            ok = bool(got) == want
        elif key.endswith("_any"):
            got = getattr(updates, key.removesuffix("_any"))
            ok = any(w in got for w in want)
        elif key.endswith("_in"):
            got = _plain(getattr(updates, key.removesuffix("_in")))
            ok = got in want
        else:
            got = _plain(getattr(updates, key))
            ok = got == want
        if not ok:
            misses.append(f"{key}: expected {want!r}, got {got!r}")
    return misses


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["rules", "anthropic"], default="anthropic")
    ap.add_argument("--ids", help="comma-separated probe ids")
    args = ap.parse_args()

    probes = json.loads((ROOT / "data/evaluation/intent_probes.json").read_text())
    if args.ids:
        probes = [p for p in probes if p["id"] in set(args.ids.split(","))]
    if args.backend == "anthropic":
        from app.services.llm import ClaudeLLM

        llm = ClaudeLLM()
    else:
        llm = RulesLLM()

    TELEMETRY.reset()
    results = []
    for probe in probes:
        state, last_field = context_state(probe["context"])
        updates = llm.extract(state, probe["message"], last_field).updates
        misses = check(updates, probe["expect"])
        results.append({"id": probe["id"], "message": probe["message"], "passed": not misses, "misses": misses})
        print(f"{'PASS' if not misses else 'FAIL'}  {probe['id']:<26} {'; '.join(misses)}")

    passed = sum(r["passed"] for r in results)
    controls = [r for r in results if r["id"].startswith("control_")]
    print(f"\n{passed}/{len(results)} probes passed "
          f"(negative controls: {sum(r['passed'] for r in controls)}/{len(controls)})")
    usage = TELEMETRY.summary()
    if usage["total_calls"]:
        print(f"cost ${usage['total_cost_usd']:.3f} over {usage['total_calls']} calls")
    out = ROOT / "data/evaluation/reports" / f"intent_probes_{args.backend}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"passed": passed, "total": len(results), "results": results, "llm_usage": usage},
                              indent=2, default=str))


if __name__ == "__main__":
    main()
