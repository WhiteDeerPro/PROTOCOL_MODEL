"""Registry of reusable VirtualDut primitive factories."""

from __future__ import annotations

from typing import Callable

from .primitives import FunctionResponder, ScriptedSource, Sink


class VirtualDutRegistry:
    def __init__(self):
        self._factories: dict[str, Callable[..., object]] = {}

    def register(self, name: str, factory: Callable[..., object]) -> None:
        if name in self._factories:
            raise ValueError(f"VirtualDut factory {name!r} is already registered")
        self._factories[name] = factory

    def create(self, primitive: str, **configuration):
        try:
            factory = self._factories[primitive]
        except KeyError as error:
            raise KeyError(f"unknown VirtualDut primitive {primitive!r}") from error
        return factory(**configuration)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))

    @classmethod
    def standard(cls) -> "VirtualDutRegistry":
        registry = cls()
        registry.register("sink", Sink)
        registry.register("scripted_source", ScriptedSource)
        registry.register("function_responder", FunctionResponder)
        return registry
