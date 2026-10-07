"""Provider-perspective LLM judge, validated with negative controls.

The judge sees only the finished lead packet (never hidden eval facts). If it
cannot score the deliberately bad packets clearly below the good ones, its
scores are not informative and the report says so.
"""

import copy

from pydantic import BaseModel, Field

from app.services.lead_packet import render_text

JUDGE_SYSTEM = """You are the owner of the home-service business named as the matched provider in this lead.
Decide whether you would accept and act on this lead today. Be strict and practical: you need to understand
the job, know it is your kind of work, know roughly where it is, and be allowed to contact the customer."""


class JudgeVerdict(BaseModel):
    would_accept: bool
    acceptability_score: int = Field(description="1 (useless) to 5 (excellent, act immediately)")
    missing_information: list[str]
    reason: str


def negative_controls(good_packet: dict) -> dict[str, dict]:
    controls = {}

    p = copy.deepcopy(good_packet)
    p["property"]["address"] = "Not provided"
    p["customer"]["contact"] = None
    controls["no_location_no_contact"] = p

    p = copy.deepcopy(good_packet)
    p["service"]["problem"] = "something is wrong with my house"
    p["service"]["details"] = {}
    controls["vague_problem"] = p

    p = copy.deepcopy(good_packet)
    p["customer"]["contact_permission"] = "No — customer did not agree to be contacted"
    controls["no_consent"] = p

    p = copy.deepcopy(good_packet)
    p["service"]["category"] = "Pest Control"
    p["service"]["problem"] = "Termites in the garage walls."
    controls["category_mismatch"] = p
    return controls


class ClaudeJudge:
    def __init__(self, client, model: str):
        self.client, self.model = client, model

    def judge(self, packet: dict) -> JudgeVerdict | None:
        resp = self.client.messages.parse(
            model=self.model,
            max_tokens=2000,
            output_config={"effort": "medium"},
            system=JUDGE_SYSTEM,
            messages=[{"role": "user", "content": render_text(packet)}],
            output_format=JudgeVerdict,
        )
        return resp.parsed_output


def run_judge(judge: ClaudeJudge, leads: list[dict]) -> dict:
    if not leads:
        return {"status": "no leads to judge"}
    real = [judge.judge(p) for p in leads]
    controls = {name: judge.judge(p) for name, p in negative_controls(leads[0]).items()}
    real_scores = [v.acceptability_score for v in real if v]
    control_scores = {k: v.acceptability_score for k, v in controls.items() if v}
    mean_real = sum(real_scores) / len(real_scores) if real_scores else None
    discriminates = bool(real_scores) and all(s <= 2 for s in control_scores.values()) and (mean_real or 0) >= 4
    return {
        "real_mean_score": round(mean_real, 2) if mean_real else None,
        "real_accept_rate": round(100 * sum(v.would_accept for v in real if v) / len(real_scores), 1) if real_scores else None,
        "negative_control_scores": control_scores,
        "judge_discriminates": discriminates,
        "real_missing_info": sorted({m for v in real if v for m in v.missing_information}),
    }
