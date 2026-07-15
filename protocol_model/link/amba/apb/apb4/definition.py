"""AMBA APB4 transaction semantics and optional signal profile."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.link import LinkProtocol

from .._common.definition import (
    bit_field,
    build_apb_variant,
    validate_apb_dimensions,
)


@dataclass(frozen=True)
class Apb4Config:
    address_width: int = 32
    data_width: int = 32
    pprot_present: bool = True
    pstrb_present: bool = True

    def __post_init__(self) -> None:
        validate_apb_dimensions(self.address_width, self.data_width)
        for name in ("pprot_present", "pstrb_present"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"APB4 {name} must be bool")

    @property
    def bytes_per_transfer(self) -> int:
        return self.data_width // 8


def build_apb4_link(
    config: Apb4Config | None = None,
    *,
    address_width: int | None = None,
    data_width: int | None = None,
    pprot_present: bool | None = None,
    pstrb_present: bool | None = None,
) -> LinkProtocol:
    """Build APB4 with independently resolved PPROT and PSTRB presence."""

    explicit = (address_width, data_width, pprot_present, pstrb_present)
    if config is not None and any(value is not None for value in explicit):
        raise ValueError("select either APB4 config or explicit arguments")
    if config is None:
        config = Apb4Config(
            32 if address_width is None else address_width,
            32 if data_width is None else data_width,
            True if pprot_present is None else pprot_present,
            True if pstrb_present is None else pstrb_present,
        )
    request_fields = {}
    write_fields = {}
    if config.pprot_present:
        request_fields["prot"] = bit_field(
            "prot", 3, "PPROT transaction protection"
        )
    if config.pstrb_present:
        write_fields["strb"] = bit_field(
            "strb", config.bytes_per_transfer, "PSTRB write byte lanes"
        )
    return build_apb_variant(
        "apb4",
        revision="APB4",
        address_width=config.address_width,
        data_width=config.data_width,
        request_fields=request_fields,
        write_fields=write_fields,
        parameters={
            "pprot_present": config.pprot_present,
            "pstrb_present": config.pstrb_present,
            "pready_default": True,
            "pslverr_default": False,
        },
        sources=(
            "Arm IHI 0024E APB Revisions; sections 3.1-3.5 and 4.1",
        ),
    )
