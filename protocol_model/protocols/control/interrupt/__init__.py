"""Edge-triggered interrupt notification interface."""

from .definition import (
    INTERRUPT_NOTIFICATION_FAMILY,
    InterruptNotificationConfig,
    build_interrupt_notification_interface,
)

__all__ = [
    "INTERRUPT_NOTIFICATION_FAMILY",
    "InterruptNotificationConfig",
    "build_interrupt_notification_interface",
]
