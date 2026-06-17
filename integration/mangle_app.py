"""Experiment: can name-mangling preserve the @decorator + Model().run call site?

The real Cls is registered under a mangled name (so Modal's container
`getattr(module, mangled)` finds a real modal.Cls), while the user-facing symbol
holds our escalating proxy. CPU-only + base succeeds, so this spends ~no GPU.
"""

import sys

import modal

import modal_gpu_retry as mgr  # noqa: F401  (must be importable in the container)
from modal_gpu_retry.proxy import _ClsProxy, _ensure_driver

app = modal.App("mgr-mangle")
img = modal.Image.debian_slim().add_local_python_source("modal_gpu_retry")


def elastic_cls(app, *, retries, **kw):
    def deco(user_cls):
        orig = user_cls.__name__
        mangled = f"_mgr_real_{orig}"
        user_cls.__name__ = mangled
        user_cls.__qualname__ = mangled
        driver = _ensure_driver(app)
        real = app.cls(retries=0, **kw)(user_cls)
        setattr(sys.modules[user_cls.__module__], mangled, real)
        return _ClsProxy(real, list(retries), None, app, mangled, driver)

    return deco


@elastic_cls(app, retries=["A100"], image=img)
class Model:
    @modal.method()
    def run(self, x):
        return f"ran with x={x}"


@app.local_entrypoint()
def main():
    print("RESULT:", Model().run.remote(42))
