"""Unit tests for the pure ladder core — no Modal, no GPU spend.

A fake ``attempt_fn`` simulates a function that fails on small tiers and succeeds
once the GPU is big enough, by recording which tiers it was asked to run on.
"""

from __future__ import annotations

import asyncio

import pytest

from modal_gpu_retry.ladder import BASE_LABEL, LadderExhausted, ladder, run_batch


class Boom(Exception):
    """Stand-in for an OOM / sizing failure."""


def make_attempt_fn(succeeds_on, calls=None):
    """Fake attempt_fn that succeeds only when the tier is in ``succeeds_on``.

    ``succeeds_on`` is a set of tier labels (None for base, or a GPU string).
    Records every (tier, x) it is invoked with into ``calls`` if provided.
    """

    async def attempt_fn(tier, x):
        if calls is not None:
            calls.append((tier, x))
        if tier in succeeds_on:
            return f"ok@{tier if tier is not None else BASE_LABEL}:{x}"
        raise Boom(f"too small: {tier}")

    return attempt_fn


def run(coro):
    return asyncio.run(coro)


# --- single-call ladder ----------------------------------------------------


def test_base_succeeds_no_escalation():
    calls = []
    fn = make_attempt_fn(succeeds_on={None}, calls=calls)
    result = run(ladder(fn, "x", ["A100", "B200"]))
    assert result == "ok@base:x"
    assert calls == [(None, "x")]  # only the base attempt ran


def test_escalates_in_order_until_success():
    calls = []
    fn = make_attempt_fn(succeeds_on={"B200"}, calls=calls)
    result = run(ladder(fn, "x", ["A100", "B200"]))
    assert result == "ok@B200:x"
    assert calls == [(None, "x"), ("A100", "x"), ("B200", "x")]


def test_empty_retries_is_single_attempt():
    calls = []
    fn = make_attempt_fn(succeeds_on={"A100"}, calls=calls)  # base will fail
    with pytest.raises(LadderExhausted) as ei:
        run(ladder(fn, "x", []))
    assert calls == [(None, "x")]
    assert len(ei.value.attempts) == 1
    assert ei.value.attempts[0][0] == BASE_LABEL


def test_exhaustion_raises_with_chained_cause_and_summary():
    fn = make_attempt_fn(succeeds_on=set())  # nothing succeeds
    with pytest.raises(LadderExhausted) as ei:
        run(ladder(fn, "x", ["A100", "B200"]))
    exc = ei.value
    # one entry per attempt, in order, base first
    assert [label for label, _ in exc.attempts] == [BASE_LABEL, "A100", "B200"]
    assert all("Boom" in err for _, err in exc.attempts)
    assert isinstance(exc.__cause__, Boom)  # real last error chained for tracebacks


def test_ladder_exhausted_is_pickle_safe():
    import pickle

    fn = make_attempt_fn(succeeds_on=set())
    with pytest.raises(LadderExhausted) as ei:
        run(ladder(fn, "x", ["A100"]))
    # the exception itself round-trips (stores only strings)
    restored = pickle.loads(pickle.dumps(LadderExhausted(ei.value.attempts)))
    assert restored.attempts == ei.value.attempts


def test_args_pass_through_untouched():
    fn = make_attempt_fn(succeeds_on={None})
    payload = {"prompt": "hi", "n": 3}
    assert run(ladder(fn, payload, ["A100"])) == f"ok@base:{payload}"


def test_should_escalate_can_stop_early():
    calls = []
    fn = make_attempt_fn(succeeds_on={"B200"}, calls=calls)
    # only allow the base attempt; never escalate
    with pytest.raises(LadderExhausted) as ei:
        run(ladder(fn, "x", ["A100", "B200"], should_escalate=lambda exc, i: False))
    assert calls == [(None, "x")]
    assert len(ei.value.attempts) == 1


# --- batch independence ----------------------------------------------------


def test_batch_each_input_walks_its_own_ladder():
    # base succeeds for "easy"; only A100 succeeds for "hard"; nothing for "doomed"
    async def attempt_fn(tier, x):
        if x == "easy" and tier is None:
            return "easy-ok@base"
        if x == "hard" and tier == "A100":
            return "hard-ok@A100"
        raise Boom(f"{x} fails on {tier}")

    results = run(run_batch(attempt_fn, ["easy", "hard", "doomed"], ["A100"]))
    assert results[0] == "easy-ok@base"
    assert results[1] == "hard-ok@A100"
    assert isinstance(results[2], LadderExhausted)  # returned in place, not raised


def test_batch_preserves_input_order():
    fn = make_attempt_fn(succeeds_on={None})
    results = run(run_batch(fn, ["a", "b", "c"], ["A100"]))
    assert results == ["ok@base:a", "ok@base:b", "ok@base:c"]
