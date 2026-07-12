"""Human-readable evidence views over protocol runs."""

from .graphviz import format_correlated_dot, format_execution_dot
from .text import (
    format_cardinality_run,
    format_correlated_run,
    format_ready_valid_run,
)
from .wavedrom import (
    VirtualWaveform,
    synthesize_axi_network_timeline,
    synthesize_axi_waveform,
    to_wavejson,
)
from .report import session_report_html

__all__ = [
    "format_cardinality_run",
    "format_correlated_dot",
    "format_correlated_run",
    "format_execution_dot",
    "format_ready_valid_run",
    "synthesize_axi_waveform",
    "synthesize_axi_network_timeline",
    "to_wavejson",
    "VirtualWaveform",
    "session_report_html",
]
