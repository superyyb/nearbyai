"""LLM layer. The model does three narrow jobs:
  1. extract facts from the latest message into ExtractionResult
  2. phrase the backend-chosen next step naturally
  3. rerank 2+ already-eligible providers by specialty fit
It never decides what to ask, whether to search, eligibility, or dispatchability.
"""

import json
import logging
import os
import re
from typing import Literal, Protocol

from pydantic import BaseModel

from app.config import settings
from app.domain import ExtractedFields, ExtractionResult, LeadState, Provider
from app.services.rules_llm import RulesLLM
from app.services.safety import affirmed
from app.services.telemetry import TELEMETRY

log = logging.getLogger(__name__)


class LLM(Protocol):
    name: str

    def extract(self, state: LeadState, message: str, last_question_field: str | None) -> ExtractionResult: ...


EXTRACTION_SYSTEM = """You extract structured facts for a home-service intake assistant.

Supported categories:
- water_damage_restoration: flooding, standing water, water intrusion into a home after storms, drying/cleanup, mold from water
- plumbing: pipes, leaks from fixtures/supply lines, toilets, drains, water heaters, sewer
- roofing: roof leaks, shingles, storm damage to roof, gutters
- hvac: heating, air conditioning, furnaces, heat pumps, thermostats
- electrical: outlets, breakers, panels, wiring, lighting circuits
Anything else -> service_category null and unsupported_service set to a short name of the service. Unsupported
examples: pest control, landscaping/tree removal, garage doors, locksmiths, pools, windows, foundations, cleaning,
moving, internet/cable, and appliance repair.
Scope rules:
- Appliances: water leaking from an appliance's water connection (dishwasher, washer, fridge line) is plumbing;
  an appliance that won't run, drain, cool, or heat is appliance repair (unsupported).
- Mold or staining caused by a water leak is water_damage_restoration.
- Several problems: safety first, then the immediate source, then the consequences. The source decides
  service_category. Damage CAUSED by the main problem goes in observed_impacts (a burst pipe that soaked the
  floor -> plumbing, observed_impacts ["kitchen floor soaked"]). secondary_issues is ONLY for unrelated problems
  that would need a separate job (a roof leak AND a broken AC -> roofing, secondary_issues ["AC not working"]).

Rules:
- Extract only what the LATEST user message states or clearly implies. For anything not stated use "" for text,
  "none" / "not_mentioned" / "not_answered" for choices, and [] for lists.
- Never invent addresses, names, phone numbers, or timing.
- issue_summary: one or two provider-facing sentences combining the current summary with any new problem facts. Keep it factual.
- service_category is your best guess even when unsure; list every plausible category in candidate_categories.
- If the right trade can't be decided yet (e.g. a ceiling stain could be roof or plumbing), set
  needs_clarification=true and say why in clarification_reason.
- suggested_question: when needs_clarification is true, or the trade is unknown, write ONE short question that
  uses what the user already told you and best resolves that open decision (e.g. "Does it get worse when it
  rains, or is there a bathroom above that spot?"). Never list the service categories back to the user, and
  never ask for contact details or a ZIP here. Otherwise "".
- hazard_categories: safety hazards the user describes as present now (not denied): gas smell / CO alarm / fire or
  smoke -> gas_co_fire; water touching or entering anything electrical (outlets, cords, light fixtures, panel) ->
  electrical_water; something hot, melting, or smelling burnt -> overheating_burning; sparks, arcing, or buzzing
  from electrical equipment -> sparking_buzzing_electrical. hazard_evidence: the user's words that show it, else "".
- utility_signal: "possible_water_outage" if the WHOLE home has no water (or pressure dropped everywhere);
  "possible_power_outage" if the WHOLE home lost power. Not for one fixture, one circuit, or half the house.
  outage_scope: "neighbors_affected" if the user says nearby homes/street/area are affected too, "home_only" if
  they say neighbors are fine or it's only their home, "unknown" only if they say they don't know whether nearby
  homes are affected (not knowing what's wrong is NOT unknown scope); else "not_mentioned".
  When utility_signal is set and outage_scope is unknown, suggested_question should ask whether it's only their
  home or nearby homes too.
- If the user mentions several unrelated problems, pick the most urgent as service_category and put the others in
  secondary_issues. Never put the main problem's own consequences in secondary_issues.
- corrections: list a field only if the user explicitly changes an earlier answer ("actually it's 95051").
- consent_to_share: "yes"/"no" when the user answers the question about sharing their contact details with the
  provider, or later explicitly withdraws ("don't share my number") or grants that permission; else "not_answered".
- declined_fields: "street_address" or "contact" when the user refuses to give them — including withdrawing an
  address they gave earlier ("don't share my address until they call").
- contact_preferences: how or when the provider should contact them, or whose number it is ("calls only, no texts",
  "after 5pm", "this is my wife's number"); else "".
- urgency: emergency (needs help immediately), same_day (today), within_week, flexible.
- If the user answers yes/no, interpret it against the assistant's last question field.
- water_still_active / active_leak / hazard_present: "yes"/"no" only when the user states the current situation
  directly. Second-hand or ambiguous reports (e.g. "my neighbor says water is pooling") are "not_mentioned".
  Use "unknown" when the user says they don't know or can't check.
- provider_feedback (about providers the assistant recommended or offered):
  "reject" — turns down a provider (dislikes them, bad past experience, doesn't want them);
  "want_alternative" — asks for someone else without rejecting ("anyone else?", "is that my only option?");
  "show_options" — wants to see the list of options or choose themselves;
  "choose_named" — asks for a specific provider by name, including changing their mind ("actually DG is fine");
  "accept_offer" / "decline_offer" — answers yes/no to an offered provider (see assistant_last_question_field);
  else "none". named_provider: the provider name the user mentioned (for reject or choose_named), else "".
  provider_feedback_reason: their stated reason, or "".
- question_topics: classify EVERY question the user asks the assistant, in order (why this provider, price, reviews,
  availability, hours/24-7, distance, license/insurance, why do you need some info, data privacy, are you a person,
  are recommendations sponsored/paid, has my request been sent; "other" for any other question); [] if none.
  For why_need_info also set question_info_field to the info they asked about; otherwise "none".
- requested_action: if the user asks the assistant to call/text the provider, book or schedule an appointment,
  send the request right now, or guarantee timing, classify it; else "none".
- A message can contain both a question and facts; extract both."""

WRITER_SYSTEM = """You write the next assistant message for a home-service intake chat.

The backend has already decided WHAT to do. Your job is only to phrase it warmly and briefly.
Rules:
- Ask at most the one question in the reference message; do not add new questions.
- The reference may first answer the user's question or respond to their request; keep that answer's meaning
  exactly (including any "I don't have verified ..." statements) and add no new facts, then ask the question.
- Keep it under 60 words. Plain text, no lists, no markdown.
- Do not mention any business, phone number, website, or fact that is not in the reference message or provider facts.
- Never say a provider has been contacted, dispatched, booked, scheduled, or will arrive at a certain time.
- If provider coverage is 'provisional', do not say they serve the user's area; say they are located nearby.
- Express sympathy at most once per conversation: only when is_first_reply is true. Otherwise get straight to the point.
- When you acknowledge the problem, refer to the user's concrete situation (user_situation), e.g. "an overflowing
  toilet can cause water damage quickly"; don't use internal category labels like "a plumbing problem" or
  "an HVAC issue".
- Safety guidance may already be shown before your text; don't repeat or paraphrase it.
- If damage_tip_verbatim is set, include that sentence exactly, word for word, after your brief acknowledgement
  and before the question.
- Do not repeat sentences or provider descriptions from previous_assistant_message.
- Never mention internal state, fields, tools, or validation."""

RERANK_SYSTEM = """Rank the candidate providers for a home-service job, best fit first.
Every candidate already passed category and service-area checks. Rank only by specialty fit to the described job
(and 24/7 availability if the job is urgent and the record says so). Return every candidate id exactly as given,
and a short reason for the top choice grounded only in its record."""


CategoryOrNone = Literal["water_damage_restoration", "plumbing", "roofing", "hvac", "electrical", "none"]
# "unknown" = the user said they can't tell; distinct from "not_mentioned".
YesNo = Literal["yes", "no", "unknown", "not_mentioned"]
CorrectableField = Literal[
    "service_category", "zip_code", "city", "street_address", "urgency", "customer_name", "contact_value",
    "water_still_active", "active_leak", "hazard_present",
]


class LLMExtraction(BaseModel):
    """Wire schema for structured outputs: flat, every field required, no unions.
    Empty string / 'none' / 'not_mentioned' mean the latest message did not state it."""

    service_category: CategoryOrNone
    candidate_categories: list[Literal["water_damage_restoration", "plumbing", "roofing", "hvac", "electrical"]]
    needs_clarification: bool
    clarification_reason: str
    suggested_question: str
    hazard_categories: list[Literal["gas_co_fire", "electrical_water", "overheating_burning", "sparking_buzzing_electrical"]]
    hazard_evidence: str
    utility_signal: Literal["possible_water_outage", "possible_power_outage", "none"]
    outage_scope: Literal["home_only", "neighbors_affected", "unknown", "not_mentioned"]
    unsupported_service: str
    issue_summary: str
    secondary_issues: list[str]
    observed_impacts: list[str]
    street_address: str
    city: str
    zip_code: str
    urgency: Literal["emergency", "same_day", "within_week", "flexible", "none"]
    preferred_time: str
    customer_name: str
    property_relationship: Literal["homeowner", "tenant", "property_manager", "other", "none"]
    contact_method: Literal["phone", "email", "none"]
    contact_value: str
    contact_preferences: str
    consent_to_share: Literal["yes", "no", "not_answered"]
    insurance_intent: str
    water_still_active: YesNo
    active_leak: YesNo
    hazard_present: YesNo
    likely_source: Literal["storm_exterior", "plumbing", "unknown", "not_mentioned"]
    declined_fields: list[Literal["street_address", "contact"]]
    provider_feedback: Literal[
        "reject", "want_alternative", "show_options", "choose_named", "accept_offer", "decline_offer", "none"
    ]
    provider_feedback_reason: str
    named_provider: str
    question_topics: list[Literal[
        "why_this_provider", "price", "reviews", "availability", "hours_or_24_7", "distance", "license_or_insurance",
        "why_need_info", "data_privacy", "is_this_a_person", "sponsorship", "request_status", "other",
    ]]
    question_info_field: Literal[
        "zip_or_address", "phone", "name", "timing", "water_still_active", "active_leak", "hazard_present",
        "consent", "other", "none",
    ]
    requested_action: Literal["call_provider", "book_appointment", "send_now", "guarantee", "other", "none"]
    corrections: list[CorrectableField]

    def to_result(self) -> ExtractionResult:
        none_values = {"", "none", "not_mentioned", "not_answered"}
        yes_no = {"yes": True, "no": False}
        data: dict = {"unknown_facts": []}
        for name, value in self.model_dump().items():
            if name in ("corrections",):
                continue
            if name in ("water_still_active", "active_leak", "hazard_present", "consent_to_share"):
                data[name] = yes_no.get(value)
                if value == "unknown" and name != "consent_to_share":
                    data["unknown_facts"].append(name)
            elif isinstance(value, str):
                data[name] = None if value.strip().lower() in none_values else value.strip()
            else:
                data[name] = value
        data["utility_signal"] = {"possible_water_outage": "water", "possible_power_outage": "power"}.get(
            self.utility_signal)
        return ExtractionResult(updates=ExtractedFields(**data), corrections=list(self.corrections))


class RerankResult(BaseModel):
    ranked_provider_ids: list[str]
    reason: str


class ClaudeLLM:
    name = "claude"

    def __init__(self) -> None:
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = settings.llm_model

    def _kwargs(self) -> dict:
        kw: dict = {"output_config": {"effort": settings.llm_effort}}
        if os.getenv("LLM_FALLBACKS", "1") == "1":
            kw["extra_headers"] = {"anthropic-beta": "server-side-fallback-2026-07-01"}
            kw["extra_body"] = {"fallbacks": "default"}
        return kw

    def extract(self, state: LeadState, message: str, last_question_field: str | None) -> ExtractionResult:
        context = {
            "current_state": state.model_dump(
                include={"service_category", "issue_summary", "zip_code", "city", "street_address", "urgency",
                         "customer_name", "contact_value", "service_details", "secondary_issues",
                         "observed_impacts"},
                mode="json",
            ),
            "assistant_last_question_field": last_question_field,
            "currently_recommended_provider": _provider_name(state.selected_provider_id),
        }
        feedback = ""
        last_error: Exception | None = None
        for attempt in range(settings.extraction_attempts):
            content = f"<context>{json.dumps(context)}</context>\n<latest_user_message>{message}</latest_user_message>{feedback}"
            try:
                resp = TELEMETRY.track(
                    "extraction", self.model, self.client.messages.parse,
                    max_tokens=2000,
                    system=_cached(EXTRACTION_SYSTEM),
                    messages=[{"role": "user", "content": content}],
                    output_format=LLMExtraction,
                    **self._kwargs(),
                )
                if resp.stop_reason == "refusal" or resp.parsed_output is None:
                    raise ValueError(f"no parsed output (stop_reason={resp.stop_reason})")
                result = resp.parsed_output.to_result()
                problems = semantic_problems(result)
                if not problems:
                    return result
                feedback = "\n<previous_attempt_errors>" + "; ".join(problems) + "</previous_attempt_errors>"
                last_error = ValueError("; ".join(problems))
                TELEMETRY.fallback("extraction_retries")
            except self._anthropic.BadRequestError as e:
                # Not retryable (bad schema/params): fail this turn, keep prior state.
                raise ExtractionFailed(str(e)) from e
            except (self._anthropic.APIConnectionError, self._anthropic.RateLimitError,
                    self._anthropic.InternalServerError, ValueError) as e:
                last_error = e
                TELEMETRY.fallback("extraction_retries")
                log.warning("extraction attempt %d failed: %s", attempt + 1, e)
        raise ExtractionFailed(str(last_error))

    def write(self, reference: str, context: dict) -> str | None:
        try:
            resp = TELEMETRY.track(
                "response", self.model, self.client.messages.create,
                max_tokens=1500,
                system=_cached(WRITER_SYSTEM),
                messages=[{
                    "role": "user",
                    "content": f"<context>{json.dumps(context)}</context>\n<reference_message>{reference}</reference_message>\nWrite the message.",
                }],
                **self._kwargs(),
            )
        except self._anthropic.APIError as e:
            log.warning("writer failed: %s", e)
            return None
        if resp.stop_reason == "refusal":
            return None
        return "".join(b.text for b in resp.content if b.type == "text").strip() or None

    def rerank(self, job: dict, candidates: list[Provider]) -> RerankResult | None:
        records = [c.model_dump(include={"id", "name", "coverage_evidence", "emergency_service"}) for c in candidates]
        try:
            resp = TELEMETRY.track(
                "rerank", self.model, self.client.messages.parse,
                max_tokens=1500,
                system=_cached(RERANK_SYSTEM),
                messages=[{"role": "user", "content": json.dumps({"job": job, "candidates": records})}],
                output_format=RerankResult,
                **self._kwargs(),
            )
        except (self._anthropic.APIError, ValueError) as e:
            log.warning("rerank failed: %s", e)
            return None
        return resp.parsed_output


def _cached(system_prompt: str) -> list[dict]:
    """The system prompts are fixed and sent on every turn; cache them (Sonnet 5.5 minimum is 512 tokens)."""
    return [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]


def _provider_name(provider_id: str | None) -> str | None:
    from app.services.provider_search import get_provider

    provider = get_provider(provider_id) if provider_id else None
    return provider.name if provider else None


class ExtractionFailed(Exception):
    pass


def semantic_problems(result: ExtractionResult) -> list[str]:
    from app.services.state_manager import normalize_contact

    up = result.updates
    problems = []
    if up.zip_code is not None and not re.fullmatch(r"\d{5}", up.zip_code.strip()):
        problems.append("zip_code must be exactly 5 digits or null")
    if up.contact_value is not None and normalize_contact(up.contact_method, up.contact_value)[1] is None:
        problems.append("contact_value must be a 10-digit US phone or an email, or null")
    return problems


# ---------- Guardrails on generated wording ----------

# Provider facts the dataset never contains; if the writer states them, they were invented.
UNVERIFIED_PROVIDER_CLAIMS = re.compile(
    r"\$\s?\d|\b\d(\.\d)?\s*(stars?|/\s*5)\b|\b(highly|top|well)[- ]rated\b|\b(great|excellent|good) reviews\b|"
    r"\b(is|are|fully) (licensed|insured|bonded)\b|\blicensed and insured\b",
    re.I,
)
INTERNAL_DETAILS = re.compile(
    r"\b(system prompt|LeadState|asked_fields|reference_message|next_step|provider_facts|guardrail|"
    r"extraction|json|my instructions)\b|[{}]",
    re.I,
)
FORBIDDEN_CLAIMS = re.compile(
    r"\b(dispatched|booked|scheduled|appointment (is|has been) (set|confirmed)|has been (contacted|notified|sent)|"
    r"(will|is going to) (arrive|come|be there)|on (their|the) way|guarantee\w*)\b",
    re.I,
)
PHONE_IN_TEXT = re.compile(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
URL_IN_TEXT = re.compile(r"https?://[^\s)]+|www\.[^\s)]+", re.I)


def guardrail_violations(text: str, allowed_phones: set[str], allowed_urls: set[str], provisional: bool) -> list[str]:
    issues = []
    # Negation-aware: "I can't guarantee timing" is the honest answer, not a claim.
    if affirmed(FORBIDDEN_CLAIMS, text):
        issues.append("forbidden claim")
    if INTERNAL_DETAILS.search(text):
        issues.append("internal details")
    if affirmed(UNVERIFIED_PROVIDER_CLAIMS, text):
        issues.append("unverified provider claim (price/rating/license)")
    digits_allowed = {re.sub(r"\D", "", p) for p in allowed_phones}
    for m in PHONE_IN_TEXT.findall(text):
        if re.sub(r"\D", "", m) not in digits_allowed:
            issues.append(f"ungrounded phone {m}")
    for m in URL_IN_TEXT.findall(text):
        if not any(m.rstrip(".,").startswith(u) or u.startswith(m.rstrip(".,")) for u in allowed_urls):
            issues.append(f"ungrounded url {m}")
    if provisional and re.search(r"\bserves? (your|the) (area|zip|city)\b", text, re.I):
        issues.append("claims verified coverage for provisional provider")
    if text.count("?") > 1:
        issues.append("more than one question")
    if len(text.split()) > 90:
        issues.append("too long")
    return issues


def get_llm():
    backend = settings.llm_backend
    if backend == "rules":
        return RulesLLM()
    if backend == "anthropic" or (backend == "auto" and os.getenv("ANTHROPIC_API_KEY")):
        return ClaudeLLM()
    return RulesLLM()
