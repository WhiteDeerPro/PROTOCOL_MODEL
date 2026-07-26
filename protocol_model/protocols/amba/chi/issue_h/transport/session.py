"""Atomic execution of one CHI Issue H directed transport link."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from protocol_model.observation import AtomicFrame
from protocol_model.semantics import (
    ConstraintKind,
    ConstraintScope,
    ResourceDecl,
    SemanticComponent,
    SemanticConstraint,
    SemanticFault,
    SemanticFragment,
    SemanticStep,
)

from ..representation import (
    CHI_ISSUE_H_CHANNEL_DOMAIN,
    ChiProtocolFlit,
)
from .link import (
    ChiDatChannelSignals,
    ChiDatTransfer,
    ChiLinkActivationPhase,
    ChiLinkActivationSignals,
    ChiReqChannelSignals,
    ChiReqTransfer,
    ChiRspChannelSignals,
    ChiRspTransfer,
    ChiSnpChannelSignals,
    ChiSnpTransfer,
    ChiTransportLink,
    ChiTransportTransfer,
)


_ALLOWED_PHASES = {
    ChiLinkActivationPhase.STOP: frozenset(
        (ChiLinkActivationPhase.STOP, ChiLinkActivationPhase.ACTIVATE)
    ),
    ChiLinkActivationPhase.ACTIVATE: frozenset(
        (ChiLinkActivationPhase.ACTIVATE, ChiLinkActivationPhase.RUN)
    ),
    ChiLinkActivationPhase.RUN: frozenset(
        (ChiLinkActivationPhase.RUN, ChiLinkActivationPhase.DEACTIVATE)
    ),
    ChiLinkActivationPhase.DEACTIVATE: frozenset(
        (ChiLinkActivationPhase.DEACTIVATE, ChiLinkActivationPhase.STOP)
    ),
}


def _protocol_representation_reasons(
    flit: object,
    profile: object,
) -> tuple[str, ...]:
    """Validate the Network packet carried by one protocol Link flit."""

    if not isinstance(flit, ChiProtocolFlit):
        return ("protocol Link flit does not carry a CHI Network packet",)
    return flit.packet.explain_profile(profile)


@dataclass(frozen=True)
class ChiLinkActivationState:
    """Link-wide activation authority shared by every configured channel."""

    phase: ChiLinkActivationPhase
    epoch: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.phase, ChiLinkActivationPhase):
            raise TypeError("activation state requires ChiLinkActivationPhase")
        if (
            not isinstance(self.epoch, int)
            or isinstance(self.epoch, bool)
            or self.epoch < 0
        ):
            raise ValueError("activation epoch must be non-negative")


@dataclass(frozen=True)
class ChiReqChannelState:
    """Dedicated L-Credits owned by the REQ Transmitter."""

    usable_credits_by_plane: tuple[int, ...]

    def __post_init__(self) -> None:
        credits = tuple(self.usable_credits_by_plane)
        if any(
            not isinstance(item, int) or isinstance(item, bool) or item < 0
            for item in credits
        ):
            raise ValueError("usable REQ L-Credit counts must be non-negative")
        object.__setattr__(self, "usable_credits_by_plane", credits)


@dataclass(frozen=True)
class ChiDatChannelState:
    """Dedicated scalar L-Credits owned by the DAT Transmitter."""

    usable_credits: int = 0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.usable_credits, int)
            or isinstance(self.usable_credits, bool)
            or self.usable_credits < 0
        ):
            raise ValueError("usable DAT L-Credits must be non-negative")


@dataclass(frozen=True)
class ChiRspChannelState:
    """Dedicated scalar L-Credits owned by the RSP Transmitter."""

    usable_credits: int = 0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.usable_credits, int)
            or isinstance(self.usable_credits, bool)
            or self.usable_credits < 0
        ):
            raise ValueError("usable RSP L-Credits must be non-negative")


@dataclass(frozen=True)
class ChiSnpChannelState:
    """Dedicated scalar L-Credits owned by the SNP Transmitter."""

    usable_credits: int = 0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.usable_credits, int)
            or isinstance(self.usable_credits, bool)
            or self.usable_credits < 0
        ):
            raise ValueError("usable SNP L-Credits must be non-negative")


@dataclass(frozen=True)
class ChiTransportLinkState:
    """One atomic link state with link-wide and per-channel ownership."""

    activation: ChiLinkActivationState
    request: ChiReqChannelState | None
    last_tick: int | None = None
    data: ChiDatChannelState | None = None
    response: ChiRspChannelState | None = None
    snoop: ChiSnpChannelState | None = None


class ChiTransportLinkSession(
    SemanticComponent[
        AtomicFrame,
        ChiTransportLinkState,
        ChiTransportTransfer,
    ]
):
    """Validate activation and dedicated channel L-Credits for one hop.

    The session reads activation and every enabled channel from one
    ``AtomicFrame`` and commits one composite state.  A fault on one channel
    therefore cannot leave another channel or activation partially advanced.
    Each channel checks a send against its frame-start credits before adding
    same-frame grants.
    """

    def __init__(self, link: ChiTransportLink):
        if not isinstance(link, ChiTransportLink):
            raise TypeError("CHI link session requires ChiTransportLink")
        self.link = link
        self.name = f"{link.name}.chi_transport"
        self.semantics = self._build_semantics()

    def _build_semantics(self) -> SemanticFragment:
        profile = self.link.profile
        resources: list[ResourceDecl] = []
        constraints = [
            SemanticConstraint(
                f"{self.name}.activation_order",
                "link-wide LINKACTIVEREQ/LINKACTIVEACK follow STOP, "
                "ACTIVATE, RUN, DEACTIVATE, STOP",
                ConstraintScope.TRANSPORT,
                kind=ConstraintKind.RELATION,
                targets=(self.link.name,),
            )
        ]
        if profile.request is not None:
            resources.extend(
                ResourceDecl(
                    f"{self.link.name}.req_lcredit.rp{plane}",
                    ConstraintScope.TRANSPORT,
                    capacity=capacity,
                    description=(
                        "dedicated REQ L-Credits currently usable by the "
                        "transmitter"
                    ),
                    acquired_by=(f"REQ.LCRDV.RP{plane}",),
                    released_by=(f"REQ.FLITV.RP{plane}",),
                )
                for plane, capacity in enumerate(
                    profile.request.credit_capacities
                )
            )
            constraints.append(
                SemanticConstraint(
                    f"{self.name}.req_prior_credit",
                    "each REQ flit consumes a dedicated L-Credit held at "
                    "the start of the frame",
                    ConstraintScope.TRANSPORT,
                    kind=ConstraintKind.RESOURCE,
                    targets=(self.link.name,),
                )
            )
        if profile.data is not None:
            resources.append(
                ResourceDecl(
                    f"{self.link.name}.dat_lcredit",
                    ConstraintScope.TRANSPORT,
                    capacity=profile.data.credit_capacity,
                    description=(
                        "dedicated DAT L-Credits currently usable by the "
                        "transmitter"
                    ),
                    acquired_by=("DAT.LCRDV",),
                    released_by=("DAT.FLITV",),
                )
            )
            constraints.append(
                SemanticConstraint(
                    f"{self.name}.dat_prior_credit",
                    "each DAT flit consumes a dedicated L-Credit held at "
                    "the start of the frame",
                    ConstraintScope.TRANSPORT,
                    kind=ConstraintKind.RESOURCE,
                    targets=(self.link.name,),
                )
            )
        if profile.response is not None:
            resources.append(
                ResourceDecl(
                    f"{self.link.name}.rsp_lcredit",
                    ConstraintScope.TRANSPORT,
                    capacity=profile.response.credit_capacity,
                    description=(
                        "dedicated RSP L-Credits currently usable by the "
                        "transmitter"
                    ),
                    acquired_by=("RSP.LCRDV",),
                    released_by=("RSP.FLITV",),
                )
            )
            constraints.append(
                SemanticConstraint(
                    f"{self.name}.rsp_prior_credit",
                    "each RSP flit consumes a dedicated L-Credit held at "
                    "the start of the frame",
                    ConstraintScope.TRANSPORT,
                    kind=ConstraintKind.RESOURCE,
                    targets=(self.link.name,),
                )
            )
        if profile.snoop is not None:
            resources.append(
                ResourceDecl(
                    f"{self.link.name}.snp_lcredit",
                    ConstraintScope.TRANSPORT,
                    capacity=profile.snoop.credit_capacity,
                    description=(
                        "dedicated SNP L-Credits currently usable by the "
                        "transmitter"
                    ),
                    acquired_by=("SNP.LCRDV",),
                    released_by=("SNP.FLITV",),
                )
            )
            constraints.append(
                SemanticConstraint(
                    f"{self.name}.snp_prior_credit",
                    "each SNP flit consumes a dedicated L-Credit held at "
                    "the start of the frame",
                    ConstraintScope.TRANSPORT,
                    kind=ConstraintKind.RESOURCE,
                    targets=(self.link.name,),
                )
            )
        constraints.append(
            SemanticConstraint(
                f"{self.name}.deactivation_return",
                "all unused channel L-Credits are returned before the link "
                "re-enters STOP",
                ConstraintScope.TRANSPORT,
                kind=ConstraintKind.RELATION,
                targets=(self.link.name,),
            )
        )
        return SemanticFragment(
            f"{self.name}.semantics",
            constraints=tuple(constraints),
            resources=tuple(resources),
            sources=(
                "Arm IHI 0050 Issue H B13.8-B13.10, B14.2, and B14.5",
            ),
        )

    def initial_state(self) -> ChiTransportLinkState:
        profile = self.link.profile
        request_state = None
        if profile.request is not None:
            request_state = ChiReqChannelState(
                tuple(0 for _ in profile.request.credit_capacities)
            )
        data_state = (
            ChiDatChannelState() if profile.data is not None else None
        )
        response_state = (
            ChiRspChannelState() if profile.response is not None else None
        )
        snoop_state = (
            ChiSnpChannelState() if profile.snoop is not None else None
        )
        return ChiTransportLinkState(
            ChiLinkActivationState(ChiLinkActivationPhase.STOP),
            request_state,
            data=data_state,
            response=response_state,
            snoop=snoop_state,
        )

    def is_quiescent(self, state: ChiTransportLinkState) -> bool:
        request_quiet = state.request is None or not any(
            state.request.usable_credits_by_plane
        )
        data_quiet = state.data is None or state.data.usable_credits == 0
        response_quiet = (
            state.response is None or state.response.usable_credits == 0
        )
        snoop_quiet = (
            state.snoop is None or state.snoop.usable_credits == 0
        )
        return (
            state.activation.phase is ChiLinkActivationPhase.STOP
            and request_quiet
            and data_quiet
            and response_quiet
            and snoop_quiet
        )

    def resource_usage(self, state: ChiTransportLinkState) -> Mapping[str, int]:
        usage: dict[str, int] = {}
        if state.request is not None:
            usage.update(
                {
                    f"{self.link.name}.req_lcredit.rp{plane}": count
                    for plane, count in enumerate(
                        state.request.usable_credits_by_plane
                    )
                }
            )
        if state.data is not None:
            usage[f"{self.link.name}.dat_lcredit"] = state.data.usable_credits
        if state.response is not None:
            usage[f"{self.link.name}.rsp_lcredit"] = (
                state.response.usable_credits
            )
        if state.snoop is not None:
            usage[f"{self.link.name}.snp_lcredit"] = (
                state.snoop.usable_credits
            )
        return MappingProxyType(usage)

    def step(
        self, state: ChiTransportLinkState, frame: AtomicFrame
    ) -> SemanticStep[ChiTransportLinkState, ChiTransportTransfer]:
        if not isinstance(state, ChiTransportLinkState):
            raise TypeError("CHI link session requires ChiTransportLinkState")
        if not isinstance(frame, AtomicFrame):
            return self._fault(state, "frame_type", "expected an AtomicFrame")
        if state.last_tick is not None and frame.tick <= state.last_tick:
            return self._fault(
                state,
                "frame_order",
                f"frame tick {frame.tick} does not follow {state.last_tick}",
            )
        profile = self.link.profile
        if frame.clock != profile.clock:
            return self._fault(
                state,
                "clock",
                f"frame clock {frame.clock!r} does not match {profile.clock!r}",
            )
        try:
            activation = frame.get(profile.activation_observation)
        except KeyError:
            return self._fault(
                state,
                "missing_activation",
                f"frame has no {profile.activation_observation!r} observation",
            )
        if not isinstance(activation, ChiLinkActivationSignals):
            return self._fault(
                state,
                "activation_type",
                f"{profile.activation_observation!r} is not "
                "ChiLinkActivationSignals",
            )

        request: ChiReqChannelSignals | None = None
        old_req: tuple[int, ...] | None = None
        if profile.request is not None:
            if state.request is None:
                return self._fault(
                    state, "req_state", "configured REQ channel has no state"
                )
            try:
                request = frame.get(profile.request.observation)
            except KeyError:
                return self._fault(
                    state,
                    "missing_request",
                    f"frame has no {profile.request.observation!r} observation",
                )
            if not isinstance(request, ChiReqChannelSignals):
                return self._fault(
                    state,
                    "request_type",
                    f"{profile.request.observation!r} is not "
                    "ChiReqChannelSignals",
                )
            if (
                len(request.lcrdv_by_plane)
                != profile.request.resource_planes
            ):
                return self._fault(
                    state,
                    "req_credit_shape",
                    "LCRDV plane count does not match the REQ profile",
                )
            old_req = state.request.usable_credits_by_plane
            if len(old_req) != profile.request.resource_planes:
                return self._fault(
                    state,
                    "req_state_shape",
                    "REQ state planes do not match its channel profile",
                )
            if request.flit_valid and not (
                0 <= request.resource_plane < profile.request.resource_planes
            ):
                return self._fault(
                    state,
                    "req_resource_plane",
                    f"REQ Resource Plane {request.resource_plane} is out of range",
                )
        elif state.request is not None:
            return self._fault(
                state, "req_state", "unconfigured REQ channel has state"
            )

        data: ChiDatChannelSignals | None = None
        old_dat: int | None = None
        if profile.data is not None:
            if state.data is None:
                return self._fault(
                    state, "dat_state", "configured DAT channel has no state"
                )
            try:
                data = frame.get(profile.data.observation)
            except KeyError:
                return self._fault(
                    state,
                    "missing_data",
                    f"frame has no {profile.data.observation!r} observation",
                )
            if not isinstance(data, ChiDatChannelSignals):
                return self._fault(
                    state,
                    "data_type",
                    f"{profile.data.observation!r} is not "
                    "ChiDatChannelSignals",
                )
            old_dat = state.data.usable_credits
        elif state.data is not None:
            return self._fault(
                state, "dat_state", "unconfigured DAT channel has state"
            )

        response: ChiRspChannelSignals | None = None
        old_rsp: int | None = None
        if profile.response is not None:
            if state.response is None:
                return self._fault(
                    state, "rsp_state", "configured RSP channel has no state"
                )
            try:
                response = frame.get(profile.response.observation)
            except KeyError:
                return self._fault(
                    state,
                    "missing_response",
                    f"frame has no {profile.response.observation!r} observation",
                )
            if not isinstance(response, ChiRspChannelSignals):
                return self._fault(
                    state,
                    "response_type",
                    f"{profile.response.observation!r} is not "
                    "ChiRspChannelSignals",
                )
            old_rsp = state.response.usable_credits
        elif state.response is not None:
            return self._fault(
                state, "rsp_state", "unconfigured RSP channel has state"
            )

        snoop: ChiSnpChannelSignals | None = None
        old_snp: int | None = None
        if profile.snoop is not None:
            if state.snoop is None:
                return self._fault(
                    state, "snp_state", "configured SNP channel has no state"
                )
            try:
                snoop = frame.get(profile.snoop.observation)
            except KeyError:
                return self._fault(
                    state,
                    "missing_snoop",
                    f"frame has no {profile.snoop.observation!r} observation",
                )
            if not isinstance(snoop, ChiSnpChannelSignals):
                return self._fault(
                    state,
                    "snoop_type",
                    f"{profile.snoop.observation!r} is not "
                    "ChiSnpChannelSignals",
                )
            old_snp = state.snoop.usable_credits
        elif state.snoop is not None:
            return self._fault(
                state, "snp_state", "unconfigured SNP channel has state"
            )

        previous_phase = state.activation.phase
        phase = activation.phase
        if phase not in _ALLOWED_PHASES[previous_phase]:
            return self._fault(
                state,
                "activation_order",
                f"illegal activation transition {previous_phase.value} -> "
                f"{phase.value}",
            )
        req_grants = 0 if request is None else sum(request.lcrdv_by_plane)
        dat_grants = int(data is not None and data.lcrdv)
        rsp_grants = int(response is not None and response.lcrdv)
        snp_grants = int(snoop is not None and snoop.lcrdv)
        has_flit = bool(
            (request is not None and request.flit_valid)
            or (data is not None and data.flit_valid)
            or (response is not None and response.flit_valid)
            or (snoop is not None and snoop.flit_valid)
        )
        has_grant = bool(
            req_grants or dat_grants or rsp_grants or snp_grants
        )
        if phase is ChiLinkActivationPhase.STOP and (has_flit or has_grant):
            return self._fault(
                state,
                "stop_activity",
                "STOP does not permit channel flits or L-Credit grants",
            )
        if phase is ChiLinkActivationPhase.ACTIVATE:
            if has_flit:
                return self._fault(
                    state,
                    "activate_flit",
                    "ACTIVATE does not permit flit transmission",
                )
            if has_grant:
                return self._fault(
                    state,
                    "activate_credit",
                    "the synchronous boundary model grants credits in RUN",
                )
        if (
            phase is ChiLinkActivationPhase.DEACTIVATE
            and has_grant
            and previous_phase is not ChiLinkActivationPhase.RUN
        ):
            return self._fault(
                state,
                "deactivate_credit",
                "credits can only race with entry into DEACTIVATE",
            )

        req_flit = None if request is None else request.flit
        if req_flit is not None:
            req_classification = CHI_ISSUE_H_CHANNEL_DOMAIN.classify(req_flit)
            if req_classification.is_protocol_flit:
                assert profile.request is not None
                reasons = _protocol_representation_reasons(
                    req_flit, profile.request.representation
                )
                if reasons:
                    return self._fault(
                        state, "req_representation", "; ".join(reasons)
                    )
            elif phase is not ChiLinkActivationPhase.DEACTIVATE:
                return self._fault(
                    state,
                    "req_credit_return_phase",
                    "ReqLCrdReturn is used during link deactivation",
                )

        dat_flit = None if data is None else data.flit
        if dat_flit is not None:
            dat_classification = CHI_ISSUE_H_CHANNEL_DOMAIN.classify(dat_flit)
            if dat_classification.is_protocol_flit:
                assert profile.data is not None
                reasons = _protocol_representation_reasons(
                    dat_flit, profile.data.representation
                )
                if reasons:
                    return self._fault(
                        state, "dat_representation", "; ".join(reasons)
                    )
            elif phase is not ChiLinkActivationPhase.DEACTIVATE:
                return self._fault(
                    state,
                    "dat_credit_return_phase",
                    "DatLCrdReturn is used during link deactivation",
                )

        rsp_flit = None if response is None else response.flit
        if rsp_flit is not None:
            rsp_classification = CHI_ISSUE_H_CHANNEL_DOMAIN.classify(rsp_flit)
            if rsp_classification.is_protocol_flit:
                assert profile.response is not None
                reasons = _protocol_representation_reasons(
                    rsp_flit, profile.response.representation
                )
                if reasons:
                    return self._fault(
                        state, "rsp_representation", "; ".join(reasons)
                    )
            elif phase is not ChiLinkActivationPhase.DEACTIVATE:
                return self._fault(
                    state,
                    "rsp_credit_return_phase",
                    "RspLCrdReturn is used during link deactivation",
                )

        snp_flit = None if snoop is None else snoop.flit
        if snp_flit is not None:
            snp_classification = CHI_ISSUE_H_CHANNEL_DOMAIN.classify(snp_flit)
            if snp_classification.is_protocol_flit:
                assert profile.snoop is not None
                reasons = _protocol_representation_reasons(
                    snp_flit, profile.snoop.representation
                )
                if reasons:
                    return self._fault(
                        state, "snp_representation", "; ".join(reasons)
                    )
            elif phase is not ChiLinkActivationPhase.DEACTIVATE:
                return self._fault(
                    state,
                    "snp_credit_return_phase",
                    "SnpLCrdReturn is used during link deactivation",
                )

        req_plane = 0
        if request is not None and request.flit_valid:
            assert old_req is not None
            req_plane = request.resource_plane
            if old_req[req_plane] == 0:
                return self._fault(
                    state,
                    "req_prior_credit",
                    "REQ FLITV has no L-Credit available at frame start",
                )
        if data is not None and data.flit_valid:
            assert old_dat is not None
            if old_dat == 0:
                return self._fault(
                    state,
                    "dat_prior_credit",
                    "DAT FLITV has no L-Credit available at frame start",
                )
        if response is not None and response.flit_valid:
            assert old_rsp is not None
            if old_rsp == 0:
                return self._fault(
                    state,
                    "rsp_prior_credit",
                    "RSP FLITV has no L-Credit available at frame start",
                )
        if snoop is not None and snoop.flit_valid:
            assert old_snp is not None
            if old_snp == 0:
                return self._fault(
                    state,
                    "snp_prior_credit",
                    "SNP FLITV has no L-Credit available at frame start",
                )

        next_req_state = None
        if request is not None:
            assert old_req is not None and profile.request is not None
            next_req = list(old_req)
            if request.flit_valid:
                next_req[req_plane] -= 1
            for plane, granted in enumerate(request.lcrdv_by_plane):
                if granted:
                    next_req[plane] += 1
            for plane, (count, capacity) in enumerate(
                zip(next_req, profile.request.credit_capacities)
            ):
                if count > capacity:
                    return self._fault(
                        state,
                        "req_credit_capacity",
                        f"REQ RP{plane} holds {count} credits, exceeding "
                        f"configured capacity {capacity}",
                    )
            next_req_state = ChiReqChannelState(tuple(next_req))

        next_dat_state = None
        if data is not None:
            assert old_dat is not None and profile.data is not None
            next_dat = old_dat - int(data.flit_valid) + int(data.lcrdv)
            if next_dat > profile.data.credit_capacity:
                return self._fault(
                    state,
                    "dat_credit_capacity",
                    f"DAT holds {next_dat} credits, exceeding configured "
                    f"capacity {profile.data.credit_capacity}",
                )
            next_dat_state = ChiDatChannelState(next_dat)

        next_rsp_state = None
        if response is not None:
            assert old_rsp is not None and profile.response is not None
            next_rsp = (
                old_rsp
                - int(response.flit_valid)
                + int(response.lcrdv)
            )
            if next_rsp > profile.response.credit_capacity:
                return self._fault(
                    state,
                    "rsp_credit_capacity",
                    f"RSP holds {next_rsp} credits, exceeding configured "
                    f"capacity {profile.response.credit_capacity}",
                )
            next_rsp_state = ChiRspChannelState(next_rsp)

        next_snp_state = None
        if snoop is not None:
            assert old_snp is not None and profile.snoop is not None
            next_snp = (
                old_snp
                - int(snoop.flit_valid)
                + int(snoop.lcrdv)
            )
            if next_snp > profile.snoop.credit_capacity:
                return self._fault(
                    state,
                    "snp_credit_capacity",
                    f"SNP holds {next_snp} credits, exceeding configured "
                    f"capacity {profile.snoop.credit_capacity}",
                )
            next_snp_state = ChiSnpChannelState(next_snp)

        if phase is ChiLinkActivationPhase.STOP:
            req_not_empty = next_req_state is not None and any(
                next_req_state.usable_credits_by_plane
            )
            dat_not_empty = (
                next_dat_state is not None
                and next_dat_state.usable_credits != 0
            )
            rsp_not_empty = (
                next_rsp_state is not None
                and next_rsp_state.usable_credits != 0
            )
            snp_not_empty = (
                next_snp_state is not None
                and next_snp_state.usable_credits != 0
            )
            if (
                req_not_empty
                or dat_not_empty
                or rsp_not_empty
                or snp_not_empty
            ):
                return self._fault(
                    state,
                    "deactivation_return",
                    "receiver acknowledged STOP before all credits returned",
                )

        epoch = state.activation.epoch
        if (
            previous_phase is ChiLinkActivationPhase.STOP
            and phase is ChiLinkActivationPhase.ACTIVATE
        ):
            epoch += 1
        candidate = ChiTransportLinkState(
            ChiLinkActivationState(phase, epoch),
            next_req_state,
            last_tick=frame.tick,
            data=next_dat_state,
            response=next_rsp_state,
            snoop=next_snp_state,
        )
        emissions: list[ChiTransportTransfer] = []
        if request is not None and request.flit_valid:
            assert req_flit is not None
            emissions.append(
                ChiReqTransfer(
                    self.link.name, req_flit, req_plane, frame.tick
                )
            )
        if data is not None and data.flit_valid:
            assert dat_flit is not None
            emissions.append(
                ChiDatTransfer(self.link.name, dat_flit, frame.tick)
            )
        if response is not None and response.flit_valid:
            assert rsp_flit is not None
            emissions.append(
                ChiRspTransfer(self.link.name, rsp_flit, frame.tick)
            )
        if snoop is not None and snoop.flit_valid:
            assert snp_flit is not None
            emissions.append(
                ChiSnpTransfer(self.link.name, snp_flit, frame.tick)
            )
        return SemanticStep(candidate, tuple(emissions))

    def _fault(
        self, state: ChiTransportLinkState, suffix: str, reason: str
    ) -> SemanticStep[ChiTransportLinkState, ChiTransportTransfer]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{suffix}",
                reason,
                ConstraintScope.TRANSPORT,
                self.link.name,
            ),
        )


__all__ = [
    "ChiDatChannelState",
    "ChiLinkActivationState",
    "ChiReqChannelState",
    "ChiRspChannelState",
    "ChiSnpChannelState",
    "ChiTransportLinkSession",
    "ChiTransportLinkState",
]
