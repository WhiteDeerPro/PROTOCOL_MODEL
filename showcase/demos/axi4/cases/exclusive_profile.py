"""Exclusive-access and bounded-resource profile examples."""

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


def exclusive_profile_cases() -> tuple[ExampleCase, ...]:
    protocol = build_axi4_link()
    exclusive_read = address("AR", key=5, addr=0xC00, lock=1)
    exclusive_write = address("AW", key=5, addr=0xC00, lock=1)
    unmatched_write = address("AW", key=6, addr=0xC80, lock=1)
    bounded = protocol.with_resource_capacities(
        "axi4_one_read",
        {"axi4.read.pending_transactions": 1},
    )

    return (
        ExampleCase(
            "exclusive-matching-exokay",
            "exclusive/profile",
            "A matching link-local exclusive sequence may succeed",
            "匹配的链路内独占序列可以成功",
            "The completed exclusive read makes one matching write eligible for EXOKAY.",
            "已完成的独占读使一笔匹配写事务具备返回 EXOKAY 的资格。",
            protocol,
            ExecutionMode.LINK,
            (
                exclusive_read,
                read_data(key=5, last=True, response="EXOKAY"),
                exclusive_write,
                write_data(last=True, strobe=0x0F),
                write_response(key=5, response="EXOKAY"),
            ),
            Verdict.PASS,
        ),
        ExampleCase(
            "profile-bounded-read-capacity",
            "exclusive/profile",
            "A refined profile can bound outstanding reads",
            "细化 profile 可以限制 outstanding read",
            "The second AR exceeds a configured capacity of one and is rolled back.",
            "在容量配置为一时，第二个 AR 超限并被回滚。",
            bounded,
            ExecutionMode.LINK,
            (
                address("AR", key=6, addr=0xD00),
                address("AR", key=7, addr=0xD08),
            ),
            Verdict.FAIL,
            "axi4_one_read.axi4.read.pending_transactions.capacity",
            "usage 2 exceeds",
        ),
        ExampleCase(
            "exclusive-unmatched-success",
            "exclusive/profile",
            "EXOKAY requires a matching completed exclusive read",
            "EXOKAY 要求存在匹配且已完成的独占读",
            "An exclusive write without a reservation may complete, but not with EXOKAY.",
            "没有 reservation 的独占写可以完成，但不能返回 EXOKAY。",
            protocol,
            ExecutionMode.LINK,
            (
                unmatched_write,
                write_data(last=True, strobe=0x0F),
                write_response(key=6, response="EXOKAY"),
            ),
            Verdict.FAIL,
            "axi4.exclusive.unmatched_success",
            "matching completed exclusive read",
        ),
    )


__all__ = ["exclusive_profile_cases"]
