"""Deterministic category-ambiguity rules.

The LLM's needs_clarification flag is a signal, not a calibrated probability.
These rules are the backstop for the known ambiguous patterns, and each
comes with a disambiguating question the backend asks verbatim (the writer
may rephrase it but must ask the same thing).
"""

import re
from dataclasses import dataclass

from app.domain import Category


@dataclass(frozen=True)
class AmbiguityRule:
    name: str
    pattern: re.Pattern
    candidates: tuple[Category, ...]
    question: str
    # If any of these appear in the conversation, the ambiguity is already resolved.
    resolved_by: re.Pattern


RULES = [
    AmbiguityRule(
        name="ceiling_water",
        pattern=re.compile(r"\bceiling\b.*\b(stain|leak|drip|wet|water|spot)|\b(stain|leak|drip|water|spot)\b.*\bceiling\b", re.I),
        candidates=(Category.ROOFING, Category.PLUMBING),
        question="Does it mainly show up when it rains, or is there a bathroom or plumbing directly above that spot?",
        resolved_by=re.compile(r"\b(rain|storm|roof|attic|bathroom|shower|toilet|pipe|upstairs|plumbing)\b", re.I),
    ),
    AmbiguityRule(
        name="no_hot_water",
        pattern=re.compile(r"\bno hot water\b|\bhot water (is )?(not|isn't|stopped)\b", re.I),
        candidates=(Category.PLUMBING, Category.HVAC),
        question="Is your hot water from a standalone water heater (tank or tankless), or tied into your heating system?",
        resolved_by=re.compile(r"\b(tank|tankless|water heater|boiler|heat pump|furnace)\b", re.I),
    ),
]


def detect(conversation_text: str) -> AmbiguityRule | None:
    for rule in RULES:
        if rule.pattern.search(conversation_text) and not rule.resolved_by.search(conversation_text):
            return rule
    return None


GENERIC_CLARIFY_QUESTION = (
    "Can you tell me a bit more about what you're seeing — for example, is it a leak, a heating or cooling "
    "problem, an electrical issue, or something with the roof?"
)
