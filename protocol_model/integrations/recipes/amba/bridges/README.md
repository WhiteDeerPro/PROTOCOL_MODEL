# AMBA-bound bridge recipes

Calling a bridge builder produces an ordinary multi-port `VirtualDut`, suitable
for use as a `SystemProtocol` topology node.  The recipe location describes the
protocols bound to its ports; it does not introduce an AMBA device superclass.

Two executable profiles currently exist:

- AXI4-Lite to APB uses `SingleIngressAddressFabricBackend` and permits one
  active cross-port address operation;
- full AXI4 to APB uses a protocol-pair backend.  The AXI attachment joins AW/W
  and expands burst geometry, while the bridge queues complete parent bursts,
  applies address route/remap, issues one APB transfer per beat, and returns one
  B or the required R sequence.

The full AXI4 profile has finite storage: by default `active + ready` contains
at most eight complete parent transactions, with separate limits for pending
AW descriptors, pre-AW W bursts, and buffered W beats.  Capacity exhaustion is
currently a VirtualDut fault; a later pin/cycle projection can derive READY
backpressure from the same occupancy contract.

Both profiles currently require equal data widths and aligned, full-width AXI
accesses.  Partial writes are preserved through PSTRB.  PPROT is preserved;
non-zero AXI cache, QoS, and region attributes are outside this first APB
conversion profile.  Route miss returns AXI `DECERR`, and APB error returns
AXI `SLVERR`.

A crossbar can reuse bridge-path transforms, attachments, route, storage, and
correlation.  Independent path composition is sufficient when each path keeps
a unique source identity.  Once multiple ingresses share an egress, admission,
the lifetime of the arbitration grant, and response-owner state must be shared
by those paths.  That coordination belongs to a fabric backend or an expanded
internal subsystem; it is not supplied by unrelated bridge instances alone.
