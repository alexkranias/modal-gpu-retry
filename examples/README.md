# Examples

Each example is a self-contained Modal app. Add `modal-gpu-retry` to your image
(`.pip_install("modal-gpu-retry")`) — Modal re-imports your module inside the
container, so the package must be present there.

| File | Shows | Run with |
|------|-------|----------|
| [`batch_jobs.py`](batch_jobs.py) | A `@mgr.function` fanned out with `.starmap`, each job retrying on a bigger GPU on OOM. The everyday `modal run` + `local_entrypoint` flow. | `modal run examples/batch_jobs.py` |
| [`detached_jobs.py`](detached_jobs.py) | A `@mgr.cls` with `.remote` and `.map`, plus detached `.spawn_map` that survives closing your laptop. | `modal run examples/detached_jobs.py` |

> Running these straight from this repo before the package is published requires
> mounting the local source instead of `pip_install` — swap
> `.pip_install("modal-gpu-retry")` for
> `.add_local_python_source("modal_gpu_retry")` and run with `PYTHONPATH=src`.

## Modal CLI details

`modal deploy evals.py` registers your function under the `_mgr_real_` name alongside
a small CPU orchestrator (the driver). This is required before `.spawn_map`, since the
driver looks the target up by name.

A couple of CLI invocations don't behave the way you might expect:

**`modal run evals.py::run_eval` skips escalation.** `run_eval` is now the wrapper, not
a `modal.Function`, so Modal won't run it directly. If you list the file you'll see
`_mgr_real_run_eval` and `_mgr_driver` instead. You can run `_mgr_real_run_eval`
directly, but that's the raw function and skips escalation. Call the function from a
`local_entrypoint` instead.

**`--detach` doesn't keep escalation alive.** It keeps the app running after you
disconnect, but the retry loop for `.remote`, `.map`, and `.starmap` runs in your local
entrypoint, not on Modal, so it stops when you disconnect. If you want escalation that
survives a disconnect, use `.spawn_map`, which runs the loop in the driver on Modal.
