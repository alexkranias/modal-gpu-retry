"""Decorator + proxy: the drop-in surface (local + detached).

``gpuretry.cls`` / ``gpuretry.function`` wrap Modal's ``app.cls`` / ``app.function``: they
pass ``retries=0`` to Modal natively, stash the GPU list as the ladder, and hand
back a proxy over Modal's object so the *native* call sites — ``.remote``,
``.remote.aio``, ``.map`` (local) and ``.spawn_map`` (detached) — escalate.

Object types this relies on (verified against modal 1.5.0):
- ``Model`` is ``modal.cls.Cls``; ``Model()`` is ``modal.cls.Obj``;
  ``Model().run`` and ``Model.with_options(...)().run`` are ``modal.Function``.
- ``Function`` exposes ``remote`` (with ``.aio``), ``map``, ``spawn``,
  ``with_options``; ``FunctionCall`` exposes ``from_id`` / ``get``.

Local vs detached: local runs the ladder in the caller's process. Detached runs
the *same* ladder inside a cheap CPU ``@app.function`` (registered once per app),
launched via ``.spawn`` — so escalation survives the client disconnecting, the
same way Modal's native retries do. ``spawn_map`` requires the app to be
deployed (it resolves the target by name inside the orchestrator container).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import sys
from collections.abc import Callable, Sequence
from typing import Any

import modal

from .ladder import AttemptFn, LadderExhausted, ShouldEscalate, ladder, run_batch

BoundFn = Callable[[str | None], "modal.Function"]
SpawnFn = Callable[[list], "LadderCall"]

# Marker the CPU orchestrator returns in place of an input that exhausted its ladder
# (kept pickle-safe: a plain dict of strings, never a raw remote exception).
_EXHAUSTED_KEY = "__mgr_exhausted__"


def _run(coro):
    """Run a coroutine to completion from sync code, even inside a live loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(1) as ex:
        return ex.submit(lambda: asyncio.run(coro)).result()


# --------------------------------------------------------------------------- #
# Detached: a generic CPU orchestrator registered once per app.
# --------------------------------------------------------------------------- #
_ORCHESTRATORS: dict[int, Any] = {}


def _ensure_orchestrator(app: modal.App):
    """Register (once per app) a CPU function that runs the ladder server-side."""
    key = id(app)
    if key in _ORCHESTRATORS:
        return _ORCHESTRATORS[key]

    @app.function(cpu=1.0, retries=0, serialized=True, name="_mgr_orchestrator")
    async def _mgr_orchestrator(payload):
        # Self-contained: only stdlib + modal, so the orchestrator image needs no deps.
        import asyncio as _asyncio

        import modal as _modal

        app_name = payload["app_name"]
        kind = payload["kind"]
        name = payload["name"]
        method = payload.get("method")
        retries = payload["retries"]
        ctor_args = payload.get("ctor_args", ())
        ctor_kwargs = payload.get("ctor_kwargs", {})
        inputs = payload["inputs"]

        def bound(tier):
            if kind == "function":
                fn = _modal.Function.from_name(app_name, name)
                return fn if tier is None else fn.with_options(gpu=tier, retries=0)
            cls = _modal.Cls.from_name(app_name, name)
            if tier is not None:
                cls = cls.with_options(gpu=tier, retries=0)
            return getattr(cls(*ctor_args, **ctor_kwargs), method)

        async def one(x):
            attempts = []
            for _i, tier in enumerate([None, *retries]):
                try:
                    return await bound(tier).remote.aio(x)
                except Exception as e:  # noqa: BLE001
                    label = "base" if tier is None else tier
                    attempts.append([label, f"{type(e).__name__}: {str(e)[:200]}"])
            # literal (not the module global) so the serialized orchestrator needs no deps
            return {"__mgr_exhausted__": attempts}

        return await _asyncio.gather(*(one(x) for x in inputs))

    _ORCHESTRATORS[key] = _mgr_orchestrator
    return _mgr_orchestrator


class LadderCall:
    """Handle for a detached batch — a thin wrapper over Modal's FunctionCall.

    ``get()`` maps the orchestrator's exhaustion markers back into ``LadderExhausted``
    so detached results look identical to local ones. Reconnect from another
    process with ``LadderCall.from_id(call_id)``.
    """

    def __init__(self, function_call):
        self._fc = function_call

    @property
    def object_id(self) -> str:
        return self._fc.object_id

    @classmethod
    def from_id(cls, call_id: str) -> LadderCall:
        return cls(modal.FunctionCall.from_id(call_id))

    def get(self, timeout: int | None = None) -> list:
        raw = self._fc.get() if timeout is None else self._fc.get(timeout=timeout)
        return [_demarker(r) for r in raw]


def _demarker(r):
    if isinstance(r, dict) and _EXHAUSTED_KEY in r:
        return LadderExhausted([tuple(a) for a in r[_EXHAUSTED_KEY]])
    return r


# --------------------------------------------------------------------------- #
# Local: the escalating call surface.
# --------------------------------------------------------------------------- #
class _Caller:
    """Mirrors Modal's ``.remote`` — callable (sync) with an ``.aio`` variant."""

    def __init__(self, sync: Callable[..., Any], aio: Callable[..., Any]):
        self._sync = sync
        self._aio = aio

    def __call__(self, *args, **kwargs):
        return self._sync(*args, **kwargs)

    def aio(self, *args, **kwargs):
        return self._aio(*args, **kwargs)


class LadderMethod:
    """The escalating call surface for one method/function."""

    def __init__(
        self,
        bound: BoundFn,
        retries: Sequence[str],
        should_escalate: ShouldEscalate | None,
        spawn: SpawnFn | None = None,
    ):
        self._bound = bound
        self._retries = list(retries)
        self._se = should_escalate
        self._spawn = spawn

    def _call_attempt(self, args, kwargs) -> AttemptFn:
        async def attempt(tier, _x):
            return await self._bound(tier).remote.aio(*args, **kwargs)

        return attempt

    def _map_attempt(self) -> AttemptFn:
        async def attempt(tier, x):
            return await self._bound(tier).remote.aio(x)

        return attempt

    def _starmap_attempt(self) -> AttemptFn:
        async def attempt(tier, args):
            return await self._bound(tier).remote.aio(*args)

        return attempt

    @property
    def remote(self) -> _Caller:
        return _Caller(
            lambda *a, **k: _run(self._remote_coro(a, k)),
            lambda *a, **k: self._remote_coro(a, k),
        )

    def _remote_coro(self, args, kwargs):
        return ladder(
            self._call_attempt(args, kwargs), None, self._retries, should_escalate=self._se
        )

    def map(self, inputs) -> list:
        """Local batch: each input walks its own ladder, concurrently.

        Mirrors Modal's ``.map`` but each input escalates the GPU on its own
        failure. Exhausted inputs come back as ``LadderExhausted`` in place
        (one failure never aborts the batch).
        """
        return _run(
            run_batch(self._map_attempt(), list(inputs), self._retries, should_escalate=self._se)
        )

    def starmap(self, inputs) -> list:
        """Local batch over tuples of args (mirrors Modal's ``.starmap``).

        Each input is a tuple unpacked into the call. Like :meth:`map`, each
        input walks its own ladder and exhausted inputs come back in place.
        """
        return _run(
            run_batch(
                self._starmap_attempt(),
                list(inputs),
                self._retries,
                should_escalate=self._se,
            )
        )

    def spawn_map(self, inputs) -> LadderCall:
        """Detached batch: run the ladder server-side; returns a LadderCall."""
        if self._spawn is None:
            raise RuntimeError(
                "spawn_map is only available on @gpuretry.cls/@gpuretry.function targets "
                "(and requires the app to be deployed)."
            )
        return self._spawn(list(inputs))

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._bound(None), name)  # delegate native features


# --------------------------------------------------------------------------- #
# Proxies over Cls / Obj.
# --------------------------------------------------------------------------- #
class _ObjProxy:
    def __init__(self, real_cls, retries, se, args, kwargs, app, cls_name):
        self._real_cls = real_cls
        self._retries = retries
        self._se = se
        self._args = args
        self._kwargs = kwargs
        self._app = app
        self._cls_name = cls_name
        self._obj = None

    def _base_obj(self):
        if self._obj is None:
            self._obj = self._real_cls(*self._args, **self._kwargs)
        return self._obj

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        attr = getattr(self._base_obj(), name)
        if not isinstance(attr, modal.Function):
            return attr

        def bound(tier, _name=name):
            if tier is None:
                return getattr(self._base_obj(), _name)
            escalated = self._real_cls.with_options(gpu=tier, retries=0)
            return getattr(escalated(*self._args, **self._kwargs), _name)

        def spawn(inputs, _name=name):
            payload = {
                "kind": "cls",
                "app_name": self._app.name,
                "name": self._cls_name,
                "method": _name,
                "retries": self._retries,
                "ctor_args": self._args,
                "ctor_kwargs": self._kwargs,
                "inputs": inputs,
            }
            orchestrator = modal.Function.from_name(self._app.name, "_mgr_orchestrator")
            return LadderCall(orchestrator.spawn(payload))

        return LadderMethod(bound, self._retries, self._se, spawn=spawn)


class _ClsProxy:
    def __init__(self, real_cls, retries, se, app, cls_name):
        self._real_cls = real_cls
        self._retries = retries
        self._se = se
        self._app = app
        self._cls_name = cls_name

    def __call__(self, *args, **kwargs):
        return _ObjProxy(
            self._real_cls,
            self._retries,
            self._se,
            args,
            kwargs,
            self._app,
            self._cls_name,
        )

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._real_cls, name)


# --------------------------------------------------------------------------- #
# Public decorators.
# --------------------------------------------------------------------------- #
def _is_ladder(retries) -> bool:
    return isinstance(retries, (list, tuple))


def _mangle(obj) -> str:
    """Rename obj so Modal registers/resolves it under a private name.

    Modal's container resolves a class/function with ``getattr(module, name)``
    where ``name`` comes from ``__name__``/``__qualname__``. By mangling that, the
    real (registered) object lives under ``_mgr_real_<name>`` while the original
    user-facing symbol is free to hold our escalating proxy.
    """
    mangled = f"_mgr_real_{obj.__name__}"
    obj.__name__ = mangled
    obj.__qualname__ = mangled
    return mangled


def cls(app, *, retries=None, should_escalate: ShouldEscalate | None = None, **modal_kwargs):
    """Drop-in replacement for ``@app.cls`` with GPU-escalating retries.

    ``retries=["A100", "B200"]`` (a list) escalates the GPU on each failure: the
    base attempt uses the configured ``gpu=``, then each entry is tried in turn.
    An int (or omitted) ``retries`` passes straight through to Modal.
    """

    def deco(user_cls):
        if not _is_ladder(retries):
            kw = dict(modal_kwargs)
            if retries is not None:
                kw["retries"] = retries
            return app.cls(**kw)(user_cls)

        mangled = _mangle(user_cls)
        _ensure_orchestrator(app)  # register the shared CPU orchestrator for the detached path
        real = app.cls(retries=0, **modal_kwargs)(user_cls)
        setattr(sys.modules[user_cls.__module__], mangled, real)
        return _ClsProxy(real, list(retries), should_escalate, app, mangled)

    return deco


def function(app, *, retries=None, should_escalate: ShouldEscalate | None = None, **modal_kwargs):
    """Drop-in replacement for ``@app.function`` with GPU-escalating retries."""

    def deco(user_fn):
        if not _is_ladder(retries):
            kw = dict(modal_kwargs)
            if retries is not None:
                kw["retries"] = retries
            return app.function(**kw)(user_fn)

        mangled = _mangle(user_fn)
        _ensure_orchestrator(app)  # register the shared CPU orchestrator for the detached path
        real = app.function(retries=0, **modal_kwargs)(user_fn)
        setattr(sys.modules[user_fn.__module__], mangled, real)

        def bound(tier):
            return real if tier is None else real.with_options(gpu=tier, retries=0)

        def spawn(inputs):
            payload = {
                "kind": "function",
                "app_name": app.name,
                "name": mangled,
                "retries": list(retries),
                "inputs": inputs,
            }
            resolved = modal.Function.from_name(app.name, "_mgr_orchestrator")
            return LadderCall(resolved.spawn(payload))

        return LadderMethod(bound, list(retries), should_escalate, spawn=spawn)

    return deco
