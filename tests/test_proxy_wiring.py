"""Proxy wiring tests — construct the proxies over real Modal objects but never
call ``.remote`` (no deploy, no account, no GPU). Verifies the decorator builds
the right object graph and routes tiers to ``with_options`` correctly.
"""

from __future__ import annotations

import modal
import pytest

import modal_gpu_retry as mgr
from modal_gpu_retry.proxy import LadderMethod, _ClsProxy


@pytest.fixture
def app():
    return modal.App("wiring-test")


def test_cls_with_list_retries_returns_proxy(app):
    @mgr.cls(app, gpu="T4", retries=["A100", "B200"], serialized=True)
    class Model:
        @modal.method()
        def run(self, x):
            return x

    assert isinstance(Model, _ClsProxy)
    assert Model._retries == ["A100", "B200"]


def test_method_access_yields_ladder_method(app):
    @mgr.cls(app, gpu="T4", retries=["A100"], serialized=True)
    class Model:
        @modal.method()
        def run(self, x):
            return x

    method = Model().run
    assert isinstance(method, LadderMethod)
    # mirrors Modal's .remote: callable with an .aio variant
    assert callable(method.remote)
    assert hasattr(method.remote, "aio")
    assert hasattr(method, "map")


def test_bound_routes_base_and_tier_to_real_functions(app):
    @mgr.cls(app, gpu="T4", retries=["A100"], serialized=True)
    class Model:
        @modal.method()
        def run(self, x):
            return x

    method = Model().run
    base = method._bound(None)
    escalated = method._bound("A100")
    assert isinstance(base, modal.Function)
    assert isinstance(escalated, modal.Function)
    # escalation goes through a *different* (with_options) handle than the base
    assert base is not escalated


def test_int_retries_passes_through_to_native_cls(app):
    @mgr.cls(app, gpu="T4", retries=3, serialized=True)
    class Model:
        @modal.method()
        def run(self, x):
            return x

    # native passthrough -> a real modal Cls, not our proxy
    assert isinstance(Model, modal.Cls)
    assert not isinstance(Model, _ClsProxy)


def test_no_retries_passes_through_to_native_cls(app):
    @mgr.cls(app, gpu="T4", serialized=True)
    class Model:
        @modal.method()
        def run(self, x):
            return x

    assert isinstance(Model, modal.Cls)


def test_function_with_list_retries_returns_ladder_method(app):
    @mgr.function(app, gpu="T4", retries=["A100"], serialized=True)
    def f(x):
        return x

    assert isinstance(f, LadderMethod)
    assert isinstance(f._bound(None), modal.Function)
    assert isinstance(f._bound("A100"), modal.Function)


def test_function_int_retries_passes_through(app):
    @mgr.function(app, gpu="T4", retries=2, serialized=True)
    def f(x):
        return x

    assert isinstance(f, modal.Function)
    assert not isinstance(f, LadderMethod)
