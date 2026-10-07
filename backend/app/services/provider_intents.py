"""User intent about providers. Handled before the normal funnel, because what the
user just said about a provider outranks the next missing field.

  reject          -> exclude that provider for the rest of the conversation; next ranked one
  want_alternative-> next ranked one; the current one stays eligible (not rejected)
  show_options    -> list the remaining eligible providers and let the user choose
  choose_named    -> select a named provider only if it is eligible for this job and area
                     (an explicit choice also restores a previously rejected provider)
  accept/decline  -> answer to a provisional offer made after verified providers ran out

Verified providers always come first. Provisional ones are only used after the user
explicitly accepts an offer that says their coverage is unconfirmed.
"""

from dataclasses import dataclass, field

from app.domain import CATEGORY_LABELS, PILOT_AREAS, LeadState, NextAction, Provider
from app.services.matching import switch_provider
from app.services.provider_search import find_by_name, get_provider, load_providers, search_tier

MAX_OPTIONS_SHOWN = 3


@dataclass
class IntentResult:
    prefix: str | None = None
    action: NextAction | None = None  # overrides the funnel's next action for this turn
    all_rejected: bool = False
    events: list[str] = field(default_factory=list)


def _label(state: LeadState) -> str:
    return CATEGORY_LABELS[state.service_category].lower()


def _area(state: LeadState) -> str:
    return PILOT_AREAS.get(state.pilot_area or "", "your area")


def _reset_consent(state: LeadState) -> None:
    # Consent was given for a specific provider; it does not carry over.
    state.consent_to_share = None
    state.asked_fields = [f for f in state.asked_fields if f != "consent"]


def _set_selected(state: LeadState, provider: Provider, coverage: str) -> None:
    if state.selected_provider_id != provider.id:
        _reset_consent(state)
    state.selected_provider_id = provider.id
    state.selected_provider_coverage = coverage
    state.match_reason = "chosen by the user"
    if provider.id in state.excluded_provider_ids:
        state.excluded_provider_ids.remove(provider.id)
    if provider.id in state.shown_provider_ids:
        state.shown_provider_ids.remove(provider.id)
    if provider.id not in state.candidate_provider_ids:
        state.candidate_provider_ids.insert(0, provider.id)
    remaining = [i for i in state.candidate_provider_ids if i != provider.id and i not in state.excluded_provider_ids]
    state.alternative_provider_id = remaining[0] if remaining else None


def _resolve_named(state: LeadState, name: str) -> Provider | None:
    """Prefer providers relevant to this job/area (two SERVPRO franchises exist), then any provider."""
    relevant = {pid: load_providers()[pid] for pid in state.candidate_provider_ids if pid in load_providers()}
    if state.service_category and state.pilot_area:
        for tier in ("verified", "provisional"):
            relevant.update({p.id: p for p in search_tier(state.service_category, state.pilot_area, tier)})
    match = find_by_name(name)
    if match is None:
        return None
    if match.id in relevant:
        return match
    # A same-brand provider that is relevant beats an unrelated one with the same name.
    brand = match.name.lower().split()[0]
    return next((p for p in relevant.values() if p.name.lower().split()[0] == brand), match)


def _offer_provisional(state: LeadState, rejected: Provider | None) -> IntentResult | None:
    options = [p for p in search_tier(state.service_category, state.pilot_area, "provisional")
               if p.id not in state.excluded_provider_ids]
    if not options:
        return None
    offer = options[0]
    state.offered_provider_id = offer.id
    opener = f"Understood — I won't use {rejected.name}. " if rejected else ""
    return IntentResult(
        prefix=None,
        action=NextAction(
            type="offer_provisional",
            field="provisional_offer",
            note=(f"{opener}I don't have another verified {_label(state)} provider for {_area(state)}. "
                  f"{offer.name} is located near you, but I haven't confirmed they serve {_area(state)}. "
                  "Would you like me to use them?"),
        ),
        events=[f"offered_provisional:{offer.id}"],
    )


def reoffer(state: LeadState) -> IntentResult | None:
    """Repeat a pending provisional offer the user didn't answer."""
    state.offered_provider_id = None
    return _offer_provisional(state, None)


def handle(state: LeadState, up) -> IntentResult | None:
    """Apply the user's provider intent to state. Returns None when there is nothing to do."""
    feedback = up.provider_feedback
    if not feedback:
        return None

    # --- answer to a provisional offer ---
    if state.offered_provider_id and feedback in ("accept_offer", "decline_offer", "reject"):
        offer = get_provider(state.offered_provider_id)
        state.offered_provider_id = None
        if feedback == "accept_offer":
            state.candidate_provider_ids = [offer.id]
            _set_selected(state, offer, "provisional")
            return IntentResult(prefix=f"Okay — I'll use {offer.name}; they'll need to confirm they cover your area.",
                                events=[f"accepted_provisional:{offer.id}"])
        state.excluded_provider_ids.append(offer.id)
        return IntentResult(all_rejected=True, events=[f"declined_provisional:{offer.id}"])

    if state.service_category is None or state.pilot_area is None:
        return None  # nothing has been matched yet; the funnel will get there

    # --- explicit choice of a named provider ---
    if feedback == "choose_named" and up.named_provider:
        named = _resolve_named(state, up.named_provider)
        if named is None:
            return IntentResult(prefix=(f"I don't have {up.named_provider} in my verified list, so I can't prepare "
                                        "a request for them."), events=["named_provider_unknown"])
        coverage = named.coverage.get(state.pilot_area, "unknown")
        if state.service_category not in named.service_categories or coverage not in ("verified", "provisional"):
            return IntentResult(
                prefix=(f"I can't confirm that {named.name} handles {_label(state)} in {_area(state)}, so I can't "
                        f"send the request to them. You can contact them directly at {named.phone}."),
                events=[f"named_provider_ineligible:{named.id}"])
        _set_selected(state, named, coverage)
        note = "" if coverage == "verified" else " Their coverage for your area is unconfirmed, so they'll need to confirm it."
        return IntentResult(prefix=f"Sure — I'll use {named.name}.{note}", events=[f"chose_named:{named.id}"])

    if state.selected_provider_id is None:
        return None

    # --- list the options ---
    if feedback == "show_options":
        ids = [i for i in state.candidate_provider_ids if i not in state.excluded_provider_ids][:MAX_OPTIONS_SHOWN]
        providers = [get_provider(i) for i in ids]
        listing = "; ".join(f"{p.name} ({p.phone})" for p in providers)
        tier = "verified" if state.selected_provider_coverage == "verified" else "nearby (coverage unconfirmed)"
        return IntentResult(
            action=NextAction(type="present_options", field="named_provider",
                              note=f"Here are the {tier} {_label(state)} options I have for {_area(state)}: {listing}. "
                                   "Which one would you like?"),
            events=[f"showed_options:{','.join(ids)}"])

    # --- reject (named or current) / want another ---
    if feedback in ("reject", "want_alternative"):
        if feedback == "reject" and up.named_provider:
            named = _resolve_named(state, up.named_provider)
            if named and named.id != state.selected_provider_id:
                if named.id not in state.excluded_provider_ids:
                    state.excluded_provider_ids.append(named.id)
                state.provider_feedback[named.id] = up.provider_feedback_reason or "rejected by user"
                return IntentResult(prefix=f"Noted — I won't use {named.name}.", events=[f"excluded:{named.id}"])
        previous_id = switch_provider(state, feedback, up.provider_feedback_reason)
        previous = get_provider(previous_id)
        events = [f"provider_feedback:{feedback}:{previous_id}->{state.selected_provider_id}"]
        if state.selected_provider_id is None:
            offer = _offer_provisional(state, previous) if state.selected_provider_coverage == "verified" else None
            if offer:
                offer.events = events + offer.events
                return offer
            return IntentResult(all_rejected=True, events=events)
        if state.selected_provider_id == previous_id:
            return IntentResult(prefix=no_other_option(state, previous), events=events)
        new = get_provider(state.selected_provider_id)
        return IntentResult(prefix=provider_switched(state, previous, new, feedback), events=events)
    return None


def provider_switched(state: LeadState, previous: Provider, new: Provider, feedback: str) -> str:
    opener = f"Understood — I won't use {previous.name}." if feedback == "reject" else "Sure."
    if state.selected_provider_coverage == "verified":
        return f"{opener} Another option is {new.name}, which also lists {_area(state)} in its service area."
    return f"{opener} Another option is {new.name}, located near you; its coverage for {_area(state)} still needs to be confirmed."


def no_other_option(state: LeadState, current: Provider) -> str:
    return f"I don't have another verified {_label(state)} provider for your area, so {current.name} is still my best match."
