"""Conversation service: load state, run one turn, persist everything."""

from sqlalchemy import select

from app.db import Conversation, EvalCandidate, Lead, Message, SessionLocal
from app.domain import LeadState
from app.services.agent import TurnResult, handle_turn
from app.services.candidates import candidate_reasons

GREETING = (
    "Hi! Tell me what's going on at your home and I'll help you find the right local pro. "
    "(Demo: please use test contact info.)"
)


def start_conversation(llm, source: str = "web") -> Conversation:
    with SessionLocal() as db:
        conv = Conversation(lead_state={}, llm_backend=llm.name, source=source)
        db.add(conv)
        db.flush()
        conv.lead_state = LeadState(conversation_id=conv.id).model_dump(mode="json")
        db.add(Message(conversation_id=conv.id, role="assistant", content=GREETING))
        db.commit()
        return conv


def send_message(conversation_id: str, text: str, llm) -> tuple[TurnResult, str | None]:
    with SessionLocal() as db:
        conv = db.get(Conversation, conversation_id)
        if conv is None:
            raise KeyError(conversation_id)
        state = LeadState.model_validate(conv.lead_state)
        history = list(
            db.scalars(
                select(Message.content).where(Message.conversation_id == conv.id, Message.role == "user").order_by(Message.id)
            )
        )
        result = handle_turn(state, text, llm, history)

        db.add(Message(conversation_id=conv.id, role="user", content=text))
        db.add(
            Message(
                conversation_id=conv.id,
                role="assistant",
                content=result.message,
                action=result.action.type,
                events=result.events,
                wording_source=result.wording_source,
            )
        )
        lead_id = None
        if result.lead:
            lead = Lead(
                conversation_id=conv.id,
                provider_id=state.selected_provider_id,
                packet=result.lead,
                quality_score=result.lead["quality_score"],
            )
            db.add(lead)
            db.flush()
            lead_id = lead.id
        conv.lead_state = state.model_dump(mode="json")
        conv.outcome = state.outcome.value if state.outcome else None

        rejections = sum(
            1
            for events in db.scalars(select(Message.events).where(Message.conversation_id == conv.id))
            for e in (events or [])
            if e.startswith("writer_rejected")
        ) + sum(e.startswith("writer_rejected") for e in result.events)
        reasons = candidate_reasons(state, rejections)
        existing = db.scalar(select(EvalCandidate).where(EvalCandidate.conversation_id == conv.id))
        if reasons and existing is None:
            db.add(EvalCandidate(conversation_id=conv.id, reasons=reasons))
        elif existing is not None:
            existing.reasons = reasons
        db.commit()
        return result, lead_id


def get_lead(lead_id: str) -> Lead | None:
    with SessionLocal() as db:
        return db.get(Lead, lead_id)


def get_transcript(conversation_id: str) -> list[dict]:
    with SessionLocal() as db:
        rows = db.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id))
        return [{"role": m.role, "content": m.content, "action": m.action} for m in rows]
