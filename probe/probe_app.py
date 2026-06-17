"""modal-gpu-retry probe — verifies the Modal behaviors the library rests on.

Run the in-session tests (escalation OOM, gather fan-out, nested .remote.aio
inside a CPU driver):

    modal run probe/probe_app.py

For the detached-survival test, deploy then use the separate client scripts:

    modal deploy probe/probe_app.py
    python probe/spawn_detached.py     # spawns driver, saves call id, exits
    python probe/get_detached.py       # fresh process: reconnect + .get()
"""

import asyncio

import modal

app = modal.App("mgr-probe")

# torch gives us a clean, catchable GPU OOM (torch.cuda.OutOfMemoryError).
gpu_image = modal.Image.debian_slim().pip_install("torch")


@app.cls(gpu="T4", image=gpu_image, retries=0)
class Model:
    @modal.method()
    def run(self, gb: float) -> str:
        import torch

        name = torch.cuda.get_device_name(0)
        # float16 = 2 bytes/elt; allocate `gb` gigabytes of device memory.
        n = int(gb * (1024**3) / 2)
        x = torch.empty(n, dtype=torch.float16, device="cuda")
        torch.cuda.synchronize()
        return f"ok on {name}: allocated {gb}GB ({x.numel()} elts)"


@app.function(cpu=1.0, retries=0)
async def driver(gb: float, tiers: list[str]) -> str:
    """CPU orchestrator: runs the ladder server-side via nested .remote.aio()."""
    last = None
    try:
        return await Model().run.remote.aio(gb)  # base attempt (T4)
    except Exception as e:  # noqa: BLE001
        last = f"{type(e).__name__}: {str(e)[:100]}"
    for t in tiers:
        try:
            return await Model.with_options(gpu=t, retries=0)().run.remote.aio(gb)
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {str(e)[:100]}"
    raise RuntimeError(f"ladder exhausted; last: {last}")


@app.local_entrypoint()
def main():
    big = 20.0  # OOMs a 16GB T4, fits a 40GB A100

    print("\n== test 1: base T4 OOM surfaces as a catchable exception ==")
    try:
        r = Model().run.remote(big)
        print("  UNEXPECTED success:", r)
    except Exception as e:  # noqa: BLE001
        print(f"  caught expected {type(e).__name__}: {str(e)[:120]}")

    print("\n== test 2: with_options(gpu='A100', retries=0) escalation succeeds ==")
    r = Model.with_options(gpu="A100", retries=0)().run.remote(big)
    print("  escalated ->", r)

    print("\n== test 3: .remote.aio() + asyncio.gather fan-out (small allocs) ==")

    async def fan():
        return await asyncio.gather(
            *[Model().run.remote.aio(1.0) for _ in range(3)],
            return_exceptions=True,
        )

    for i, res in enumerate(asyncio.run(fan())):
        print(f"  [{i}] {res!r}"[:120])

    print("\n== test 4: nested .remote.aio() from inside a CPU @app.function ==")
    print("  driver ->", driver.remote(big, ["A100"]))

    print("\nALL IN-SESSION TESTS DONE")
