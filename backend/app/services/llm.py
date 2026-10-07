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
Anything else (pest control, landscaping, appliances, cleaning, locksmith...) -> service_category null and unsupported_service set to a short name of the service.

Rules:
- Extract only what the LATEST user message states or clearly implies. For anything not stated use "" for text,
  "none" / "not_mentioned" / "not_answered" for choices, and [] for lists.
- Never invent addresses, names, phone numbers, or timing.
- issue_summary: one or two provider-facing sentences combining the current summary with any new problem facts. Keep it factual.
- If the cause is genuinely ambiguous between categories (e.g. a ceiling stain could be roof or plumbing), set needs_clarification=true and list candidate_categories.
- If the user mentions several unrelated problems, pick the most urgent as service_category and put the others in secondary_issues.
- corrections: list a field only if the user explicitly changes an earlier answer ("actually it's 95051").
- consent_to_share: only set when the user is answering the explicit question about sharing contact details with the provider.
- declined_fields: "street_address" or "contact" when the user refuses to give them.
- urgency: emergency (needs help immediately), same_day (today), within_week, flexible.
- If the user answers yes/no, interpret it against the assistant's last question field.
- water_still_active / active_leak / hazard_present: "yes"/"no" only when the user states the current situation
  directly. Second-hand or ambiguous reports (e.g. "my neighbor says water is pooling") are "not_mentioned".
  Use "unknown" when the user says they don't know or can't check.
- provider_feedback: "reject" if the user turns down the currently recommended provider (dislikes them, bad past
  experience, doesn't want them); "want_alternative" if they ask for other options without rejecting it; else "none".
  provider_feedback_reason: their stated reason, or ""."""

WRITER_SYSTEM = """You write the next assistant message for a home-service intake chat.

The backend has already decided WHAT to do. Your job is only to phrase it warmly and briefly.
Rules:
- Ask at most the one question in the reference message; do not add new questions.
- Keep it under 60 words. Plain text, no lists, no markdown.
- Do not mention any business, phone number, website, or fact that is not in the reference message or provider facts.
- Never say a provider has been contacted, dispatched, booked, scheduled, or will arrive at a certain time.
- If provider coverage is 'provisional', do not say they serve the user's area; say they are located nearby.
- Express sympathy at most once per conversation: only when is_first_reply is true. Otherwise get straight to the point.
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
    unsupported_service: str
    issue_summary: str
    secondary_issues: list[str]
    street_address: str
    city: str
    zip_code: str
    urgency: Literal["emergency", "same_day", "within_week", "flexible", "none"]
    preferred_time: str
    customer_name: str
    property_relationship: Literal["homeowner", "tenant", "property_manager", "other", "none"]
    contact_method: Literal["phone", "email", "none"]
    contact_value: str
    consent_to_share: Literal["yes", "no", "not_answered"]
    insurance_intent: str
    water_still_active: YesNo
    active_leak: YesNo
    hazard_present: YesNo
    likely_source: Literal["storm_exterior", "plumbing", "unknown", "not_mentioned"]
    declined_fields: list[Literal["street_address", "contact"]]
    provider_feedback: Literal["reject", "want_alternative", "none"]
    provider_feedback_reason: str
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
                         "customer_name", "contact_value", "service_details", "secondary_issues"},
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
                    system=EXTRACTION_SYSTEM,
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
                system=WRITER_SYSTEM,
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
                system=RERANK_SYSTEM,
                messages=[{"role": "user", "content": json.dumps({"job": job, "candidates": records})}],
                output_format=RerankResult,
                **self._kwargs(),
            )
        except (self._anthropic.APIError, ValueError) as e:
            log.warning("rerank failed: %s", e)
            return None
        return resp.parsed_output


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

FORBIDDEN_CLAIMS = re.compile(
    r"\b(dispatched|booked|scheduled|appointment (is|has been) (set|confirmed)|has been (contacted|notified|sent)|"
    r"(will|is going to) (arrive|come|be there)|on (their|the) way|guarantee\w*)\b",
    re.I,
)
PHONE_IN_TEXT = re.compile(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
URL_IN_TEXT = re.compile(r"https?://[^\s)]+|www\.[^\s)]+", re.I)


def guardrail_violations(text: str, allowed_phones: set[str], allowed_urls: set[str], provisional: bool) -> list[str]:
    issues = []
    if FORBIDDEN_CLAIMS.search(text):
        issues.append("forbidden claim")
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
