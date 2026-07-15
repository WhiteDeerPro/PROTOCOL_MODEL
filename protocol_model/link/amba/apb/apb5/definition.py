"""APB5 transaction semantics and optional sideband profile."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from protocol_model.link import LinkProtocol

from .._common.definition import (
    bit_field,
    boolean_field,
    build_apb_variant,
    validate_apb_dimensions,
)


class Apb5CheckType(str, Enum):
    """Parity profile currently executable by this APB5 observer."""

    NONE = "none"


@dataclass(frozen=True)
class Apb5Config:
    address_width: int = 32
    data_width: int = 32
    pprot_present: bool = True
    pstrb_present: bool = True
    wakeup_signal: bool = False
    user_request_width: int = 0
    user_data_width: int = 0
    user_response_width: int = 0
    rme_support: bool = False
    check_type: Apb5CheckType = Apb5CheckType.NONE

    def __post_init__(self) -> None:
        validate_apb_dimensions(self.address_width, self.data_width)
        for name in (
            "pprot_present",
            "pstrb_present",
            "wakeup_signal",
            "rme_support",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"APB5 {name} must be bool")
        for name in (
            "user_request_width",
            "user_data_width",
            "user_response_width",
        ):
            width = getattr(self, name)
            if (
                not isinstance(width, int)
                or isinstance(width, bool)
                or width < 0
            ):
                raise ValueError(f"APB5 {name} must be a non-negative integer")
        if not isinstance(self.check_type, Apb5CheckType):
            object.__setattr__(
                self, "check_type", Apb5CheckType(self.check_type)
            )
        if self.rme_support and not self.pprot_present:
            raise ValueError("APB5 RME support requires PPROT to be present")

    @property
    def bytes_per_transfer(self) -> int:
        return self.data_width // 8


def build_apb5_link(config: Apb5Config | None = None) -> LinkProtocol:
    """Build an APB5 link with user, wake-up, and optional RME semantics.

    Interface parity is an optional APB5 profile.  This executable profile
    declares ``check_type=none`` and therefore has no check signals.
    """

    config = config or Apb5Config()
    request_fields = {}
    write_fields = {}
    read_response_fields = {}
    write_response_fields = {}
    if config.pprot_present:
        request_fields["prot"] = bit_field(
            "prot", 3, "PPROT transaction protection"
        )
    if config.rme_support:
        request_fields["nse"] = boolean_field(
            "nse", "PNSE extension to the protection type"
        )
    if config.user_request_width:
        request_fields["auser"] = bit_field(
            "auser", config.user_request_width, "PAUSER request attribute"
        )
    if config.pstrb_present:
        write_fields["strb"] = bit_field(
            "strb", config.bytes_per_transfer, "PSTRB write byte lanes"
        )
    if config.user_data_width:
        write_fields["wuser"] = bit_field(
            "wuser", config.user_data_width, "PWUSER write data attribute"
        )
        read_response_fields["ruser"] = bit_field(
            "ruser", config.user_data_width, "PRUSER read data attribute"
        )
    if config.user_response_width:
        buser = bit_field(
            "buser", config.user_response_width, "PBUSER response attribute"
        )
        read_response_fields["buser"] = buser
        write_response_fields["buser"] = buser
    return build_apb_variant(
        "apb5",
        revision="APB5",
        address_width=config.address_width,
        data_width=config.data_width,
        request_fields=request_fields,
        write_fields=write_fields,
        read_response_fields=read_response_fields,
        write_response_fields=write_response_fields,
        parameters={
            "pprot_present": config.pprot_present,
            "pstrb_present": config.pstrb_present,
            "wakeup_signal": config.wakeup_signal,
            "user_request_width": config.user_request_width,
            "user_data_width": config.user_data_width,
            "user_response_width": config.user_response_width,
            "rme_support": config.rme_support,
            "check_type": config.check_type.value,
            "pready_default": True,
            "pslverr_default": False,
        },
        sources=(
            "Arm IHI 0024E sections 3.1-3.8, 4.1, and 5.2",
        ),
    )
