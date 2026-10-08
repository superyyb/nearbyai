"""Provider-perspective lead judge: would a local business understand and act on this lead?

Design (milestone eval, run once on final leads):
- The judge sees a provider-view rendering only: the job, impacts, location, timing, customer and contact.
  Consent, coverage, provider identity, provenance, and internal status are hard rules checked by code, so
  they are not shown and not judged.
- Negative controls are PAIRED degradations of real generated leads: same renderer, same format, one quality
  dimension removed. The score drop between a lead and its degraded copy measures whether the judge
  discriminates on information quality rather than on style.
- Each lead is judged in its own call, in shuffled order, with no label or hint of which items are controls.
- Model, effort, rubric, and renderer versions are recorded with the results. (This model does not accept a
  temperature setting; the fixed model + effort + rubric is the control.)
- missing_information is aggregated as a product-discovery signal, not as an automatic feature backlog.
"""

import copy
import random
import statistics
from collections import Counter

from pydantic import BaseModel, Field

from app.services.telemetry import TELEMETRY

JUDGE_MODEL = "claude-opus-5-5"
JUDGE_EFFORT = "medium"
RUBRIC_VERSION = "provider-lead-v2"
RENDERER_VERSION = "provider-view-v1"

DEGRADATIONS = ("no_timing", "vague_problem", "vague_problem_no_timing")

JUDGE_SYSTEM = """You own a local {trade} business and just received this inbound lead from a lead service.
Judge only how useful the lead itself is to you. Assume the customer agreed to be contacted and the job is in your
service area; don't judge those.

Score 1-5:
5 = Immediately actionable: you understand the job, where it is, how urgent it is or when they want help, and you
    can contact the customer and decide whether to pursue it.
4 = Good lead; only minor nice-to-have details missing.
3 = Potentially useful, but you'd need meaningful clarification before deciding or scheduling.
2 = Weak: important job details or timing/context are missing.
1 = Not actionable; too vague to reasonably pursue.

would_act: would you call this customer about this job today?
missing_information: short items you'd want that the lead doesn't have ([] if none).
reason: one sentence, at most 25 words."""


class JudgeVerdict(BaseModel):
    lead_quality_score: int = Field(description="1-5 per the rubric")
    would_act: bool
    missing_information: list[str]
    reason: str


def render_for_judge(packet: dict) -> str:
    """What a provider would act on - and nothing the system decides deterministically."""
    c, p, s, t = packet["customer"], packet["property"], packet["service"], packet["timing"]
    lines = [
        f"Service requested: {s['category']}",
        f"Issue: {s['problem'] or 'not provided'}",
    ]
    lines += [f"  {k}: {v}" for k, v in (s.get("details") or {}).items()]
    if s.get("observed_impacts"):
        lines.append(f"Observed impact: {'; '.join(s['observed_impacts'])}")
    lines += [
        f"Location: {p['address']}",
        f"Timing: {t['preference'] or 'not provided'}",
        f"Customer: {c['name']}",
        f"Contact: {c['contact']} ({c['contact_method']})",
    ]
    if c.get("contact_preferences"):
        lines.append(f"Contact preferences: {c['contact_preferences']}")
    return "\n".join(lines)


def degrade(packet: dict, kind: str) -> dict:
    """A copy of a real lead with one quality dimension removed; everything else, and the format, unchanged."""
    p = copy.deepcopy(packet)
    if kind in ("no_timing", "vague_problem_no_timing"):
        p["timing"]["preference"] = "not provided"
    if kind in ("vague_problem", "vague_problem_no_timing"):
        p["service"]["problem"] = f"{p['service']['category']} problem."
        p["service"]["details"] = {}
        p["service"]["observed_impacts"] = []
    return p


def build_items(leads: list[dict], n_controls: int, seed: int = 7) -> list[dict]:
    """Real leads plus paired degraded controls, anonymized and shuffled."""
    rng = random.Random(seed)
    items = [{"kind": "generated", "pair": i, "packet": lead} for i, lead in enumerate(leads)]
    for k, i in enumerate(rng.sample(range(len(leads)), min(n_controls, len(leads)))):
        kind = DEGRADATIONS[k % len(DEGRADATIONS)]
        items.append({"kind": f"control:{kind}", "pair": i, "packet": degrade(leads[i], kind)})
    rng.shuffle(items)
    for n, item in enumerate(items):
        item["eval_id"] = f"lead-{n:03d}"
    return items


class ClaudeJudge:
    def __init__(self, client, model: str = JUDGE_MODEL):
        self.client, self.model = client, model

    def judge(self, packet: dict) -> JudgeVerdict | None:
        trade = packet["service"]["category"].split(" (")[0].lower()
        resp = TELEMETRY.track(
            "judge", self.model, self.client.messages.parse,
            max_tokens=2000,
            output_config={"effort": JUDGE_EFFORT},
            system=JUDGE_SYSTEM.format(trade=trade),
            messages=[{"role": "user", "content": render_for_judge(packet)}],
            output_format=JudgeVerdict,
        )
        return resp.parsed_output


def summarize(items: list[dict]) -> dict:
    """Separation between generated leads and their degraded copies, plus missing-information counts."""
    def stats(group):
        scored = [i for i in group if i.get("verdict")]
        if not scored:
            return {"n": 0}
        return {
            "n": len(scored),
            "mean_score": round(statistics.mean(i["verdict"]["lead_quality_score"] for i in scored), 2),
            "would_act_rate": round(100 * sum(i["verdict"]["would_act"] for i in scored) / len(scored), 1),
        }

    generated = [i for i in items if i["kind"] == "generated"]
    controls = [i for i in items if i["kind"].startswith("control:")]
    by_pair = {i["pair"]: i for i in generated if i.get("verdict")}
    drops = [by_pair[c["pair"]]["verdict"]["lead_quality_score"] - c["verdict"]["lead_quality_score"]
             for c in controls if c.get("verdict") and c["pair"] in by_pair]
    missing = Counter(m.strip().lower() for i in generated if i.get("verdict") for m in i["verdict"]["missing_information"])
    return {
        "judge_model": JUDGE_MODEL, "judge_effort": JUDGE_EFFORT,
        "rubric_version": RUBRIC_VERSION, "renderer_version": RENDERER_VERSION,
        "generated": stats(generated),
        "controls": stats(controls),
        "controls_by_kind": {k: stats([c for c in controls if c["kind"] == f"control:{k}"]) for k in DEGRADATIONS},
        "mean_paired_drop": round(statistics.mean(drops), 2) if drops else None,
        "pairs_where_degraded_scored_lower": f"{sum(d > 0 for d in drops)}/{len(drops)}",
        "most_common_missing_information": missing.most_common(8),
    }


def run_provider_judge(judge: ClaudeJudge, leads: list[dict], n_controls: int = 6) -> dict:
    if not leads:
        return {"status": "no leads to judge"}
    items = build_items(leads, n_controls)
    for item in items:
        verdict = judge.judge(item["packet"])
        item["verdict"] = verdict.model_dump() if verdict else None
    return {
        "summary": summarize(items),
        "items": [{"eval_id": i["eval_id"], "kind": i["kind"], "pair": i["pair"],
                   "rendered": render_for_judge(i["packet"]), "verdict": i["verdict"]} for i in items],
    }
