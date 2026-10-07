"""Hard-eligibility provider search with verified-first tiering.

    verified candidates exist      -> only verified are eligible
    else provisional candidates    -> provisional eligible, labeled unconfirmed
    else                           -> no match
'unknown' and 'out_of_area' are never auto-matched.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import settings
from app.domain import Category, Provider


@dataclass
class SearchResult:
    tier: str | None  # "verified" | "provisional" | None
    candidates: list[Provider]


@lru_cache
def load_providers(path: str | None = None) -> dict[str, Provider]:
    raw = json.loads(Path(path or settings.providers_path).read_text())
    providers = [Provider.model_validate(p) for p in raw]
    return {p.id: p for p in providers}


def get_provider(provider_id: str) -> Provider | None:
    return load_providers().get(provider_id)


def search(category: Category, pilot_area: str, providers: dict[str, Provider] | None = None) -> SearchResult:
    pool = providers if providers is not None else load_providers()
    in_category = [p for p in pool.values() if category in p.service_categories]
    for tier in ("verified", "provisional"):
        matches = [p for p in in_category if p.coverage.get(pilot_area) == tier]
        if matches:
            return SearchResult(tier=tier, candidates=sorted(matches, key=lambda p: p.id))
    return SearchResult(tier=None, candidates=[])


def search_tier(category: Category, pilot_area: str, tier: str) -> list[Provider]:
    return sorted(
        (p for p in load_providers().values() if category in p.service_categories and p.coverage.get(pilot_area) == tier),
        key=lambda p: p.id,
    )


# Trade words appear in many provider names, so they can't identify one provider on their own.
_GENERIC_TOKENS = {
    "the", "and", "of", "inc", "llc", "co", "company", "services", "service", "group", "guys",
    "heating", "air", "conditioning", "plumbing", "plumbers", "plumber", "rooter", "rooters", "roofing", "roof",
    "electric", "electrical", "electrician", "restoration", "hvac", "mechanical", "construction", "exterior",
    "water", "damage", "cleanup", "home", "refrigeration", "waterproofing", "san", "jose", "santa", "clara",
}


def _tokens(text: str) -> set[str]:
    import re

    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _GENERIC_TOKENS}


def find_by_name(name: str) -> Provider | None:
    """Best provider whose distinctive name tokens overlap the user's wording ("DG", "the EVS guys")."""
    wanted = _tokens(name)
    best, best_score = None, 0.0
    for p in load_providers().values():
        name_tokens = _tokens(p.name)
        overlap = wanted & name_tokens
        if not overlap:
            continue
        # The first distinctive token ("dg", "evs", "promax") is the strongest signal.
        first = next((t for t in _tokens(p.name.split()[0])), None)
        score = len(overlap) / len(name_tokens) + (1.0 if first in overlap else 0.0)
        if score > best_score:
            best, best_score = p, score
    return best if best_score >= 0.5 else None


def coverage_matrix(providers: dict[str, Provider] | None = None) -> dict[tuple[str, str], dict[str, int]]:
    """(category, area) -> counts per coverage status. Used as a data-quality acceptance check."""
    from app.domain import PILOT_AREAS

    pool = providers if providers is not None else load_providers()
    out: dict[tuple[str, str], dict[str, int]] = {}
    for cat in Category:
        for area in PILOT_AREAS:
            counts: dict[str, int] = {}
            for p in pool.values():
                if cat in p.service_categories:
                    status = p.coverage.get(area, "unknown")
                    counts[status] = counts.get(status, 0) + 1
            out[(cat.value, area)] = counts
    return out
