"""AMBA 3 APB transaction semantics."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.link import LinkProtocol

from .._common.definition import build_apb_variant, validate_apb_dimensions


@dataclass(frozen=True)
class Apb3Config:
    address_width: int = 32
    data_width: int = 32

    def __post_init__(self) -> None:
        validate_apb_dimensions(self.address_width, self.data_width)


def build_apb3_link(
    config: Apb3Config | None = None,
    *,
    address_width: int | None = None,
    data_width: int | None = None,
) -> LinkProtocol:
    """Build APB3 canonical request/completion semantics."""

    if config is not None and (
        address_width is not None or data_width is not None
    ):
        raise ValueError("select either APB3 config or width arguments")
    if config is None:
        config = Apb3Config(
            32 if address_width is None else address_width,
            32 if data_width is None else data_width,
        )
    return build_apb_variant(
        "apb3",
        revision="APB3",
        address_width=config.address_width,
        data_width=config.data_width,
        parameters={
            "pprot_present": False,
            "pstrb_present": False,
            "pready_default": True,
            "pslverr_default": False,
        },
        sources=(
            "Arm IHI 0024E APB Revisions; sections 3.1, 3.3, 3.4, and 4.1",
        ),
    )
