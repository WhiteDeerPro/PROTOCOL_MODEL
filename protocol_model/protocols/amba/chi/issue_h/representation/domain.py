"""Runtime classification for CHI Issue H messages and hop-local flits.

Issue H separates protocol messages, which are placed in routable packets and
then transport flits, from link-maintenance flits that terminate at one hop.
This module is the runtime authority for that distinction.

The marker is intentionally structural.  A newly implemented object declares
its protocol channel, representation kind, and opcode.  The kind prevents a
typed protocol message from being mistaken for the Link flit that later
carries its Network packet.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Protocol, runtime_checkable


class ChiChannelKind(str, Enum):
    """The four protocol channel kinds defined by CHI Issue H."""

    REQ = "req"
    RSP = "rsp"
    SNP = "snp"
    DAT = "dat"


class ChiChannelItemKind(str, Enum):
    """Which representation boundary one channel item occupies."""

    PROTOCOL_MESSAGE = "protocol_message"
    PROTOCOL_FLIT = "protocol_flit"
    LINK_MAINTENANCE_FLIT = "link_maintenance_flit"


@runtime_checkable
class ChiChannelItem(Protocol):
    """Structural marker common to messages and both Link-flit forms."""

    chi_channel: ChiChannelKind
    chi_item_kind: ChiChannelItemKind

    @property
    def opcode(self) -> object:
        ...


@runtime_checkable
class ChiProtocolMessage(ChiChannelItem, Protocol):
    """A typed protocol message before Network-layer routing is attached."""


@runtime_checkable
class ChiChannelProfile(Protocol):
    """One channel-local representation profile understood by the domain."""

    channel: ChiChannelKind

    def explain(self, message: object) -> tuple[str, ...]:
        ...


@dataclass(frozen=True)
class ChiChannelClassification:
    """Normalized runtime classification of one channel item."""

    channel: ChiChannelKind
    item_kind: ChiChannelItemKind

    @property
    def is_message(self) -> bool:
        return self.item_kind is ChiChannelItemKind.PROTOCOL_MESSAGE

    @property
    def is_protocol_flit(self) -> bool:
        return self.item_kind is ChiChannelItemKind.PROTOCOL_FLIT

    @property
    def is_link_maintenance(self) -> bool:
        return (
            self.item_kind
            is ChiChannelItemKind.LINK_MAINTENANCE_FLIT
        )


@lru_cache(maxsize=None)
def _default_profile(channel: ChiChannelKind) -> ChiChannelProfile | None:
    """Resolve implemented profiles lazily to avoid representation cycles."""

    if channel is ChiChannelKind.REQ:
        from .req import ChiIssueHReqProfile

        return ChiIssueHReqProfile()
    if channel is ChiChannelKind.RSP:
        from .rsp import ChiIssueHRspProfile

        return ChiIssueHRspProfile()
    if channel is ChiChannelKind.DAT:
        from .dat import ChiIssueHDatProfile

        return ChiIssueHDatProfile()
    if channel is ChiChannelKind.SNP:
        from .snp import ChiIssueHSnpProfile

        return ChiIssueHSnpProfile()
    return None


class ChiIssueHChannelDomain:
    """Classify channel items and dispatch message-profile validation."""

    def classify(self, item: object) -> ChiChannelClassification:
        """Return the declared channel domain of ``item``.

        Classification does not imply that a selected profile implements the
        item's opcode.  That decision is made by :meth:`explain_profile`.
        """

        if not isinstance(item, ChiChannelItem):
            raise TypeError(
                "CHI channel item must declare chi_channel, "
                "chi_item_kind, and opcode"
            )
        try:
            channel = ChiChannelKind(item.chi_channel)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "CHI item declares an unknown channel"
            ) from error
        try:
            item_kind = ChiChannelItemKind(item.chi_item_kind)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "CHI item declares an unknown representation kind"
            ) from error
        return ChiChannelClassification(channel, item_kind)

    def default_profile(
        self,
        channel: ChiChannelKind,
    ) -> ChiChannelProfile | None:
        """Return the currently implemented profile for ``channel``."""

        return _default_profile(ChiChannelKind(channel))

    def explain_profile(
        self,
        message: object,
        profile: ChiChannelProfile | None = None,
    ) -> tuple[str, ...]:
        """Return profile errors after first checking the runtime domain."""

        classification = self.classify(message)
        if not classification.is_message:
            subject = (
                "link-maintenance flits are hop-local"
                if classification.is_link_maintenance
                else "protocol Link flits must be unwrapped to their message"
            )
            return (
                f"{subject} and do not directly use a protocol message "
                "profile",
            )
        selected = profile or self.default_profile(classification.channel)
        if selected is None:
            return (
                f"no representation profile is installed for the "
                f"{classification.channel.name} channel",
            )
        try:
            profile_channel = ChiChannelKind(selected.channel)
        except (AttributeError, TypeError, ValueError):
            return ("representation profile does not declare a known channel",)
        if profile_channel is not classification.channel:
            return (
                f"{profile_channel.name} profile cannot validate a "
                f"{classification.channel.name} protocol message",
            )
        return tuple(selected.explain(message))

    def profile_contains(
        self,
        message: object,
        profile: ChiChannelProfile | None = None,
    ) -> bool:
        """Return whether ``message`` belongs to the selected profile."""

        return not self.explain_profile(message, profile)

    def require_profile(
        self,
        message: object,
        profile: ChiChannelProfile | None = None,
    ) -> None:
        """Raise when ``message`` does not belong to the selected profile."""

        reasons = self.explain_profile(message, profile)
        if reasons:
            raise ValueError("; ".join(reasons))


CHI_ISSUE_H_CHANNEL_DOMAIN = ChiIssueHChannelDomain()


__all__ = [
    "CHI_ISSUE_H_CHANNEL_DOMAIN",
    "ChiChannelKind",
    "ChiChannelItem",
    "ChiChannelItemKind",
    "ChiChannelProfile",
    "ChiIssueHChannelDomain",
    "ChiChannelClassification",
    "ChiProtocolMessage",
]
