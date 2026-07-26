# AXI4-Lite single-manager address fabric demo

This example builds one AXI4-Lite manager boundary, one constructed
single-ingress address-fabric `VirtualDut`, and three subordinate endpoints:

```text
scenario-driven manager
          |
          v
AXI4-Lite decoder / response mux
    |-- control register (read/write)
    |-- status register  (read-only)
    `-- memory window
```

The execution writes and reads the control register, reads the status value,
writes and reads memory, and finally reads an unmapped address.  The last
access is a normal AXI4-Lite `DECERR` completion rather than a model fault.

Run from the repository root:

```bash
python3 showcase/demos/system/axi4_lite_single_manager_fabric/run.py
```

Use `--publish-root <directory>` to build a scratch publication without
changing the maintained `showcase/generated/` tree.  The named publication
contains:

- a canonical port-to-port topology;
- a bus-strip projection of the same explicit fabric topology;
- the fabric's generated port/attachment/backend structure;
- a transaction-semantic model-step view;
- the recorded causal graph, result, provenance, and manifest.

The bus strip is a presentation-only folding of the fabric `VirtualDut` and
its binary `InterfaceConnection` instances.  It does not replace the canonical
system topology with an implicit multi-drop connection.  Likewise, the
model-step view is not an ACLK, pin, RTL, or VCD waveform.
