"""Project-owned AXI manager source and subordinate responder scripts."""

from __future__ import annotations

from typing import Mapping, Sequence

from protocol_model.patterns import ReadyValidSample, ResetSample
from protocol_model.virtual_dut import ScriptedSource, VirtualDutContract, VirtualDutKind


AxiDrive = Mapping[str, ResetSample[ReadyValidSample]]


class AxiManagerSource(ScriptedSource[AxiDrive]):
    """Drive the manager-owned AW/W/AR channels for a scenario."""

    def __init__(self, sequence: Sequence[AxiDrive]):
        super().__init__(sequence, name="axi_scenario_manager_source")
        self.capabilities = frozenset({"axi_manager", "scripted_cycles"})
        self.contract = VirtualDutContract(
            guarantees=("drives only AW, W, and AR channel samples",)
        )


class AxiSubordinateResponder(ScriptedSource[AxiDrive]):
    """Drive the subordinate-owned B/R channels for a scenario."""

    kind = VirtualDutKind.RESPONDER

    def __init__(self, sequence: Sequence[AxiDrive]):
        super().__init__(sequence, name="axi_scenario_subordinate_responder")
        self.capabilities = frozenset({"axi_subordinate", "scripted_cycles"})
        self.contract = VirtualDutContract(
            assumptions=("manager requests are supplied by the paired source",),
            guarantees=("drives only B and R channel samples",),
        )
