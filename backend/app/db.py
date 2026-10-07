"""Persistence: conversations (with LeadState), messages, leads, eval candidates.
Providers are read from data/providers.json (version-controlled source of truth)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import settings


def _now() -> datetime:
    return datetime.now(UTC)


def _id() -> str:
    return uuid.uuid4().hex[:12]


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    lead_state: Mapped[dict] = mapped_column(JSON)
    llm_backend: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String, default="web")  # web | eval
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String)  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    action: Mapped[str | None] = mapped_column(String, nullable=True)
    events: Mapped[list] = mapped_column(JSON, default=list)
    wording_source: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    provider_id: Mapped[str] = mapped_column(String)
    packet: Mapped[dict] = mapped_column(JSON)
    quality_score: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String, default="ready_to_dispatch")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EvalCandidate(Base):
    __tablename__ = "eval_candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), unique=True)
    reasons: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


engine = create_engine(settings.database_url, connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
