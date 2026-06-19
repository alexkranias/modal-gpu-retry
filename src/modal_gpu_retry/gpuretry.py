"""The GPU retry escalation ladder.

`ladder` runs a base attempt on the GPU specified by `gpus=`, then one attempt per GPU tier,
returning on the first success and raising `GPURetryExhausted` if every attempt fails.
The Modal binding (see :mod:`modal_gpu_retry.wrapper`) supplies an ``attempt_fn`` that turns
``(tier, x)`` into a remote call; tests supply a fake. This separation is what
lets the whole escalation policy be tested with **zero GPU spend**.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

# attempt_fn(tier, x) -> awaitable result.  tier is None for the untouched base
# attempt (the GPU the user configured in @app.cls), or a GPU string to escalate.
AttemptFn = Callable[[str | None, Any], Awaitable[Any]]

# should_escalate(exc, attempt_index) -> keep climbing the ladder?  Default: always.
ShouldEscalate = Callable[[BaseException, int], bool]

BASE_LABEL = "base"


class GPURetryExhausted(Exception):
    """Every tier in the ladder failed.

    Self-contained and pickle-safe: it stores only the *stringified* tier labels
    and error reprs, never the raw remote exception objects (which may reference
    modules — e.g. ``torch`` — that the orchestrator process cannot import). The real
    last exception is still chained via ``raise ... from`` for local tracebacks;
    callers that serialize results across a process boundary strip that cause.
    """

    def __init__(self, attempts: Sequence[tuple[str, str]]):
        self.attempts: list[tuple[str, str]] = [(a[0], a[1]) for a in attempts]
        summary = " -> ".join(f"{label} ({err})" for label, err in self.attempts)
        super().__init__(f"all {len(self.attempts)} attempt(s) failed: {summary}")

    def __reduce__(self):
        # Rebuild from attempts (not from the formatted message in self.args).
        return (self.__class__, (self.attempts,))


def _err_repr(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()
    first = text[0] if text else ""
    return f"{type(exc).__name__}: {first}" if first else type(exc).__name__


async def ladder(
    attempt_fn: AttemptFn,
    x: Any,
    retries: Sequence[str],
    *,
    should_escalate: ShouldEscalate | None = None,
) -> Any:
    """Walk the escalation ladder for a single input ``x``.

    Attempt 0 is the untouched base (``tier=None``); attempt ``i`` (i>=1) uses
    ``retries[i-1]`` as the GPU. Returns the first success. Raises
    :class:`GPURetryExhausted` (chained from the last error) if all attempts fail,
    or stops early if ``should_escalate`` returns False.
    """
    tiers: list[str | None] = [None, *retries]
    attempts: list[tuple[str, str]] = []
    last_exc: BaseException | None = None

    for i, tier in enumerate(tiers):
        try:
            return await attempt_fn(tier, x)
        except Exception as exc:  # noqa: BLE001 — failure-agnostic by design
            label = BASE_LABEL if tier is None else tier
            attempts.append((label, _err_repr(exc)))
            last_exc = exc
            is_last = i == len(tiers) - 1
            if not is_last and should_escalate is not None and not should_escalate(exc, i):
                break

    raise GPURetryExhausted(attempts) from last_exc


async def run_batch(
    attempt_fn: AttemptFn,
    xs: Sequence[Any],
    retries: Sequence[str],
    *,
    should_escalate: ShouldEscalate | None = None,
) -> list[Any]:
    """Run an independent ladder per input, concurrently.

    Each input climbs its own ladder and escalates the instant *it* fails — no
    tier-by-tier barrier. Failures come back in place (as the result value) via
    ``return_exceptions=True`` so one input's exhaustion never aborts the batch.
    """
    return await asyncio.gather(
        *(ladder(attempt_fn, x, retries, should_escalate=should_escalate) for x in xs),
        return_exceptions=True,
    )
