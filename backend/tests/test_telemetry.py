from types import SimpleNamespace

import pytest

from app.services.telemetry import Telemetry


def fake_response(inp: int, out: int, iterations=None):
    usage = SimpleNamespace(input_tokens=inp, output_tokens=out, cache_read_input_tokens=0,
                            cache_creation_input_tokens=0, iterations=iterations)
    return SimpleNamespace(usage=usage, model="claude-sonnet-5-5", stop_reason="end_turn")


def test_track_records_usage_cost_and_latency():
    t = Telemetry()
    t.track("extraction", "claude-sonnet-5-5", lambda **kw: fake_response(1_000_000, 100_000))
    row = t.summary()["by_call_type"]["extraction"]
    assert row["calls"] == 1 and row["input_tokens"] == 1_000_000
    assert row["cost_usd"] == pytest.approx(2.0 + 1.0)
    assert row["avg_latency_ms"] >= 0


def test_track_records_failed_calls_and_reraises():
    t = Telemetry()

    def boom(**kw):
        raise RuntimeError("api down")

    with pytest.raises(RuntimeError):
        t.track("response", "claude-sonnet-5-5", boom)
    assert t.summary()["by_call_type"]["response"]["errors"] == 1


def test_server_side_fallback_and_deterministic_fallbacks_are_counted():
    t = Telemetry()
    t.track("rerank", "claude-sonnet-5-5", lambda **kw: fake_response(10, 5, [SimpleNamespace(type="fallback_message")]))
    t.fallback("rerank_invalid_or_failed")
    s = t.summary()
    assert s["by_call_type"]["rerank"]["server_fallbacks"] == 1
    assert s["deterministic_fallbacks"] == {"rerank_invalid_or_failed": 1}


def test_cache_reads_and_writes_are_priced():
    t = Telemetry()
    usage = SimpleNamespace(input_tokens=0, output_tokens=0, cache_read_input_tokens=1_000_000,
                            cache_creation_input_tokens=1_000_000, iterations=None)
    t.track("extraction", "claude-sonnet-5-5", lambda **kw: SimpleNamespace(usage=usage, model="claude-sonnet-5-5",
                                                                             stop_reason="end_turn"))
    assert t.summary()["by_call_type"]["extraction"]["cost_usd"] == pytest.approx(0.20 + 2.0 * 1.25)
