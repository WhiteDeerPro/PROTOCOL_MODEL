"""Shared response and error encodings used by the current CHI forms."""

from __future__ import annotations

from enum import IntEnum


class ChiRespCode(IntEnum):
    """Meaning of the three-bit ``Resp`` field.

    The same bit pattern is interpreted in the context of the response
    opcode.  In particular, encoding ``0b110`` is named ``UC_PD`` for a snoop
    response and ``UD_PD`` for a completion response.
    """

    I = 0b000
    SC = 0b001
    UC = 0b010
    SD = 0b011
    I_PD = 0b100
    SC_PD = 0b101
    UC_PD = 0b110
    UD_PD = 0b110
    SD_PD = 0b111


class ChiRespErr(IntEnum):
    """Meaning of the two-bit ``RespErr`` field."""

    OK = 0b00
    EXOK = 0b01
    DERR = 0b10
    NDERR = 0b11


__all__ = ["ChiRespCode", "ChiRespErr"]
