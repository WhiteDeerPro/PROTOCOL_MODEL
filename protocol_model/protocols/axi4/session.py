"""Constructive random scheduling over the unified AXI4 ProtocolSession."""

from __future__ import annotations

from random import Random

from protocol_model.engine import ExecutionTrace

from .spec import Axi4Config, build_axi4_spec


class Axi4RandomScheduler:
    """Generate a finite legal subset by choosing enabled semantic actions."""

    def __init__(
        self,
        config: Axi4Config | None = None,
        *,
        seed: int = 0,
        max_beats: int = 4,
        max_steps: int = 10_000,
    ):
        if max_beats <= 0 or max_beats > 256:
            raise ValueError("max_beats must be in [1, 256]")
        self.spec = build_axi4_spec(config)
        self.session = self.spec.open_session()
        self.rng = Random(seed)
        self.max_beats = max_beats
        self.max_steps = max_steps

    def _address(self, channel: str):
        beats = self.rng.randint(1, self.max_beats)
        return self.spec.channel(channel).transfer.sample_constrained(
            self.rng,
            payload={"len": beats - 1, "burst": "INCR"},
        )

    def generate(
        self, *, reads: int = 2, writes: int = 2
    ) -> ExecutionTrace:
        if reads < 0 or writes < 0:
            raise ValueError("transaction counts must be non-negative")
        state = self.session.initial_state()
        events = []
        steps = []
        issued_reads = 0
        issued_writes = 0

        while (
            issued_reads < reads
            or issued_writes < writes
            or not self.session.is_quiescent(state)
        ):
            if len(events) >= self.max_steps:
                raise RuntimeError("AXI4 scheduler exceeded max_steps")
            read_state = state.state_of("read")
            write_state = state.state_of("write")
            candidates = []
            if issued_reads < reads:
                candidates.append(("issue_read", self._address("AR")))
            if issued_writes < writes:
                candidates.append(("issue_write", self._address("AW")))
            if read_state.pending:
                candidates.append(
                    (
                        "read_beat",
                        self.spec.transaction_models["read"].sample_legal(
                            read_state, self.rng, allow_begin=False
                        ),
                    )
                )
            if write_state.descriptors:
                candidates.append(
                    (
                        "write_beat",
                        self.spec.transaction_models["write"].sample_data(
                            write_state, self.rng
                        ),
                    )
                )
            if write_state.completions:
                candidates.append(
                    (
                        "write_response",
                        self.spec.transaction_models["write"].sample_completion(
                            write_state, self.rng
                        ),
                    )
                )
            if not candidates:
                raise RuntimeError("AXI4 scheduler reached a non-quiescent deadlock")

            self.rng.shuffle(candidates)
            selected = []
            for candidate in candidates:
                proposed = tuple(item[1] for item in selected + [candidate])
                if self.session.can_cooccur(state, proposed):
                    selected.append(candidate)
            if not selected:
                selected.append(candidates[0])

            step_indices = []
            for action, event in selected:
                transition = self.session.step(state, event)
                if transition.fault is not None:
                    raise RuntimeError(
                        f"constructive scheduler generated {transition.fault.rule}: "
                        f"{transition.fault.reason}"
                    )
                state = transition.state
                step_indices.append(len(events))
                events.append(transition.emissions[0])
                if action == "issue_read":
                    issued_reads += 1
                elif action == "issue_write":
                    issued_writes += 1
            steps.append(tuple(step_indices))

        return self.session.execution_trace(state, tuple(events), tuple(steps))
