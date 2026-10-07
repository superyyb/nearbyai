"""Test helpers.

ScriptedLLM lets conversation-level tests say "the extractor understood X this
turn" and assert the resulting state transition. That separates orchestration
correctness (deterministic, free) from language understanding (tested against
Claude with intent probes).
"""

import typing

from app.domain import ExtractedFields, ExtractionResult, LeadState
from app.services.agent import handle_turn
from app.services.llm import LLMExtraction


def wire_defaults(**overrides) -> LLMExtraction:
    """An LLMExtraction where nothing was mentioned, plus overrides."""
    values = {}
    for name, field in LLMExtraction.model_fields.items():
        ann = field.annotation
        origin = typing.get_origin(ann)
        if origin is list:
            values[name] = []
        elif ann is bool:
            values[name] = False
        elif origin is typing.Literal:
            args = typing.get_args(ann)
            values[name] = next(a for a in ("none", "not_mentioned", "not_answered") if a in args)
        else:
            values[name] = ""
    values.update(overrides)
    return LLMExtraction(**values)


class ScriptedLLM:
    """Returns one scripted extraction per turn: a dict of ExtractedFields values, optionally with 'corrections'."""

    name = "scripted"

    def __init__(self, turns: list[dict]):
        self.turns = list(turns)

    def extract(self, state: LeadState, message: str, last_question_field: str | None) -> ExtractionResult:
        spec = dict(self.turns.pop(0)) if self.turns else {}
        corrections = spec.pop("corrections", [])
        return ExtractionResult(updates=ExtractedFields(**spec), corrections=corrections)


def converse(turns: list[tuple[str, dict]], state: LeadState | None = None):
    """Run (message, extraction) pairs through the real orchestrator. Returns (state, results)."""
    state = state or LeadState(conversation_id="scripted")
    llm = ScriptedLLM([extraction for _, extraction in turns])
    history, results = [], []
    for message, _ in turns:
        results.append(handle_turn(state, message, llm, history))
        history.append(message)
    return state, results


# Common extraction payloads
AC_ISSUE = {"service_category": "hvac", "issue_summary": "AC runs but blows warm air"}
SANTA_CLARA = {"city": "Santa Clara"}
