"""Live integration test — gated behind creds + an opt-in env var (spends GPU).

Run with:  RUN_MODAL_INTEGRATION=1 pytest tests/test_integration.py
Requires Modal credentials configured (`modal token ...`).
"""

from __future__ import annotations

import os

import pytest

modal = pytest.importorskip("modal")
import modal_gpu_retry as gpuretry  # noqa: E402

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_MODAL_INTEGRATION") != "1",
    reason="set RUN_MODAL_INTEGRATION=1 (and configure Modal creds) to run live GPU tests",
)

app = modal.App("mgr-pytest-integration")
image = modal.Image.debian_slim().pip_install("torch").add_local_python_source("modal_gpu_retry")

BIG = 20.0  # OOMs a 16GB T4
SMALL = 1.0  # fits a T4


@gpuretry.cls(app, gpu="T4", retries=["A100"], image=image)
class Model:
    @modal.method()
    def run(self, gb: float) -> str:
        import torch

        name = torch.cuda.get_device_name(0)
        n = int(gb * (1024**3) / 2)
        x = torch.empty(n, dtype=torch.float16, device="cuda")
        torch.cuda.synchronize()
        return f"{name}|{x.numel()}"


def test_local_map_each_input_uses_smallest_sufficient_gpu():
    with app.run():
        results = Model().run.map([SMALL, BIG])
    assert "T4" in results[0]  # SMALL stayed on the base tier
    assert "A100" in results[1]  # BIG escalated
