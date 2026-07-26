# AMBA-bound VirtualDut recipes

Recipes are composition roots.  They select concrete AMBA attachments, bind
them to `InterfacePort` objects, choose a backend, and return a concrete
`VirtualDut`.

- `endpoints/` constructs boundary modules, including passive address/stream
  endpoints, an initiating memory-copy fixture, and AMBA roles for
  protocol-neutral idle/blackhole modules;
- `fabrics/` constructs same-family multi-port routing modules;
- `bridges/` constructs two-boundary translation/correlation modules.  The
  generic serial builder also permits supported same-family or variant
  translations; "bridge" therefore describes the relational behavior rather
  than requiring two different family names;
- `chi/` assembles a concrete transport-bound VirtualDut together with the
  wider CHI participant facet consumed by family construction and runtime.

The grouped inventory and selection guidance live one level above in the
[`VirtualDut construction catalog`](../README.md).

The AMBA qualifier describes the resulting port bindings.  It does not create
an AMBA-specific VirtualDut superclass or make protocol family the module's
primary identity.

## AXI4 response stepping

`build_axi4_address_space_vdut()` normally returns its canonical R/B
completion batch in the same abstract action.  Callers that need a paced
event witness can pass a `SteppedEmissionProfile`.  The resulting backend
reserves finite output-event capacity and releases at most one R or B event
per explicit `DutAdvanceAction`; its wait policy may leave empty service
opportunities between R beats.

This profile schedules already-computed response events.  It does not assign
an ACLK period or drive RVALID/RREADY pins.  FIFO scheduling remains the
default.  Selecting round-robin scheduling lets different RID batches
alternate one R beat at a time, while the AXI recipe prevents a later batch
with the same RID from passing its predecessor.  This is local endpoint
scheduling, not a multi-subordinate AXI crossbar.  A pin/cycle adapter can
later map one service opportunity to one cycle and must still hold R payload
while the manager deasserts RREADY.

The backend now exposes a non-destructive `prepare_offer()` /
`current_offer()` / `accept_offer()` seam.  A selected beat remains in the
finite FIFO until explicit acceptance, so a future R-channel driver can keep
RID/RDATA/RRESP/RLAST stable without making RVALID depend on RREADY.  The
driver and reset behavior are still separate protocol-observation work;
ordinary `advance()` preserves the event-level shortcut by preparing and
immediately accepting as though the destination were always ready.

## Fabric profiles

The single-ingress fabric recipes bind APB, AHB, or AXI4-Lite attachments to
the protocol-independent decoder/response-mux backend.  They forward a
complete address operation immediately and retain one completion owner.

The first executable N-ingress/M-egress profile is separate:

```python
build_axi4_lite_address_crossbar_vdut(
    name,
    protocol,
    ingress_ports=("m0", "m1"),
    egress_ports=("s0", "s1"),
    routes=(...),
    ingress_queue_capacity=2,
)
```

This recipe creates an independent AXI4-Lite completer attachment for every
ingress and an independent requester attachment for every egress, then calls
the protocol-neutral `build_scheduled_address_crossbar_vdut()` composition
root.  The backend owns complete-operation FIFOs, one round-robin cursor per
egress, active request ownership, and completion return.  Requests are issued
only when a caller supplies an explicit service opportunity; that operation
does not imply an RTL clock cycle.

All ports in this initial recipe use the same AXI4-Lite profile and data width.
It models single address accesses, static route/remap, ordered route misses,
and at most one active request per ingress and per egress.  It does not model a
full AXI crossbar, burst routing, AXI ID remapping, QoS, or cycle-accurate
READY/backpressure.

AXI4 burst reads use a protocol-specific N×M recipe because RID ordering and
return ownership must remain visible instead of being lowered to one
`AddressAccess`.  The recipe requires `build_axi4_read_only_profile()` (or an
equivalent profile that forbids AW/W/B), so its five-channel interface shape
cannot silently accept a write event that the backend does not route:

```python
protocol = build_axi4_read_only_profile(...)
build_axi4_read_crossbar_vdut(
    name,
    protocol,
    ingress_ports=("manager0", "manager1"),
    egress_ports=("memory", "control"),
    routes=(...),
    table_profile=Axi4ReadRouteTableProfile(
        active_id_capacity=8,
        outstanding_bursts_per_id=8,
    ),
)
```

The backend retains AR/R events and owns one sparse pending-burst ledger.  Two
views are derived from those entries: `(ingress, RID) -> egress` is the
manager-local destination lock, while `(egress, downstream RID) -> FIFO of
ingress owners` restores each R burst to the manager whose AR reached that
downstream ordering stream first.  The capacity profile is applied
independently to every ingress.

Canonical AR events already denote accepted transfers.  Their submission
order is the grant order of that execution witness; this profile therefore
does not add a pin-level request queue, simultaneous-AR arbiter, or ACLK
timing.  The current `raw-ID-serialized` policy preserves ARID downstream.
Managers that reuse one RID at the same subordinate share a legal downstream
ordering stream, which can serialize otherwise independent reads without
losing ordinary response ownership.  Multi-ingress exclusive reads are
rejected until a source-qualified identity or ID-remap profile is selected.

`build_axi4_read_demux_vdut()` is the one-ingress convenience specialization
of the same backend and state model.  The generic recipe accepts arbitrary
non-empty ingress and egress tuples; the public 2×4 witness demonstrates that
N and M are independent.  Neither read recipe routes AW/W/B, so they are
AXI4 AR/R fabric slices rather than complete five-channel AXI crossbars.

The corresponding write slice uses `build_axi4_write_only_profile()` and
`build_axi4_write_crossbar_vdut()`.  It retains port-local AW/W FIFO
correlation, including W-before-AW, and forwards a joined burst as one
store-and-forward `AW, W...WLAST` batch.  AW admission reserves the
manager-local BID destination/order domain; an `Axi4BurstAssemblyProfile`
bounds partial input storage, while `Axi4WriteRouteTableProfile` bounds active
BID domains and accepted bursts per BID.  Returned B events use an
`(egress, downstream BID)` owner FIFO.  A decode miss first consumes the
matching complete W burst and then returns local DECERR.

This write profile uses canonical submission order as the accepted grant
order.  It does not yet supply cut-through W routing, a per-beat W arbiter, or
AWREADY/WREADY pin timing.  Combining this slice with AR/R under one full
five-channel backend remains a separate composition step.

`CanonicalEventRelayAttachment` is the small reusable boundary piece: it
reuses the supplied `InterfaceProtocol` direction and schema checks while
preserving the canonical event.  RID interpretation, route locks, and owner
state stay in the AXI fabric backend.  Interface monitors retain their own
ordering ledger, so the executable table and protocol oracle do not share one
mutable FIFO instance.

## System construction boundary

An address network may keep one route authority in an
`AddressRouterContract`.  `SystemProtocolBuilder.construct_address_router()`
passes that contract to an injected factory; the AXI4-Lite and AXI4 read/write
factories can pass `contract.routes` directly to their recipes.  The
constructed backend projects its actual ingress, egress, and route
configuration, and the builder compares that projection with the contract
before registration.  System elaboration then checks
that every translated route window has one covering claim on the directly
connected egress endpoint.

This direct-neighbor address closure does not infer crossbar behavior from a
star-shaped topology and does not execute arbitration.  Queue, cursor, and
owner state, including the AXI read/write ledgers, remain private to the
constructed VirtualDut backend.  Multi-hop
address search and boundary comparison against an arbitrary external RTL
crossbar remain later work.  An external/opaque crossbar still needs a future
adapter before its asserted route contract can be checked against the implementation.
