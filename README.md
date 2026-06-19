# modal-gpu-retry

<p align="center">
  <img src="https://raw.githubusercontent.com/alexkranias/modal-gpu-retry/main/assets/banner_decorator.png" alt="modal-gpu-retry: change modal.App to modal_gpu_retry.App and add retries=[...]" width="100%">
</p>


## Install

```bash
pip install modal-gpu-retry
```

## What it does

Modal's native `retries=` reruns a failed job on the *same* hardware, which doesn't help
with OOM errors since the rerun will just run out of memory again. `modal-gpu-retry` reuses the same `retries`
argument but takes a *list of GPUs* and escalates to the next one on each failure.

```python
@app.function(gpu="L40S", retries=["A100", "H100"])
```

If the job OOMs on the L40S it reruns on the A100, then the H100.

<p align="center">
  <img src="https://raw.githubusercontent.com/alexkranias/modal-gpu-retry/main/assets/oom_escalation.png" alt="On OOM, each retry escalates to the next GPU: L40S to A100 to H100" width="80%">
</p>

## Usage

To integrate with your existing Modal scripts, there are exactly two changes needed to be made. Modify the app initialization to use `modal_gpu_retry` instead of `modal`:

```python
app = modal.App("my-evals")             # before
app = modal_gpu_retry.App("my-evals")   # after
```

and give the decorator a list-valued `retries=[...]` containing the fallback GPUs:

```python
@app.function(gpu="L40S", image=image)                            # before
@app.function(gpu="L40S", retries=["A100", "H100"], image=image)  # after
```

Your code should look like this now:

```python
import modal
import modal_gpu_retry

app = modal_gpu_retry.App("my-evals")
image = modal.Image.debian_slim().pip_install("torch")

@app.function(gpu="L40S", retries=["A100", "H100"], image=image)
def run_eval(config):
    ...  # if this OOMs on L40S, it runs again on A100, then H100

@app.local_entrypoint()
def main():
    results = list(run_eval.map(configs))
```

You can run it as normal with the Modal CLI, for example `modal run evals.py` works just fine. 

The `retries=` value decides the behavior:

- `retries=3`: native Modal (rerun the same GPU).
- `retries=["A100", "H100"]`: escalate to a bigger GPU each time.
- `retries=[]`: same as `retries=0`.

## Exhausted jobs come back in place

If a job fails on every GPU, you get a `GPURetryExhausted` in the results instead of
an exception, so one bad job doesn't kill the batch:

```python
results = list(run_eval.map(configs))
dead = [c for c, r in zip(configs, results, strict=True)
        if isinstance(r, modal_gpu_retry.GPURetryExhausted)]
```

## Detached runs

`.remote`, `.map`, and `.starmap` run the retry loop in your process, so it stops if
you disconnect. `modal run --detach` doesn't help: it keeps the *app* alive but the loop
still runs locally. For escalation that survives a disconnect, `modal deploy` your app and
use `.spawn_map`, which runs the loop in a CPU orchestrator on Modal:

```python
handle = run_eval.spawn_map(configs)
results = handle.get()   # later, or from a different process
```

Reconnect from anywhere with `modal_gpu_retry.GPURetryCall.from_id(call_id)`.

## Notes

- A few `modal run` CLI patterns behave unexpectedly, such as targeting the wrapped
  function directly. See [the examples README](examples/README.md#modal-cli-details).
- Your class/function appears in the Modal dashboard under a `_mgr_real_` prefix; that's
  how the wrapper keeps your call sites unchanged without breaking how Modal loads your
  class in the container.
- It works on `@app.cls` too, and `.remote`, `.map`, and `.starmap` keep their usual call sites.
- You don't need to modify your image because the library will install itself on the image you pass into `modal_gpu_retry.App` via `image=` automatically.

## License

MIT. This is a community wrapper around the modal SDK and isn't affiliated
with Modal.
