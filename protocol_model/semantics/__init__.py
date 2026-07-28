"""Scope-aware semantic IR shared by interface, module, and system models."""

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
    ResourceDemand,
    ResourceDecl,
    ResourceExhaustionPolicy,
    SemanticConstraint,
)
from .schema import EventField, EventSchema

__all__ = [
    "ConstraintKind",
    "ConstraintScope",
    "BitVectorDomain",
    "CanonicalEvent",
    "CausalGraph",
    "ConstantDomain",
    "EnumDomain",
    "EventConstraint",
    "EventField",
    "EventOffer",
    "EventSchema",
    "IntDomain",
    "NaturalDomain",
    "ObligationDecl",
    "PartialOrderViolation",
    "ResourceDemand",
    "ResourceDecl",
    "ResourceExhaustionPolicy",
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
