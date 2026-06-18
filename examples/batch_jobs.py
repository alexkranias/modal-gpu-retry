"""Run a batch of jobs, each retrying on a bigger GPU.

A `@gpuretry.function` fanned out over many configs with `.starmap` from a
`local_entrypoint`, run with `modal run`. If a job OOMs on the base GPU it is
retried on the next GPU in `retries=[...]`, per job. A job that fails on every GPU
comes back as a `LadderExhausted` in the results instead of aborting the batch.

    modal run examples/batch_jobs.py

The only change from native Modal is `@app.function(gpu=...)` to
`@gpuretry.function(app, gpu=..., retries=[...])`, plus adding `modal-gpu-retry` to the
image. The `.starmap` call site is unchanged.
"""

import modal

import modal_gpu_retry as gpuretry

app = modal.App("example-gpu-escalation-sweep")

image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "torch",
    "modal-gpu-retry",  # required: Modal re-imports this module in the container
)

MODELS = [
    ("Qwen/Qwen3-4B", "qwen3-4b"),
    ("meta-llama/Llama-3.1-8B-Instruct", "llama3.1-8b"),
]
TARGET_SIZES = [0.01, 0.05, 0.10]

# (model_idx, model_tag, target_size) — fanned out below.
TASKS = [(mi, tag, ts) for mi, (_, tag) in enumerate(MODELS) for ts in TARGET_SIZES]


# Native:  @app.function(gpu="L40S", image=image, timeout=8 * 3600)
# Elastic: add retries=[...] and switch the decorator. Base runs on L40S; on any
# failure (e.g. CUDA OOM) the task is retried on A100, then H100.
@gpuretry.function(app, gpu="L40S", retries=["A100", "H100"], image=image, timeout=8 * 3600)
def run_task(model_idx: int, model_tag: str, target_size: float) -> str:
    import torch

    model_name, _ = MODELS[model_idx]
    gpu = torch.cuda.get_device_name(0)
    # ... your real benchmark work here; this stand-in just reports the GPU.
    return f"{model_name} ({model_tag}) @ {target_size} ran on {gpu}"


@app.local_entrypoint()
def main():
    print(f"Spawning {len(TASKS)} tasks...")
    results = list(run_task.starmap(TASKS))  # unchanged from native Modal

    ok, exhausted = [], []
    for task, res in zip(TASKS, results, strict=True):
        if isinstance(res, gpuretry.LadderExhausted):
            exhausted.append((task, res))
        else:
            ok.append(res)

    for res in ok:
        print("  OK       ", res)
    for task, res in exhausted:
        print("  EXHAUSTED", task, "->", res)
    print(f"\n{len(ok)} succeeded, {len(exhausted)} exhausted all GPU tiers.")
