# AMBA-bound bridge recipes

Calling `build_amba_serial_bridge_vdut()` produces an ordinary two-port
`VirtualDut`, suitable for use as a `SystemProtocol` topology node.  The recipe
location describes the protocols bound to its ports; it does not introduce an
AMBA device superclass or one class for every protocol pair.

## Current construction profiles

The composition root selects one of two operation shapes from the ingress:

- AXI4-Lite, AHB, and APB decode to one `AddressAccess` and use the
  single-access profile;
- full AXI4 first assembles AW/W or AR into a parent burst, then expands that
  burst into ordered `AddressAccess` children.

Both profiles use the same AMBA requester factory at the egress.  AXI4,
AXI4-Lite, AHB, and APB can therefore be selected on either side without
maintaining a static N-by-N recipe table.  Thin pair-named builders remain
convenience entry points; the route, typed stages, serial executor, capacity,
and completion fold are shared construction parts.

The current executor is deliberately strict serial: it retains the parent and
one child owner until the downstream completion returns.  `parent_capacity`
limits admitted complete operations (eight by default).  Full AXI4 assembly
also declares separate bounds for pending AW descriptors, pre-AW W bursts, and
buffered W beats.  Capacity exhaustion currently forms a VirtualDut fault; it
does not yet project to pin/cycle READY backpressure.

## Translation boundary

The single-access profile, and the currently audited pair-named presets,
require equal data widths.  The generic full-AXI burst profile can be
constructed with unequal bus widths, but it does not split or merge a beat:
the whole parent is rejected before issue unless every beat is directly
representable by the target shape.  Construction compatibility is therefore
not a claim that arbitrary width conversion is implemented.

Protection attributes are decoded to a shared form and then encoded for the
target protocol.  A target with a smaller response vocabulary can lose error
provenance: for example, an APB decode error returning through AHB becomes AXI
`SLVERR`, because APB cannot retain AXI's `DECERR`/`SLVERR` distinction.

## Relation to a crossbar

A crossbar can reuse bridge-path transforms, attachments, route, storage, and
correlation.  Once multiple ingresses share an egress, however, admission,
arbitration-grant lifetime, response ownership, and per-ingress ordering must
be shared by those paths.  That coordination belongs to a fabric backend or an
expanded internal subsystem; unrelated bridge instances do not provide it.
The corresponding construction-pressure analysis is recorded in
`docs/architecture/address-fabric.md`.
