# AMBA-bound VirtualDut recipes

Recipes are composition roots.  They select concrete AMBA attachments, bind
them to `ProtocolPort` objects, choose a backend, and return a concrete
`VirtualDut`.

- `endpoints/` constructs single-role address/stream modules and selects AMBA
  roles for protocol-neutral idle/blackhole modules;
- `fabrics/` constructs same-family multi-port routing modules;
- `bridges/` constructs cross-protocol relational modules.

The AMBA qualifier describes the resulting port bindings.  It does not create
an AMBA-specific VirtualDut superclass or make protocol family the module's
primary identity.
