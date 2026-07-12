"""APB3/APB4 schemas and two-phase monitor elaboration."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.patterns import ClockedTwoPhaseTransfer
from protocol_model.domains import (
    BitVectorDomain,
    ConstantDomain,
    EnumDomain,
    EventSpace,
    NaturalDomain,
)
from protocol_model.core import CanonicalEvent
from protocol_model.protocols.spec import ChannelSpec, ProtocolRequirement, ProtocolSpec


@dataclass(frozen=True)
class ApbConfig:
    version: int
    address_width: int = 32
    data_width: int = 32
    generated_max_wait: int = 3

    def __post_init__(self) -> None:
        if self.version not in {3, 4}:
            raise ValueError("APB version must be 3 or 4")
        if not 1 <= self.address_width <= 32:
            raise ValueError("APB address width must be in [1, 32]")
        if self.data_width not in {8, 16, 32}:
            raise ValueError("APB data width must be 8, 16, or 32 bits")
        if self.generated_max_wait < 0:
            raise ValueError("generated_max_wait must be non-negative")

    @property
    def strobe_width(self) -> int:
        return self.data_width // 8


@dataclass(frozen=True)
class ApbPinSample:
    cycle: int
    presetn: bool
    psel: bool
    penable: bool
    pwrite: bool
    paddr: int
    pwdata: int
    pready: bool
    prdata: int
    pslverr: bool
    pstrb: int | None = None
    pprot: int | None = None
    source: str = "waveform"

    def __post_init__(self) -> None:
        for name in ("presetn", "psel", "penable", "pwrite", "pready", "pslverr"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be bool")


def _request(sample: ApbPinSample, config: ApbConfig) -> CanonicalEvent:
    payload = {
        "addr": sample.paddr,
        "write": sample.pwrite,
        "wdata": sample.pwdata if sample.pwrite else 0,
    }
    if config.version == 4:
        payload.update(
            {
                "strb": sample.pstrb if sample.pwrite else 0,
                "prot": sample.pprot,
            }
        )
    return CanonicalEvent("APB_REQUEST", None, payload)


def _completion(
    request: CanonicalEvent,
    sample: ApbPinSample,
    wait_cycles: int,
    config: ApbConfig,
) -> CanonicalEvent:
    payload = dict(request.payload)
    payload.update(
        {
            "rdata": sample.prdata if not request.payload["write"] else 0,
            "error": sample.pslverr,
            "wait_cycles": wait_cycles,
        }
    )
    return CanonicalEvent(
        "APB_TRANSFER",
        None,
        payload,
        source=sample.source,
        clock="pclk",
        timestamp=sample.cycle,
        sequence=sample.cycle,
    )


def _sample_reason(sample: ApbPinSample, config: ApbConfig) -> str | None:
    address = BitVectorDomain(config.address_width).explain(sample.paddr)
    if address:
        return f"PADDR: {address}"
    data_domain = BitVectorDomain(config.data_width)
    for name, value in (("PWDATA", sample.pwdata), ("PRDATA", sample.prdata)):
        reason = data_domain.explain(value)
        if reason:
            return f"{name}: {reason}"
    if config.version == 3:
        if sample.pstrb is not None or sample.pprot is not None:
            return "APB3 does not contain PSTRB or PPROT"
    else:
        if sample.pstrb is None or sample.pprot is None:
            return "APB4 requires PSTRB and PPROT"
        reason = BitVectorDomain(config.strobe_width).explain(sample.pstrb)
        if reason:
            return f"PSTRB: {reason}"
        reason = BitVectorDomain(3).explain(sample.pprot)
        if reason:
            return f"PPROT: {reason}"
        if sample.psel and not sample.pwrite and sample.pstrb != 0:
            return "PSTRB must be zero during an APB read transfer"
    return None


def build_apb_spec(config: ApbConfig) -> ProtocolSpec:
    payload = {
        "addr": BitVectorDomain(config.address_width),
        "write": EnumDomain((False, True)),
        "wdata": BitVectorDomain(config.data_width),
        "rdata": BitVectorDomain(config.data_width),
        "error": EnumDomain((False, True)),
        "wait_cycles": NaturalDomain(config.generated_max_wait),
    }
    if config.version == 4:
        payload.update(
            {
                "strb": BitVectorDomain(config.strobe_width),
                "prot": BitVectorDomain(3),
            }
        )
    transfer = EventSpace("APB_TRANSFER", ConstantDomain(None), payload)
    monitor = ClockedTwoPhaseTransfer(
        f"apb{config.version}.two_phase",
        transfer,
        cycle_of=lambda sample: sample.cycle,
        reset_asserted=lambda sample: not sample.presetn,
        selected=lambda sample: sample.psel,
        enabled=lambda sample: sample.penable,
        ready=lambda sample: sample.pready,
        inactive_during_reset=lambda sample: not sample.psel and not sample.penable,
        validate_sample=lambda sample: _sample_reason(sample, config),
        request_of=lambda sample: _request(sample, config),
        completion_of=lambda request, sample, waits: _completion(
            request, sample, waits, config
        ),
    )
    requirements = [
        ProtocolRequirement(
            "two_phase",
            "every transfer has one SETUP cycle followed by ACCESS",
            "ClockedTwoPhaseTransfer",
            "implemented",
        ),
        ProtocolRequirement(
            "wait_states",
            "PREADY LOW extends ACCESS without changing request signals",
            "ClockedTwoPhaseTransfer",
            "implemented",
        ),
        ProtocolRequirement(
            "error_sampling",
            "PSLVERR is sampled only on the completing ACCESS cycle",
            "CompletionProjection",
            "implemented",
        ),
        ProtocolRequirement(
            "reset",
            "PRESETn LOW returns the interface to IDLE",
            "ClockedTwoPhaseTransfer",
            "implemented",
        ),
    ]
    if config.version == 4:
        requirements.extend(
            (
                ProtocolRequirement(
                    "write_strobes",
                    "PSTRB has one bit per byte and is zero on reads",
                    "SampleInvariant",
                    "implemented",
                ),
                ProtocolRequirement(
                    "protection",
                    "PPROT is a stable three-bit request attribute",
                    "BitVectorDomain",
                    "implemented",
                ),
            )
        )
    return ProtocolSpec(
        f"apb{config.version}",
        frozenset({"requester", "completer"}),
        {
            "APB": ChannelSpec(
                "APB", "requester", "completer", transfer, monitor
            )
        },
        tuple(requirements),
        {
            "version": config.version,
            "address_width": config.address_width,
            "data_width": config.data_width,
        },
    )


def build_apb3_spec(
    *, address_width: int = 32, data_width: int = 32, generated_max_wait: int = 3
) -> ProtocolSpec:
    return build_apb_spec(
        ApbConfig(3, address_width, data_width, generated_max_wait)
    )


def build_apb4_spec(
    *, address_width: int = 32, data_width: int = 32, generated_max_wait: int = 3
) -> ProtocolSpec:
    return build_apb_spec(
        ApbConfig(4, address_width, data_width, generated_max_wait)
    )
