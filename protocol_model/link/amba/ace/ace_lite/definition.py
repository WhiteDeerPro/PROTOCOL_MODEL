"""ACE-Lite ordinary-data transactions over the AXI4 five-channel core."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.link import (
    ChannelProtocol,
    EventField,
    EventSchema,
    LinkProtocol,
)
from protocol_model.link.amba.axi.axi4 import Axi4Config, build_axi4_link
from protocol_model.semantics import (
    BitVectorDomain,
    ConstraintKind,
    ConstraintScope,
    EventConstraint,
    SemanticConstraint,
    SemanticFragment,
)


ACE_LITE_FAMILY = "amba.ace_lite"


@dataclass(frozen=True)
class AceLiteDataConfig:
    """Widths for the current non-barrier ACE-Lite data profile."""

    address_width: int = 32
    data_width: int = 64
    id_width: int = 4

    def __post_init__(self) -> None:
        self.axi4_config()

    def axi4_config(self) -> Axi4Config:
        return Axi4Config(
            address_width=self.address_width,
            data_width=self.data_width,
            id_width=self.id_width,
        )


def _is_normal_transaction(event) -> bool:
    return int(event.payload["bar"]) & 0b01 == 0


def _cacheable_domain_is_legal(event) -> bool:
    cacheable = int(event.payload["cache"]) & 0b1100 != 0
    system_domain = int(event.payload["domain"]) == 0b11
    return not (cacheable and system_domain)


def _read_snoop_domain_is_supported(event) -> bool:
    # ARSNOOP=0000 is ReadNoSnoop in Non-shareable/System domains and
    # ReadOnce in Inner/Outer Shareable domains.
    return int(event.payload["snoop"]) == 0


def _write_snoop_domain_is_supported(event) -> bool:
    snoop = int(event.payload["snoop"])
    domain = int(event.payload["domain"])
    # AWSNOOP=000 selects WriteNoSnoop or WriteUnique by domain.
    # AWSNOOP=001 is WriteLineUnique and is shareable only.
    return snoop == 0 or (snoop == 1 and domain in (0b01, 0b10))


def _coherent_address_schema(
    base: EventSchema, *, read: bool
) -> EventSchema:
    fields = dict(base.fields)
    fields.update(
        {
            "snoop": EventField(
                "snoop",
                BitVectorDomain(4 if read else 3),
                "ACE-Lite AxSNOOP encoding",
            ),
            "domain": EventField(
                "domain", BitVectorDomain(2), "ACE-Lite shareability domain"
            ),
            "bar": EventField(
                "bar", BitVectorDomain(2), "ACE-Lite barrier attributes"
            ),
        }
    )
    operation_constraint = EventConstraint(
        "data_profile_snoop_domain",
        _read_snoop_domain_is_supported
        if read
        else _write_snoop_domain_is_supported,
        "snoop/domain combination is outside the current ACE-Lite data profile",
    )
    return EventSchema(
        base.name,
        fields,
        base.key,
        (
            *base.constraints,
            EventConstraint(
                "data_profile_barrier",
                _is_normal_transaction,
                "barrier transactions are outside the current ACE-Lite data profile",
            ),
            EventConstraint(
                "cacheable_system_domain",
                _cacheable_domain_is_legal,
                "a cacheable ACE-Lite transaction cannot use System domain",
            ),
            operation_constraint,
        ),
    )


def build_ace_lite_data_link(
    config: AceLiteDataConfig | None = None,
) -> LinkProtocol:
    """Build the executable ordinary-data subset of an ACE-Lite interface.

    The explicit ``data`` name is part of the contract: this builder does not
    accept ACE-Lite barrier or cache-maintenance transactions.
    """

    config = config or AceLiteDataConfig()
    axi4 = build_axi4_link(config.axi4_config())
    channels = {}
    for name, channel in axi4.channels.items():
        event = channel.event
        if name in ("AR", "AW"):
            event = _coherent_address_schema(event, read=name == "AR")
        manager_to_interconnect = name in ("AR", "AW", "W")
        channels[name] = ChannelProtocol(
            name,
            "manager" if manager_to_interconnect else "coherent_interconnect",
            "coherent_interconnect" if manager_to_interconnect else "manager",
            event,
        )

    fragment = SemanticFragment(
        "ace_lite.data_profile",
        constraints=(
            SemanticConstraint(
                "ace_lite.address_control",
                "AxSNOOP, AxDOMAIN, and AxBAR form a supported "
                "ordinary-data operation",
                ConstraintScope.EVENT,
                targets=("AR", "AW"),
            ),
            SemanticConstraint(
                "ace_lite.axi_transport",
                "ordinary ACE-Lite data transactions retain AXI4 burst, "
                "ID, join, and response relations",
                ConstraintScope.LINK,
                kind=ConstraintKind.RELATION,
                targets=("AR", "R", "AW", "W", "B"),
            ),
        ),
        sources=("Arm IHI 0022H D11; ordinary data transaction profile",),
    )
    return LinkProtocol.define(
        "ace_lite_data",
        family=ACE_LITE_FAMILY,
        roles=frozenset(("manager", "coherent_interconnect")),
        channels=channels,
        fragments=(axi4.semantics, fragment),
        parameters={
            **axi4.parameters,
            "barrier_transactions": False,
            "cache_maintenance_operations": False,
            "snoop_channels": False,
        },
        monitors=axi4.monitors,
    )
