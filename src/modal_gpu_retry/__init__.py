"""modal-gpu-retry — Retries that escalate the GPU.

Modal's native ``retries=`` re-runs the *identical* spec. This wraps a Modal
``Cls``/``Function`` so a list-valued ``retries=["A100", "B200"]`` instead
escalates the GPU on each failure: the base attempt uses whatever ``gpu=`` you
configured, then each list entry is tried in turn until one succeeds.

Contrast with Modal's native ``gpu=["H100", "A100"]``, which is an *availability*
fallback (try preferred, fall back if unavailable). This is *escalation on
failure* — same syntax shape, opposite trigger.
"""

from __future__ import annotations

from .gpuretry import GPURetryExhausted, ladder, run_batch
from .wrapper import App, GPURetryCall, GPURetryMethod

__all__ = [
    "App",
    "GPURetryCall",
    "GPURetryExhausted",
    "GPURetryMethod",
    "ladder",
    "run_batch",
]
__version__ = "0.0.0"
