"""Live integration app for modal-gpu-retry (run with PYTHONPATH=src).

Local mode:    modal run integration/app.py
Detached mode: modal deploy integration/app.py
               python integration/spawn.py   # spawn_map, save id, exit
               python integration/get.py      # fresh process: LadderCall.from_id().get()
"""

import modal

import modal_gpu_retry as mgr

app = modal.App("mgr-integration")
# The container re-imports this module (which imports modal_gpu_retry), so the
# package must be in the image. Published users would .pip_install("modal-gpu-retry");
# here we mount the local source.
gpu_image = (
    modal.Image.debian_slim().pip_install("torch").add_local_python_source("modal_gpu_retry")
)

BIG = 20.0  # OOMs a 16GB T4, fits a 40GB A100
SMALL = 1.0  # fits a T4


@mgr.cls(app, gpu="T4", retries=["A100"], image=gpu_image)
class Model:
    @modal.method()
    def run(self, gb: float) -> str:
        import torch

        name = torch.cuda.get_device_name(0)
        n = int(gb * (1024**3) / 2)
        x = torch.empty(n, dtype=torch.float16, device="cuda")
        torch.cuda.synchronize()
        return f"{name}|{gb}GB|{x.numel()}elts"


@app.local_entrypoint()
def main():
    print("\n== LOCAL .remote (BIG -> base T4 OOM -> escalate A100) ==")
    print("  ", Model().run.remote(BIG))

    print("\n== LOCAL .map ([SMALL, BIG, SMALL]) each its own ladder ==")
    for i, r in enumerate(Model().run.map([SMALL, BIG, SMALL])):
        print(f"   [{i}] {r}")
