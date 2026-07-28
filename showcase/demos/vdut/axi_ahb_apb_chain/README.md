# AXI4-Lite → AHB-Lite → APB4 bridge-chain demo

This demo assembles and executes a small, non-coherent peripheral network
using only the current architecture:

```text
scenario actions
  → AXI4-Lite requester boundary
  → serial AXI4-Lite/AHB-Lite bridge
  → serial AHB-Lite/APB4 bridge
  → single-ingress APB4 decoder/response mux
  → control and status register endpoints
```

The source `VirtualDut` is intentionally thin.  Its boundary supplies the
AXI4-Lite manager port and its `CaptureBackend` records returned responses; the
deterministic request driver belongs to the scenario outside the module.  The
two bridges are not empty wrappers: their attachments decode AMBA events into
protocol-independent address operations, their translation plans apply route,
shape, and protection rules, and their serial executors retain ownership until
the downstream completion can be encoded on the upstream protocol.

Run from any working directory:

```bash
python3 showcase/demos/vdut/axi_ahb_apb_chain/run.py
```

The named script publishes to
`showcase/generated/vdut/axi-ahb-apb-chain/` by default.  It records the DOT
sources next to an expanded topology, one structure view for each bridge, an
APB fabric structure view, a WaveDrom cross-interface transaction projection, a
causal trace, execution results, provenance, and a manifest.  All internal
structure views come from the shared VirtualDut projector; this demo does not
maintain a private hand-drawn bridge layout.  The WaveDrom source uses one
column per scenario action and makes no pin/cycle timing claim.

The run also sends one address that passes both bridges but misses the APB
decoder.  APB carries a single error indication, so that local decode error
returns through AHB `ERROR` as AXI4-Lite `SLVERR`; the narrower downstream
response vocabulary cannot preserve AXI's `DECERR`/`SLVERR` distinction.

Use `--publish-root <directory>` to write a scratch publication elsewhere.
