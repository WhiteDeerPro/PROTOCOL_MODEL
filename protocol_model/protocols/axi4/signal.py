"""Whole-interface AXI4 cycle monitor with cross-channel dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from protocol_model.core import (
    CanonicalEvent,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)
from protocol_model.patterns import ReadyValidSample, ResetSample
from protocol_model.protocols.session import ProtocolSessionState

from .spec import Axi4Config, build_axi4_spec


@dataclass(frozen=True)
class Axi4Cycle:
    channels: Mapping[str, ResetSample[ReadyValidSample]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "channels", MappingProxyType(dict(self.channels)))

    @property
    def cycle(self) -> int:
        return next(iter(self.channels.values())).observation.cycle


@dataclass(frozen=True)
class Axi4SignalState:
    channel_states: Mapping[str, Any]
    protocol_state: ProtocolSessionState

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "channel_states", MappingProxyType(dict(self.channel_states))
        )


class Axi4SignalSession(
    SemanticComponent[Axi4Cycle, Axi4SignalState, CanonicalEvent]
):
    """Synchronous product of five pin-level monitors and one transaction session."""

    def __init__(self, config: Axi4Config | None = None, *, spec=None):
        self.spec = spec or build_axi4_spec(config)
        self.protocol = self.spec.open_session()
        self.name = "axi4.signal_session"

    def initial_state(self) -> Axi4SignalState:
        return Axi4SignalState(
            {
                name: channel.observation_model.initial_state()
                for name, channel in self.spec.channels.items()
            },
            self.protocol.initial_state(),
        )

    def is_quiescent(self, state: Axi4SignalState) -> bool:
        return self.protocol.is_quiescent(state.protocol_state) and all(
            self.spec.channel(name).observation_model.is_quiescent(local_state)
            for name, local_state in state.channel_states.items()
        )

    def _fault(
        self,
        state: Axi4SignalState,
        rule: str,
        reason: str,
        *,
        scope: str = "SPEC",
    ) -> SemanticStep:
        return SemanticStep(
            state, fault=SemanticFault(f"{self.name}.{rule}", reason, scope=scope)
        )

    def step(
        self, state: Axi4SignalState, cycle: Axi4Cycle
    ) -> SemanticStep[Axi4SignalState, CanonicalEvent]:
        expected = set(self.spec.channels)
        if set(cycle.channels) != expected:
            return self._fault(
                state,
                "channel_set",
                f"expected channels {sorted(expected)}, got {sorted(cycle.channels)}",
            )
        cycle_numbers = {
            sample.observation.cycle for sample in cycle.channels.values()
        }
        reset_levels = {sample.asserted for sample in cycle.channels.values()}
        if len(cycle_numbers) != 1:
            return self._fault(state, "sample_alignment", "channel cycle numbers differ")
        if len(reset_levels) != 1:
            return self._fault(state, "reset_consistency", "ARESETn differs by channel")
        reset_asserted = next(iter(reset_levels))

        quiet_channels = tuple(self.spec.parameters.get("quiet_channels", ()))
        for name in quiet_channels:
            if cycle.channels[name].observation.valid:
                return self._fault(
                    state,
                    "quiet_channel",
                    f"{name}VALID must remain low in the read-only profile",
                    scope="PROFILE",
                )

        if not reset_asserted:
            write_state = state.protocol_state.state_of("write")
            read_state = state.protocol_state.state_of("read")
            if cycle.channels["B"].observation.valid and not write_state.completions:
                return self._fault(
                    state,
                    "bvalid_dependency",
                    "BVALID asserted without a previously joined AW/W completion",
                )
            if cycle.channels["R"].observation.valid and not read_state.pending:
                return self._fault(
                    state,
                    "rvalid_dependency",
                    "RVALID asserted without a previously accepted AR",
                )

        channel_states = dict(state.channel_states)
        transfers = []
        for name, channel in self.spec.channels.items():
            transition = channel.observation_model.step(
                state.channel_states[name], cycle.channels[name]
            )
            if transition.fault is not None:
                return SemanticStep(state, fault=transition.fault)
            channel_states[name] = transition.state
            transfers.extend(transition.emissions)

        if reset_asserted:
            return SemanticStep(
                Axi4SignalState(channel_states, self.protocol.initial_state())
            )

        protocol_state = state.protocol_state
        if (
            len(transfers) > 1
            and not self.protocol.can_cooccur(protocol_state, tuple(transfers))
        ):
            return self._fault(
                state,
                "cycle_conflict",
                "same-cycle transfers do not commute from the common pre-state",
            )
        normalized = []
        for event in transfers:
            transition = self.protocol.step(protocol_state, event)
            if transition.fault is not None:
                return SemanticStep(state, fault=transition.fault)
            protocol_state = transition.state
            normalized.extend(transition.emissions)
        return SemanticStep(
            Axi4SignalState(channel_states, protocol_state), tuple(normalized)
        )
