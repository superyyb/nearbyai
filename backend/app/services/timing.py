"""When the user wants the visit: kept in their words, anchored to a calendar date by code.

Found by manual testing: "I prefer this afternoon after 2pm" was extracted correctly, but the lead only said
"Same-day service preferred" (the urgency label replaced the specific time), and the reply didn't confirm it.

The extractor reports a day reference (today, tomorrow, a weekday) and a short time window ("after 2 PM"). Code
turns the day into a date in the pilot area's time zone when it is said, so a provider reading the lead the next
day sees "Thursday, Oct 8 after 2 PM", not "this afternoon". Periods such as "this weekend" are not turned into a
date; the lead keeps the user's own words. The user sees relative wording ("today after 2 PM").
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain import LeadState

PILOT_TZ = ZoneInfo("America/Los_Angeles")  # every pilot area is in this time zone
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
TIMING_FIELDS = ("urgency", "preferred_time", "preferred_day", "preferred_window")
SHORT_URGENCY = {"emergency": "ASAP", "same_day": "Same-day", "within_week": "Next few days", "flexible": "Flexible"}
# What the user sees about their own request; the provider-facing labels live in lead_packet.
USER_URGENCY = {"emergency": "As soon as possible", "same_day": "Same-day service preferred",
                "within_week": "Within the next few days", "flexible": "Flexible timing"}


def local_today() -> date:
    return datetime.now(PILOT_TZ).date()


def resolve_day(day: str | None, today: date) -> date | None:
    if day == "today":
        return today
    if day == "tomorrow":
        return today + timedelta(days=1)
    if day in WEEKDAYS:
        ahead = (WEEKDAYS.index(day) - today.weekday()) % 7
        # "Thursday" said on a Thursday could mean today or next week; don't guess.
        return today + timedelta(days=ahead) if ahead else None
    return None


def has_timing(state: LeadState) -> bool:
    return any(getattr(state, f) for f in TIMING_FIELDS)


def clear(state: LeadState) -> None:
    for f in TIMING_FIELDS:
        setattr(state, f, None)
    state.preferred_date = None


def anchor(state: LeadState, today: date | None = None) -> None:
    """Resolve the preferred day to a date. Same-day service with no other day means today."""
    if state.preferred_day is None and state.urgency == "same_day":
        state.preferred_day = "today"
    resolved = resolve_day(state.preferred_day, today or local_today())
    state.preferred_date = resolved.isoformat() if resolved else None


def _join(*parts: str | None) -> str | None:
    return " ".join(p for p in parts if p) or None


def user_when(state: LeadState) -> str | None:
    """Relative wording for the user, e.g. "today after 2 PM"; None if only the urgency is known."""
    if state.preferred_day == "other":
        return state.preferred_time
    day = state.preferred_day.capitalize() if state.preferred_day in WEEKDAYS else state.preferred_day
    return _join(day, state.preferred_window)


def is_specific(state: LeadState) -> bool:
    """A time worth confirming back: a time window, or a day other than plain "today"."""
    return bool(state.preferred_window) or state.preferred_day not in (None, "today")


def provider_when(state: LeadState) -> str | None:
    """Absolute wording for the provider, e.g. "Thursday, Oct 8 after 2 PM"."""
    if state.preferred_day == "other":
        return state.preferred_time
    if state.preferred_date:
        d = date.fromisoformat(state.preferred_date)
        return _join(f"{d:%A}, {d:%b} {d.day}", state.preferred_window)
    return state.preferred_window or (state.preferred_time if not state.urgency else None)


def provider_label(state: LeadState) -> str:
    from app.services.lead_packet import URGENCY_LABELS

    label = URGENCY_LABELS.get(state.urgency) if state.urgency else None
    return " — ".join(p for p in (label, provider_when(state)) if p) or "Not stated by the customer"


def progress_label(state: LeadState) -> str | None:
    """Short label for the progress panel, e.g. "Same-day · after 2 PM"."""
    when = user_when(state)
    if state.urgency == "same_day" and state.preferred_day == "today":
        when = state.preferred_window  # "Same-day · today after 2 PM" says today twice
    if not state.urgency:
        return when
    if not when:
        return USER_URGENCY[state.urgency]
    return f"{SHORT_URGENCY[state.urgency]} · {when}"


def confirmation(state: LeadState) -> str:
    return f"Got it — I'll note that you'd prefer {user_when(state)}. The provider would still need to confirm that time."


def confirmation_kept(text: str, state: LeadState) -> bool:
    """The rephrased reply still names the time and says the provider has to confirm it."""
    lower = text.lower()
    return (user_when(state) or "").lower() in lower and "confirm" in lower
