"""Deterministic safety screen. Runs on every user message before anything else.

Two tiers:
- redirect: the right next step is emergency services / the utility, not a
  contractor lead (gas, fire, carbon monoxide). Outcome = safety_redirect.
- urgent: give safety guidance first, then keep qualifying the lead
  (sparking electrical, water near live electrical).
"""

import re
from dataclasses import dataclass

REDIRECT_RULES = {
    "gas_leak": re.compile(r"\b(smell(s|ing)? (of |like )?gas|gas (smell|leak|odor)|rotten eggs?)\b", re.I),
    "fire": re.compile(r"\b(on fire|fire (in|inside)|flames?|smoke (is )?coming|house is burning)\b", re.I),
    "carbon_monoxide": re.compile(r"\b(carbon monoxide|co (alarm|detector))\b", re.I),
}
URGENT_RULES = {
    "electrical_sparking": re.compile(
        r"\b(spark(s|ing|ed)?|arcing|burning smell|smell(s|ing)? (of )?burning|melt(ed|ing)|scorch(ed)?)\b", re.I
    ),
    "water_near_electrical": re.compile(
        r"\bwater\b.*\b(outlet|panel|breaker|wires?|wiring|electrical)\b"
        r"|\b(outlet|panel|breaker|wires?|wiring|electrical)\b.*\bwater\b",
        re.I,
    ),
}

REDIRECT_GUIDANCE = {
    "gas_leak": (
        "If you smell gas, please leave the home now, avoid using light switches, flames, or your phone indoors, "
        "and once you're outside call 911 and PG&E's gas emergency line at 1-800-743-5000."
    ),
    "fire": "If there is fire or smoke, get everyone out of the home and call 911 right away.",
    "carbon_monoxide": (
        "If a carbon monoxide alarm is going off, get everyone outside into fresh air immediately and call 911."
    ),
}
URGENT_GUIDANCE = {
    "electrical_sparking": (
        "For safety: if it's safe to reach, switch off the breaker for that circuit and don't touch the outlet or "
        "panel. If you see smoke or flames, leave and call 911."
    ),
    "water_near_electrical": (
        "For safety: stay out of standing water that may be near outlets, cords, or the electrical panel. "
        "If you can reach the main breaker without touching water, switch it off; otherwise wait for a professional."
    ),
}


@dataclass
class SafetyResult:
    redirect_flags: list[str]
    urgent_flags: list[str]

    @property
    def is_redirect(self) -> bool:
        return bool(self.redirect_flags)

    def guidance(self) -> str:
        flags = self.redirect_flags or self.urgent_flags
        table = REDIRECT_GUIDANCE if self.redirect_flags else URGENT_GUIDANCE
        return " ".join(table[f] for f in flags)


NEGATION = re.compile(
    r"\b(no|not|nothing|never|without|none|don'?t|doesn'?t|didn'?t|isn'?t|aren'?t|wasn'?t|haven'?t|hasn'?t|can'?t)\b",
    re.I,
)
CLAUSE_BREAK = re.compile(r"[.;!?,]|\bbut\b", re.I)


def _affirmed(rx: re.Pattern, message: str) -> bool:
    """True if the pattern matches at least once outside a negated clause.

    "No sparks or burning smell" -> negated. "No, I do see sparks" -> affirmed,
    because the comma ends the clause that holds the "no".
    """
    for m in rx.finditer(message):
        clause = CLAUSE_BREAK.split(message[: m.start()])[-1]
        if not NEGATION.search(clause):
            return True
    return False


def screen(message: str) -> SafetyResult:
    return SafetyResult(
        redirect_flags=[name for name, rx in REDIRECT_RULES.items() if _affirmed(rx, message)],
        urgent_flags=[name for name, rx in URGENT_RULES.items() if _affirmed(rx, message)],
    )
