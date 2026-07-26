"""Protocol-independent interrupt-notification operations for VirtualDut ports.

The operation is independent of its eventual interface encoding, while its
``interrupt_id`` and ``priority`` fields intentionally keep this SPI within
the interrupt/control domain.  A future generic event bus should use a
different operation form instead of widening this one implicitly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from protocol_model.semantics import CanonicalEvent, SemanticFault

from .base import AttachmentEmission, InterfaceAttachment


def _require_non_negative(value: int, *, subject: str) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ValueError(f"{subject} must be a non-negative integer")


@dataclass(frozen=True)
class Notification:
    """One retained interrupt edge, independent of its interface encoding."""

    notification_ref: int
    interrupt_id: int
    priority: int
    attributes: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_negative(
            self.notification_ref, subject="notification reference"
        )
        _require_non_negative(self.interrupt_id, subject="interrupt id")
        _require_non_negative(self.priority, subject="interrupt priority")
        object.__setattr__(
            self, "attributes", MappingProxyType(dict(self.attributes))
        )


@dataclass(frozen=True)
class NotificationCompletion:
    """Receiver completion correlated to one notification occurrence."""

    notification_ref: int
    interrupt_id: int

    def __post_init__(self) -> None:
        _require_non_negative(
            self.notification_ref, subject="notification reference"
        )
        _require_non_negative(self.interrupt_id, subject="interrupt id")


@dataclass(frozen=True)
class NotificationDecode:
    state: object
    notification: Notification | None = None
    reply_context: object | None = None
    fault: SemanticFault | None = None


@dataclass(frozen=True)
class NotificationCompletionDecode:
    state: object
    completion: NotificationCompletion | None = None
    fault: SemanticFault | None = None


class NotificationHandlerAttachment(InterfaceAttachment, ABC):
    """Decode incoming notifications and encode local completion."""

    @abstractmethod
    def decode_notification(
        self, state: object, event: CanonicalEvent
    ) -> NotificationDecode:
        raise NotImplementedError

    @abstractmethod
    def encode_completion(
        self, state: object, context: object | None
    ) -> AttachmentEmission:
        raise NotImplementedError


class NotificationNotifierAttachment(InterfaceAttachment, ABC):
    """Encode notifications and decode their correlated completion."""

    @abstractmethod
    def encode_notification(
        self, state: object, notification: Notification
    ) -> AttachmentEmission:
        raise NotImplementedError

    @abstractmethod
    def decode_completion(
        self, state: object, event: CanonicalEvent
    ) -> NotificationCompletionDecode:
        raise NotImplementedError


__all__ = [
    "Notification",
    "NotificationCompletion",
    "NotificationCompletionDecode",
    "NotificationDecode",
    "NotificationHandlerAttachment",
    "NotificationNotifierAttachment",
]
