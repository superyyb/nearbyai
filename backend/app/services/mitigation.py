"""A tiny, fixed table of damage-limiting tips.

Only obvious, low-risk, non-diagnostic actions, triggered by state, shown at most once per conversation, and
never rewritten by the LLM (like safety copy). This is deliberately not a troubleshooting assistant: no
diagnosis, no DIY repair, and nothing for equipment that may involve gas, electricity, or heat (water heaters
are excluded on purpose).
"""

import re

from app.domain import Category, LeadState

TOILET_OVERFLOW = re.compile(r"\btoilet\b.{0,40}\b(overflow\w*|running over|flood\w*|spilling)\b|\b(overflow\w*)\b.{0,20}\btoilet\b", re.I)
ACTIVE_PIPE_LEAK = re.compile(r"\b(burst|bursting|spraying|gushing|pouring|won'?t stop)\b", re.I)
EXCLUDED_EQUIPMENT = re.compile(r"\bwater heater\b|\btankless\b|\bboiler\b", re.I)

TIPS = {
    "toilet_overflow": "If it's safe and accessible, turn off the toilet's water supply valve.",
    "active_pipe_leak": ("If you can safely reach and recognize the main water shutoff, turning it off may help "
                         "limit further water damage."),
}


def tip_for(state: LeadState, conversation_text: str) -> tuple[str, str] | None:
    """Returns (tip_id, text) when a fixed tip applies and hasn't been shown yet."""
    if state.mitigation_given:  # at most one tip per conversation
        return None
    if state.service_category != Category.PLUMBING or state.outcome == "safety_redirect":
        return None
    if EXCLUDED_EQUIPMENT.search(conversation_text):
        return None
    if TOILET_OVERFLOW.search(conversation_text):
        tip_id = "toilet_overflow"
    elif ACTIVE_PIPE_LEAK.search(conversation_text) or state.service_details.water_still_active is True:
        tip_id = "active_pipe_leak"
    else:
        return None
    return tip_id, TIPS[tip_id]
