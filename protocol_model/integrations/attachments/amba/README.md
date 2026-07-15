# AMBA attachment implementations

Each leaf package implements one AMBA link family's translation to or from a
small VirtualDut operation contract.  An attachment belongs to one port: it
owns that port's transport state, such as APB pending completion, AXI AW/W
join, AHB phase context, or AXI4-Stream optional-field mapping.

These packages do not construct complete modules and do not own route tables
or cross-port completion correlation.  Module construction is under
`integrations/recipes/`; reusable operation and backend contracts remain under
`virtual_dut/`.
