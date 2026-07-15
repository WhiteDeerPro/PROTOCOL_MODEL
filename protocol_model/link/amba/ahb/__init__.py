"""AMBA AHB LinkProtocol family identity.

Concrete revisions live in :mod:`ahb_lite` and :mod:`ahb5`.  The family root
does not flatten their public APIs, so callers state which interface contract
they are constructing.
"""

AHB_FAMILY = "amba.ahb"

__all__ = ["AHB_FAMILY"]
