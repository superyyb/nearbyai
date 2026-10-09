"""Per-field validation of values the user typed, and the correction question when one is wrong.

The LLM copies candidate values exactly as typed; code decides whether they are valid. One bad field never
discards the rest of the message: valid fields are saved, the invalid one is marked for correction, and only that
field is asked for again, saying what looks wrong. An invalid contact is never treated as a refusal to share.

Found by manual testing: "yy, 669222192, 1450 Lafayette St" (a 9-digit number) was silently dropped twice, the
contact ask limit was hit, and the user was sent to self-serve with "No problem, I won't share your details".
"""

import re

ZIP_PLUS4 = re.compile(r"^\s*(\d{5})(?:-\d{4})?\s*$")
EXAMPLES = {"phone": "408-555-0142", "email": "name@example.com", "zip_code": "95050"}


def normalize_zip(raw: str) -> str | None:
    """'95050' and '95050-1234' -> '95050' (coverage is looked up by 5-digit ZIP); anything else -> None."""
    m = ZIP_PLUS4.match(raw or "")
    return m.group(1) if m else None


def contact_kind(raw: str) -> str:
    return "email" if "@" in raw else "phone"


def _digits(raw: str) -> str:
    return re.sub(r"\D", "", raw)


def _show_digits(raw: str) -> str:
    d = _digits(raw)
    return "-".join(p for p in (d[:3], d[3:6], d[6:]) if p)


def correction_message(field: str, raw: str, attempt: int, provider=None) -> str:
    """attempt 1: say exactly what's wrong; 2: also give a format example; 3+: offer another way forward."""
    if field == "phone":
        n = len(_digits(raw))
        what = f"I got {_show_digits(raw)} for the phone number, but that's {n} digit{'s' if n != 1 else ''}"
        rule = "US numbers have 10"
    elif field == "email":
        what = f"The email address {raw.strip()} doesn't look complete"
        rule = "an email looks like name@example.com"
    else:
        what = f"I got {raw.strip()} for the ZIP code, but that doesn't look like a 5-digit ZIP"
        rule = "ZIP codes have 5 digits"

    if attempt <= 1:
        return f"{what} — {rule}. Could you double-check it?"
    if attempt == 2:
        return f"That still doesn't look right — {rule}, for example {EXAMPLES[field]}. Could you check it again?"
    if field == "zip_code":
        return "If you're not sure of the ZIP code, the city name works too."
    other = "a phone number" if field == "email" else "an email address"
    direct = f" — or you can contact {provider.name} directly at {provider.phone}" if provider else ""
    return f"I'm still not getting a complete {'email' if field == 'email' else 'number'}. If it's easier, {other} works too{direct}."
