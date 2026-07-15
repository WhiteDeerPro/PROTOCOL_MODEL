"""Construction root for immutable VirtualDut declarations."""

from __future__ import annotations

from protocol_model.link import LinkProtocol
from protocol_model.semantics import SemanticFragment

from ..attachments.base import ProtocolAttachment
from ..backend.base import VirtualDutModel
from ..boundary.module import DutFacet, VirtualDut
from ..boundary.port import ProtocolPort
from .port import PortAttachmentBinding


class VirtualDutBuilder:
    """Assemble ports, local attachment bindings, and an optional backend."""

    def __init__(self, name: str) -> None:
        if not name:
            raise ValueError("VirtualDutBuilder requires a name")
        self.name = name
        self._ports: dict[str, ProtocolPort] = {}
        self._bindings: dict[str, PortAttachmentBinding] = {}
        self._model: VirtualDutModel | None = None
        self._facets: frozenset[DutFacet] = frozenset()
        self._semantics: SemanticFragment | None = None
        self._subsystem: object | None = None
        self._description = ""

    def add_port(self, port: ProtocolPort) -> "VirtualDutBuilder":
        if not isinstance(port, ProtocolPort):
            raise TypeError("VirtualDutBuilder.add_port requires a ProtocolPort")
        if port.name in self._ports:
            raise ValueError(f"duplicate VirtualDut port {port.name!r}")
        self._ports[port.name] = port
        return self

    def port(
        self,
        name: str,
        protocol: LinkProtocol,
        role: str,
        *,
        capability: object | None = None,
        clock_domain: str | None = None,
        reset_domain: str | None = None,
    ) -> "VirtualDutBuilder":
        return self.add_port(
            ProtocolPort(
                name=name,
                protocol=protocol,
                role=role,
                capability=capability,
                clock_domain=clock_domain,
                reset_domain=reset_domain,
            )
        )

    def bind(self, binding: PortAttachmentBinding) -> "VirtualDutBuilder":
        if not isinstance(binding, PortAttachmentBinding):
            raise TypeError("VirtualDutBuilder.bind requires a PortAttachmentBinding")
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
        self, name: str, attachment: ProtocolAttachment
    ) -> "VirtualDutBuilder":
        try:
            port = self._ports[name]
        except KeyError as exc:
            raise ValueError(
                f"cannot bind attachment to unknown port {name!r}"
            ) from exc
        return self.bind(PortAttachmentBinding(port, attachment))

    def with_model(self, model: VirtualDutModel) -> "VirtualDutBuilder":
        if self._model is not None:
            raise ValueError("VirtualDut backend model is already configured")
        if not isinstance(model, VirtualDutModel):
            raise TypeError("VirtualDut backend must implement VirtualDutModel")
        self._model = model
        return self

    def with_facets(self, *facets: DutFacet) -> "VirtualDutBuilder":
        self._facets = frozenset(
            item if isinstance(item, DutFacet) else DutFacet(item)
            for item in facets
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
            facets=self._facets,
            model=self._model,
            semantics=self._semantics,
            subsystem=self._subsystem,
            description=self._description,
            bindings=self._bindings,
        )
