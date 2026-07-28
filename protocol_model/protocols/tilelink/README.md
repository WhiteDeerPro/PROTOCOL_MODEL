# TileLink protocol-family boundary

This directory reserves the concrete TileLink family boundary. It currently
contains no executable interface builder or observer.

Planned conformance profiles are `tl_ul/`, `tl_uh/`, and `tl_c/`. Their common
A/D channel vocabulary should be extracted only when the first executable
`InterfaceProtocol` is implemented. TileLink agents are logical protocol
participants rather than aliases for `VirtualDut`; TL-C permission/coherence
state will additionally require participant and SystemProtocol-visible
components.

The TileLink specification's term *link* remains valid inside this family. In
the generic project API, a complete role/channel bundle is an
`InterfaceProtocol` and one concrete topology binding is an
`InterfaceConnection`.
