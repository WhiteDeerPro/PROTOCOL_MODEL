"""Control-oriented point-to-point interface protocols."""

from .interrupt import (
    INTERRUPT_NOTIFICATION_FAMILY,
    InterruptNotificationConfig,
    build_interrupt_notification_interface,
)

__all__ = [
    "INTERRUPT_NOTIFICATION_FAMILY",
    "InterruptNotificationConfig",
    "build_interrupt_notification_interface",
]
