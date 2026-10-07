"""Core domain model: supported scope, LeadState, and the structured shapes
that flow between the LLM layer and the deterministic orchestrator."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Category(StrEnum):
    WATER_DAMAGE = "water_damage_restoration"
    PLUMBING = "plumbing"
    ROOFING = "roofing"
    HVAC = "hvac"
    ELECTRICAL = "electrical"


CATEGORY_LABELS = {
    Category.WATER_DAMAGE: "Water Damage Restoration",
    Category.PLUMBING: "Plumbing",
    Category.ROOFING: "Roofing",
    Category.HVAC: "HVAC (Heating & Cooling)",
    Category.ELECTRICAL: "Electrical",
}


class Outcome(StrEnum):
    READY_TO_DISPATCH = "ready_to_dispatch"
    SELF_SERVE = "self_serve"
    NO_MATCH = "no_match"
    UNSUPPORTED_CATEGORY = "unsupported_category"
    SAFETY_REDIRECT = "safety_redirect"
    ABANDONED = "abandoned"


TERMINAL_OUTCOMES = {
    Outcome.READY_TO_DISPATCH,
    Outcome.SELF_SERVE,
    Outcome.NO_MATCH,
    Outcome.UNSUPPORTED_CATEGORY,
    Outcome.SAFETY_REDIRECT,
}

# Pilot geography. Provider coverage in the dataset is recorded per area,
# so every supported ZIP maps to exactly one area.
PILOT_AREAS = {
    "santa_clara": "Santa Clara",
    "sunnyvale": "Sunnyvale",
    "north_san_jose": "North San Jose",
}
PILOT_ZIPS = {
    "95050": "santa_clara",
    "95051": "santa_clara",
    "95053": "santa_clara",
    "95054": "santa_clara",
    "94085": "sunnyvale",
    "94086": "sunnyvale",
    "94087": "sunnyvale",
    "94089": "sunnyvale",
    "95131": "north_san_jose",
    "95134": "north_san_jose",
}
# City names users commonly type. North San Jose is not a city, so a bare
# "San Jose" without a pilot ZIP still needs a ZIP to decide coverage.
PILOT_CITIES = {"santa clara": "santa_clara", "sunnyvale": "sunnyvale"}

# Category-specific facts that block dispatch. Kept deliberately small:
# only facts that change provider fit or urgency.
BLOCKING_QUALIFICATION = {
    Category.WATER_DAMAGE: ["water_still_active"],
    Category.PLUMBING: [],
    Category.ROOFING: ["active_leak"],
    Category.HVAC: [],
    Category.ELECTRICAL: ["hazard_present"],
}
QUALIFICATION_FIELDS = {"water_still_active", "likely_source", "active_leak", "hazard_present"}

Urgency = Literal["emergency", "same_day", "within_week", "flexible"]
ContactMethod = Literal["phone", "email"]
LikelySource = Literal["storm_exterior", "plumbing", "unknown"]
PropertyRelationship = Literal["homeowner", "tenant", "property_manager", "other"]
QuestionTopic = Literal[
    "why_this_provider", "price", "reviews", "availability", "hours_or_24_7", "distance", "license_or_insurance",
    "why_need_info", "data_privacy", "is_this_a_person", "sponsorship", "request_status", "other",
]
InfoField = Literal[
    "zip_or_address", "phone", "name", "timing", "water_still_active", "active_leak", "hazard_present", "consent", "other",
]
RequestedAction = Literal["call_provider", "book_appointment", "send_now", "guarantee", "other"]


class ServiceDetails(BaseModel):
    water_still_active: bool | None = None
    likely_source: LikelySource | None = None
    active_leak: bool | None = None
    hazard_present: bool | None = None


class LeadState(BaseModel):
    """Structured source of truth for one conversation."""

    conversation_id: str

    # Problem
    service_category: Category | None = None
    candidate_categories: list[Category] = Field(default_factory=list)
    category_confirmed: bool = False
    unsupported_service: str | None = None
    issue_summary: str | None = None
    service_details: ServiceDetails = Field(default_factory=ServiceDetails)
    secondary_issues: list[str] = Field(default_factory=list)

    # Location
    street_address: str | None = None
    city: str | None = None
    zip_code: str | None = None
    pilot_area: str | None = None

    # Timing
    urgency: Urgency | None = None
    preferred_time: str | None = None

    # Customer
    customer_name: str | None = None
    property_relationship: PropertyRelationship | None = None
    contact_method: ContactMethod | None = None
    contact_value: str | None = None
    consent_to_share: bool | None = None

    # Enrichment
    insurance_intent: str | None = None

    # Safety
    safety_flags: list[str] = Field(default_factory=list)
    safety_guidance_given: bool = False

    # Matching (candidate_provider_ids is kept in ranked order)
    candidate_provider_ids: list[str] = Field(default_factory=list)
    excluded_provider_ids: list[str] = Field(default_factory=list)  # rejected by the user; never re-offered
    shown_provider_ids: list[str] = Field(default_factory=list)  # offered, then user asked for another
    provider_feedback: dict[str, str] = Field(default_factory=dict)
    selected_provider_id: str | None = None
    selected_provider_coverage: str | None = None
    alternative_provider_id: str | None = None
    match_reason: str | None = None

    # Funnel bookkeeping
    last_question_field: str | None = None
    last_agent_message: str | None = None
    asked_fields: list[str] = Field(default_factory=list)
    declined_fields: list[str] = Field(default_factory=list)
    user_turns: int = 0
    corrections_seen: int = 0
    category_changes: int = 0
    extraction_failures: int = 0

    # Outcome
    missing_blocking_fields: list[str] = Field(default_factory=list)
    outcome: Outcome | None = None

    @property
    def address_status(self) -> Literal["complete", "pending"]:
        return "complete" if self.street_address else "pending"


# ---------- LLM extraction contract ----------


class ExtractedFields(BaseModel):
    """Facts the user stated or clearly implied in the latest message.
    Every field is optional; null means 'not mentioned in this message'."""

    service_category: Category | None = Field(
        default=None,
        description="Best supported category for the primary issue; null if unclear or outside the five categories.",
    )
    candidate_categories: list[Category] = Field(
        default_factory=list, description="All plausible categories when the cause is ambiguous."
    )
    needs_clarification: bool = Field(
        default=False, description="True if the category cannot be chosen without asking the user."
    )
    clarification_reason: str | None = None
    unsupported_service: str | None = Field(
        default=None, description="Set (e.g. 'pest control') only when the job is outside all five categories."
    )
    issue_summary: str | None = Field(
        default=None, description="One provider-facing sentence describing the problem, using only stated facts."
    )
    secondary_issues: list[str] = Field(default_factory=list)
    street_address: str | None = None
    city: str | None = None
    zip_code: str | None = None
    urgency: Urgency | None = None
    preferred_time: str | None = None
    customer_name: str | None = None
    property_relationship: PropertyRelationship | None = None
    contact_method: ContactMethod | None = None
    contact_value: str | None = None
    consent_to_share: bool | None = Field(
        default=None, description="Only true/false when the user answered the explicit sharing-consent question."
    )
    insurance_intent: str | None = None
    water_still_active: bool | None = None
    likely_source: LikelySource | None = None
    active_leak: bool | None = None
    hazard_present: bool | None = None
    provider_feedback: Literal["reject", "want_alternative"] | None = Field(
        default=None, description="User rejects the recommended provider, or asks for other options."
    )
    provider_feedback_reason: str | None = None
    question_topic: QuestionTopic | None = Field(default=None, description="What the user asked about, if anything.")
    question_info_field: InfoField | None = None
    requested_action: RequestedAction | None = Field(
        default=None, description="Something the user asked the system to do that it cannot (call, book, ...)."
    )
    unknown_facts: list[str] = Field(
        default_factory=list, description="Qualification facts the user said they cannot confirm."
    )
    declined_fields: list[str] = Field(
        default_factory=list,
        description="Fields the user explicitly declined to give, e.g. 'street_address', 'contact'.",
    )


class ExtractionResult(BaseModel):
    updates: ExtractedFields = Field(default_factory=ExtractedFields)
    corrections: list[str] = Field(
        default_factory=list, description="Fields the user explicitly changed versus earlier answers."
    )


# ---------- Orchestrator decisions ----------

ActionType = Literal[
    "safety_redirect",
    "ask_category",
    "clarify_category",
    "unsupported_category",
    "ask_location",
    "out_of_area",
    "ask_qualification",
    "match_provider",
    "no_match",
    "present_provider_ask_timing",
    "ask_timing",
    "ask_address",
    "ask_contact",
    "ask_consent",
    "lead_ready",
    "self_serve",
    "already_closed",
]


class NextAction(BaseModel):
    type: ActionType
    field: str | None = None
    note: str | None = None


class Provider(BaseModel):
    id: str
    name: str
    service_categories: list[Category]
    address: str | None = None
    city: str | None = None
    zip_code: str | None = None
    phone: str
    website: str
    coverage: dict[str, str]
    coverage_evidence: str
    emergency_service: bool | None = None
    source_url: str
    source_type: str | None = None
    implementation_note: str | None = None
    verified_at: str | None = None


class ValidationResult(BaseModel):
    valid: bool
    missing_fields: list[str]
    errors: list[str]
    quality_score: float
    quality_breakdown: dict[str, float]
