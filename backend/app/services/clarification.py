"""Choosing the clarifying question.

The LLM proposes a question in the user's own terms ("Is it only your home, or are your neighbors out of
water too?"). Code decides *whether* to clarify (next_action) and validates the proposal here. Order:

  1. the LLM's question, if it passes validation
  2. a curated rule question for a known ambiguous pattern (ambiguity.py)
  3. the generic category template - the last resort, tracked as "generic fallback"

Validation only checks what code can decide reliably; whether the question is the *best* one is measured
by the first-turn generalization eval, not enforced at runtime.
"""

import re

from app.domain import LeadState
from app.services.llm import INTERNAL_DETAILS, PHONE_IN_TEXT, URL_IN_TEXT, guardrail_violations
from app.services.provider_search import load_providers

MAX_WORDS = 40
CATEGORY_FAMILIES = [
    re.compile(r"\b(leak\w*|plumb\w*|pipes?)\b", re.I),
    re.compile(r"\b(heat\w*|cool\w*|hvac|a/?c|air condition\w*)\b", re.I),
    re.compile(r"\belectric\w*\b", re.I),
    re.compile(r"\broof\w*\b", re.I),
]
ASKS_LOCATION = re.compile(r"\b(zip|address|where (do you|is the (home|house|property)) (live|located))\b", re.I)
ASKS_CONTACT = re.compile(r"\b(phone|number|email|your name)\b", re.I)


def is_category_menu(text: str) -> bool:
    """Reciting three or more trades back to the user is the generic fallback, not a targeted question."""
    return sum(bool(rx.search(text)) for rx in CATEGORY_FAMILIES) >= 3


def question_issues(question: str, state: LeadState) -> list[str]:
    q = question.strip()
    issues = []
    if not q:
        return ["empty"]
    if q.count("?") != 1:
        issues.append("must contain exactly one question")
    if len(q.split()) > MAX_WORDS:
        issues.append("too long")
    if is_category_menu(q):
        issues.append("generic category menu")
    if any(p.name.lower() in q.lower() for p in load_providers().values()):
        issues.append("mentions a provider")
    if PHONE_IN_TEXT.search(q) or URL_IN_TEXT.search(q):
        issues.append("contains a phone number or URL")
    if INTERNAL_DETAILS.search(q):
        issues.append("internal details")
    if ASKS_CONTACT.search(q):
        issues.append("asks for contact details during clarification")
    if state.pilot_area and ASKS_LOCATION.search(q):
        issues.append("asks for a location that is already known")
    issues += [v for v in guardrail_violations(q, set(), set(), False) if v not in ("more than one question",)]
    return list(dict.fromkeys(issues))


def choose_question(state: LeadState, llm_question: str | None, rule_question: str | None) -> tuple[str | None, str, list[str]]:
    """Returns (question or None for the generic template, source, rejected-proposal issues)."""
    issues: list[str] = []
    if llm_question:
        issues = question_issues(llm_question, state)
        if not issues:
            return llm_question.strip(), "llm", []
    if rule_question:
        return rule_question, "rule", issues
    return None, "generic", issues
