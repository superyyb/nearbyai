"""Offline, rule-based implementation of the LLM interface.

Purpose: run the full product and the eval suite without an API key, and act
as the deterministic baseline the Claude backend is compared against. It is
intentionally simple; it is not meant to match Claude on messy language.
"""

import re

from app.domain import ELECTRICAL_FACTS, Category, ExtractedFields, ExtractionResult, LeadState
from app.services.provider_search import find_by_name
from app.services.safety import affirmed

CATEGORY_KEYWORDS: list[tuple[Category, re.Pattern]] = [
    (Category.WATER_DAMAGE, re.compile(r"\b(flood(ed|ing)?|basement.*water|water.*basement|water damage|standing water|soaked|mold)\b", re.I)),
    (Category.ROOFING, re.compile(r"\b(roof|shingles?|gutter|skylight|attic leak)\b", re.I)),
    (Category.PLUMBING, re.compile(r"\b(pipe|plumb\w*|toilet|sink|faucet|drain|clog\w*|water heater|leak(ing)?|burst|sewer|garbage disposal)\b", re.I)),
    (Category.HVAC, re.compile(r"\b(ac|a/c|air condition\w*|hvac|furnace|heater|heat pump|thermostat|warm air|cold air|no heat|not cooling|heating)\b", re.I)),
    (Category.ELECTRICAL, re.compile(r"\b(outlet|breaker|electric\w*|wiring|wires?|spark\w*|lights? (flicker\w*|out)|panel|switch)\b", re.I)),
]
UNSUPPORTED_KEYWORDS = re.compile(
    r"\b(pests?|termites?|rodents?|mice|rats?|ants|cockroach\w*|bed ?bugs|landscap\w*|lawn|tree (trimming|removal)|"
    r"pool|painting|cleaning service|locksmith|locked out|garage door|windows?|foundation|moving|internet|wifi|cable|"
    r"appliance repair)\b",
    re.I,
)
ZIP_RE = re.compile(r"\b(9\d{4})\b")
PHONE_RE = re.compile(r"(\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", re.I)
STREET_RE = re.compile(r"\b\d{1,6}\s+[A-Za-z0-9 .]+?\s(st|street|ave|avenue|rd|road|dr|drive|blvd|ct|court|ln|lane|way|pl|place|cir|circle)\b\.?", re.I)
CITY_RE = re.compile(r"\b(santa clara|sunnyvale|san jose|fremont|oakland|san francisco|mountain view|cupertino|palo alto|milpitas|campbell)\b", re.I)
NAME_RE = re.compile(r"\b(?:my name is|i am|i'm|this is|name'?s)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", re.I)
YES_RE = re.compile(r"^\s*(y|ya|yes|yeah|yep|yup|sure|ok|okay|of course|please do|go ahead|that'?s fine|fine)\b", re.I)
NO_RE = re.compile(r"^\s*(n|no|nope|nah|not really|don'?t|do not)\b", re.I)
DONT_KNOW_RE = re.compile(r"\b(not sure|don'?t know|no idea|unsure|idk|dunno)\b", re.I)
SHOW_OPTIONS_RE = re.compile(r"\b(show me (all |my |the )?options|what are (my|the) options|list (them|the options)|let me (choose|pick))\b", re.I)
CHOOSE_RE = re.compile(r"\b(use|go with|prefer|pick|choose|is fine|are fine|works)\b", re.I)
WHOLE_HOME_NO_WATER = re.compile(r"\b(no water|water (is )?(off|out)|lost water|no running water)\b", re.I)
WHOLE_HOME_NO_POWER = re.compile(r"\b(no power|power(?:'s| is)? out|lost power|no electricity|power outage|blackout)\b", re.I)
PARTIAL = re.compile(r"\b(half|some|one|part of|outside faucet|kitchen only|in the (kitchen|bathroom|shower))\b", re.I)
NEIGHBORS_AFFECTED = re.compile(r"\bneighbou?rs?\b.{0,30}\b(too|also|as well|same|out|dark|no (water|power))\b|\bwhole (street|block|neighborhood)\b|\b(street|block|neighborhood) (is|went|lost)\b", re.I)
HOME_ONLY = re.compile(r"\bneighbou?rs?\b.{0,30}\b(fine|ok|okay|have (water|power)|lights (are )?on)\b|\b(only|just) (my|our) (house|home|place)\b|\bonly (us|me)\b", re.I)
EDIT_TARGETS = [
    ("phone", re.compile(r"\b(phone|number|cell)\b", re.I)),
    ("zip_code", re.compile(r"\bzip\b", re.I)),
    ("street_address", re.compile(r"\baddress\b", re.I)),
    ("name", re.compile(r"\bname\b", re.I)),
    ("timing", re.compile(r"\b(time|timing|day|date|when)\b", re.I)),
    ("issue", re.compile(r"\b(problem|issue)\b", re.I)),
]
WANTS_CHANGE_RE = re.compile(r"\b(change|update|edit|switch|different)\b", re.I)
WRONG_VALUE_RE = re.compile(r"\b(wrong|incorrect|not my|typo|mistake|misspel\w*|isn'?t right)\b", re.I)
QUESTION_TOPICS = [
    ("sponsorship", re.compile(r"\b(sponsor\w*|paid (placement|ads?)|affiliat\w*|get paid|kickback)\b", re.I)),
    ("is_this_a_person", re.compile(r"\b(real person|human|a bot|are you (an? )?(ai|robot))\b", re.I)),
    ("request_status", re.compile(r"\b(did you (send|contact)|(has|have) (it|my request|they) been (sent|contacted)|already sent)\b", re.I)),
    ("data_privacy", re.compile(r"\b(my data|privacy|who (sees|gets) my|store my|selling my)\b", re.I)),
    ("why_need_info", re.compile(r"\bwhy (do|would) you need\b", re.I)),
    ("price", re.compile(r"\b(price|cost|charge|how much|expensive|cheap|quote)\b", re.I)),
    ("reviews", re.compile(r"\b(reviews?|rating|rated|good company|any good|reputable|trust(worthy)?)\b", re.I)),
    ("license_or_insurance", re.compile(r"\b(licen[cs]ed?|insured|insurance|bonded)\b", re.I)),
    ("distance", re.compile(r"\b(how far|distance|close to me|nearby)\b", re.I)),
    ("hours_or_24_7", re.compile(r"\b(open (now|late)|24/7|hours|weekends?)\b", re.I)),
    ("availability", re.compile(r"\b(can they come|available|availability|come (today|tomorrow)|how soon)\b", re.I)),
    ("why_this_provider", re.compile(r"\bwhy (this|them|that|did you (pick|choose))\b", re.I)),
]
INFO_FIELDS = [
    ("phone", re.compile(r"\b(phone|number)\b", re.I)),
    ("zip_or_address", re.compile(r"\b(zip|address|location)\b", re.I)),
    ("name", re.compile(r"\bname\b", re.I)),
]
REQUESTED_ACTIONS = [
    ("book_appointment", re.compile(r"\b(book|schedule|make an appointment|set up an appointment)\b", re.I)),
    ("call_provider", re.compile(r"\b(call|text|phone|contact|email) (them|the (company|provider|plumber|electrician))\b", re.I)),
    ("send_now", re.compile(r"\bsend (it|my request|the request)\b", re.I)),
    ("guarantee", re.compile(r"\bguarantee\b", re.I)),
]
QUESTION_RE = re.compile(r"\?|^\s*(why|how|what|who|are|is|do|does|can|could|will|would)\b", re.I)
REJECT_PROVIDER_RE = re.compile(
    r"\b(don'?t (like|want|trust)|bad experience|terrible|awful|not (them|that one|happy with)|never again|avoid)\b", re.I
)
ALTERNATIVE_RE = re.compile(r"\b(other options?|another (one|company|provider|option)|someone else|anyone else|alternatives?)\b", re.I)
DECLINE_RE = re.compile(r"\b(rather not|prefer not|no thanks|don'?t want to (share|give)|not comfortable|i'?ll call them myself|i will call)\b", re.I)


def _yes_no(msg: str) -> bool | None:
    if YES_RE.search(msg):
        return True
    if NO_RE.search(msg):
        return False
    return None


def _urgency(msg: str) -> str | None:
    m = msg.lower()
    if re.search(r"\b(asap|right now|emergency|immediately|urgent)\b", m):
        return "emergency"
    if re.search(r"\b(today|tonight|this afternoon|this evening)\b", m):
        return "same_day"
    if re.search(r"\b(tomorrow|this week|next few days|in a few days|weekend)\b", m):
        return "within_week"
    if re.search(r"\b(no rush|whenever|flexible|next week|any ?time|not urgent)\b", m):
        return "flexible"
    return None


DAY_RE = re.compile(r"\b(today|tonight|this (?:afternoon|evening|morning)|tomorrow|monday|tuesday|wednesday|thursday|"
                    r"friday|saturday|sunday)\b", re.I)
CLOCK_RE = re.compile(r"\b((?:after|before|by|around) \d{1,2}(?::\d{2})? ?(?:am|pm))\b", re.I)
PART_OF_DAY_RE = re.compile(r"\b(morning|afternoon|evening)\b", re.I)


def _visit_time(msg: str) -> tuple[str | None, str | None]:
    """(day, window) for the visit; the rule-based backend only knows plain days and simple times."""
    day = window = None
    if m := DAY_RE.search(msg):
        word = m.group(1).lower()
        day = "today" if word in ("today", "tonight") or word.startswith("this ") else word
    if m := CLOCK_RE.search(msg) or PART_OF_DAY_RE.search(msg):  # the clock time is the more specific one
        window = re.sub(r"(\d) ?(am|pm)", lambda x: f"{x.group(1)} {x.group(2).upper()}", m.group(1).lower())
    return day, window


ELECTRICAL_FACT_RES = {
    "sparks_present": re.compile(r"\bspark\w*\b", re.I),
    "burning_smell_present": re.compile(r"\b(burning smell|smells? (like )?burn\w*|smoke)\b", re.I),
    "hot_fixture_present": re.compile(r"\bhot to the touch\b", re.I),
}
APPLIANCE_RE = re.compile(r"\b(dishwasher|washing machine|washer|dryer|fridge|refrigerator|oven|stove|microwave)\b", re.I)
LEAK_RE = re.compile(r"\b(leak\w*|water (on|all over)|flood\w*|dripping)\b", re.I)


def _classify(msg: str) -> list[Category]:
    cats = [cat for cat, rx in CATEGORY_KEYWORDS if rx.search(msg)]
    if APPLIANCE_RE.search(msg) and LEAK_RE.search(msg) and Category.PLUMBING not in cats:
        cats.insert(0, Category.PLUMBING)  # leak from an appliance's water connection is plumbing
    return cats


class RulesLLM:
    name = "rules"

    def extract(self, state: LeadState, message: str, last_question_field: str | None) -> ExtractionResult:
        up = ExtractedFields()
        msg = message.strip()
        corrections: list[str] = []
        is_correction = bool(re.search(r"\b(actually|sorry|correction|i meant|wrong|instead|changed?)\b", msg, re.I))

        # Category (an appliance that won't run/drain/cool is appliance repair, checked before trade keywords)
        appliance_fault = bool(APPLIANCE_RE.search(msg) and not LEAK_RE.search(msg))
        cats = [] if appliance_fault else _classify(msg)
        if appliance_fault:
            up.unsupported_service = "appliance repair"
        elif UNSUPPORTED_KEYWORDS.search(msg) and not cats:
            up.unsupported_service = UNSUPPORTED_KEYWORDS.search(msg).group(0).lower()
        elif cats:
            primary = cats[0]
            # Basement water after rain/storm is restoration, not plumbing.
            if Category.WATER_DAMAGE in cats:
                primary = Category.WATER_DAMAGE
            if last_question_field in (None, "service_category") or is_correction or state.service_category is None:
                up.service_category = primary
                up.candidate_categories = cats
                if len(cats) > 1 and state.service_category is None:
                    distinct = {c for c in cats if c != primary}
                    unrelated = distinct - {Category.PLUMBING, Category.WATER_DAMAGE, Category.ROOFING}
                    if unrelated:
                        up.secondary_issues = [f"possible {CATEGORY_LABELS_SHORT[c]} issue also mentioned" for c in unrelated]
                if is_correction and state.service_category and primary != state.service_category:
                    corrections.append("service_category")
            if state.issue_summary is None or is_correction or last_question_field in (None, "service_category"):
                up.issue_summary = msg[:240]

        # Damage caused by the problem (not a separate job)
        impacts = re.findall(r"\b((?:floor|ceiling|wall|carpet|drywall|cabinets?)\w* (?:is |are |got )?(?:soaked|stained|warp\w*|wet|ruined|damaged))\b", msg, re.I)
        if impacts:
            up.observed_impacts = list(dict.fromkeys(i.lower() for i in impacts))

        # Disambiguation answers
        if last_question_field == "service_category" and not cats:
            if re.search(r"\b(rain|storm)\b", msg, re.I):
                up.service_category = Category.ROOFING
            elif re.search(r"\b(bathroom|shower|toilet|pipe|upstairs)\b", msg, re.I):
                up.service_category = Category.PLUMBING
            if up.service_category and state.issue_summary:
                up.issue_summary = f"{state.issue_summary} ({msg})"

        # Location
        if z := ZIP_RE.search(msg):
            up.zip_code = z.group(1)
            if state.zip_code and state.zip_code != up.zip_code:
                corrections.append("zip_code")
        if s := STREET_RE.search(msg):
            up.street_address = s.group(0).strip().rstrip(",")
        if c := CITY_RE.search(msg):
            up.city = c.group(1).title()
            if state.city and state.city != up.city:
                corrections.append("city")

        # Contact
        if e := EMAIL_RE.search(msg):
            up.contact_method, up.contact_value = "email", e.group(0)
        else:
            phone_text = ZIP_RE.sub("", msg) if up.zip_code else msg
            if p := PHONE_RE.search(phone_text):
                up.contact_method, up.contact_value = "phone", p.group(0)
        if (n := NAME_RE.search(msg)) and not DONT_KNOW_RE.search(n.group(0)):  # "I'm not sure" isn't a name
            up.customer_name = n.group(1).title()
        elif last_question_field and "customer_name" in last_question_field:
            # "Test User, 408-555-0142" / "Pat Lee 6505550199" style answers.
            without_contact = PHONE_RE.sub(",", EMAIL_RE.sub(",", msg))
            head = re.split(r"[,;\n]| and | at ", without_contact)[0].strip()
            if head and not re.search(r"\d", head) and len(head.split()) <= 3 and not YES_RE.search(head):
                up.customer_name = head.title()

        # A digit run that isn't a full phone number is still a phone attempt; code validates it.
        if up.contact_value is None and last_question_field and ("contact_value" in last_question_field
                                                                or last_question_field.startswith(("edit:phone", "correct:"))):
            run = re.search(r"(?<!\d)\d[\d\s().-]{5,14}\d(?!\d)", ZIP_RE.sub("", msg) if up.zip_code else msg)
            if run:
                up.contact_method, up.contact_value = "phone", run.group(0)

        # Timing
        if u := _urgency(msg):
            up.urgency = u
            up.preferred_time = msg[:80] if last_question_field == "urgency" else None
            if last_question_field == "urgency":
                up.preferred_day, up.preferred_window = _visit_time(msg)
        elif last_question_field == "urgency" and _yes_no(msg) is True:
            up.urgency = "same_day"  # answered "yes" to "would you like help today if possible?"
        elif last_question_field == "urgency" and DONT_KNOW_RE.search(msg):
            up.urgency = "flexible"

        # Qualification answers
        yn = _yes_no(msg)
        if last_question_field == "water_still_active" and yn is not None:
            up.water_still_active = yn
        if last_question_field == "active_leak" and yn is not None:
            up.active_leak = yn
        if last_question_field == "electrical_symptoms" and yn is not None:
            up.sparks_present = up.burning_smell_present = up.hot_fixture_present = yn
        if last_question_field in ("water_still_active", "active_leak") and DONT_KNOW_RE.search(msg):
            up.unknown_facts.append(last_question_field)
        if last_question_field == "electrical_symptoms" and DONT_KNOW_RE.search(msg):
            up.unknown_facts += ELECTRICAL_FACTS
        if re.search(r"\b(still (coming|leaking|dripping|flowing)|getting worse|won'?t stop)\b", msg, re.I):
            up.water_still_active = True
            up.active_leak = True
        if re.search(r"\b(stopped|dried|no longer)\b", msg, re.I):
            up.water_still_active = False
        if re.search(r"\b(storm|rain(ed|ing)?)\b", msg, re.I) and (cats and Category.WATER_DAMAGE in cats):
            up.likely_source = "storm_exterior"
        for fact, rx in ELECTRICAL_FACT_RES.items():
            if rx.search(msg):  # "no sparks" is a fact too: sparks_present = False
                setattr(up, fact, affirmed(rx, msg))

        # Possible utility outage
        if WHOLE_HOME_NO_WATER.search(msg) and not PARTIAL.search(msg):
            up.utility_signal = "water"
        elif WHOLE_HOME_NO_POWER.search(msg) and not PARTIAL.search(msg):
            up.utility_signal = "power"
        if NEIGHBORS_AFFECTED.search(msg):
            up.outage_scope = "neighbors_affected"
        elif HOME_ONLY.search(msg):
            up.outage_scope = "home_only"
        elif last_question_field == "outage_scope" and DONT_KNOW_RE.search(msg):
            up.outage_scope = "unknown"

        # Feedback about providers
        named = find_by_name(msg) if state.service_category else None
        if last_question_field == "provisional_offer" and yn is not None:
            up.provider_feedback = "accept_offer" if yn else "decline_offer"
        elif state.selected_provider_id or last_question_field == "named_provider":
            if REJECT_PROVIDER_RE.search(msg):
                up.provider_feedback = "reject"
                up.provider_feedback_reason = msg[:120]
                up.named_provider = named.name if named else None
            elif SHOW_OPTIONS_RE.search(msg):
                up.provider_feedback = "show_options"
            elif named and (last_question_field == "named_provider" or CHOOSE_RE.search(msg)):
                up.provider_feedback, up.named_provider = "choose_named", named.name
            elif ALTERNATIVE_RE.search(msg):
                up.provider_feedback = "want_alternative"

        # Field edits announced without the new value
        target = next((f for f, rx in EDIT_TARGETS if rx.search(msg)), None)
        if target and (WRONG_VALUE_RE.search(msg) or WANTS_CHANGE_RE.search(msg)) and state.outcome is not None \
                or target and WRONG_VALUE_RE.search(msg):
            up.edit_field = target
            up.edit_kind = "current_value_wrong" if WRONG_VALUE_RE.search(msg) else "wants_change"
        if last_question_field and last_question_field.startswith("edit:name") and not up.customer_name:
            head = re.split(r"[,;\n]", PHONE_RE.sub(",", msg))[0].strip()
            if head and not re.search(r"\d", head) and len(head.split()) <= 3:
                up.customer_name = head.title()

        # Questions and requests the system can't fulfil
        if QUESTION_RE.search(msg):
            up.question_topics = [topic for topic, rx in QUESTION_TOPICS if rx.search(msg)]
            if "why_need_info" in up.question_topics:
                up.question_info_field = next((f for f, rx in INFO_FIELDS if rx.search(msg)), "other")
        for action, rx in REQUESTED_ACTIONS:
            if rx.search(msg):
                up.requested_action = action
                break

        # Address / contact refusals
        if DECLINE_RE.search(msg) or (yn is False and last_question_field in ("street_address",)):
            if last_question_field == "street_address":
                up.declined_fields.append("street_address")
            elif last_question_field and ("customer_name" in last_question_field or "contact_value" in last_question_field):
                up.declined_fields.append("contact")
            elif last_question_field == "consent_to_share":
                up.consent_to_share = False

        # Consent: answered when asked, or withdrawn/granted at any later point
        if last_question_field == "consent_to_share" and up.consent_to_share is None and yn is not None:
            up.consent_to_share = yn
        if re.search(r"\b(don'?t|do not) share\b|\bwithdraw\b|\bcancel (the|my) request\b", msg, re.I):
            up.consent_to_share = False
        elif re.search(r"\b(you can|ok to|okay to|go ahead and) share\b", msg, re.I):
            up.consent_to_share = True

        if re.search(r"\b(rent|renting|tenant|landlord)\b", msg, re.I):
            up.property_relationship = "tenant"
        elif re.search(r"\b(my house|my home|i own|homeowner)\b", msg, re.I):
            up.property_relationship = "homeowner"

        return ExtractionResult(updates=up, corrections=corrections)


CATEGORY_LABELS_SHORT = {
    Category.WATER_DAMAGE: "water damage",
    Category.PLUMBING: "plumbing",
    Category.ROOFING: "roofing",
    Category.HVAC: "heating/cooling",
    Category.ELECTRICAL: "electrical",
}
