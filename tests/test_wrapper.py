"""Wrapper wiring tests — construct the wrappers over real Modal objects but never
call ``.remote`` (no deploy, no account, no GPU). Verifies the decorator builds
the right object graph and routes tiers to ``with_options`` correctly.
"""

from __future__ import annotations

import modal
import pytest

import modal_gpu_retry
from modal_gpu_retry.wrapper import GPURetryMethod, _ClsWrapper, _ensure_pkg_in_image


@pytest.fixture
def app():
    return modal_gpu_retry.App("wiring-test")


def test_cls_with_list_retries_returns_wrapper(app):
    @app.cls(gpu="T4", retries=["A100", "B200"], serialized=True)
    class Model:
        @modal.method()
        def run(self, x):
            return x

    assert isinstance(Model, _ClsWrapper)
    assert Model._retries == ["A100", "B200"]


def test_method_access_yields_ladder_method(app):
    @app.cls(gpu="T4", retries=["A100"], serialized=True)
    class Model:
        @modal.method()
        def run(self, x):
            return x

    method = Model().run
    assert isinstance(method, GPURetryMethod)
    # mirrors Modal's .remote: callable with an .aio variant
    assert callable(method.remote)
    assert hasattr(method.remote, "aio")
    assert hasattr(method, "map")


def test_bound_routes_base_and_tier_to_real_functions(app):
    @app.cls(gpu="T4", retries=["A100"], serialized=True)
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
    @app.cls(gpu="T4", retries=3, serialized=True)
    class Model:
        @modal.method()
        def run(self, x):
            return x

    # native passthrough -> a real modal Cls, not our wrapper
    assert isinstance(Model, modal.Cls)
    assert not isinstance(Model, _ClsWrapper)


def test_no_retries_passes_through_to_native_cls(app):
    @app.cls(gpu="T4", serialized=True)
    class Model:
        @modal.method()
        def run(self, x):
            return x

    assert isinstance(Model, modal.Cls)


def test_function_with_list_retries_returns_ladder_method(app):
    @app.function(gpu="T4", retries=["A100"], serialized=True)
    def f(x):
        return x

    assert isinstance(f, GPURetryMethod)
    assert isinstance(f._bound(None), modal.Function)
    assert isinstance(f._bound("A100"), modal.Function)


def test_function_int_retries_passes_through(app):
    @app.function(gpu="T4", retries=2, serialized=True)
    def f(x):
        return x

    assert isinstance(f, modal.Function)
    assert not isinstance(f, GPURetryMethod)


def test_ensure_pkg_in_image_appends_self_to_image():
    calls = []

    class FakeImage:
        def pip_install(self, *pkgs):
            calls.append(pkgs)
            return self

    kwargs = {"image": FakeImage(), "gpu": "T4"}
    _ensure_pkg_in_image(kwargs)
    assert calls == [("modal-gpu-retry",)]
    assert kwargs["gpu"] == "T4"  # other kwargs untouched


def test_ensure_pkg_in_image_noop_without_image():
    kwargs = {"gpu": "T4"}
    _ensure_pkg_in_image(kwargs)
    assert kwargs == {"gpu": "T4"}


def test_cls_auto_installs_self_into_image(app, monkeypatch):
    calls = []
    original_pip_install = modal.Image.pip_install

    def spy(self, *pkgs, **kw):
        calls.append(pkgs)
        return original_pip_install(self, *pkgs, **kw)

    monkeypatch.setattr(modal.Image, "pip_install", spy)

    @app.cls(gpu="T4", retries=["A100"], image=modal.Image.debian_slim(), serialized=True)
    class Model:
        @modal.method()
        def run(self, x):
            return x

    assert ("modal-gpu-retry",) in calls


def test_function_auto_installs_self_into_image(app, monkeypatch):
    calls = []
    original_pip_install = modal.Image.pip_install

    def spy(self, *pkgs, **kw):
        calls.append(pkgs)
        return original_pip_install(self, *pkgs, **kw)

    monkeypatch.setattr(modal.Image, "pip_install", spy)

    @app.function(gpu="T4", retries=["A100"], image=modal.Image.debian_slim(), serialized=True)
    def f(x):
        return x

    assert ("modal-gpu-retry",) in calls
