"""AtomicFrame, ready/valid, same-edge, and reset examples."""

from protocol_model import Verdict
from protocol_model.link.amba.axi.axi4 import build_axi4_link

from common import (
    ExecutionMode,
    ExampleCase,
    address,
    frame,
    read_data,
    write_data,
    write_response,
)


def observation_cases() -> tuple[ExampleCase, ...]:
    protocol = build_axi4_link()
    same_frame_aw = address("AW", key=1, addr=0x800)
    same_frame_w = write_data(last=True, strobe=0x0F, data=0xAA)
    same_frame_ar = address("AR", key=2, addr=0x900)
    stalled = address("AR", key=3, addr=0xA00)
    mutated = address("AR", key=3, addr=0xA08)
    reset_read = address("AR", key=4, addr=0xB00)

    return (
        ExampleCase(
            "observation-same-frame-aw-w",
            "observation/reset",
            "AW and W at one edge commit as one frame",
            "同一采样沿的 AW 与 W 作为一个帧提交",
            "The observation lowering correlates both transfers before the later B.",
            "观察层在后续 B 之前关联同一帧中的两个传输。",
            protocol,
            ExecutionMode.OBSERVATION,
            (
                frame(0, reset=True),
                frame(1, {"AW": same_frame_aw, "W": same_frame_w}),
                frame(2, {"B": write_response(key=1)}),
            ),
            Verdict.PASS,
        ),
        ExampleCase(
            "observation-same-frame-ar-r",
            "observation/reset",
            "A response cannot consume an obligation born at the same edge",
            "响应不能消费同一采样沿刚建立的义务",
            "R is checked against state visible before the current AR commits.",
            "R 依据当前 AR 提交之前可见的状态进行检查。",
            protocol,
            ExecutionMode.OBSERVATION,
            (
                frame(0, reset=True),
                frame(
                    1,
                    {
                        "AR": same_frame_ar,
                        "R": read_data(key=2, last=True),
                    },
                ),
            ),
            Verdict.FAIL,
            "axi4.read.orphan_beat",
        ),
        ExampleCase(
            "observation-stalled-payload-mutation",
            "observation/reset",
            "Payload remains stable while VALID is stalled",
            "VALID 阻塞期间 payload 保持稳定",
            "Changing ARADDR before acceptance violates ready/valid stability.",
            "AR 接受前改变 ARADDR 会违反 ready/valid 稳定性。",
            protocol,
            ExecutionMode.OBSERVATION,
            (
                frame(0, reset=True),
                frame(1, {"AR": stalled}, ready=False),
                frame(2, {"AR": mutated}, ready=False),
            ),
            Verdict.FAIL,
            "axi4.observation.AR.ready_valid.payload_stability",
        ),
        ExampleCase(
            "observation-reset-clears-pending-read",
            "observation/reset",
            "Reset starts a new observation and link epoch",
            "复位开启新的观察与链路 epoch",
            "An R after reset cannot complete the pre-reset AR.",
            "复位后的 R 不能完成复位前的 AR。",
            protocol,
            ExecutionMode.OBSERVATION,
            (
                frame(0, reset=True),
                frame(1, {"AR": reset_read}),
                frame(2, reset=True),
                frame(3, {"R": read_data(key=4, last=True)}),
            ),
            Verdict.FAIL,
            "axi4.read.orphan_beat",
        ),
    )


__all__ = ["observation_cases"]
