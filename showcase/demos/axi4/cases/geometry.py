"""Burst-boundary and byte-lane geometry examples."""

from protocol_model import Verdict
from protocol_model.link.amba.axi.axi4 import byte_lane_mask, build_axi4_link

from common import (
    ExecutionMode,
    ExampleCase,
    address,
    read_data,
    write_data,
    write_response,
)


def geometry_cases() -> tuple[ExampleCase, ...]:
    protocol = build_axi4_link()
    crossing = address("AR", key=1, addr=0x0FFC, length=1, size=2)
    narrow = address("AW", key=2, addr=0x0003, length=3, size=2)
    bad_strobe = address("AW", key=3, addr=0x0003, size=2)
    legal_wrap = address(
        "AR", key=8, addr=0x002C, length=3, size=2, burst="WRAP"
    )
    illegal_wrap = address(
        "AR", key=9, addr=0x0040, length=2, size=2, burst="WRAP"
    )
    legal_fixed = address(
        "AR", key=10, addr=0x0FFF, length=15, size=2, burst="FIXED"
    )
    illegal_fixed = address(
        "AR", key=11, addr=0x0100, length=16, size=2, burst="FIXED"
    )
    narrow_data = tuple(
        write_data(
            last=index == 3,
            strobe=byte_lane_mask(narrow, index, bus_bytes=8),
            data=(index + 1) * 0x1111111111111111,
        )
        for index in range(4)
    )

    return (
        ExampleCase(
            "read-crosses-4kb-boundary",
            "geometry",
            "An INCR burst stays within one 4KB region",
            "INCR burst 必须位于同一个 4KB 区域",
            "Two four-byte transfers starting at 0xFFC cross the boundary.",
            "从 0xFFC 开始的两个四字节传输会跨越该边界。",
            protocol,
            ExecutionMode.LINK,
            (crossing,),
            Verdict.FAIL,
            "axi4.link_session.AR.event_schema",
            "4KB",
        ),
        ExampleCase(
            "write-narrow-unaligned-incr",
            "geometry",
            "Narrow unaligned transfers rotate legal byte lanes",
            "窄位宽非对齐传输轮换合法字节通道",
            "The four legal WSTRB masks are derived from the AW geometry.",
            "四拍合法 WSTRB 由 AW 几何信息派生。",
            protocol,
            ExecutionMode.LINK,
            (narrow, *narrow_data, write_response(key=2)),
            Verdict.PASS,
        ),
        ExampleCase(
            "write-strobe-outside-lanes",
            "geometry",
            "WSTRB cannot select bytes outside the transfer container",
            "WSTRB 不得选择传输容器之外的字节",
            "At address 0x3 only lane 3 is legal for this first transfer.",
            "该首拍位于地址 0x3，只有字节通道 3 合法。",
            protocol,
            ExecutionMode.LINK,
            (bad_strobe, write_data(last=True, strobe=0x10)),
            Verdict.FAIL,
            "axi4.write.byte_lanes",
            "outside allowed mask",
        ),
        ExampleCase(
            "read-wrap-four-legal",
            "geometry",
            "A four-transfer WRAP burst rotates inside its wrap window",
            "四拍 WRAP burst 在自身窗口内回绕",
            "Starting at 0x2C produces a legal four-transfer wrap in 0x20–0x2F.",
            "从 0x2C 开始的四拍传输会在 0x20–0x2F 窗口内合法回绕。",
            protocol,
            ExecutionMode.LINK,
            (
                legal_wrap,
                read_data(key=8, last=False, data=0x81),
                read_data(key=8, last=False, data=0x82),
                read_data(key=8, last=False, data=0x83),
                read_data(key=8, last=True, data=0x84),
            ),
            Verdict.PASS,
        ),
        ExampleCase(
            "read-wrap-three-illegal",
            "geometry",
            "WRAP uses one of the protocol's permitted transfer counts",
            "WRAP 必须使用协议允许的传输拍数",
            "Three transfers are not a legal AXI4 WRAP length.",
            "三拍不是 AXI4 允许的 WRAP 长度。",
            protocol,
            ExecutionMode.LINK,
            (illegal_wrap,),
            Verdict.FAIL,
            "axi4.link_session.AR.event_schema",
            "WRAP burst length",
        ),
        ExampleCase(
            "read-fixed-sixteen-legal",
            "geometry",
            "FIXED permits sixteen transfers at one address container",
            "FIXED 允许在同一地址容器上传输十六拍",
            "Even at 0xFFF, every transfer reuses the same in-page container.",
            "即使位于 0xFFF，每一拍仍复用同一个页内传输容器。",
            protocol,
            ExecutionMode.LINK,
            (
                legal_fixed,
                *(
                    read_data(
                        key=10,
                        last=index == 15,
                        data=0x100 + index,
                    )
                    for index in range(16)
                ),
            ),
            Verdict.PASS,
        ),
        ExampleCase(
            "read-fixed-seventeen-illegal",
            "geometry",
            "FIXED length does not exceed sixteen transfers",
            "FIXED 长度不超过十六拍",
            "AxLEN=16 encodes seventeen transfers and is rejected for FIXED.",
            "AxLEN=16 表示十七拍，因此不适用于 FIXED。",
            protocol,
            ExecutionMode.LINK,
            (illegal_fixed,),
            Verdict.FAIL,
            "axi4.link_session.AR.event_schema",
            "FIXED burst length",
        ),
    )


__all__ = ["geometry_cases"]
