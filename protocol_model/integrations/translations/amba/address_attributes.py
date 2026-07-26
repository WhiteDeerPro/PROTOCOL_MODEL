"""Hub-and-spoke AMBA protection conversion for address bridge plans."""

from __future__ import annotations

from dataclasses import dataclass, replace

from protocol_model.interface import InterfaceProtocol
from protocol_model.protocols.amba.ahb import AHB_FAMILY
from protocol_model.protocols.amba.apb import APB_FAMILY
from protocol_model.protocols.amba.axi.axi4 import AXI4_FAMILY
from protocol_model.protocols.amba.axi.axi4_lite import AXI4_LITE_FAMILY
from protocol_model.virtual_dut.address.access import (
    AccessResult,
    AddressAccess,
    AddressRead,
    AddressWrite,
)
from protocol_model.virtual_dut.address.attributes import (
    AccessProtection,
    PROTECTION_ATTRIBUTE,
)
from protocol_model.virtual_dut.translation.address import (
    ADDRESS_ACCESS_SIGNATURE,
)
from protocol_model.virtual_dut.translation.contract import (
    SemanticEffect,
    SemanticEffectKind,
    StageContract,
)
from protocol_model.virtual_dut.translation.signature import OperationSignature
from protocol_model.virtual_dut.translation.stage import (
    LoweredOne,
    Rejected,
    UnaryTranslationStage,
)


_SUPPORTED_FAMILIES = frozenset(
    (AXI4_FAMILY, AXI4_LITE_FAMILY, AHB_FAMILY, APB_FAMILY)
)


def amba_raw_address_signature(protocol: InterfaceProtocol) -> OperationSignature:
    """Identify the family-specific meaning of ``AddressAccess.attributes``."""

    if protocol.interface_family not in _SUPPORTED_FAMILIES:
        raise ValueError(
            f"AMBA address bridge does not support family {protocol.interface_family!r}"
        )
    return OperationSignature(
        protocol.interface_family,
        "raw_address_access",
        "1",
        (AddressRead, AddressWrite),
        (AccessResult,),
    )


def _copy_access(
    access: AddressAccess, attributes: dict[str, object]
) -> AddressAccess:
    return replace(access, attributes=attributes)


def _nonzero_extensions(
    attributes: dict[str, object], consumed: set[str]
) -> tuple[str, ...]:
    return tuple(
        sorted(
            name
            for name, value in attributes.items()
            if name not in consumed and value not in (0, False, None)
        )
    )


def _three_bit_protection(value: int) -> AccessProtection:
    return AccessProtection(
        privileged=bool(value & 0b001),
        nonsecure=bool(value & 0b010),
        instruction=bool(value & 0b100),
    )


def _encode_three_bit_protection(protection: AccessProtection) -> int:
    return (
        int(bool(protection.privileged))
        | (int(bool(protection.nonsecure)) << 1)
        | (int(bool(protection.instruction)) << 2)
    )


@dataclass(frozen=True)
class DecodeAmbaProtectionStage(
    UnaryTranslationStage[
        AddressAccess,
        AccessResult,
        AddressAccess,
        AccessResult,
    ]
):
    """Convert one AMBA family's wire-oriented attributes to common intent."""

    protocol: InterfaceProtocol

    def __post_init__(self) -> None:
        amba_raw_address_signature(self.protocol)

    @property
    def name(self) -> str:
        return f"decode_{self.protocol.interface_family.replace('.', '_')}_protection"

    @property
    def source(self) -> OperationSignature:
        return amba_raw_address_signature(self.protocol)

    target = ADDRESS_ACCESS_SIGNATURE
    contract = StageContract(
        semantic_effects=(
            SemanticEffect(
                "protection",
                SemanticEffectKind.RECOMPUTE,
                "decode protocol protection bits into common access intent",
                "amba.protection.decode",
            ),
            SemanticEffect(
                "unsupported_sideband",
                SemanticEffectKind.REJECT,
                "non-default attributes outside the common bridge profile are rejected",
                "amba.attributes.supported_subset",
            ),
        ),
        provenance="integrations.amba.decode_protection",
    )

    def lower(
        self, parent: AddressAccess
    ) -> LoweredOne[AddressAccess] | Rejected:
        raw = dict(parent.attributes)
        consumed: set[str]
        if self.protocol.interface_family in {
            AXI4_FAMILY,
            AXI4_LITE_FAMILY,
            APB_FAMILY,
        }:
            protection = (
                _three_bit_protection(int(raw["prot"]))
                if "prot" in raw
                else AccessProtection()
            )
            consumed = {"prot"}
        else:
            hprot = int(raw.get("prot", 0))
            if hprot & 0b1100:
                return Rejected(
                    "AHB bufferable/cacheable attributes require an explicit memory-attribute policy",
                    "amba.attributes.ahb_memory",
                )
            if bool(raw.get("lock", False)) or bool(
                raw.get("exclusive", False)
            ):
                return Rejected(
                    "locked or Exclusive AHB access requires a dedicated semantic bridge",
                    "amba.attributes.ahb_lock",
                )
            protection = AccessProtection(
                privileged=bool(hprot & 0b0010),
                nonsecure=(
                    bool(raw["nonsecure"])
                    if "nonsecure" in raw
                    else None
                ),
                instruction=not bool(hprot & 0b0001),
            )
            consumed = {"prot", "lock", "exclusive", "nonsecure"}

        unsupported = _nonzero_extensions(raw, consumed)
        if unsupported:
            return Rejected(
                f"AMBA address attributes require an explicit policy: {list(unsupported)!r}",
                "amba.attributes.extension",
            )
        return LoweredOne(
            _copy_access(parent, {PROTECTION_ATTRIBUTE: protection})
        )

    def lift(
        self, context: object | None, child_result: AccessResult
    ) -> AccessResult:
        return child_result


@dataclass(frozen=True)
class EncodeAmbaProtectionStage(
    UnaryTranslationStage[
        AddressAccess,
        AccessResult,
        AddressAccess,
        AccessResult,
    ]
):
    """Encode common access intent into one target AMBA family."""

    protocol: InterfaceProtocol

    def __post_init__(self) -> None:
        amba_raw_address_signature(self.protocol)

    @property
    def name(self) -> str:
        return f"encode_{self.protocol.interface_family.replace('.', '_')}_protection"

    source = ADDRESS_ACCESS_SIGNATURE

    @property
    def target(self) -> OperationSignature:
        return amba_raw_address_signature(self.protocol)

    contract = StageContract(
        semantic_effects=(
            SemanticEffect(
                "protection",
                SemanticEffectKind.RECOMPUTE,
                "encode common access intent into target protection bits",
                "amba.protection.encode",
            ),
            SemanticEffect(
                "unspecified_protection",
                SemanticEffectKind.DEFAULT,
                "properties absent at the source use the target's normal data-access default",
                "amba.protection.default",
            ),
        ),
        provenance="integrations.amba.encode_protection",
    )

    def lower(
        self, parent: AddressAccess
    ) -> LoweredOne[AddressAccess] | Rejected:
        attributes = dict(parent.attributes)
        protection = attributes.pop(
            PROTECTION_ATTRIBUTE, AccessProtection()
        )
        if not isinstance(protection, AccessProtection):
            return Rejected(
                "canonical protection attribute has the wrong type",
                "amba.protection.type",
            )
        if attributes:
            return Rejected(
                f"target AMBA profile has no policy for attributes {sorted(attributes)!r}",
                "amba.attributes.target_subset",
            )

        raw: dict[str, object] = {}
        if self.protocol.interface_family in {AXI4_FAMILY, AXI4_LITE_FAMILY}:
            raw["prot"] = _encode_three_bit_protection(protection)
        elif self.protocol.interface_family == APB_FAMILY:
            request_fields = self.protocol.event_kinds["READ"].schema.fields
            if "prot" in request_fields:
                raw["prot"] = _encode_three_bit_protection(protection)
            elif any(
                value is True
                for value in (
                    protection.privileged,
                    protection.nonsecure,
                    protection.instruction,
                )
            ):
                return Rejected(
                    "target APB profile has no PPROT field",
                    "amba.protection.apb_absent",
                )
        else:
            request_fields = self.protocol.event_kinds["READ"].schema.fields
            if protection.nonsecure is True and "nonsecure" not in request_fields:
                return Rejected(
                    "target AHB profile has no HNONSEC field for a Non-secure access",
                    "amba.protection.ahb_security",
                )
            raw["prot"] = (
                int(not bool(protection.instruction))
                | (int(bool(protection.privileged)) << 1)
            )
            raw["lock"] = False
            if "nonsecure" in request_fields:
                raw["nonsecure"] = bool(protection.nonsecure)

        return LoweredOne(_copy_access(parent, raw))

    def lift(
        self, context: object | None, child_result: AccessResult
    ) -> AccessResult:
        return child_result


__all__ = [
    "DecodeAmbaProtectionStage",
    "EncodeAmbaProtectionStage",
    "amba_raw_address_signature",
]
