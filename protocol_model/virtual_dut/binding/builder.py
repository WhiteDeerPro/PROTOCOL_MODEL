"""Construction root for immutable VirtualDut declarations."""

from __future__ import annotations

from protocol_model.interface import InterfaceProtocol
from protocol_model.semantics import SemanticFragment

from ..attachments.base import InterfaceAttachment
from ..backend.base import VirtualDutBackend
from ..boundary.module import DutBehaviorTag, VirtualDut
from ..boundary.port import InterfacePort
from .port import InterfaceAttachmentBinding


class VirtualDutBuilder:
    """Assemble ports, local attachment bindings, and an optional backend."""

    def __init__(self, name: str) -> None:
        if not name:
            raise ValueError("VirtualDutBuilder requires a name")
        self.name = name
        self._ports: dict[str, InterfacePort] = {}
        self._bindings: dict[str, InterfaceAttachmentBinding] = {}
        self._backend: VirtualDutBackend | None = None
        self._behavior_tags: frozenset[DutBehaviorTag] = frozenset()
        self._semantics: SemanticFragment | None = None
        self._subsystem: object | None = None
        self._description = ""

    def add_port(self, port: InterfacePort) -> "VirtualDutBuilder":
        if not isinstance(port, InterfacePort):
            raise TypeError("VirtualDutBuilder.add_port requires an InterfacePort")
        if port.name in self._ports:
            raise ValueError(f"duplicate VirtualDut port {port.name!r}")
        self._ports[port.name] = port
        return self

    def port(
        self,
        name: str,
        protocol: InterfaceProtocol,
        role: str,
        *,
        capability: object | None = None,
        clock_domain: str | None = None,
        reset_domain: str | None = None,
    ) -> "VirtualDutBuilder":
        return self.add_port(
            InterfacePort(
                name=name,
                protocol=protocol,
                role=role,
                capability=capability,
                clock_domain=clock_domain,
                reset_domain=reset_domain,
            )
        )

    def bind(self, binding: InterfaceAttachmentBinding) -> "VirtualDutBuilder":
        if not isinstance(binding, InterfaceAttachmentBinding):
            raise TypeError(
                "VirtualDutBuilder.bind requires an InterfaceAttachmentBinding"
            )
        if binding.name in self._bindings:
            raise ValueError(f"duplicate attachment binding {binding.name!r}")
        existing = self._ports.get(binding.name)
        if existing is None:
            self._ports[binding.name] = binding.port
        elif existing != binding.port:
            raise ValueError(
                f"attachment binding for {binding.name!r} disagrees with its port"
            )
        self._bindings[binding.name] = binding
        return self

    def bind_port(
        self, name: str, attachment: InterfaceAttachment
    ) -> "VirtualDutBuilder":
        try:
            port = self._ports[name]
        except KeyError as exc:
            raise ValueError(
                f"cannot bind attachment to unknown port {name!r}"
            ) from exc
        return self.bind(InterfaceAttachmentBinding(port, attachment))

    def with_backend(self, backend: VirtualDutBackend) -> "VirtualDutBuilder":
        if self._backend is not None:
            raise ValueError("VirtualDut backend is already configured")
        if not isinstance(backend, VirtualDutBackend):
            raise TypeError("VirtualDut backend must implement VirtualDutBackend")
        self._backend = backend
        return self

    def with_behavior_tags(
        self, *behavior_tags: DutBehaviorTag
    ) -> "VirtualDutBuilder":
        self._behavior_tags = frozenset(
            item if isinstance(item, DutBehaviorTag) else DutBehaviorTag(item)
            for item in behavior_tags
        )
        return self

    def with_semantics(
        self, semantics: SemanticFragment
    ) -> "VirtualDutBuilder":
        self._semantics = semantics
        return self

    def with_subsystem(self, subsystem: object) -> "VirtualDutBuilder":
        self._subsystem = subsystem
        return self

    def describe(self, description: str) -> "VirtualDutBuilder":
        self._description = description
        return self

    def build(self) -> VirtualDut:
        return VirtualDut(
            self.name,
            self._ports,
            behavior_tags=self._behavior_tags,
            backend=self._backend,
            semantics=self._semantics,
            subsystem=self._subsystem,
            description=self._description,
            bindings=self._bindings,
        )
