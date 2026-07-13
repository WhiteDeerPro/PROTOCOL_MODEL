"""Project: verify a virtual read bridge between two AXI4 links."""

from .evidence import (
    axi_read_chain_dot,
    axi_read_chain_report_html,
    axi_read_network_dot,
)
from .project import (
    AxiReadCase,
    AxiReadNetworkProject,
    AxiReadNetworkRun,
    NetworkMilestone,
)
from .virtual_dut_bridge import AxiReadBridge
from .virtual_dut_responder import DumbAxiReadResponder
from .simulation import DEFAULT_SIM_DIR, AxiReadBridgeSimulation, build_simulation

__all__ = [
    "AxiReadCase",
    "AxiReadNetworkProject",
    "AxiReadNetworkRun",
    "AxiReadBridge",
    "AxiReadBridgeSimulation",
    "DumbAxiReadResponder",
    "DEFAULT_SIM_DIR",
    "NetworkMilestone",
    "axi_read_chain_dot",
    "axi_read_chain_report_html",
    "axi_read_network_dot",
    "build_simulation",
]
