"""Run jobs that survive disconnect, using an @app.cls on a modal_gpu_retry.App.

Local (runs in your process, streams in your terminal):

    modal run examples/detached_jobs.py

Detached (survives disconnect; requires a deployed app):

    modal deploy examples/detached_jobs.py
    python examples/detached_jobs.py spawn          # prints a call id, then exit
    python examples/detached_jobs.py get <call_id>  # reconnect later, fetch results
"""

import sys

import modal

import modal_gpu_retry

app = modal_gpu_retry.App("example-cls-escalation")
image = modal.Image.debian_slim().pip_install("torch")

INPUTS = [1.0, 20.0, 1.0]  # GB to allocate; 20GB OOMs a T4, fits an A100


@app.cls(gpu="T4", retries=["A100"], image=image)
class Model:
    @modal.method()
    def run(self, gb: float) -> str:
        import torch

        name = torch.cuda.get_device_name(0)
        torch.empty(int(gb * (1024**3) / 2), dtype=torch.float16, device="cuda")
        torch.cuda.synchronize()
        return f"{name} ({gb}GB)"


@app.local_entrypoint()
def main():
    print("single  :", Model().run.remote(20.0))  # T4 OOM -> A100
    print("batch   :", Model().run.map(INPUTS))  # each input its own ladder


# Detached entry points (plain client, not a Modal entrypoint).
if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "spawn":
        handle = Model().run.spawn_map(INPUTS)
        print("call id:", handle.object_id)
    elif len(sys.argv) >= 3 and sys.argv[1] == "get":
        print(modal_gpu_retry.GPURetryCall.from_id(sys.argv[2]).get(timeout=600))
