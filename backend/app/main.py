import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import conversations
from app.config import settings
from app.db import init_db
from app.domain import CATEGORY_LABELS, PILOT_AREAS, PILOT_ZIPS
from app.services.lead_packet import URGENCY_LABELS, render_text
from app.services.llm import get_llm
from app.services.provider_search import load_providers

app = FastAPI(title="NearbyAI — Home Service Lead Agent")
llm = get_llm()
init_db()

RATE_LIMIT = 30  # messages per IP per 10 minutes
_hits: dict[str, deque] = defaultdict(deque)


def guard(request: Request, x_demo_code: str | None = Header(default=None)) -> None:
    if settings.demo_access_code and x_demo_code != settings.demo_access_code:
        raise HTTPException(401, "Demo access code required")
    ip = request.client.host if request.client else "unknown"
    now, window = time.time(), _hits[ip]
    while window and now - window[0] > 600:
        window.popleft()
    if len(window) >= RATE_LIMIT:
        raise HTTPException(429, "Too many messages; please wait a few minutes")
    window.append(now)


class MessageIn(BaseModel):
    # Generous limit: long messages are trimmed by the agent rather than rejected.
    content: str = Field(default="", max_length=20000)


@app.get("/health")
def health():
    return {"status": "ok", "llm_backend": llm.name, "providers": len(load_providers())}


@app.post("/api/conversations", dependencies=[Depends(guard)])
def create_conversation():
    conv = conversations.start_conversation(llm)
    return {"conversation_id": conv.id, "message": conversations.GREETING}


@app.post("/api/conversations/{conversation_id}/messages", dependencies=[Depends(guard)])
def post_message(conversation_id: str, body: MessageIn):
    try:
        result, lead_id = conversations.send_message(conversation_id, body.content.strip(), llm)
    except KeyError:
        raise HTTPException(404, "conversation not found")
    s = result.state
    return {
        "message": result.message,
        "action": result.action.type,
        "outcome": s.outcome,
        "dispatchable": lead_id is not None,
        "lead_withdrawn": result.lead_withdrawn,
        "lead_id": lead_id,
        "lead": result.lead,
        "lead_text": render_text(result.lead) if result.lead else None,
        "provider": _provider_card(result.provider, s.selected_provider_coverage) if result.provider else None,
        "alternative_provider": _provider_card(result.alternative, s.selected_provider_coverage)
        # One alternative at most, only when it helps: coverage unconfirmed, or the user is self-serving.
        if result.alternative and (s.selected_provider_coverage == "provisional" or s.outcome == "self_serve")
        else None,
        "progress": {
            "service_category": s.service_category,
            "service_label": CATEGORY_LABELS.get(s.service_category) if s.service_category else None,
            "area_label": PILOT_AREAS.get(s.pilot_area) if s.pilot_area else None,
            "urgency_label": URGENCY_LABELS.get(s.urgency) if s.urgency else s.preferred_time,
            "zip_code": s.zip_code,
            "address_status": s.address_status,
            "urgency": s.urgency,
            "has_contact": bool(s.customer_name and s.contact_value),
            "consent": s.consent_to_share,
            "user_turns": s.user_turns,
        },
    }


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str):
    return {"messages": conversations.get_transcript(conversation_id)}


@app.get("/api/leads/{lead_id}")
def get_lead(lead_id: str):
    lead = conversations.get_lead(lead_id)
    if lead is None:
        raise HTTPException(404, "lead not found")
    return {"id": lead.id, "packet": lead.packet, "text": render_text(lead.packet)}


@app.get("/api/providers")
def list_providers():
    return {
        "pilot_areas": PILOT_AREAS,
        "pilot_zips": PILOT_ZIPS,
        "providers": [p.model_dump() for p in load_providers().values()],
    }


def _provider_card(p, coverage: str | None) -> dict:
    return {
        "name": p.name,
        "phone": p.phone,
        "website": p.website,
        "address": p.address,
        "coverage": coverage,
        "source_url": p.source_url,
    }


# Serve the static frontend from the same process (one deployable unit, no CORS).
FRONTEND_INDEX = Path(settings.frontend_dir) / "index.html"


@app.get("/", include_in_schema=False)
def index():
    if not FRONTEND_INDEX.exists():
        raise HTTPException(404, "frontend not found")
    return FileResponse(FRONTEND_INDEX)
