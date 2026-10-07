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
