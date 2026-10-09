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
    UTILITY_REDIRECT = "utility_redirect"
    ABANDONED = "abandoned"


TERMINAL_OUTCOMES = {
    Outcome.READY_TO_DISPATCH,
    Outcome.SELF_SERVE,
    Outcome.NO_MATCH,
    Outcome.UNSUPPORTED_CATEGORY,
    Outcome.SAFETY_REDIRECT,
    Outcome.UTILITY_REDIRECT,
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
# The day the user wants the visit. "other" = a period code doesn't turn into a date ("this weekend").
PreferredDay = Literal[
    "today", "tomorrow", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "other"
]
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
ProviderFeedback = Literal["reject", "want_alternative", "show_options", "choose_named", "accept_offer", "decline_offer"]
RequestedAction = Literal["call_provider", "book_appointment", "send_now", "guarantee", "unclear"]
EditField = Literal["street_address", "zip_code", "phone", "name", "timing", "issue"]
EditKind = Literal["wants_change", "current_value_wrong"]


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
    secondary_issues: list[str] = Field(default_factory=list)  # unrelated problems needing a separate job
    observed_impacts: list[str] = Field(default_factory=list)  # damage caused by the main problem

    # Location
    street_address: str | None = None
    city: str | None = None
    zip_code: str | None = None
    pilot_area: str | None = None

    # Timing
    urgency: Urgency | None = None
    preferred_time: str | None = None  # the user's own words, e.g. "this afternoon after 2pm"
    preferred_day: PreferredDay | None = None
    preferred_window: str | None = None  # e.g. "after 2 PM", "morning"
    preferred_date: str | None = None  # ISO date resolved by code from preferred_day when it was said

    # Customer
    customer_name: str | None = None
    property_relationship: PropertyRelationship | None = None
    contact_method: ContactMethod | None = None
    contact_value: str | None = None
    contact_preferences: str | None = None  # e.g. "calls only, after 5pm", "wife's number"
    consent_to_share: bool | None = None

    # Enrichment
    insurance_intent: str | None = None

    # Possible utility outage (water / power): a contractor can't fix an area-wide outage
    utility_signal: Literal["water", "power"] | None = None
    outage_scope: Literal["home_only", "neighbors_affected", "unknown"] | None = None

    # Safety
    safety_flags: list[str] = Field(default_factory=list)
    safety_guidance_given: bool = False
    mitigation_given: list[str] = Field(default_factory=list)  # fixed damage-limiting tips already shown

    # Matching (candidate_provider_ids is kept in ranked order)
    candidate_provider_ids: list[str] = Field(default_factory=list)
    excluded_provider_ids: list[str] = Field(default_factory=list)  # rejected by the user; never re-offered
    shown_provider_ids: list[str] = Field(default_factory=list)  # offered, then user asked for another
    provider_feedback: dict[str, str] = Field(default_factory=dict)
    offered_provider_id: str | None = None  # provisional provider offered after verified ones were exhausted
    selected_provider_id: str | None = None
    selected_provider_coverage: str | None = None
    alternative_provider_id: str | None = None
    match_reason: str | None = None

    # Funnel bookkeeping
    last_question_field: str | None = None
    pending_edit: str | None = None  # field the user wants to change; the new value hasn't arrived yet
    invalid_field: str | None = None  # phone / email / zip_code the user typed but that failed validation
    invalid_raw: str | None = None
    invalid_turn: int = 0
    invalid_attempts: dict[str, int] = Field(default_factory=dict)
    pending_edit_turn: int = 0
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
    suggested_question: str | None = Field(
        default=None, description="One targeted question, in the user's terms, that resolves the open decision."
    )
    unsupported_service: str | None = Field(
        default=None, description="Set (e.g. 'pest control') only when the job is outside all five categories."
    )
    issue_summary: str | None = Field(
        default=None, description="One provider-facing sentence describing the problem, using only stated facts."
    )
    secondary_issues: list[str] = Field(
        default_factory=list, description="Unrelated problems that would need a separate job."
    )
    observed_impacts: list[str] = Field(
        default_factory=list, description="Damage caused by the main problem (e.g. 'ceiling stained')."
    )
    street_address: str | None = None
    city: str | None = None
    zip_code: str | None = None
    urgency: Urgency | None = None
    preferred_time: str | None = None
    preferred_day: PreferredDay | None = None
    preferred_window: str | None = None
    customer_name: str | None = None
    property_relationship: PropertyRelationship | None = None
    contact_method: ContactMethod | None = None
    contact_value: str | None = None
    contact_preferences: str | None = Field(
        default=None, description="How/when to contact, or whose number it is (e.g. 'calls only', 'wife's number')."
    )
    consent_to_share: bool | None = Field(
        default=None, description="Only true/false when the user answered the explicit sharing-consent question."
    )
    insurance_intent: str | None = None
    water_still_active: bool | None = None
    likely_source: LikelySource | None = None
    active_leak: bool | None = None
    hazard_present: bool | None = None
    provider_feedback: ProviderFeedback | None = Field(
        default=None, description="What the user wants regarding the recommended provider."
    )
    named_provider: str | None = Field(default=None, description="Provider the user named, if any.")
    provider_feedback_reason: str | None = None
    question_topics: list[QuestionTopic] = Field(
        default_factory=list, description="Every question the user asked in this message, in order."
    )
    question_info_field: InfoField | None = None
    edit_field: EditField | None = Field(
        default=None, description="A detail the user wants to change without giving the new value yet."
    )
    edit_kind: EditKind | None = None
    requested_action: RequestedAction | None = Field(
        default=None, description="Something the user asked the system to do that it cannot (call, book, ...)."
    )
    utility_signal: Literal["water", "power"] | None = Field(
        default=None, description="The whole home has no water / no power, which could be a utility outage."
    )
    hazard_categories: list[str] = Field(default_factory=list, description="Safety hazard families the user describes.")
    hazard_evidence: str | None = None
    outage_scope: Literal["home_only", "neighbors_affected", "unknown"] | None = None
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
    "clarify_outage",
    "utility_redirect",
    "ask_location",
    "out_of_area",
    "ask_qualification",
    "match_provider",
    "present_options",
    "ask_edit",
    "ask_correction",
    "offer_provisional",
    "no_match",
    "present_provider_ask_timing",
    "ask_timing",
    "ask_address",
    "ask_contact",
    "ask_consent",
    "lead_ready",
    "self_serve",
    "already_closed",
    "empty_input",
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
    completeness_score: float  # required/useful fields present; not a judgment of lead quality
    completeness_breakdown: dict[str, float]
