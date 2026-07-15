"""AMBA APB LinkProtocol family.

Concrete protocol revisions have independent public APIs in :mod:`apb3`,
:mod:`apb4`, and :mod:`apb5`.  The family root deliberately exports only the
identity used by integrations and system elaboration.
"""

from ._common.definition import APB_FAMILY

__all__ = ["APB_FAMILY"]
