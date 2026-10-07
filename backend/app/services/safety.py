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
    "hvac_burning_smell": re.compile(
        r"\b(burning|burnt|burned)( smell| odor)?\b.{0,40}\b(furnace|heater|vents?|ac|a/c|hvac|heat pump)\b"
        r"|\b(furnace|heater|vents?|ac|a/c|hvac|heat pump)\b.{0,40}\b(burning|burnt|burned)\b",
        re.I,
    ),
    "sewage_backup": re.compile(r"\b(sewage|raw sewage|sewer (backup|backed up|overflow\w*))\b", re.I),
    "ceiling_sagging": re.compile(
        r"\bceiling\b.{0,30}\b(sagging|bulging|bowing|collapsing|caving)\b|\b(sagging|bulging|bowing)\b.{0,15}\bceiling\b",
        re.I,
    ),
    "tree_on_house": re.compile(
        r"\btree\b.{0,40}\b(fell|fallen|came down|crashed)\b.{0,30}\b(roof|house|home)\b|\btree\b.{0,20}\bthrough (the|my) roof\b",
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
    "hvac_burning_smell": (
        "For safety: turn the system off at the thermostat. If you see smoke or the smell gets stronger, "
        "leave the home and call 911."
    ),
    "sewage_backup": (
        "For safety: avoid contact with the sewage water, keep kids and pets away, and don't use sinks, toilets, "
        "or showers until it's fixed."
    ),
    "ceiling_sagging": (
        "For safety: stay out from under that part of the ceiling — a sagging, water-filled ceiling can come down. "
        "If it's safe, move valuables away and put a bucket nearby."
    ),
    "tree_on_house": (
        "For safety: stay away from the damaged area. If anyone is hurt, or you see downed power lines or "
        "structural damage, leave and call 911."
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


def affirmed(rx: re.Pattern, message: str) -> bool:
    """True if the pattern matches at least once outside a negated clause.

    "No sparks or burning smell" -> negated. "No, I do see sparks" -> affirmed,
    because the comma ends the clause that holds the "no".
    """
    for m in rx.finditer(message):
        clause = CLAUSE_BREAK.split(message[: m.start()])[-1]
        if not NEGATION.search(clause):
            return True
    return False


SPARK_WORDS = re.compile(r"\b(spark\w*|arcing|outlet|panel|breaker|switch|wires?|wiring)\b", re.I)


def screen(message: str) -> SafetyResult:
    urgent = [name for name, rx in URGENT_RULES.items() if affirmed(rx, message)]
    # A burning smell from the heating/cooling system gets HVAC guidance (turn it off at the thermostat),
    # not the breaker-and-outlet guidance — unless electrical parts are mentioned too.
    if "hvac_burning_smell" in urgent and "electrical_sparking" in urgent and not SPARK_WORDS.search(message):
        urgent.remove("electrical_sparking")
    return SafetyResult(
        redirect_flags=[name for name, rx in REDIRECT_RULES.items() if affirmed(rx, message)],
        urgent_flags=urgent,
    )
