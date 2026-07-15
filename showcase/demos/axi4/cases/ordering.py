"""Read response ordering and cross-ID interleave examples."""

from protocol_model import Verdict
from protocol_model.link.amba.axi.axi4 import build_axi4_link

from common import (
    ExecutionMode,
    ExampleCase,
    address,
    read_data,
    write_data,
    write_response,
)


def ordering_cases() -> tuple[ExampleCase, ...]:
    protocol = build_axi4_link()
    first = address("AR", key=1, addr=0x400, length=1)
    second = address("AR", key=2, addr=0x500, length=1)
    same_id_oldest = address("AR", key=3, addr=0x600, length=1)
    same_id_later = address("AR", key=3, addr=0x700, length=0)
    first_write = address("AW", key=14, addr=0xE00)
    second_write = address("AW", key=15, addr=0xE08)

    return (
        ExampleCase(
            "read-cross-id-interleave",
            "ordering/interleave",
            "Responses for different IDs may interleave",
            "不同 ID 的读响应可以交织",
            "Each ID keeps its own beat count while the link alternates IDs.",
            "链路交替返回不同 ID，同时分别维护各自的拍数。",
            protocol,
            ExecutionMode.LINK,
            (
                first,
                second,
                read_data(key=1, last=False, data=0x11),
                read_data(key=2, last=False, data=0x21),
                read_data(key=1, last=True, data=0x12),
                read_data(key=2, last=True, data=0x22),
            ),
            Verdict.PASS,
        ),
        ExampleCase(
            "read-same-id-later-cannot-overtake",
            "ordering/interleave",
            "The oldest same-ID read consumes responses first",
            "同 ID 的最早读请求优先消费响应",
            "A final beat shaped for the later one-beat read is early for the oldest read.",
            "面向后一笔单拍读的末拍，对最早的两拍读而言属于过早结束。",
            protocol,
            ExecutionMode.LINK,
            (
                same_id_oldest,
                same_id_later,
                read_data(key=3, last=True),
            ),
            Verdict.FAIL,
            "axi4.read.final_marker",
            "beat 1/2",
        ),
        ExampleCase(
            "write-multiple-outstanding-reverse-b",
            "ordering/interleave",
            "Different write IDs may complete in reverse request order",
            "不同写 ID 可以按请求的逆序完成",
            "W remains FIFO-correlated with AW while B selects pending writes by ID.",
            "W 仍按 FIFO 与 AW 关联，而 B 可以按 ID 选择待完成写事务。",
            protocol,
            ExecutionMode.LINK,
            (
                first_write,
                second_write,
                write_data(last=True, strobe=0x0F, data=0x14),
                write_data(last=True, strobe=0x0F, data=0x15),
                write_response(key=15),
                write_response(key=14),
            ),
            Verdict.PASS,
        ),
    )


__all__ = ["ordering_cases"]
