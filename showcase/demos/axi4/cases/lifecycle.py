"""Read/write obligation and completion lifecycle examples."""

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


def lifecycle_cases() -> tuple[ExampleCase, ...]:
    protocol = build_axi4_link()
    single_read = address("AR", key=1, addr=0x100)
    single_write = address("AW", key=2, addr=0x200)
    before_address = address("AW", key=3, addr=0x208)
    long_write = address("AW", key=4, addr=0x300, length=3)
    single_for_missing_last = address("AW", key=12, addr=0x308)
    wrong_bid = address("AW", key=12, addr=0x380)

    return (
        ExampleCase(
            "read-single-lifecycle",
            "lifecycle",
            "Single read opens and discharges one obligation",
            "单拍读事务打开并解除一个义务",
            "AR creates one pending read; the matching final R releases it.",
            "AR 建立一个待读资源，匹配的末拍 R 将其释放。",
            protocol,
            ExecutionMode.LINK,
            (single_read, read_data(key=1, last=True, data=0x11223344)),
            Verdict.PASS,
        ),
        ExampleCase(
            "read-orphan-response",
            "lifecycle",
            "An R response requires a pending AR",
            "R 响应必须对应已接受的 AR",
            "A response with no pending request is rejected locally.",
            "没有待读请求的响应会在单链路范围内被拒绝。",
            protocol,
            ExecutionMode.LINK,
            (read_data(key=7, last=True),),
            Verdict.FAIL,
            "axi4.read.orphan_beat",
        ),
        ExampleCase(
            "write-single-lifecycle",
            "lifecycle",
            "AW and W join before B completion",
            "AW 与 W 关联后再由 B 完成",
            "The joined write owns one completion resource until B arrives.",
            "关联后的写事务占用一个 completion 资源，直到 B 到达。",
            protocol,
            ExecutionMode.LINK,
            (
                single_write,
                write_data(last=True, strobe=0x0F, data=0xAABBCCDD),
                write_response(key=2),
            ),
            Verdict.PASS,
        ),
        ExampleCase(
            "write-data-before-address",
            "lifecycle",
            "A complete W burst may precede its AW descriptor",
            "完整 W burst 可以先于 AW 描述符到达",
            "The ID-less W burst waits in FIFO order and joins the later AW.",
            "无 ID 的 W burst 按 FIFO 顺序等待并关联后续 AW。",
            protocol,
            ExecutionMode.LINK,
            (
                write_data(last=True, strobe=0x0F, data=0x55),
                before_address,
                write_response(key=3),
            ),
            Verdict.PASS,
        ),
        ExampleCase(
            "write-early-wlast",
            "lifecycle",
            "WLAST follows the oldest AW beat count",
            "WLAST 必须符合最早 AW 声明的拍数",
            "AWLEN=3 requires four W transfers, so WLAST on beat one is early.",
            "AWLEN=3 表示四拍，因此首拍置 WLAST 属于过早结束。",
            protocol,
            ExecutionMode.LINK,
            (long_write, write_data(last=True, strobe=0x0F)),
            Verdict.FAIL,
            "axi4.write.final_marker",
        ),
        ExampleCase(
            "write-missing-wlast",
            "lifecycle",
            "The final required W transfer asserts WLAST",
            "最后一拍必需的 W 传输必须置 WLAST",
            "A single-beat AW requires WLAST on its only W transfer.",
            "单拍 AW 要求唯一的 W 传输同时也是末拍。",
            protocol,
            ExecutionMode.LINK,
            (
                single_for_missing_last,
                write_data(last=False, strobe=0x0F),
            ),
            Verdict.FAIL,
            "axi4.write.final_marker",
            "requires last=True",
        ),
        ExampleCase(
            "write-wrong-bid",
            "lifecycle",
            "BID identifies a pending write context",
            "BID 必须标识一笔待完成写事务",
            "A B response for ID 13 cannot complete the joined write for ID 12.",
            "ID 13 的 B 响应不能完成 ID 12 的已关联写事务。",
            protocol,
            ExecutionMode.LINK,
            (
                wrong_bid,
                write_data(last=True, strobe=0x0F),
                write_response(key=13),
            ),
            Verdict.FAIL,
            "axi4.exclusive.orphan_write_response",
            "no matching AW context",
        ),
    )


__all__ = ["lifecycle_cases"]
