"""In-process telemetry for every Claude call and every deterministic fallback.

Each LLM responsibility (extraction, response, rerank, simulator, judge) is
recorded separately so cost and latency can be reported per responsibility.
Fallback counters make it visible when deterministic code covered for the model.
"""

import logging
import time
from collections import Counter
from dataclasses import dataclass

log = logging.getLogger(__name__)

# USD per million tokens (input, output, cache read), list prices.
PRICES = {
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-haiku-4-5": (1.00, 5.00, 0.10),
}


@dataclass
class CallRecord:
    call_type: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    latency_ms: float
    ok: bool
    server_fallback_used: bool

    @property
    def cost_usd(self) -> float:
        p_in, p_out, p_cache = PRICES.get(self.model, (0.0, 0.0, 0.0))
        return (self.input_tokens * p_in + self.output_tokens * p_out + self.cache_read_tokens * p_cache) / 1e6


class Telemetry:
    def __init__(self) -> None:
        self.calls: list[CallRecord] = []
        self.fallbacks: Counter = Counter()

    def reset(self) -> None:
        self.calls.clear()
        self.fallbacks.clear()

    def track(self, call_type: str, model: str, fn, **kwargs):
        """Run one SDK call, recording usage and latency whether it succeeds or not."""
        start = time.perf_counter()
        try:
            resp = fn(model=model, **kwargs)
        except Exception:
            self.calls.append(CallRecord(call_type, model, 0, 0, 0, (time.perf_counter() - start) * 1000, False, False))
            raise
        usage = getattr(resp, "usage", None)
        iterations = getattr(usage, "iterations", None) or []
        record = CallRecord(
            call_type=call_type,
            model=getattr(resp, "model", model) or model,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            latency_ms=(time.perf_counter() - start) * 1000,
            ok=getattr(resp, "stop_reason", None) != "refusal",
            server_fallback_used=any(getattr(i, "type", None) == "fallback_message" for i in iterations),
        )
        self.calls.append(record)
        log.info("llm_call %s model=%s in=%d out=%d %.0fms", call_type, record.model,
                 record.input_tokens, record.output_tokens, record.latency_ms)
        return resp

    def fallback(self, kind: str) -> None:
        self.fallbacks[kind] += 1

    def summary(self) -> dict:
        by_type: dict[str, dict] = {}
        for c in self.calls:
            row = by_type.setdefault(
                c.call_type,
                {"calls": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "_lat": [],
                 "server_fallbacks": 0},
            )
            row["calls"] += 1
            row["errors"] += 0 if c.ok else 1
            row["input_tokens"] += c.input_tokens
            row["output_tokens"] += c.output_tokens
            row["cost_usd"] += c.cost_usd
            row["server_fallbacks"] += c.server_fallback_used
            row["_lat"].append(c.latency_ms)
        for row in by_type.values():
            lat = sorted(row.pop("_lat"))
            row["avg_latency_ms"] = round(sum(lat) / len(lat))
            row["p95_latency_ms"] = round(lat[min(len(lat) - 1, int(0.95 * len(lat)))])
            row["cost_usd"] = round(row["cost_usd"], 4)
        return {
            "by_call_type": by_type,
            "total_cost_usd": round(sum(c.cost_usd for c in self.calls), 4),
            "total_calls": len(self.calls),
            "deterministic_fallbacks": dict(self.fallbacks),
        }


TELEMETRY = Telemetry()
