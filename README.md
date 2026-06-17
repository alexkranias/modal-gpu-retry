# modal-gpu-retry

**Retries that escalate the GPU.**

Modal's native `retries=` re-runs the *identical* spec. `modal-gpu-retry` makes a
list-valued `retries=["A100", "B200"]` an **escalation ladder**: the base attempt
uses whatever `gpu=` you configured, and each failure climbs to the next, bigger
GPU until one succeeds.

It is **failure-agnostic** — any exception advances the ladder, on the assumption
that failures are sizing failures (OOM). A deterministic bug's blast radius is
exactly `1 + len(retries)`.

> Not affiliated with Modal. A community wrapper around the `modal` SDK.

## Contrast with native Modal

Modal's native `gpu=["H100", "A100"]` is an **availability** fallback (try the
preferred type, fall back if it is *unavailable*). This is **escalation on
failure** — same syntax shape, opposite trigger.

## Install

```bash
pip install modal-gpu-retry
```

## Usage

Swap `@app.cls` for `@mgr.cls` (or `@app.function` for `@mgr.function`) and pass a
**list** of GPUs as `retries`. Every existing call site keeps working:

```python
import modal
import modal_gpu_retry as mgr

app = modal.App("my-app")
image = modal.Image.debian_slim().pip_install("torch", "modal-gpu-retry")

@mgr.cls(app, gpu="T4", retries=["A100", "B200"], image=image)
class Model:
    @modal.method()
    def run(self, x):
        ...  # OOMs on T4? -> retried on A100, then B200

# local: the ladder runs in your process
Model().run.remote(x)          # single:  T4 -> A100 -> B200
Model().run.map(inputs)        # batch: each input walks its OWN ladder, concurrently

# detached: the ladder runs server-side, survives disconnect
handle = Model().run.spawn_map(inputs)
results = handle.get()         # ... later, even from another process:
# results = mgr.LadderCall.from_id(call_id).get()
```

- **List `retries`** → escalation ladder. **Int (or omitted)** → passed straight
  through to Modal's native retries. Empty list → single base attempt.
- On exhaustion you get a `LadderExhausted` (in `.map`/`spawn_map` results it is
  returned in place, so one input's failure never aborts the batch).

### `.map` vs `.spawn_map`

| Call | Where the ladder runs | Survives client disconnect? |
|------|-----------------------|------------------------------|
| `.remote` / `.map` | your process (local) | no |
| `.spawn_map` | a cheap CPU driver on Modal | yes — reconnect with `LadderCall.from_id` |

## Requirements & caveats

- **Your image must contain `modal-gpu-retry`.** Modal re-imports your module
  inside the container, so add it to your image: `.pip_install("modal-gpu-retry")`.
- `spawn_map` requires the app to be **deployed** (`modal deploy ...`); it resolves
  the target by name inside the driver container.
- The decorated class/function appears in the Modal dashboard under a mangled name
  (`_mgr_real_<Name>`). This is how the wrapper keeps your call sites unchanged
  while staying compatible with Modal's container class resolution.

## How it works

The pure escalation logic ([`ladder.py`](src/modal_gpu_retry/ladder.py)) is
Modal-agnostic and unit-tested with a fake attempt function (zero GPU spend). The
decorator ([`proxy.py`](src/modal_gpu_retry/proxy.py)) wraps Modal's `app.cls` /
`app.function`, passes `retries=0` natively, and returns a proxy that routes
`.remote` / `.map` (local) and `.spawn_map` (a server-side CPU driver) through the
ladder.

## License

Apache-2.0.
