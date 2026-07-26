# Sensor FIFO → DMA → memory demo

This named publication script builds and executes a small AXI4-Lite system:

```text
incrementing sample policy → sensor FIFO ← DMA → memory
                                      \      /
                                  1×2 crossbar
```

The sensor is deliberately deterministic, so the generated evidence can be
reproduced.  Four service opportunities produce two retained samples and two
overruns in a depth-two FIFO.  A serialized DMA then copies the retained
samples through a one-ingress/two-egress AXI4-Lite crossbar into memory.

Run from the repository root:

```bash
.venv/bin/python showcase/demos/vdut/sensor_dma_capture/run.py
```

The script atomically replaces only
`showcase/generated/vdut/sensor-dma-capture/`.  It stores Graphviz DOT and
WaveDrom JSON sources alongside the rendered SVG files and records the run in
`manifest.json` and `provenance.json`.

The waveform is a transaction-semantic **model-step view**.  It is not an
ACLK/pin waveform or a cycle-exact reference trace.
