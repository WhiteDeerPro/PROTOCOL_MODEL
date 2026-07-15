"""Executable backend contract for one concrete VirtualDut."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Mapping, TYPE_CHECKING

from .transition import DutTransition, PortInput

if TYPE_CHECKING:
    from ..binding.port import PortAttachmentBinding


class VirtualDutModel(ABC):
    """Minimal protocol-visible backend for one concrete module."""

    @abstractmethod
    def initial_state(self) -> object:
        raise NotImplementedError

    @abstractmethod
    def accept(self, state: object, action: PortInput) -> DutTransition:
        raise NotImplementedError

    def is_quiescent(self, state: object) -> bool:
        return True

    def local_attachment_bindings(
        self,
    ) -> Mapping[str, "PortAttachmentBinding"] | None:
        """Bindings consumed by this backend, if attachment-aware.

        Raw canonical-event and external models return ``None``.  Backends
        that decode through attachments expose the exact immutable bindings so
        VirtualDut construction can reject a split configuration.
        """

        return None
