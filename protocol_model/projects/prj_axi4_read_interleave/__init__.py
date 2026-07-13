"""Project: constrained AXI4 cross-ID read interleaving with two VirtualDuts."""

from .constraints import ReadInterleaveConstraints, derive_constrained_axi4
from .evidence import format_run, report_html, topology_dot
from .project import AxiReadInterleaveProject, AxiReadInterleaveRun, ConstraintCheck
from .simulation import DEFAULT_SIM_DIR, AxiReadInterleaveSimulation, build_simulation
from .virtual_dut import InterleavingReadResponder, build_read_initiator

__all__ = [
    "AxiReadInterleaveProject",
    "AxiReadInterleaveRun",
    "AxiReadInterleaveSimulation",
    "ConstraintCheck",
    "DEFAULT_SIM_DIR",
    "InterleavingReadResponder",
    "ReadInterleaveConstraints",
    "build_read_initiator",
    "build_simulation",
    "derive_constrained_axi4",
    "format_run",
    "report_html",
    "topology_dot",
]
