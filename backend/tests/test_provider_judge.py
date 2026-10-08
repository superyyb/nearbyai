"""Provider-perspective judge plumbing (no API calls): renderer, paired controls, blindness, aggregation."""

from types import SimpleNamespace

from app.evaluation.provider_judge import (
    JUDGE_MODEL,
    ClaudeJudge,
    build_items,
    degrade,
    render_for_judge,
    run_provider_judge,
)
from tests.helpers import AC_ISSUE, SANTA_CLARA, converse

LEAD_TURNS = [("AC blows warm air", AC_ISSUE), ("Santa Clara", SANTA_CLARA), ("today", {"urgency": "same_day"}),
              ("Sam 408-555-0100", {"customer_name": "Sam", "contact_value": "408-555-0100",
                                    "contact_preferences": "calls only"}),
              ("yes", {"consent_to_share": True})]


def real_lead() -> dict:
    _, results = converse(LEAD_TURNS)
    assert results[-1].lead
    return results[-1].lead


def test_judge_view_hides_hard_rules_and_internal_metadata():
    text = render_for_judge(real_lead()).lower()
    for hidden in ("permission", "consent", "coverage", "verified", "source", "prototype", "quality",
                   "dg heating", "no provider has been contacted"):
        assert hidden not in text, hidden
    for shown in ("issue:", "location:", "timing:", "customer: sam", "contact:", "calls only"):
        assert shown in text, shown


def test_degraded_copies_keep_the_format_and_change_one_dimension():
    lead = real_lead()
    original = render_for_judge(lead).splitlines()
    for kind in ("no_timing", "vague_problem", "vague_problem_no_timing"):
        degraded = render_for_judge(degrade(lead, kind)).splitlines()
        labels = lambda lines: [ln.split(":")[0] for ln in lines if not ln.startswith("  ")]  # noqa: E731
        assert labels(degraded) == [x for x in labels(original) if x != "Observed impact"]
    assert "Timing: not provided" in render_for_judge(degrade(lead, "no_timing"))
    assert "Issue: HVAC (Heating & Cooling) problem." in render_for_judge(degrade(lead, "vague_problem"))
    assert lead["timing"]["preference"] != "not provided"  # the original is untouched


def test_items_are_paired_shuffled_and_anonymous():
    leads = [real_lead() for _ in range(5)]
    items = build_items(leads, n_controls=3)
    assert len(items) == 8 and [i["eval_id"] for i in items] == [f"lead-{n:03d}" for n in range(8)]
    controls = [i for i in items if i["kind"].startswith("control:")]
    assert len(controls) == 3 and all(0 <= c["pair"] < 5 for c in controls)
    assert items != sorted(items, key=lambda i: i["kind"])  # shuffled, not grouped by kind


def test_judge_prompt_is_blind_to_labels_and_uses_the_fixed_model():
    seen = []

    def fake_parse(**kw):
        seen.append(kw)
        return SimpleNamespace(parsed_output=None, usage=None, model=kw["model"], stop_reason="end_turn")

    ClaudeJudge(SimpleNamespace(messages=SimpleNamespace(parse=fake_parse))).judge(degrade(real_lead(), "no_timing"))
    call = seen[0]
    assert call["model"] == JUDGE_MODEL == "claude-opus-5-5"
    prompt = (call["system"] + call["messages"][0]["content"]).lower()
    assert "control" not in prompt and "degraded" not in prompt and "negative" not in prompt


def test_summary_reports_separation_and_missing_information():
    class FakeJudge:
        def judge(self, packet):
            vague = packet["service"]["problem"].endswith("problem.")
            no_time = packet["timing"]["preference"] == "not provided"
            score = 5 - 2 * vague - 1 * no_time
            return SimpleNamespace(model_dump=lambda: {"lead_quality_score": score, "would_act": score >= 4,
                                                      "missing_information": ["photos"] if score == 5 else [],
                                                      "reason": "x"})

    report = run_provider_judge(FakeJudge(), [real_lead() for _ in range(4)], n_controls=3)
    s = report["summary"]
    assert s["generated"]["mean_score"] == 5 and s["controls"]["mean_score"] < 5
    assert s["mean_paired_drop"] == 2.0 and s["pairs_where_degraded_scored_lower"] == "3/3"
    assert s["most_common_missing_information"][0] == ("photos", 4)
    assert s["rubric_version"] and s["renderer_version"] and s["judge_model"] == JUDGE_MODEL
