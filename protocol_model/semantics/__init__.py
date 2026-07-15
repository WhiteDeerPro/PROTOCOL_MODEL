"""Scope-aware semantic IR used by link and system protocols."""

from .causal import CausalGraph, PartialOrderViolation
from .fragment import SemanticFragment, compose_fragments
from .generation import EventOffer
from .component import (
    SemanticComponent,
    SemanticFault,
    SemanticRun,
    SemanticStep,
    TraceViolation,
    Verdict,
)
from .event import (
    BitVectorDomain,
    CanonicalEvent,
    ConstantDomain,
    EnumDomain,
    EventConstraint,
    IntDomain,
    NaturalDomain,
    ValueDomain,
)
from .model import (
    ConstraintKind,
    ConstraintScope,
    ObligationDecl,
    ResourceDecl,
    SemanticConstraint,
)

__all__ = [
    "ConstraintKind",
    "ConstraintScope",
    "BitVectorDomain",
    "CanonicalEvent",
    "CausalGraph",
    "ConstantDomain",
    "EnumDomain",
    "EventConstraint",
    "EventOffer",
    "IntDomain",
    "NaturalDomain",
    "ObligationDecl",
    "PartialOrderViolation",
    "ResourceDecl",
    "SemanticConstraint",
    "SemanticComponent",
    "SemanticFault",
    "SemanticFragment",
    "SemanticRun",
    "SemanticStep",
    "TraceViolation",
    "ValueDomain",
    "Verdict",
    "compose_fragments",
]
