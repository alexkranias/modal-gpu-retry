# Examples

Each example is a self-contained Modal app. Add `modal-gpu-retry` to your image
(`.pip_install("modal-gpu-retry")`) — Modal re-imports your module inside the
container, so the package must be present there.

| File | Shows | Run with |
|------|-------|----------|
| [`gpu_escalation_sweep.py`](gpu_escalation_sweep.py) | A `@mgr.function` benchmark sweep that escalates the GPU on per-task OOM — the native `modal run` + `local_entrypoint` + `.starmap` flow. | `modal run examples/gpu_escalation_sweep.py` |
| [`cls_local_and_detached.py`](cls_local_and_detached.py) | A `@mgr.cls` with `.remote`, `.map`, and detached `.spawn_map`. | `modal run examples/cls_local_and_detached.py` |

> Running these straight from this repo (before the package is published) requires
> mounting the local source instead of `pip_install`; see the `integration/`
> scripts for that dev variant.
