"""Project-specific terminating AXI read responder."""

from __future__ import annotations

from random import Random

from protocol_model.core import CanonicalEvent
from protocol_model.protocols.spec import ProtocolSpec
from protocol_model.virtual_dut import FunctionResponder, VirtualDutContract


class DumbAxiReadResponder(FunctionResponder[CanonicalEvent, CanonicalEvent]):
    """Produce deterministic R beats; deliberately has no memory state."""

    def __init__(self, spec: ProtocolSpec):
        self.spec = spec
        self.data_mask = (1 << int(spec.parameters["data_width"])) - 1
        super().__init__(
            self._respond,
            "dumb_axi_read_responder",
            capabilities=frozenset({"axi_read", "deterministic_payload"}),
            contract=VirtualDutContract(
                assumptions=("input is an AXI-valid AR transfer",),
                guarantees=("emits AxLEN+1 R beats and asserts RLAST on the final beat",),
            ),
        )

    def _respond(self, event: CanonicalEvent):
        if event.kind != "AR_TRANSFER":
            raise ValueError("responder accepts only AR transfers")
        beats = int(event.payload["len"]) + 1
        address = int(event.payload["addr"])
        stride = 1 << int(event.payload["size"])
        return tuple(
            self.spec.channel("R").transfer.sample_constrained(
                Random(address + index),
                key=event.key,
                payload={
                    "data": (address + index * stride) & self.data_mask,
                    "resp": "OKAY",
                    "last": index == beats - 1,
                },
            )
            for index in range(beats)
        )
