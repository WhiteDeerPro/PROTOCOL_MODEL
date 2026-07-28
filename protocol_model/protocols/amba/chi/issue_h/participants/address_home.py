"""ReadNoSnp Home participant backed by a protocol-neutral address target."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.semantics import (
    ConstraintScope,
    SemanticFault,
    SemanticStep,
)
from protocol_model.virtual_dut.address import (
    AccessStatus,
    AddressRead,
    AddressStep,
    AddressTarget,
)

from ..interface import ChiReadNoSnpDirectProfile
from ..representation import (
    ChiCompDataMessage,
    ChiReadNoSnpMessage,
    ChiRespErr,
)
from .direct_home import (
    ChiDirectHomeAccept,
    ChiDirectHomeAction,
    ChiDirectHomeNode,
    ChiDirectHomeState,
)


@dataclass(frozen=True)
class ChiAddressHomeState(ChiDirectHomeState):
    """Direct-Home transaction state plus one local address-state authority."""

    target_state: object = None


class ChiAddressHomeNode(ChiDirectHomeNode):
    """Delegate one restricted ReadNoSnp to an ``AddressTarget``.

    CHI fields and the REQ/DAT lifecycle remain owned by this participant.
    The target owns only protocol-neutral address state.  This first profile
    accepts an aligned, full-DAT-width read with default sideband semantics.
    Protocol-neutral decode/access failures become ``CompData_I(NDERR)``;
    narrow data placement, corrupt-data DERR, and target effects remain
    explicit later extensions.
    """

    def __init__(
        self,
        name: str,
        profile: ChiReadNoSnpDirectProfile,
        target: AddressTarget,
        *,
        request_capacity: int = 4,
    ) -> None:
        if not isinstance(target, AddressTarget):
            raise TypeError("CHI address Home requires an AddressTarget")
        super().__init__(
            name,
            profile,
            lambda _request: 0,
            request_capacity=request_capacity,
        )
        self.target = target

    def initial_state(self) -> ChiAddressHomeState:
        return ChiAddressHomeState(target_state=self.target.initial_state())

    def step(
        self,
        state: ChiAddressHomeState,
        action: ChiDirectHomeAction,
    ) -> SemanticStep[ChiAddressHomeState, ChiCompDataMessage]:
        if not isinstance(state, ChiAddressHomeState):
            raise TypeError("CHI address Home requires ChiAddressHomeState")
        return super().step(state, action)

    def _accept(
        self,
        state: ChiAddressHomeState,
        request: ChiReadNoSnpMessage,
    ) -> SemanticStep[ChiAddressHomeState, ChiCompDataMessage]:
        requested_bytes = 1 << request.size
        if (
            requested_bytes != self.profile.data_bytes
            or request.address % self.profile.data_bytes
        ):
            return self._profile_fault(
                state,
                "address_shape",
                "current address-backed Home requires one aligned, "
                "full-DAT-width read",
            )
        unsupported = tuple(
            name
            for name, value in (
                ("QoS", request.qos),
                ("PAS", request.pas),
                ("LikelyShared", request.likely_shared),
                ("MemAttr", request.memory_attributes),
                ("SnpAttr", request.snoop_attribute),
                ("Excl", request.exclusive),
                ("TagOp", request.tag_operation),
                ("TraceTag", request.trace_tag),
            )
            if value not in (0, False)
        )
        if unsupported:
            return self._profile_fault(
                state,
                "address_attributes",
                "current address-backed Home has no semantic policy for "
                f"{list(unsupported)!r}",
            )

        accepted = super()._accept(state, request)
        if accepted.fault is not None or accepted.blocked is not None:
            return SemanticStep(
                state,
                accepted.emissions,
                accepted.fault,
                accepted.causal_predecessors,
                accepted.blocked,
            )
        candidate = accepted.state
        return SemanticStep(
            ChiAddressHomeState(
                pending=candidate.pending,
                accepted_count=candidate.accepted_count,
                completed_count=candidate.completed_count,
                target_state=state.target_state,
            ),
            accepted.emissions,
            causal_predecessors=accepted.causal_predecessors,
        )

    def _service(
        self,
        state: ChiAddressHomeState,
    ) -> SemanticStep[ChiAddressHomeState, ChiCompDataMessage]:
        if not state.pending:
            empty = super()._service(state)
            return SemanticStep(
                state,
                empty.emissions,
                empty.fault,
                empty.causal_predecessors,
                empty.blocked,
            )

        request = state.pending[0]
        accessed = self.target.access(
            state.target_state,
            AddressRead(request.address, 1 << request.size),
        )
        if not isinstance(accessed, AddressStep):
            return self._target_fault(
                state,
                "result_type",
                "address target did not return AddressStep",
            )
        result = accessed.result
        if result.effects:
            return self._target_fault(
                state,
                "effects",
                "current CHI address Home cannot commit target-local effects",
            )
        if result.status is AccessStatus.OK:
            data = result.data
            response_error = ChiRespErr.OK
        elif result.status in (
            AccessStatus.DECODE_ERROR,
            AccessStatus.ACCESS_ERROR,
        ):
            data = 0
            response_error = ChiRespErr.NDERR
        else:
            return self._target_fault(
                state,
                "status",
                "address target returned an unknown access status",
            )
        if response_error is ChiRespErr.OK and (
            not isinstance(data, int)
            or isinstance(data, bool)
            or not 0 <= data < (1 << self.profile.data_width)
        ):
            return self._target_fault(
                state,
                "read_data",
                "address target did not return one full-width data value",
            )
        assert isinstance(data, int)

        response = ChiCompDataMessage(
            transaction_id=request.transaction_id,
            home_node_id=self.profile.home_node_id,
            data=data,
            data_id=self.profile.expected_data_id(request.address),
            response_error=response_error,
            response=0,
            data_buffer_id=0,
        )
        return SemanticStep(
            ChiAddressHomeState(
                pending=state.pending[1:],
                accepted_count=state.accepted_count,
                completed_count=state.completed_count + 1,
                target_state=accessed.state,
            ),
            (response,),
        )

    def _profile_fault(
        self,
        state: ChiAddressHomeState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[ChiAddressHomeState, ChiCompDataMessage]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{suffix}",
                reason,
                ConstraintScope.INTERFACE,
                self.name,
            ),
        )

    def _target_fault(
        self,
        state: ChiAddressHomeState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[ChiAddressHomeState, ChiCompDataMessage]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.target.{suffix}",
                reason,
                ConstraintScope.VIRTUAL_DUT,
                self.name,
            ),
        )


__all__ = ["ChiAddressHomeNode", "ChiAddressHomeState"]
