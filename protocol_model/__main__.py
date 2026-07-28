"""Show the active Protocol Model architecture."""

from . import __version__


print(f"protocol_model {__version__}")
print(
    "Architecture anchors: CanonicalEvent + InterfaceProtocol + "
    "VirtualDut + SystemProtocol"
)
