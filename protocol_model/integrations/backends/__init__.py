"""Protocol-bound execution backends used by integration recipes.

This package owns state machines whose behavior depends on both a concrete
interface protocol and the generic :mod:`protocol_model.virtual_dut` backend
contract.  It deliberately does not re-export protocol-family implementations
from the package root; internal callers import the relevant leaf module.
"""
