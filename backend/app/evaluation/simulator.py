"""Simulated users. They answer only from hidden_facts and never invent facts.

StructuredSimulator (offline, free, deterministic): answers the field the agent
just asked for, using the agent's structured action. Good for regression.

ClaudeSimulator: reads only the agent's text, plays the persona. Closer to
real users; requires an API key.
"""

import json
import re

from app.services.telemetry import TELEMETRY

QUESTION_FIELD_TO_FACT = {
    "water_still_active": "water_still_active",
    "active_leak": "active_leak",
    "electrical_symptoms": "hazard_present",  # the scenario fact covers the whole question
}


def _yes_no(value) -> str:
    return {True: "yes", False: "no"}.get(value, "I'm not sure")


class StructuredSimulator:
    name = "structured"

    def __init__(self, case: dict):
        self.case = case
        self.facts = dict(case["hidden_facts"])
        self.persona = case["persona"].lower()
        self.zip_corrected = False
        self.category_corrected = False

    def reply(self, agent_message: str, action_type: str, field: str | None) -> str:
        f = self.facts
        # Provider-preference behaviors trigger the first time a provider is recommended.
        found = re.search(r"I found (.+?), which", agent_message)
        if found and f.get("reject_first_provider") and not f.get("_rejected"):
            f["_rejected"] = True
            return f["rejection_message"].format(provider=found.group(1))
        if found and f.get("ask_question") and not f.get("_asked"):
            f["_asked"] = True
            return f["question_message"]
        # Persona-driven corrections are volunteered on the turn after the original answer.
        if "corrected_zip_code" in f and f.get("_zip_given") and not self.zip_corrected:
            self.zip_corrected = True
            return f"Sorry, actually the ZIP is {f['corrected_zip_code']}, not {f['zip_code']}"
        if "correction_message" in f and f.get("_zip_given") and not self.category_corrected:
            self.category_corrected = True
            return f["correction_message"]

        if action_type in ("ask_category", "clarify_category"):
            return f.get("clarification_answer", "I'm not sure")
        if action_type == "ask_location":
            f["_zip_given"] = True
            if f.get("zip_code") == "unknown":
                return f"I am in {f['city']}. I don't know the ZIP code"
            if f.get("street_address"):
                f["_street_given"] = True
            if f.get("street_address") and "full address" in self.persona:
                return f"{f['street_address']}, {f.get('city', '')}, CA {f['zip_code']}"
            if f.get("street_address"):
                return f"{f['street_address']}, {f.get('city', '')} {f['zip_code']}"
            return f["zip_code"]
        if action_type == "ask_qualification":
            return _yes_no(f.get(QUESTION_FIELD_TO_FACT.get(field, ""), None))
        if action_type == "ask_timing":
            return f.get("preferred_time", "I'm not sure")
        if action_type == "ask_address":
            return f["street_address"] if f.get("street_address") else "I'd rather not share the address yet"
        if action_type == "ask_contact":
            parts = [f.get("customer_name", ""), f.get("phone", "")]
            if "address" in agent_message.lower() and f.get("street_address") and not f.get("_street_given"):
                parts.append(f"{f['street_address']}, {f.get('city', '')}")
            return ", ".join(p for p in parts if p)
        if action_type == "ask_consent":
            return "yes" if f.get("consent_to_share") else "no, I'd rather call them myself"
        return "ok"


SIMULATOR_SYSTEM = """You are role-playing a homeowner chatting with a home-service assistant, for testing.
Persona: {persona}
Your private facts (JSON): {facts}

Rules:
- Reply to what the assistant just said, in 1-2 short sentences, in character. Follow the persona's behavior
  (terse, vague, typos, volunteering extra details, etc.).
- Use only the private facts. If the assistant asks for something not in your facts, say you don't know or would rather not say.
- Volunteer facts the assistant did not ask for only if the persona says you do.
- Phone numbers, ZIP codes and addresses must be copied exactly from your facts.
- If consent_to_share is false, refuse when asked whether your details may be shared with a provider.
- If zip_code is "unknown", say you don't know your ZIP code and give your city instead.
- If reject_first_provider is true: the first time a provider is recommended, send rejection_message (with the
  provider's name filled in) instead of answering, then continue normally with the next provider.
- If ask_question is true: the first time a provider is recommended, send question_message instead of answering,
  then continue normally.
- If your facts include corrected_zip_code, give zip_code first, then correct it on your next message.
- If your facts include correction_message, say it (verbatim) the first time after you've given your ZIP.
- Never mention that you are simulated."""


class ClaudeSimulator:
    name = "claude"

    def __init__(self, case: dict, client, model: str):
        self.case, self.client, self.model = case, client, model
        self.history: list[dict] = [
            {"role": "user", "content": "(The chat starts. Send your opening message.)"},
            {"role": "assistant", "content": case["opening"]},
        ]

    def reply(self, agent_message: str, action_type: str, field: str | None) -> str:
        # Roles are flipped: the agent is the "user" from the simulator's point of view.
        self.history.append({"role": "user", "content": agent_message})
        resp = TELEMETRY.track(
            "simulator", self.model, self.client.messages.create,
            max_tokens=1000,
            output_config={"effort": "low"},
            system=SIMULATOR_SYSTEM.format(persona=self.case["persona"], facts=json.dumps(self.case["hidden_facts"])),
            messages=self.history,
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        self.history.append({"role": "assistant", "content": text})
        return text
