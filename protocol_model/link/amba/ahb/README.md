# AHB LinkProtocol family

`ahb_lite/` is the baseline single-Manager address/data pipeline. `ahb5/`
derives the Issue C interface-property payload from that transaction core:
extended HPROT, security, sparse-write strobes, Exclusive signaling, and User
signals can be selected independently.

Decoder/multiplexor composition and multi-Manager arbitration are interconnect
VirtualDut/SystemProtocol work. AHB5 parity is a pin-observation profile and is
not declared by the current canonical link builder.
