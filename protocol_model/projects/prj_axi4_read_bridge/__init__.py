"""Project: verify a virtual read bridge between two AXI4 links."""

from pathlib import Path

DEFAULT_SIM_DIR = Path(__file__).resolve().parent / "sims" / "01"

from .evidence import axi_read_chain_dot, axi_read_chain_report_html
from .project import (
    AxiReadCase,
    AxiReadNetworkProject,
    AxiReadNetworkRun,
    NetworkMilestone,
)
from .virtual_dut_bridge import AxiReadBridge
from .virtual_dut_responder import DumbAxiReadResponder

__all__ = [
    "AxiReadCase",
    "AxiReadNetworkProject",
    "AxiReadNetworkRun",
    "AxiReadBridge",
    "DumbAxiReadResponder",
    "DEFAULT_SIM_DIR",
    "NetworkMilestone",
    "axi_read_chain_dot",
    "axi_read_chain_report_html",
]
