# Protocol integration source layout

`integrations` is a dependency meeting point, not an additional protocol
semantic layer.  It contains code that must understand both a concrete
`InterfaceProtocol` family asset and a VirtualDut operation or construction contract.

The integration source separates four artifact roles:

- `attachments/`: single-port event/operation translation and its interface-facing
  state;
- [`translations/`](translations/README.md): reusable protocol-bound typed
  stages and plan fragments;
- `backends/`: protocol-bound execution state machines that may correlate or
  route across several ports;
- `recipes/`: composition roots that bind attachments to ports and backends,
  producing concrete `VirtualDut` modules.

Concrete-protocol cross-port execution is a third internal artifact role.  It
is needed when AXI ID/channel ordering or another protocol law directly shapes
the VirtualDut state machine and therefore cannot move into the
protocol-neutral `virtual_dut/backend` package. Such implementations live in
the integration-owned [`backends/`](backends/README.md) package. AXI4
address-space, read-fabric, and write-fabric execution have been moved there;
their recipes remain responsible only for selecting ports, bindings, profiles,
and the backend that realizes the module.

The [`recipes/` catalog](recipes/README.md) is the user-facing inventory of
currently constructible modules. It indexes protocol-neutral foundations and
protocol-bound products without storing network-specific instances.

Within recipes, `endpoints/`, `fabrics/`, and `bridges/` group products by
module role. Bridges contain relational products whose behavior is primarily
transform, route, correlation, and completion return.
Protocol-neutral execution cores remain under `virtual_dut/`; protocol laws
remain under `protocols/`.

An AMBA recipe means that the constructed module has AMBA-bound ports.  AMBA
is not a VirtualDut base class or device identity.  A cross-family product,
such as a future AXI-to-TileLink bridge, should live in a cross-family recipe
scope while reusing the same protocol-neutral operators where their behavior
fits.
