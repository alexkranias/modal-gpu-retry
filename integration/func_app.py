"""Validates the native `modal run` + local_entrypoint + .starmap pattern
(mirrors pranav_compaction's benchmark scripts). CPU-only, base succeeds -> ~free.

    modal run integration/func_app.py
"""

import modal

import modal_gpu_retry as mgr

app = modal.App("mgr-func")
image = modal.Image.debian_slim().add_local_python_source("modal_gpu_retry")

# (model_idx, name) tuples, exactly like TASKS in the real benchmark scripts.
TASKS = [(i, f"cfg{i}") for i in range(4)]


@mgr.function(app, retries=["A100"], image=image)  # CPU base; would escalate on OOM
def run_task(model_idx: int, name: str) -> str:
    return f"ran {model_idx}:{name}"


@app.local_entrypoint()
def main():
    results = list(run_task.starmap(TASKS))  # unchanged from native Modal
    for r in results:
        print("RESULT", r)
