"""Constructive APB3/APB4 pin-level waveform generation."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

from protocol_model.core import CanonicalEvent, Verdict

from .spec import ApbConfig, ApbPinSample, build_apb_spec
from protocol_model.protocols.spec import ProtocolSpec


@dataclass(frozen=True)
class ApbGeneratedTrace:
    samples: tuple[ApbPinSample, ...]
    transfers: tuple[CanonicalEvent, ...]


def generate_apb_trace(
    config: ApbConfig,
    *,
    transactions: int = 4,
    seed: int = 0,
    spec: ProtocolSpec | None = None,
) -> ApbGeneratedTrace:
    if transactions < 0:
        raise ValueError("transactions must be non-negative")
    rng = Random(seed)
    spec = spec or build_apb_spec(config)
    if spec.parameters.get("version") != config.version:
        raise ValueError("APB generator config does not match bound protocol instance")
    monitor = spec.channel("APB").observation_model
    samples = []
    cycle = 0

    def append(**signals):
        nonlocal cycle
        defaults = {
            "presetn": True,
            "psel": False,
            "penable": False,
            "pwrite": False,
            "paddr": 0,
            "pwdata": 0,
            "pready": bool(rng.getrandbits(1)),
            "prdata": 0,
            "pslverr": False,
            "pstrb": 0 if config.version == 4 else None,
            "pprot": 0 if config.version == 4 else None,
            "source": f"virtual_apb{config.version}",
        }
        defaults.update(signals)
        samples.append(ApbPinSample(cycle=cycle, **defaults))
        cycle += 1

    append(presetn=False)
    append()
    for _ in range(transactions):
        write = bool(rng.getrandbits(1))
        request = {
            "psel": True,
            "pwrite": write,
            "paddr": rng.getrandbits(config.address_width),
            "pwdata": rng.getrandbits(config.data_width) if write else 0,
        }
        if config.version == 4:
            request.update(
                {
                    "pstrb": rng.getrandbits(config.strobe_width) if write else 0,
                    "pprot": rng.getrandbits(3),
                }
            )
        append(penable=False, **request)
        waits = rng.randint(0, config.generated_max_wait)
        for _ in range(waits):
            append(penable=True, pready=False, **request)
        append(
            penable=True,
            pready=True,
            prdata=rng.getrandbits(config.data_width) if not write else 0,
            pslverr=rng.random() < 0.15,
            **request,
        )
    append()
    result = monitor.run(samples)
    if result.verdict == Verdict.FAIL:
        violation = result.violations[0]
        raise RuntimeError(f"APB generator violated {violation.rule}: {violation.reason}")
    return ApbGeneratedTrace(tuple(samples), result.emissions)
