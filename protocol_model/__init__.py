"""Executable reference model for protocol semantics experiments."""

__version__ = "0.1.1"

from .core import (
    CanonicalEvent,
    SemanticComponent,
    SemanticFault,
    SemanticRun,
    SemanticStep,
    TraceValidation,
    TraceViolation,
    Verdict,
)
from .engine import ExecutionTrace

__all__ = [
    "CanonicalEvent",
    "ExecutionTrace",
    "SemanticComponent",
    "SemanticFault",
    "SemanticRun",
    "SemanticStep",
    "TraceValidation",
    "TraceViolation",
    "Verdict",
    "__version__",
]
