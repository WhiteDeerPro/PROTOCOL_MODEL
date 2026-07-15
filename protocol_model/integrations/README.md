# Protocol integration source layout

`integrations` is a dependency meeting point, not an additional protocol
semantic layer.  It contains code that must understand both a concrete
`LinkProtocol` family and a VirtualDut operation or construction contract.

The source tree separates two artifact roles:

- `attachments/`: single-port event/operation translation and its transport
  state;
- `recipes/`: composition roots that bind attachments to ports and backends,
  producing concrete `VirtualDut` modules.

Within recipes, `endpoints/`, `fabrics/`, and `bridges/` group products by
module role. Bridges contain relational products whose behavior is primarily
transform, route, correlation, and completion return.
Protocol-neutral execution cores remain under `virtual_dut/`; protocol laws
remain under `link/`.

An AMBA recipe means that the constructed module has AMBA-bound ports.  AMBA
is not a VirtualDut base class or device identity.  A cross-family product,
such as a future AXI-to-TileLink bridge, should live in a cross-family recipe
scope while reusing the same protocol-neutral operators where their behavior
fits.
